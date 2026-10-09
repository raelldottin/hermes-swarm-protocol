"""Runner invariants; live fleet acceptance uses the actual isolated CLI probes."""
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from test_swarm_protocol import swarm_env


@pytest.mark.parametrize("status,runs", [("queued", []), ("running", [object()]), ("blocked", [object()]), ("done", [])])
def test_canary_rejects_runnable_or_dispatched_creation(status, runs):
    with pytest.raises(RuntimeError):
        canary.creation_observation(SimpleNamespace(status=status), runs)


def test_canary_observes_blocked_creation_and_honest_completed_reuse():
    new = canary.creation_observation(SimpleNamespace(status="blocked"), [])
    assert new["observed_blocked_no_runs"] and not new["reused_completed"]
    reused = canary.creation_observation(SimpleNamespace(status="done"), [object()], existed_before=True)
    assert reused["reused_completed"] and not reused["observed_blocked_no_runs"]


def test_completion_reads_public_task_dataclass(swarm_env):
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc

    result = canary.actor_action(SimpleNamespace(), {
        "action": "complete", "board": None, "task_id": swarm_env["source_tid"],
    })
    assert result == {"ok": True}
    conn = kbc.connect()
    try:
        assert kb.get_task(conn, swarm_env["source_tid"]).status == "done"
    finally:
        conn.close()


def test_real_hermes_rejection_envelope_remains_an_explicit_denial(swarm_env):
    result = canary.sanitized_tool_reply(swarm_env["mod"]._reject("private diagnostic"))
    assert result == {"ok": False, "error_reported": True}
    assert canary.require_reply({"reply": result}, accepted=False) == result
    assert "private diagnostic" not in json.dumps(result)


@pytest.mark.parametrize("reply", [{}, {"error": ""}, {"error": {}}, {"ok": True, "error": "conflict"}])
def test_ambiguous_response_cannot_prove_rejection(reply):
    with pytest.raises(RuntimeError):
        sanitized = canary.sanitized_tool_reply(reply)
        canary.require_reply({"reply": sanitized}, accepted=False)

SPEC = importlib.util.spec_from_file_location("fleet_canary", Path(__file__).parents[1] / "ops/fleet_canary.py")
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


def options(tmp_path):
    return SimpleNamespace(python="python", hermes_root=str(tmp_path / ".hermes"),
                           agent_root=str(tmp_path / "agent"), release_sha="a" * 40)


def test_isolation_removes_inherited_task_and_plugin_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_KANBAN_DB", "unrelated.db")
    monkeypatch.setenv("HERMES_KANBAN_TASK", "unrelated-task")
    monkeypatch.setenv("SWARM_PROTOCOL_PLUGIN_DIR", "dirty-checkout")
    monkeypatch.setenv("TEST_PROVIDER_SECRET", "keep-runtime-only")
    env = canary.isolated_env(tmp_path / ".hermes", tmp_path / "agent", "la-verifier")
    assert env["HERMES_HOME"] == str(tmp_path / ".hermes/profiles/la-verifier")
    assert env["HERMES_PROFILE"] == env["HERMES_PROFILE_NAME"] == "la-verifier"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["TEST_PROVIDER_SECRET"] == "keep-runtime-only"
    assert not any(k.startswith("HERMES_KANBAN_") for k in env)
    assert "SWARM_PROTOCOL_PLUGIN_DIR" not in env
    with pytest.raises(ValueError):
        canary.isolated_env(tmp_path, tmp_path, "../../other")


def test_child_accepts_only_one_marked_result_without_leaking_logs(monkeypatch, tmp_path):
    captured = {}
    def run(cmd, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='diagnostic-private\n' + canary.MARKER + '{"ok":true,"profile":"default"}\n', stderr="private")
    monkeypatch.setattr(canary.subprocess, "run", run)
    assert canary.child(options(tmp_path), "default", "_probe") == {"ok": True, "profile": "default"}
    assert captured["env"]["HERMES_HOME"] == str(tmp_path / ".hermes")
    monkeypatch.setattr(canary.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=canary.MARKER + '{"ok":true}\n' + canary.MARKER + '{"ok":true}\n'))
    with pytest.raises(RuntimeError, match="exactly one"):
        canary.child(options(tmp_path), "default", "_probe")


def test_preexisting_row_fingerprints_allow_only_additions(tmp_path):
    path = tmp_path / "board.db"
    conn = sqlite3.connect(path)
    for table in canary.TABLES:
        conn.execute('CREATE TABLE "' + table + '" (id TEXT PRIMARY KEY, content TEXT)')
        conn.execute('INSERT INTO "' + table + '" VALUES (?, ?)', ("old", "original"))
    conn.commit()
    before = canary.board_snapshot(path)
    conn.execute('INSERT INTO task_comments VALUES (?, ?)', ("new", "canary"))
    conn.commit()
    report = canary.preserved(before, canary.board_snapshot(path))
    assert report["task_comments"] == {"before": 1, "after": 2}
    conn.execute('UPDATE tasks SET content=? WHERE id=?', ("changed", "old"))
    conn.commit()
    with pytest.raises(RuntimeError, match="pre-existing"):
        canary.preserved(before, canary.board_snapshot(path))
    conn.close()


def test_verifier_requires_fresh_runtime_and_both_original_and_raw_bytes(tmp_path):
    fixture = {"configuration": {"board": "hsp"}, "release_sha": "a" * 40}
    source, raw = tmp_path / "fixture.json", tmp_path / "raw.json"
    content = canary.encoded(fixture)
    source.write_bytes(content)
    raw.write_bytes(content)
    reference = {"sha256": canary.digest(content)}
    canary.fresh_evidence_check(fixture, source, raw, reference)
    with pytest.raises(RuntimeError, match="fresh runtime"):
        canary.fresh_evidence_check(dict(fixture, release_sha="b" * 40), source, raw, reference)
    raw.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="fresh runtime"):
        canary.fresh_evidence_check(fixture, source, raw, reference)
    raw.write_bytes(content)
    source.unlink()
    source.symlink_to(raw)
    with pytest.raises(RuntimeError, match="fresh runtime"):
        canary.fresh_evidence_check(fixture, source, raw, reference)


def test_profile_report_requires_actual_deadlines_identity_and_authorization(monkeypatch, tmp_path):
    opts = options(tmp_path)
    fleet = {"board": "hsp", "project_key": "p", "profiles": ["default", "hsp-verifier"],
             "workspace": "/repo", "repo": "/repo", "knowledge_tree": "/knowledge",
             "task_workspace_root": "/tasks", "task_workspace_root_exists": True,
             "proposed_maintainers": ["default"]}
    mapping = canary.expected_mappings(opts, {"fleets": [fleet]})["p"]
    origin = str((Path(opts.hermes_root) / "releases/swarm-protocol" / opts.release_sha / "hermes_swarm_protocol/__init__.py").resolve())
    def good(options, profile, *args):
        return {"profile": profile, "plugin_origin": origin, "provider_curate_timeout": 600,
                "plugin_curate_timeout": 600, "provider_auto_extract": profile != "default",
                "wiki_projects": {"p": mapping}}
    monkeypatch.setattr(canary, "child", good)
    assert canary.profile_report(opts, {"fleets": [fleet]})["profile_count"] == 2
    def wrong(options, profile, *args):
        result = good(options, profile)
        result["provider_curate_timeout"] = 120
        return result
    monkeypatch.setattr(canary, "child", wrong)
    with pytest.raises(RuntimeError, match="deadline"):
        canary.profile_report(opts, {"fleets": [fleet]})


def test_failure_json_does_not_echo_runtime_exception_or_credentials(monkeypatch, capsys):
    def fail(*args):
        raise RuntimeError("private credential detail")
    monkeypatch.setattr(canary, "runtime_probe", fail)
    assert canary.main(["_probe", "--release-sha", "a" * 40]) == 1
    output = capsys.readouterr().out
    assert "private" not in output
    assert json.loads(output.removeprefix(canary.MARKER))["error_type"] == "RuntimeError"


def test_board_plan_is_read_only_and_keeps_explicit_shared_tree_board(monkeypatch, tmp_path):
    opts = options(tmp_path)
    opts.board, opts.execute = "home-lab", False
    cfg = {"board": "home-lab", "workspace": str(tmp_path / "home_lab"),
           "repo": str(tmp_path / "home_lab"), "knowledge_tree": "/knowledge/opnory", "task_workspaces": [],
           "profiles": ["home-lab"], "maintainers": ["default"]}
    report = {"release_sha": opts.release_sha, "plugin_origin": "/release/__init__.py", "origin_sha256": "b" * 64,
              "profile": "default", "tools": list(canary.TOOLS), "wiki_projects": {"home-lab": cfg},
              "provider_curate_timeout": 600, "plugin_curate_timeout": 600, "provider_auto_extract": False}
    monkeypatch.setattr(canary, "child", lambda *a, **k: report)
    monkeypatch.setattr(canary, "board_snapshot", lambda *a: pytest.fail("plan read canonical board"))
    fleet = {"board": "home-lab", "project_key": "home-lab", "profiles": ["home-lab"],
             "workspace": cfg["workspace"], "repo": cfg["repo"], "knowledge_tree": cfg["knowledge_tree"],
             "task_workspace_root": "/missing", "task_workspace_root_exists": False,
             "proposed_maintainers": ["default"]}
    result = canary.board_canary(opts, {"fleets": [fleet]})
    assert not result["executed"]
    assert result["plan"]["board"] == result["plan"]["project"] == "home-lab"
    assert not (tmp_path / "home_lab").exists()


def test_tool_rejection_cannot_be_inferred_from_malformed_response():
    with pytest.raises(RuntimeError):
        canary.require_reply({"reply": {}}, accepted=False)
    assert canary.require_reply({"reply": {"ok": False}}, accepted=False) == {"ok": False}


def test_owned_mapping_checks_cover_authorization_unions_and_preserve_custom_keys(tmp_path):
    opts = options(tmp_path)
    fleet = {"board": "home-lab", "project_key": "home-lab", "profiles": ["home-lab"],
             "existing_role_profiles": ["opnory-verifier"], "workspace": "/home_lab", "repo": "/home_lab",
             "knowledge_tree": "/knowledge/opnory", "task_workspace_root": "/tasks", "task_workspace_root_exists": True,
             "proposed_maintainers": ["default"]}
    reviewed = tmp_path / "plan.json"
    mappings = canary.expected_mappings(opts, {"fleets": [fleet]})
    reviewed.write_text(json.dumps({"inventory": mappings}))
    opts.reviewed_plan = str(reviewed)
    assert canary.expected_mappings(opts, {"fleets": [fleet]}) == mappings
    report = {"wiki_projects": {"home-lab": dict(mappings["home-lab"], preserved_custom_option=True)}}
    canary.check_project_mappings(report, "opnory-verifier", mappings)
    for field, value in [("repo", "/other"), ("task_workspaces", ["/broader"]), ("profiles", ["home-lab"]), ("maintainers", ["default", "outsider"])]:
        changed = json.loads(json.dumps(report))
        changed["wiki_projects"]["home-lab"][field] = value
        with pytest.raises(RuntimeError, match="owned fleet"):
            canary.check_project_mappings(changed, "opnory-verifier", mappings)
    with pytest.raises(RuntimeError, match="project set"):
        canary.check_project_mappings({"wiki_projects": dict(report["wiki_projects"], unintended={})}, "default", mappings)


def test_denials_require_zero_changes_on_intended_and_foreign_boards_and_raw(tmp_path):
    fleets = []
    for board in ["intended", "foreign"]:
        path = tmp_path / (board + ".db")
        conn = sqlite3.connect(path)
        for table in canary.TABLES:
            conn.execute('CREATE TABLE "' + table + '" (id TEXT PRIMARY KEY, content TEXT)')
            conn.execute('INSERT INTO "' + table + '" VALUES (?, ?)', ("old", "original"))
        conn.commit()
        conn.close()
        fleets.append({"board": board, "project_key": board, "task_source": str(path), "workspace": str(tmp_path / board)})
    inventory = {"fleets": fleets}
    rejected = lambda: {"reply": {"ok": False}}
    proof = canary.rejected_without_changes(rejected, inventory)
    assert proof == {"zero_persisted_writes": True, "boards_checked": 2, "raw_roots_checked": 2}
    def bad_board_rejection():
        conn = sqlite3.connect(fleets[1]["task_source"])
        conn.execute('INSERT INTO task_comments VALUES (?, ?)', ("unexpected", "denied write"))
        conn.commit()
        conn.close()
        return rejected()
    with pytest.raises(RuntimeError, match="denied operation changed"):
        canary.rejected_without_changes(bad_board_rejection, inventory)
    def bad_raw_rejection():
        root = Path(fleets[1]["workspace"]) / ".swarm/raw"
        root.mkdir(parents=True)
        (root / "unexpected.json").write_text("denied write")
        return rejected()
    with pytest.raises(RuntimeError, match="denied operation changed"):
        canary.rejected_without_changes(bad_raw_rejection, inventory)
@pytest.mark.parametrize("reply", [
    {"error": "denied", "ok": 1},
    {"error": "denied", "ok": "true"},
    {"error": "denied", "evidence": {}},
    {"error": "denied", "event_id": "event"},
])
def test_mixed_rejection_envelopes_are_ambiguous(reply):
    with pytest.raises(RuntimeError):
        canary.sanitized_tool_reply(reply)
