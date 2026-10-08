"""Real Hermes comment/capture integration through isolated worker fixtures."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from test_swarm_protocol import swarm_env


@pytest.fixture
def wiki_env(swarm_env, tmp_path, monkeypatch):
    from hermes_cli import kanban_db_connect as kbc
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tree = tmp_path / "knowledge"
    tree.mkdir()
    (workspace / ".swarm").mkdir()
    (workspace / ".swarm/SWARM_WIKI.md").write_text("# Trusted fixture rules\n")
    with kbc.connect() as conn:
        conn.execute("UPDATE tasks SET workspace_path=? WHERE id=?", (str(workspace), swarm_env["source_tid"]))
        conn.commit()
    mod = swarm_env["mod"]
    actor = ["opnory-builder"]
    monkeypatch.setattr(mod, "_identity", lambda: actor[0])
    cfg = {"wiki_projects": {"p": {"workspace": str(workspace), "knowledge_tree": str(tree),
            "profiles": ["opnory-builder", "opnory-verifier"], "maintainers": ["maintainer"]}},
           "projects": {"p": {"builder": "opnory-builder"}}}
    monkeypatch.setattr(mod, "_plugin_settings", lambda: cfg)
    return dict(swarm_env, workspace=workspace, tree=tree, actor=actor, cfg=cfg)


def test_scratch_capture_uses_shared_storage_and_denies_unconfigured_roots(wiki_env, tmp_path):
    from hermes_cli import kanban_db_connect as kbc
    env = wiki_env
    scratch = tmp_path / "scratch/task"
    scratch.mkdir(parents=True)
    (scratch / "result.txt").write_text("Original scratch result")
    with kbc.connect() as conn:
        conn.execute("UPDATE tasks SET workspace_path=? WHERE id=?", (str(scratch), env["source_tid"]))
        conn.commit()
    args = {"project": "p", "topic": "auth/issuer", "task_id": env["source_tid"], "publication_key": "scratch",
            "source_path": "result.txt", "category": "test-results"}
    assert not json.loads(env["mod"].swarm_capture(args)).get("ok")
    env["cfg"]["wiki_projects"]["p"]["task_workspaces"] = [str(scratch.parent)]
    reply = json.loads(env["mod"].swarm_capture(args))
    assert reply.get("ok"), reply
    assert (env["workspace"] / ".swarm/raw" / reply["evidence"]["path"]).read_text() == "Original scratch result"
    assert not (scratch / ".swarm/raw").exists()
    with kbc.connect() as conn:
        body = conn.execute("SELECT body FROM task_comments WHERE id=?", (reply["comment_id"],)).fetchone()[0]
    assert json.loads(body.split("\n", 1)[1])["workspace"] == str(scratch)


def test_knowledge_capture_cannot_be_relabelled_live_proof(wiki_env):
    env = wiki_env
    (env["tree"] / "memory.md").write_text("Canonical memory")
    args = {"project": "p", "topic": "auth/issuer", "task_id": env["source_tid"], "publication_key": "memory",
            "source_kind": "knowledge", "source_path": "memory.md", "category": "source-snapshots"}
    reply = json.loads(env["mod"].swarm_capture(args))
    assert reply.get("ok"), reply
    c = publish(env)
    env["actor"][0] = "opnory-verifier"
    v = publish(env, "verification", "memory-pass", {"claim_id": c["event_id"], "scope": "tenant", "verdict": "pass",
                "rationale": "Memory snapshot", "live_evidence": [reply["evidence"]]})
    assert not v.get("ok"), v
    (env["tree"] / "memory.md").write_text("New canonical revision")
    assert (env["workspace"] / ".swarm/raw" / reply["evidence"]["path"]).read_text() == "Canonical memory"
    assert "source_kind" in env["mod"].SWARM_CAPTURE_SCHEMA["parameters"]["properties"]


def test_reconciliation_rejects_evidence_lost_since_verification(wiki_env):
    env = wiki_env
    (env["workspace"] / "proof.txt").write_text("Live proof")
    import wiki_records as records
    ref = {"kind": "file", "path": "proof.txt", "sha256": records.byte_hash(b"Live proof")}
    c = publish(env)
    other = publish(env, "claim", "other", {"assertion": "Alternative claim", "scope": "tenant"})
    env["actor"][0] = "opnory-verifier"
    v = publish(env, "verification", "proof", {"claim_id": c["event_id"], "scope": "tenant", "verdict": "pass",
                "rationale": "Independent", "live_evidence": [ref]})
    assert v.get("ok"), v
    conflict = publish(env, "contradiction", "conflict", {"claims": [c["event_id"], other["event_id"]],
                        "scope": "tenant", "explanation": "Two claims"})
    assert conflict.get("ok"), conflict
    (env["workspace"] / "proof.txt").unlink()
    resolution = publish(env, "reconciliation", "resolution", {"contradiction_id": conflict["event_id"], "scope": "tenant",
                          "disposition": "resolved", "conclusion": "Resolve", "supporting_records": [v["event_id"]]})
    assert not resolution.get("ok"), resolution


def publish(env, kind="claim", key="claim1", data=None, **extra):
    args = {"project": "p", "topic": "auth/issuer", "task_id": env["source_tid"],
            "type": kind, "publication_key": key, "data": data or {"assertion": "Tenant issuer is lost", "scope": "tenant"}, **extra}
    return json.loads(env["mod"].swarm_publish(args))


def test_runtime_identity_idempotency_and_conflicting_payload(wiki_env):
    from hermes_cli import kanban_db_connect as kbc
    env = wiki_env
    first = publish(env, actor="impostor")
    assert first.get("ok"), first
    assert not first["duplicate"]
    retry = publish(env)
    assert retry["ok"] and retry["duplicate"] and retry["event_id"] == first["event_id"]
    conflict = publish(env, data={"assertion": "Different assertion", "scope": "tenant"})
    assert "different payload" in conflict["error"]
    with kbc.connect() as conn:
        comments = conn.execute("SELECT author,body FROM task_comments WHERE id=?", (first["comment_id"],)).fetchone()
        assert comments[0] == "opnory-builder"
        assert '"actor":"opnory-builder"' in comments[1]
        assert "impostor" not in comments[1]
        assert conn.execute("SELECT COUNT(*) FROM task_comments").fetchone()[0] == 1


def test_concurrent_same_key_creates_one_canonical_comment(wiki_env):
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: publish(wiki_env), range(2)))
    assert all(r.get("ok") for r in replies), replies
    assert sorted(r["duplicate"] for r in replies) == [False, True]
    assert len({r["comment_id"] for r in replies}) == 1


def test_capture_publish_verify_and_accepted_byte_rover_synthesis(wiki_env):
    env = wiki_env
    (env["workspace"] / "result.txt").write_text("Independent original test output\n")
    capture = json.loads(env["mod"].swarm_capture({"project": "p", "topic": "auth/issuer", "task_id": env["source_tid"],
                        "publication_key": "capture1", "source_path": "result.txt", "category": "test-results"}))
    assert capture.get("ok"), capture
    raw = env["workspace"] / ".swarm/raw" / capture["evidence"]["path"]
    assert raw.read_text() == "Independent original test output\n"
    c = publish(env, data={"assertion": "Tenant issuer is lost", "scope": "tenant", "evidence": [capture["evidence"]]})
    assert c["ok"]
    vdata = {"claim_id": c["event_id"], "scope": "tenant", "verdict": "pass", "rationale": "reproduced", "live_evidence": [capture["evidence"]]}
    assert not publish(env, "verification", "self-pass", vdata).get("ok")
    env["actor"][0] = "opnory-verifier"
    v = publish(env, "verification", "verify1", vdata)
    assert v["ok"]
    env["tree"].joinpath("issuer.md").write_text("---\ntitle: Issuer\nsummary: Tenant failure independently reproduced.\n---\nMaintained synthesis citing canonical findings.\n")
    records = env["mod"]._wiki_records()
    sdata = {"node_path": "issuer.md", "node_sha256": records.byte_hash(env["tree"].joinpath("issuer.md").read_bytes()),
             "source_digests": {r["event_id"]: r["payload_digest"] for r in (capture, c, v)}, "category": "architecture"}
    assert not publish(env, "synthesis", "synth1", sdata).get("ok")
    env["actor"][0] = "maintainer"
    s = publish(env, "synthesis", "synth1", sdata)
    assert s["ok"]
    # Compile the real Hermes fixture schema, not only the lightweight unit DB.
    from hermes_cli import kanban_db_connect as kbc, kanban_db as kb
    import wiki_compiler as wiki
    with kbc.connect() as conn:
        db = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    inputs = wiki.snapshot(db, env["tree"], env["workspace"] / ".swarm/raw", env["workspace"] / ".swarm/SWARM_WIKI.md")
    projection = wiki.Projection(inputs, "p", "fixture", env["workspace"], env["workspace"], kb.VALID_STATUSES, ["maintainer"])
    files = projection.render()
    assert projection.accepted(projection.events[s["event_id"]])
    assert projection.state(projection.events[c["event_id"]]) == "PASS"
    assert b"Maintained synthesis" in files[projection.topic_path("auth/issuer")]
    wiki.publish(env["workspace"] / ".swarm/wiki", files, inputs, env["workspace"])
    assert b"[original](" in files[projection.event_path(projection.events[c["event_id"]])]
    env["tree"].joinpath("issuer.md").write_text("Later node revision")
    # A retry returns its original committed publication, even if now stale.
    assert publish(env, "synthesis", "synth1", sdata)["duplicate"]


def test_project_membership_task_scope_and_reserved_payload_identity(wiki_env, monkeypatch):
    env = wiki_env
    env["actor"][0] = "outsider"
    assert not publish(env).get("ok")
    env["actor"][0] = "opnory-builder"
    monkeypatch.setenv("HERMES_KANBAN_TASK", "different-task")
    assert not publish(env).get("ok")
    monkeypatch.delenv("HERMES_KANBAN_TASK")
    assert not publish(env, data={"assertion": "a", "scope": "b", "actor": "fake"}).get("ok")
    assert not publish(env, kind="artifact").get("ok")


def test_synthesis_requires_complete_current_sources_and_routing_is_configured(wiki_env):
    env = wiki_env
    first = publish(env)
    assert first.get("ok"), first
    records = env["mod"]._wiki_records()
    (env["tree"] / "summary.md").write_text("Curated summary")
    env["actor"][0] = "maintainer"
    data = {"node_path": "summary.md", "node_sha256": records.byte_hash((env["tree"] / "summary.md").read_bytes()),
            "source_digests": {"missing-event": "a" * 64}, "category": "architecture"}
    assert not publish(env, "synthesis", "s", data).get("ok")
    assert not publish(env, "route", "badroute", {"role": "builder", "outcome": "ROUTE_RESOLVED", "target_profile": "guessed"}).get("ok")
    assert publish(env, "route", "route1", {"role": "builder", "outcome": "ROUTE_RESOLVED", "target_profile": "opnory-builder"})["ok"]


def test_manifest_and_registration_expose_exactly_the_five_tools(wiki_env):
    registrations = {}
    class Context:
        def register_tool(self, **kwargs):
            registrations[kwargs["name"]] = kwargs
    wiki_env["mod"].register(Context())
    assert set(registrations) == {"swarm_request", "swarm_verify", "swarm_route", "swarm_publish", "swarm_capture"}
    assert all(r["toolset"] == "swarm" for r in registrations.values())


def test_supersession_cannot_hide_another_authors_claim(wiki_env):
    env = wiki_env
    original = publish(env)
    env["actor"][0] = "opnory-verifier"
    correction = {"assertion": "Narrowed assertion", "scope": "tenant", "supersedes": original["event_id"]}
    assert not publish(env, key="correction", data=correction).get("ok")
    env["actor"][0] = "opnory-builder"
    assert publish(env, key="correction", data=correction)["ok"]
