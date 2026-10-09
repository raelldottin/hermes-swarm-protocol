"""Audit corrections must preserve historical unknowns and exact acceptance scope."""
import json
import sqlite3
import subprocess
import pytest
from test_swarm_wiki import project, add, build, classes
from test_swarm_wiki_plugin import wiki_env, publish
from test_swarm_protocol import swarm_env
import wiki_records as records
import wiki_compiler as wiki

def test_delayed_indexes_reopen_eight_findings_and_reviewed_corrections_restore_check(project):
    root = node_subject(project, "_index.md")
    original = records.capture(project["workspace"], "_index.md", "source-snapshots", source_root=project["tree"])
    original_bytes = (project["tree"] / "_index.md").read_bytes()
    adopted = annotation(project, root, "adoption")
    linked = annotation(project, root, "work_link", time=21, source_task_ids=["t1"])
    p, files, inputs = build(project)
    assert not p.unresolved_findings
    assert wiki.publish(project["out"], files, inputs, project["workspace"], False)
    assert wiki.publish(project["out"], files, inputs, project["workspace"], True)

    paths = ["_index.md", "curated_content/_index.md", "curated_content/general/_index.md"]
    for path in paths:
        file = project["tree"] / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("Delayed generated index: historical project context")
    p, files, inputs = build(project)
    assert len(p.unresolved_findings) == 8
    assert not wiki.publish(project["out"], files, inputs, project["workspace"], True)

    for i, path in enumerate(paths):
        subject = {"kind":"knowledge", "path":path,
                   "sha256":records.byte_hash((project["tree"]/path).read_bytes())}
        annotation(project, subject, "adoption", time=30+i*2,
                   **({"supersedes":adopted["event_id"]} if i==0 else {}))
        annotation(project, subject, "work_link", time=31+i*2, source_task_ids=["t1"],
                   **({"supersedes":linked["event_id"]} if i==0 else {}))
    p, files, inputs = build(project)
    assert not p.unresolved_findings
    assert len(p.findings) == 8
    assert sum(f["outcome"]=="superseded_history" for f in p.findings) == 2
    assert sum(f["outcome"]=="adopted_current_revision" for f in p.findings) == 3
    assert sum(f["outcome"]=="linked" for f in p.findings) == 3
    assert wiki.publish(project["out"], files, inputs, project["workspace"], False)
    assert wiki.publish(project["out"], files, inputs, project["workspace"], True)
    assert (project["raw"]/original["path"]).read_bytes() == original_bytes
    assert adopted["event_id"] in p.events and linked["event_id"] in p.events

def test_repeated_index_revisions_retire_stale_annotation_chains(project):
    prior = {}
    for generation in range(3):
        (project["tree"]/"_index.md").write_text("Reviewed generation " + str(generation))
        subject = {"kind":"knowledge", "path":"_index.md",
                   "sha256":records.byte_hash((project["tree"]/"_index.md").read_bytes())}
        for offset,relation in enumerate(["adoption", "work_link"]):
            fields = {"source_task_ids":["t1"]} if relation=="work_link" else {}
            if relation in prior: fields["supersedes"] = prior[relation]["event_id"]
            prior[relation] = annotation(project, subject, relation, time=20+generation*2+offset, **fields)
    p, _, _ = build(project)
    assert not p.unresolved_findings
    history = [f for f in p.findings if f["class"]=="invalid-audit-record"]
    assert len(history)==4
    assert all(f["outcome"]=="superseded_history" for f in history)
    assert {f["correction_event_id"] for f in history} == {e["event_id"] for e in prior.values()}

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


def synthesis_data(project, source_digests, path="context.md", **changes):
    sha = records.file_hash(project["tree"], path)
    return {"node_path": path, "node_sha256": sha, "source_digests": source_digests, "category": "investigations",
            "evidence": [{"kind": "knowledge", "path": path, "sha256": sha}], **changes}


def test_current_synthesis_retires_only_its_obsolete_node_revision_findings(project):
    subject = node_subject(project)
    captured = records.capture(project["workspace"], subject["path"], "source-snapshots", source_root=project["tree"])
    original = (project["raw"] / captured["path"]).read_bytes()
    artifact = add(project, "artifact", {"capture": captured, "source_path": subject["path"], "media_type": "text/markdown", "source_origin": "knowledge"}, key="source-artifact", time=18)
    sources = {artifact["event_id"]: artifact["payload_digest"]}
    prior = add(project, "synthesis", synthesis_data(project, sources), actor="maintainer", key="synthesis-old")
    assert build(project)[0].accepted(prior)
    (project["tree"] / subject["path"]).write_text("---\nrelated: [generated.md]\n---\nHistorical context, not live proof")
    (project["tree"] / "generated.md").write_text("Associated context, not independent verification")
    current = add(project, "synthesis", synthesis_data(project, sources, supersedes=prior["event_id"]), actor="maintainer", key="synthesis-current", time=30)
    before = project["db"].read_bytes()
    projection, files, inputs = build(project)
    historical = [f for f in projection.findings if f["target"] == prior["event_id"]]
    assert {f["class"] for f in historical} == {"stale-knowledge", "stale-reference"}
    assert all(f["outcome"] == "superseded_history" and f["correction_event_id"] == current["event_id"] for f in historical)
    assert prior["event_id"] in projection.events and current["event_id"] in projection.events
    assert projection.accepted(current)
    assert (project["raw"] / captured["path"]).read_bytes() == original
    assert project["db"].read_bytes() == before
    assert files == build(project)[1]


def synthesis_history_fixture(project, **prior_changes):
    subject = node_subject(project)
    captured = records.capture(project["workspace"], subject["path"], "source-snapshots", source_root=project["tree"])
    artifact = add(project, "artifact", {"capture": captured, "source_path": subject["path"], "media_type": "text/markdown", "source_origin": "knowledge"}, key="source-artifact", time=18)
    sources = {artifact["event_id"]: artifact["payload_digest"]}
    prior = add(project, "synthesis", synthesis_data(project, sources, **prior_changes), actor="maintainer", key="synthesis-old")
    (project["tree"] / subject["path"]).write_text("---\nrelated: []\n---\nHistorical context, not live proof")
    return prior, sources, captured


@pytest.mark.parametrize("invalid", ["author", "topic", "project", "type", "node_hash", "source_digest", "own_evidence", "source_capture"])
def test_invalid_synthesis_successor_cannot_retire_predecessor_findings(project, invalid):
    prior, sources, captured = synthesis_history_fixture(project)
    data = synthesis_data(project, sources, supersedes=prior["event_id"])
    actor, topic, kind = "maintainer", "auth/issuer", "synthesis"
    if invalid == "author":
        actor = "other-maintainer"  # even configured maintainer authority cannot change this chain's author
    elif invalid == "topic":
        topic = "another/topic"
    elif invalid == "node_hash":
        data["node_sha256"] = "0" * 64
    elif invalid == "source_digest":
        data["source_digests"] = {next(iter(sources)): "0" * 64}
    elif invalid == "own_evidence":
        data["evidence"] = prior["data"]["evidence"]
    elif invalid == "source_capture":
        path = project["raw"] / captured["path"]
        path.unlink()
        path.write_bytes(b"changed original capture")
    elif invalid == "type":
        kind, data = "claim", {"assertion": "Different type", "scope": "historical", "supersedes": prior["event_id"]}
    if invalid == "project":
        event = records.make_record("other-project", "t1", actor, "synthesis-current", topic, kind, data, 30)
        with sqlite3.connect(project["db"]) as conn:
            conn.execute("INSERT INTO task_comments(task_id,author,body,created_at) VALUES (?,?,?,?)", ("t1", actor, records.PREFIX + records.canonical(event), 30))
    else:
        add(project, kind, data, actor=actor, topic=topic, key="synthesis-current", time=30)
    projection = build(project, maintainers=("maintainer", "other-maintainer"))[0]
    historical = [f for f in projection.findings if f["target"] == prior["event_id"]]
    assert historical and all(f["outcome"] == "unresolved" for f in historical)


def test_synthesis_retirement_keeps_lost_original_artifact_finding_unresolved(project):
    subject = node_subject(project)
    extra = records.capture(project["workspace"], subject["path"], "test-results", source_root=project["tree"])
    prior, sources, _ = synthesis_history_fixture(project, evidence=[extra])
    (project["raw"] / extra["path"]).unlink()
    current = add(project, "synthesis", synthesis_data(project, sources, supersedes=prior["event_id"]), actor="maintainer", key="synthesis-current", time=30)
    projection = build(project)[0]
    historical = [f for f in projection.findings if f["target"] == prior["event_id"]]
    assert projection.accepted(current)
    assert next(f for f in historical if f["class"] == "stale-knowledge")["outcome"] == "superseded_history"
    lost = next(f for f in historical if f["class"] == "stale-reference")
    assert json.loads(lost["message"])["kind"] == "artifact"
    assert lost["outcome"] == "unresolved"


def test_synthesis_history_retirement_validates_full_chain_and_rejects_cycles(project):
    prior, sources, _ = synthesis_history_fixture(project)
    middle = add(project, "synthesis", synthesis_data(project, sources, supersedes=prior["event_id"]), actor="maintainer", key="synthesis-middle", time=30)
    (project["tree"] / "context.md").write_text("---\nrelated: []\ntitle: Historical context\n---\nHistorical context, not live proof")
    current = add(project, "synthesis", synthesis_data(project, sources, supersedes=middle["event_id"]), actor="maintainer", key="synthesis-current", time=40)
    projection = build(project)[0]
    historical = [f for f in projection.findings if f["target"] in {prior["event_id"], middle["event_id"]}]
    assert len(historical) == 4 and all(f["outcome"] == "superseded_history" and f["correction_event_id"] == current["event_id"] for f in historical)
    # Canonical event identity is publication-key based, allowing a fully hashed adversarial cycle.
    prior_data = dict(prior["data"], supersedes=middle["event_id"])
    cyclic_prior = records.make_record("p", "t1", "maintainer", "synthesis-old", "auth/issuer", "synthesis", prior_data, 20)
    with sqlite3.connect(project["db"]) as conn:
        conn.execute("UPDATE task_comments SET body=? WHERE body=?", (records.PREFIX + records.canonical(cyclic_prior), records.PREFIX + records.canonical(prior)))
    projection = build(project)[0]
    assert projection.accepted(current)
    historical = [f for f in projection.findings if f["target"] in {prior["event_id"], middle["event_id"]}]
    assert historical and all(f["outcome"] == "unresolved" for f in historical)


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
