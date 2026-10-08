"""Audit corrections must preserve historical unknowns and exact acceptance scope."""
import json
import sqlite3
import subprocess
import pytest
from test_swarm_wiki import project, add, build, classes
from test_swarm_wiki_plugin import wiki_env, publish
from test_swarm_protocol import swarm_env
import wiki_records as records

def task_subject(project, actor=None):
    with sqlite3.connect(project["db"]) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("UPDATE tasks SET created_by=? WHERE id='t1'", (actor,))
        row = dict(conn.execute("SELECT * FROM tasks WHERE id='t1'").fetchone())
    return {"kind": "task", "id": "t1", "board": "fixture", "sha256": records.digest(row)}

def test_task_creator_disclosure_preserves_unknown_and_clears_both_findings(project):
    subject = task_subject(project)
    event = annotation(project, subject, "unknown_disclosure")
    p, files, _ = build(project)
    findings = [f for f in p.findings if f["target"] in {"t1", "tasks/t1"}]
    assert len(findings) == 2
    assert all(f["outcome"] == "disclosed_unknown" for f in findings)
    assert all(f["correction_event_id"] == event["event_id"] for f in findings)
    assert not p.unresolved_findings
    with sqlite3.connect(project["db"]) as conn:
        assert conn.execute("SELECT created_by FROM tasks WHERE id='t1'").fetchone()[0] is None

@pytest.mark.parametrize("change", ["board", "hash", "known_actor", "invented_actor"])
def test_task_creator_annotation_fails_closed(project, change):
    subject = task_subject(project, "builder" if change == "known_actor" else None)
    if change == "board": subject["board"] = "other"
    if change == "hash": subject["sha256"] = "0" * 64
    annotation(project, subject, "actor_attribution" if change == "invented_actor" else "unknown_disclosure",
               **({"attributed_actor": "guessed"} if change == "invented_actor" else {}))
    p, _, _ = build(project)
    assert "invalid-audit-record" in classes(p)

def test_changed_task_revision_invalidates_creator_annotation(project):
    annotation(project, task_subject(project), "unknown_disclosure")
    with sqlite3.connect(project["db"]) as conn:
        conn.execute("UPDATE tasks SET status='done' WHERE id='t1'")
    p, _, _ = build(project)
    assert "invalid-audit-record" in classes(p)
    assert p.unresolved_findings

def test_valid_successor_retires_changed_revision_annotation_without_erasing_history(project):
    old = annotation(project, task_subject(project), "unknown_disclosure")
    with sqlite3.connect(project["db"]) as conn:
        conn.execute("UPDATE tasks SET status='done' WHERE id='t1'")
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM tasks WHERE id='t1'").fetchone())
    new = annotation(project, {"kind":"task","id":"t1","board":"fixture","sha256":records.digest(row)},
                     "unknown_disclosure", time=21, supersedes=old["event_id"])
    p, files, _ = build(project)
    stale = next(f for f in p.findings if f["target"] == old["event_id"])
    assert stale["outcome"] == "superseded_history"
    assert stale["correction_event_id"] == new["event_id"]
    assert not p.unresolved_findings
    assert old["event_id"] in p.events and new["event_id"] in p.events

def test_invalid_successor_cannot_retire_invalid_source_annotation(project):
    old = annotation(project, task_subject(project), "unknown_disclosure")
    annotation(project, {"kind":"task","id":"t1","board":"fixture","sha256":"0"*64},
               "unknown_disclosure", time=21, supersedes=old["event_id"])
    with sqlite3.connect(project["db"]) as conn:
        conn.execute("UPDATE tasks SET status='done' WHERE id='t1'")
    p, _, _ = build(project)
    assert all(f["outcome"] == "unresolved" for f in p.findings if f["class"] == "invalid-audit-record")
    assert p.unresolved_findings

def test_manifest_declares_standalone_addon():
    from pathlib import Path
    import yaml
    manifest = yaml.safe_load((Path(__file__).parents[1]/"hermes_swarm_protocol/plugin.yaml").read_text())
    assert manifest["kind"] == "standalone"
    assert manifest["version"] == "1.2.0"

def test_cli_succeeds_for_disclosed_history_and_fails_for_stale_annotation(project):
    from pathlib import Path
    import sys
    annotation(project, task_subject(project), "unknown_disclosure")
    command = [sys.executable, str(Path(__file__).parents[1]/"ops/build_wiki.py"),
               "--board", "fixture", "--project", "p", "--maintainer", "maintainer"]
    for name in ["workspace", "db", "tree", "raw", "rules"]:
        command.extend(["--"+name, str(project[name])])
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["unresolved_findings"] == 0
    assert summary["audit_outcomes"]["disclosed_unknown"] == 2
    assert subprocess.run(command+["--check"], capture_output=True).returncode == 0
    with sqlite3.connect(project["db"]) as conn:
        conn.execute("UPDATE tasks SET status='done' WHERE id='t1'")
    assert subprocess.run(command, capture_output=True).returncode == 1


def node_subject(project, name="context.md"):
    (project["tree"] / name).write_text("Historical context, not live proof")
    return {"kind": "knowledge", "path": name, "sha256": records.file_hash(project["tree"], name)}


def annotation(project, subject, relation, time=20, **fields):
    return add(project, "provenance", {"subject": subject, "relation": relation, "rationale": "Reviewed original revision", **fields}, actor="maintainer", time=time)


def event_subject(project, kind="promoted", payload="{}"):
    with sqlite3.connect(project["db"]) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO task_events VALUES (1,'t1',NULL,?,?,10)", (kind, payload))
        row = dict(conn.execute("SELECT * FROM task_events WHERE id=1").fetchone())
    return {"kind": "task_event", "id": 1, "board": "fixture", "sha256": records.digest(row)}


def legacy_request(project):
    from test_swarm_wiki import STATUSES
    STATUSES.add("archived")
    root = project["workspace"]
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    (root / "proof.txt").write_text("Original independent test output: 20 passed")
    subprocess.run(["git", "-C", str(root), "add", "proof.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "Frozen artifact"], check=True)
    sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    request = {"protocol": "hermes-swarm/v1", "kind": "request", "request_id": "req1", "target_profile": "builder", "evidence_required": True, "acceptance": ["Original artifact exists", "Original tests passed"]}
    with sqlite3.connect(project["db"]) as conn:
        conn.execute("UPDATE tasks SET body=?,status='archived' WHERE id='t1'", (json.dumps(request),))
    ref = records.capture(root, "proof.txt", "test-results")
    data = {"subject_task_id": "t1", "request_id": "req1", "request_digest": records.digest(request), "artifact_commit": sha,
            "scope": "request:req1@" + sha, "rationale": "Independent frozen-artifact assessment", "verdict": "pass", "live_evidence": [ref],
            "acceptance_results": [{"index": i, "criterion_digest": records.digest(text), "verdict": "pass", "rationale": "Inspected original", "evidence": [ref]} for i, text in enumerate(request["acceptance"])]}
    return request, data, ref


def test_adoption_and_work_link_have_distinct_outcomes_and_never_invent_author(project):
    subject = node_subject(project)
    adopted = annotation(project, subject, "adoption")
    linked = annotation(project, subject, "work_link", time=21, source_task_ids=["t1"])
    p, files, _ = build(project)
    outcomes = {f["class"]: f["outcome"] for f in p.findings if f["target"] == "context.md"}
    assert outcomes == {"missing-provenance": "adopted_current_revision", "orphan-topic": "linked"}
    assert not p.unresolved_findings
    page = files[p.node_path("context.md")]
    assert b"UNKNOWN" in page and b"not original authorship" in page and b"UNVERIFIED" in page
    assert adopted["schema_version"] == 2 and linked["protocol"] == records.AUDIT_PROTOCOL
    assert len(p.render()) == len(files)  # Repeated renders must not duplicate findings.
    assert len(p.findings) == 2


def test_changed_node_invalidates_annotations_retains_original_records(project):
    subject = node_subject(project)
    a = annotation(project, subject, "adoption")
    annotation(project, subject, "work_link", time=21, source_task_ids=["t1"])
    (project["tree"] / "context.md").write_text("Changed revision")
    p, files, _ = build(project)
    assert p.event_path(a) in files
    assert "invalid-audit-record" in classes(p)
    assert {f["outcome"] for f in p.findings if f["target"] == "context.md"} == {"unresolved"}


def test_unknown_event_disclosure_is_not_historical_attribution(project):
    subject = event_subject(project)
    a = annotation(project, subject, "unknown_disclosure")
    p, files, _ = build(project)
    f = next(f for f in p.findings if f["target"] == "task_events/1")
    assert f["outcome"] == "disclosed_unknown" and f["correction_event_id"] == a["event_id"]
    assert b"UNKNOWN" in files["log.md"]
    assert not p.unresolved_findings
    annotation(project, subject, "actor_attribution", time=21, attributed_actor="dispatcher")
    p, _, _ = build(project)
    assert "invalid-audit-record" in classes(p)


@pytest.mark.parametrize("change", ["board", "hash", "author"])
def test_provenance_rejects_wrong_board_changed_subject_or_untrusted_author(project, change):
    subject = event_subject(project)
    if change == "board": subject["board"] = "other"
    if change == "hash": subject["sha256"] = "0" * 64
    event = annotation(project, subject, "unknown_disclosure") if change != "author" else add(project, "provenance", {"subject": subject, "relation": "unknown_disclosure", "rationale": "Claim"}, actor="builder")
    p, _, _ = build(project)
    assert not p.valid_audit(event)
    assert "invalid-audit-record" in classes(p)


def test_derivation_is_explicit_hash_bound_and_cycles_fail(project):
    a = node_subject(project, "a.md"); b = node_subject(project, "b.md")
    parent = lambda s: dict(s)
    first = annotation(project, a, "derivation", parent_revisions=[parent(b)])
    p, _, _ = build(project)
    assert p.valid_audit(first)
    second = annotation(project, b, "derivation", time=21, parent_revisions=[parent(a)])
    p, _, _ = build(project)
    assert not p.valid_audit(first) and not p.valid_audit(second)


def test_complete_independent_frozen_request_assessment_resolves_both_gaps(project):
    _, data, ref = legacy_request(project)
    event = add(project, "request_assessment", data, actor="verifier")
    p, files, _ = build(project)
    assert p.valid_audit(event)
    gaps = [f for f in p.findings if f["target"] == "t1"]
    assert {f["class"] for f in gaps} == {"knowledge-gap", "missing-independent-verification"}
    assert all(f["outcome"] == "verified" for f in gaps)
    assert b"Historical request independently assessed: PASS" in files[p.task_path("t1")]
    (project["raw"] / ref["path"]).unlink()
    p, _, _ = build(project)
    assert not p.valid_audit(event) and not p.request_assessment("t1")


@pytest.mark.parametrize("change", ["self", "creator", "partial", "duplicate", "criterion", "request", "scope", "memory"])
def test_request_assessment_fails_closed_on_independence_coverage_scope_and_memory(project, change):
    _, data, ref = legacy_request(project)
    actor = "verifier"
    if change in {"self", "creator"}: actor = "builder"
    if change == "partial": data["acceptance_results"].pop()
    if change == "duplicate": data["acceptance_results"][1]["index"] = 0
    if change == "criterion": data["acceptance_results"][0]["criterion_digest"] = "0" * 64
    if change == "request": data["request_digest"] = "0" * 64
    if change == "scope": data["scope"] = "today's worktree"
    if change == "memory":
        add(project, "artifact", {"capture": ref, "source_path": "proof.txt", "source_origin": "knowledge", "media_type": "text/plain"}, time=19)
    event = add(project, "request_assessment", data, actor=actor)
    p, _, _ = build(project)
    assert not p.valid_audit(event)
    assert not p.request_assessment("t1")
    assert "invalid-audit-record" in classes(p)


def test_later_fail_or_changed_request_cannot_reuse_old_pass(project):
    request, data, _ = legacy_request(project)
    first = add(project, "request_assessment", data, actor="verifier")
    other = json.loads(json.dumps(data)); other["verdict"] = "fail"; other["acceptance_results"][0]["verdict"] = "fail"
    add(project, "request_assessment", other, actor="other-verifier", time=21)
    p, _, _ = build(project)
    assert p.valid_audit(first) and not p.request_assessment("t1")
    request["acceptance"].append("New condition")
    with sqlite3.connect(project["db"]) as conn: conn.execute("UPDATE tasks SET body=? WHERE id='t1'", (json.dumps(request),))
    p, _, _ = build(project)
    assert not p.valid_audit(first)


def test_v1_and_v2_decode_strictly_and_prefix_cannot_hide_new_records(project):
    v1 = add(project, "claim", {"assertion": "Old claim", "scope": "old"})
    v2 = annotation(project, node_subject(project), "adoption", time=21)
    for event in [v1, v2]:
        prefix = records.AUDIT_PREFIX if event["schema_version"] == 2 else records.PREFIX
        row = {"body": prefix + records.canonical(event), "author": event["actor"], "task_id": event["task_id"]}
        assert records.decode_record(row) == event
    with pytest.raises(ValueError): records.decode_record({"body": records.PREFIX + records.canonical(v2), "author": v2["actor"], "task_id": "t1"})
    with pytest.raises(ValueError): records.payload("provenance", {"subject": {"kind": "knowledge", "path": "../escape", "sha256": "0"*64}, "relation": "adoption", "rationale": "No"})


def test_plugin_enforces_audit_board_and_maintainer_before_canonical_write(wiki_env):
    env = wiki_env
    (env["tree"] / "context.md").write_text("Original context")
    subject = {"kind": "knowledge", "path": "context.md", "sha256": records.byte_hash(b"Original context")}
    data = {"subject": subject, "relation": "adoption", "rationale": "Adopt current revision"}
    assert not publish(env, "provenance", "untrusted", data).get("ok")
    env["actor"][0] = "maintainer"
    assert not publish(env, "provenance", "no-board", data).get("ok")
    from hermes_cli import kanban_db_connect as kbc
    with kbc.connect() as conn:
        path = conn.execute("PRAGMA database_list").fetchone()[2]
    # Move the isolated legacy fixture into an explicit named board; explicit
    # connect(board=...) correctly does not route to the legacy default DB.
    board = "fixture"
    destination = env["home"] / "kanban/boards/fixture/kanban.db"
    destination.parent.mkdir(parents=True)
    with sqlite3.connect(path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    env["cfg"]["wiki_projects"]["p"]["board"] = board
    result = publish(env, "provenance", "trusted", data)
    assert result.get("ok"), result
    with kbc.connect(board=board) as conn:
        body = conn.execute("SELECT body FROM task_comments WHERE id=?", (result["comment_id"],)).fetchone()[0]
    assert body.startswith(records.AUDIT_PREFIX)
    assert publish(env, "provenance", "trusted", data)["duplicate"]
