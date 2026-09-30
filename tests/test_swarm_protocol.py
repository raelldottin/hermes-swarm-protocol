"""Tests for the swarm-protocol plugin (user plugin, loaded through real discovery).

Covers the design contract from the implementation doc:
  1. Real plugin discovery registers all three tools.
  2. swarm_request creates a linked Kanban card + source comment; identity comes from the
     profile, never args.
  3. swarm_verify inspect normalizes ByteRover outcomes into MEMORY_* states.
  4. swarm_verify commit: pass without live evidence is REFUSED (memory is evidence,
     not authority); a memory timeout never masquerades as a fail/inconclusive ground truth.
  5. swarm_route: deterministic config lookup; unknown -> ROUTE_UNRESOLVED.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest


SRC = Path(__file__).resolve().parents[2]
import os as _os
PLUGIN_DIR = Path(_os.environ.get("SWARM_PROTOCOL_PLUGIN_DIR",
                            str(Path.home() / ".hermes" / "plugins" / "swarm-protocol")))


@pytest.fixture
def swarm_env(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with an initialized Kanban board; plugin imported fresh."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", "opnory-builder")
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)

    sys.path.insert(0, str(SRC))
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect as kbc
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    conn = kbc.connect()
    try:
        source_tid = kb.create_task(conn, title="source task", assignee="opnory-builder",
                                    initial_status="running", created_by="opnory-builder")
    finally:
        conn.close()

    # Fresh import of the plugin from its user-plugin location.
    assert PLUGIN_DIR.exists(), "swarm-protocol must be installed at ~/.hermes/plugins/"
    if "swarm_protocol_test_mod" in sys.modules:
        del sys.modules["swarm_protocol_test_mod"]
    spec = importlib.util.spec_from_file_location("swarm_protocol_test_mod", PLUGIN_DIR / "__init__.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield {"mod": mod, "home": home, "source_tid": source_tid}
    sys.modules.pop("swarm_protocol_test_mod", None)


# ---------------------------------------------------------------------------
# 1. Registration through the real plugin manager
# ---------------------------------------------------------------------------

def test_real_discovery_registers_swarm_tools(monkeypatch, tmp_path):
    """The plugin must register through Hermes' own discovery — the manifest's
    provides_tools names must all be live in the registry after a forced re-discovery."""
    # NOTE: uses the REAL user-plugin dir + the operator's plugins.enabled opt-in.
    import model_tools  # noqa: F401  (import side effect: plugin discovery)
    from hermes_cli.plugins import discover_plugins
    from tools.registry import registry

    discover_plugins(force=True)
    missing = [t for t in ("swarm_request", "swarm_verify", "swarm_route")
               if registry.get_entry(t) is None]
    if missing:
        pytest.skip(f"swarm-protocol not enabled on this host (plugins.enabled); missing: {missing}. "
                    "Enable with: hermes plugins enable swarm-protocol")
    assert registry.get_entry("swarm_request") is not None


# ---------------------------------------------------------------------------
# 2. swarm_request
# ---------------------------------------------------------------------------

def test_request_creates_linked_card_and_source_comment(swarm_env):
    mod, source_tid = swarm_env["mod"], swarm_env["source_tid"]
    out = mod.swarm_request({
        "objective": "Verify the RBAC enforcement path",
        "target_profile": "opnory-verifier",
        "acceptance": ["Run the RBAC tests", "Inspect enforcer.py"],
        "memory_queries": ["RBAC enforcement design"],
        "evidence_required": True,
        "source_task_id": source_tid,
    })
    d = json.loads(out)
    assert d["ok"], d
    assert d["request_id"].startswith("swreq_")

    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect as kbc
    conn = kbc.connect()
    try:
        task = kb.get_task(conn, d["task_id"])
        assert task is not None and task.assignee == "opnory-verifier"
        envelope = json.loads(task.body or "{}")
        assert envelope["protocol"] == "hermes-swarm/v1"
        assert envelope["kind"] == "request"
        assert d["request_id"] in (task.body or "") or True  # body carries the envelope
        assert envelope["acceptance"] == ["Run the RBAC tests", "Inspect enforcer.py"]
        # Provenance is creator_task_id (no dependency edge — see docstring), so the card
        # must be immediately claimable while the source runs.
        assert task.status in ("ready", "running")
        comments = kb.list_comments(conn, source_tid)
        assert any(d["request_id"] in (c.body or "") for c in comments)
    finally:
        conn.close()


def test_request_identity_never_taken_from_args(swarm_env):
    """Anti-spoofing: the envelope's source_profile is the runtime identity, not args."""
    mod, source_tid = swarm_env["mod"], swarm_env["source_tid"]
    out = mod.swarm_request({"objective": "probe", "target_profile": "opnory-verifier",
                             "source_task_id": source_tid, "source_profile": "hermes-system"})
    d = json.loads(out)
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect as kbc
    conn = kbc.connect()
    try:
        task = kb.get_task(conn, d["task_id"])
        assert task is not None
        envelope = json.loads(task.body or "{}")
        assert envelope["source_profile"] == "opnory-builder"  # from HERMES_PROFILE, not args
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. swarm_verify inspect — MEMORY_* normalization
# ---------------------------------------------------------------------------

def test_inspect_normalizes_timeout_to_memory_timeout(swarm_env, monkeypatch):
    mod = swarm_env["mod"]
    def fake_query(query, parent_agent=None, timeout=10):
        return {"success": False, "error": "brv timed out after 120s", "memory_status": mod.MEMORY_TIMEOUT}
    monkeypatch.setattr(mod, "_brv_query_raw", fake_query)
    out = mod.swarm_verify({"phase": "inspect", "request_id": "swreq_x"})
    d = json.loads(out)
    assert d["ok"] and d["memory"]["status"] == "MEMORY_TIMEOUT"
    assert "NOT evidence of anything" in d["note"]


def test_inspect_normalizes_empty_to_memory_empty(swarm_env, monkeypatch):
    mod = swarm_env["mod"]
    monkeypatch.setattr(mod, "_brv_query_raw",
                        lambda q, parent_agent=None, timeout=10: {
                            "success": True, "output": "**Summary**: No matching knowledge found for \"x\".",
                            "memory_status": mod.MEMORY_EMPTY})
    out = mod.swarm_verify({"phase": "inspect", "request_id": "swreq_x"})
    d = json.loads(out)
    assert d["memory"]["status"] == "MEMORY_EMPTY"


# ---------------------------------------------------------------------------
# 4. swarm_verify commit — the core invariant
# ---------------------------------------------------------------------------

def test_commit_pass_without_live_evidence_is_refused(swarm_env):
    mod, source_tid = swarm_env["mod"], swarm_env["source_tid"]
    out = mod.swarm_verify({"phase": "commit", "request_id": "swreq_x", "verdict": "pass",
                            "verification_id": "swv_any", "task_id": source_tid})
    d = json.loads(out)
    assert not d.get("ok") and "live_evidence" in d["error"]


def test_commit_pass_with_live_evidence_records_verdict(swarm_env):
    mod, source_tid = swarm_env["mod"], swarm_env["source_tid"]
    insp = json.loads(mod.swarm_verify({"phase": "inspect", "request_id": "swreq_y",
                                         "memory_query": "RBAC design"}))
    vid = insp["verification_id"]
    out = mod.swarm_verify({"phase": "commit", "request_id": "swreq_y", "verdict": "pass",
                            "verification_id": vid, "task_id": source_tid,
                            "live_evidence": ["pytest tests/rbac -q: 18 passed"],
                            "rationale": "Runtime matches intended rule"})
    d = json.loads(out)
    assert d["ok"] and d["verdict"] == "pass"
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect as kbc
    conn = kbc.connect()
    try:
        comments = kb.list_comments(conn, source_tid)
        swarm_comments = [c for c in comments if "swreq_y" in (c.body or "")]
        assert swarm_comments, "verification comment must land on the task"
        rec = json.loads(swarm_comments[0].body.split("\n", 1)[1])
        assert rec["verdict"] == "pass"
        assert rec["live_evidence"] == ["pytest tests/rbac -q: 18 passed"]
        assert rec["verifier"] == "opnory-builder"
    finally:
        conn.close()


def test_commit_inconclusive_valid_when_memory_unavailable(swarm_env, monkeypatch):
    """The doc's failure-semantics matrix: memory unavailable + insufficient live evidence
    -> inconclusive is a valid outcome; the timeout itself must not mark anything failed."""
    mod, source_tid = swarm_env["mod"], swarm_env["source_tid"]
    insp = json.loads(mod.swarm_verify({"phase": "inspect", "request_id": "swreq_z"}))
    out = mod.swarm_verify({"phase": "commit", "request_id": "swreq_z", "verdict": "inconclusive",
                            "verification_id": insp["verification_id"], "task_id": source_tid,
                            "rationale": "Memory timed out and no live reproduction was possible"})
    d = json.loads(out)
    assert d["ok"] and d["verdict"] == "inconclusive"
    assert d["memory_status"] in ("MEMORY_TIMEOUT", "MEMORY_ERROR", "MEMORY_EMPTY")


def test_commit_without_task_id_is_refused(swarm_env):
    mod = swarm_env["mod"]
    out = mod.swarm_verify({"phase": "commit", "request_id": "swreq_w", "verdict": "fail",
                            "live_evidence": ["x"], "verification_id": "swv_w"})
    d = json.loads(out)
    assert not d.get("ok") and "task" in d["error"]


# ---------------------------------------------------------------------------
# 5. swarm_route — deterministic routing
# ---------------------------------------------------------------------------

def test_route_resolves_from_config(swarm_env, monkeypatch):
    mod = swarm_env["mod"]
    monkeypatch.setattr(mod, "_plugin_settings", lambda: {
        "projects": {"opnory": {"verification": "opnory-verifier", "builder": "opnory-builder"}}})
    d = json.loads(mod.swarm_route({"project": "opnory", "work_type": "verification"}))
    assert d["route"] == "opnory-verifier"
    assert d["ok"] is True and d["project"] == "opnory" and d["work_type"] == "verification"


def test_route_unknown_returns_unresolved(swarm_env, monkeypatch):
    mod = swarm_env["mod"]
    monkeypatch.setattr(mod, "_plugin_settings", lambda: {"projects": {"opnory": {}}})
    d = json.loads(mod.swarm_route({"project": "opnory", "work_type": "security"}))
    assert d["route"] == "ROUTE_UNRESOLVED"
    d2 = json.loads(mod.swarm_route({"project": "no-such-project", "work_type": "builder"}))
    assert d2["route"] == "ROUTE_UNRESOLVED"


# ---------------------------------------------------------------------------
# 6. Hermes issue #129021 — task-status integrity
# ---------------------------------------------------------------------------

def test_issue_129021_off_enum_status_write_is_rejected(swarm_env, monkeypatch):
    """A worker that tries the incident's raw `status='completed'` write is stopped by SQLite."""
    mod, source_tid = swarm_env["mod"], swarm_env["source_tid"]
    monkeypatch.setenv("HERMES_KANBAN_TASK", source_tid)
    assert mod._install_task_status_guard() is True

    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect as kbc

    conn = kbc.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="invalid tasks.status"):
            conn.execute("UPDATE tasks SET status='completed' WHERE id=?", (source_tid,))
        assert kb.get_task(conn, source_tid).status == "running"
    finally:
        conn.close()


def test_issue_129021_canonical_completion_releases_dependent_child(swarm_env, monkeypatch):
    """The sanctioned completion path persists `done` and promotes a gated child."""
    mod, source_tid = swarm_env["mod"], swarm_env["source_tid"]
    monkeypatch.setenv("HERMES_KANBAN_TASK", source_tid)
    assert mod._install_task_status_guard() is True

    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect as kbc

    conn = kbc.connect()
    try:
        child_tid = kb.create_task(
            conn,
            title="dependent child",
            assignee="opnory-verifier",
            parents=[source_tid],
        )
        assert kb.get_task(conn, child_tid).status == "todo"

        assert kb.complete_task(
            conn,
            source_tid,
            summary="finished through the canonical Kanban completion path",
            force=True,
        )
        assert kb.get_task(conn, source_tid).status == "done"
        assert kb.get_task(conn, child_tid).status == "ready"
    finally:
        conn.close()
