"""swarm-protocol — coordination semantics over Kanban + ByteRover. No new storage.

Design contract (verified against tools/kanban_tools.py + hermes_cli/kanban_db.py):

  swarm_request  -> kb.create_task (linked child) + comment envelope. Worker A asks worker B.
  swarm_verify   -> two-stage: inspect (memory receipt, MEMORY_* status) then commit
                    (verdict + live evidence). A pass REQUIRES non-memory evidence; memory
                    alone is evidence, never authority.
  swarm_route    -> deterministic mapping from plugins.entries.swarm-protocol.settings
                    .projects.<project>.<work_type> -> profile. Unknown -> ROUTE_UNRESOLVED.

Identity: author/creator names come from hermes_cli.profiles.current_profile_name() — the
same source kanban_tools._persisted_identity() uses — never from tool args (anti-spoofing,
mirrors the #19713 comment-authorship guard).

Storage: none. Requests are Kanban cards; verification outcomes are comments + review state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.registry import tool_error

PROTOCOL = "hermes-swarm/v1"
logger = logging.getLogger(__name__)

# ByteRover outcome normalization (Phase 4 of the design): four explicit states so a
# timeout is never collapsed into "memory says no".
MEMORY_AVAILABLE = "MEMORY_AVAILABLE"
MEMORY_EMPTY = "MEMORY_EMPTY"
MEMORY_TIMEOUT = "MEMORY_TIMEOUT"
MEMORY_ERROR = "MEMORY_ERROR"

VERDICTS = ("pass", "fail", "inconclusive", "blocked")

# Hermes currently caps every ByteRover curate at 120s while ByteRover's own
# agentic task budget can run for ~10 minutes. Raise the Hermes-side floor so a
# healthy curate is not killed before ByteRover's own budget expires. This is
# deliberately monotonic: a future Hermes release with a larger timeout wins.
_DEFAULT_BRV_CURATE_TIMEOUT_SECONDS = 660
_MIN_BRV_CURATE_TIMEOUT_SECONDS = 120
_MAX_BRV_CURATE_TIMEOUT_SECONDS = 7200

# In-process receipts for two-stage verification: verification_id -> {request_id, issued_at,
# memory_status, digest}. Short-lived by construction (process-scoped); the durable record is
# the Kanban comment the commit phase writes. A restarted worker must re-inspect — that is the
# point of inspect-before-commit.
_receipts: Dict[str, Dict[str, Any]] = {}
_RECEIPT_TTL_SECONDS = 30 * 60


def _ok(**fields: Any) -> str:
    return json.dumps({"ok": True, **fields})


def _reject(message: str) -> str:
    return tool_error(f"swarm-protocol: {message}")


def _identity() -> str:
    """Trusted profile identity — never from tool args (anti-spoofing, #19713 pattern)."""
    from hermes_cli.profiles import current_profile_name
    return current_profile_name("worker") or "worker"


def _board(board: Optional[str] = None):
    """(kb, conn) context manager over the same env/symlink resolution chain as kanban tools."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        from hermes_cli import kanban_db as kb
        from hermes_cli import kanban_db_connect as kbc
        conn = kbc.connect(board=board)
        try:
            yield kb, conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return _ctx()


def _plugin_settings() -> Dict[str, Any]:
    """plugins.entries.swarm-protocol.settings from the CURRENT profile's config."""
    try:
        from hermes_cli.plugins_state import _plugin_settings_entry
        from hermes_cli.config import load_config
        entry = _plugin_settings_entry(load_config() or {}, "swarm-protocol")
        return dict((entry or {}).get("settings") or {})
    except Exception:
        return {}


def _active_memory_provider() -> str:
    """Return the configured external memory provider name, or an empty string."""
    try:
        from hermes_cli.config import load_config
        memory = (load_config() or {}).get("memory") or {}
        return str(memory.get("provider") or "").strip() if isinstance(memory, dict) else ""
    except Exception:
        return ""


def _configured_brv_curate_timeout() -> int:
    """Resolve the swarm ByteRover curate timeout floor from plugin settings."""
    raw = _plugin_settings().get(
        "byterover_curate_timeout_seconds", _DEFAULT_BRV_CURATE_TIMEOUT_SECONDS
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "swarm-protocol invalid byterover_curate_timeout_seconds=%r; using %ss",
            raw,
            _DEFAULT_BRV_CURATE_TIMEOUT_SECONDS,
        )
        value = _DEFAULT_BRV_CURATE_TIMEOUT_SECONDS
    return max(_MIN_BRV_CURATE_TIMEOUT_SECONDS, min(value, _MAX_BRV_CURATE_TIMEOUT_SECONDS))


def _patch_byterover_curate_timeout() -> bool:
    """Raise Hermes' process-wide ByteRover curate timeout floor when ByteRover is active.

    Hermes' bundled ByteRover provider reads its module-level curate timeout each time
    ByteRoverMemoryProvider._curate runs. Updating that module global therefore covers
    explicit brv_curate calls and automatic/background curations without replacing the
    provider or changing its storage topology.

    The patch only raises the value. A future upstream Hermes fix remains authoritative,
    and multiplexed profiles cannot shorten another profile's deadline.
    """
    if _active_memory_provider() != "byterover":
        return False
    try:
        from plugins.memory import byterover as brv

        current = getattr(brv, "_CURATE_TIMEOUT", None)
        if not isinstance(current, (int, float)):
            logger.warning(
                "swarm-protocol could not patch ByteRover curate timeout: "
                "plugins.memory.byterover._CURATE_TIMEOUT is unavailable"
            )
            return False

        requested = _configured_brv_curate_timeout()
        effective = max(int(current), requested)
        if effective != current:
            brv._CURATE_TIMEOUT = effective
            logger.info(
                "swarm-protocol raised ByteRover curate timeout from %ss to %ss",
                current,
                effective,
            )
        return True
    except Exception:
        logger.exception("swarm-protocol could not patch ByteRover curate timeout")
        return False


# ---------------------------------------------------------------------------
# Hermes Kanban task-status integrity (#129021 follow-up)
# ---------------------------------------------------------------------------

# Current Hermes releases already inject task-scoped Kanban lifecycle tools for
# dispatcher-owned workers. This plugin therefore does not patch worker toolset
# selection. It keeps only the independent defense-in-depth requested in #129021:
# make off-enum tasks.status writes fail at the SQLite boundary.
_STATUS_GUARD_TRIGGERS = (
    "hermes_swarm_tasks_status_insert_guard",
    "hermes_swarm_tasks_status_update_guard",
)


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _install_task_status_guard() -> bool:
    """Persist SQLite triggers that reject off-enum `tasks.status` writes.

    The trigger lives in the board database, so it also applies to accidental
    raw sqlite3 writes performed after plugin initialization. Existing invalid
    rows are reported but not guessed at or silently rewritten.
    """
    if not os.environ.get("HERMES_KANBAN_TASK"):
        return False

    try:
        from hermes_cli import kanban_db as kb
        from hermes_cli import kanban_db_connect as kbc

        valid = sorted(str(s) for s in kb.VALID_STATUSES)
        allowed_sql = ", ".join(_sql_string(s) for s in valid)
        placeholders = ", ".join("?" for _ in valid)

        conn = kbc.connect()
        try:
            invalid = conn.execute(
                f"SELECT id, status FROM tasks "
                f"WHERE status IS NULL OR status NOT IN ({placeholders}) "
                f"ORDER BY id",
                valid,
            ).fetchall()

            conn.execute("BEGIN IMMEDIATE")
            try:
                for trigger in _STATUS_GUARD_TRIGGERS:
                    conn.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
                conn.execute(
                    f"""
                    CREATE TRIGGER "{_STATUS_GUARD_TRIGGERS[0]}"
                    BEFORE INSERT ON tasks
                    FOR EACH ROW
                    WHEN NEW.status IS NULL OR NEW.status NOT IN ({allowed_sql})
                    BEGIN
                        SELECT RAISE(ABORT, 'hermes-swarm-protocol: invalid tasks.status');
                    END
                    """
                )
                conn.execute(
                    f"""
                    CREATE TRIGGER "{_STATUS_GUARD_TRIGGERS[1]}"
                    BEFORE UPDATE OF status ON tasks
                    FOR EACH ROW
                    WHEN NEW.status IS NULL OR NEW.status NOT IN ({allowed_sql})
                    BEGIN
                        SELECT RAISE(ABORT, 'hermes-swarm-protocol: invalid tasks.status');
                    END
                    """
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            if invalid:
                preview = ", ".join(f"{task_id}={status!r}" for task_id, status in invalid[:10])
                logger.error(
                    "swarm-protocol found pre-existing invalid Kanban task statuses: %s%s. "
                    "Future off-enum writes are blocked; repair these rows before relying on "
                    "dependency promotion.",
                    preview,
                    " ..." if len(invalid) > 10 else "",
                )
            return True
        finally:
            conn.close()
    except Exception:
        logger.exception("swarm-protocol could not install the Kanban task-status guard")
        return False


# ---------------------------------------------------------------------------
# ByteRover outcome normalization
# ---------------------------------------------------------------------------

def _brv_query_raw(query: str, parent_agent: Any = None, timeout: int = 10) -> Dict[str, Any]:
    """Run brv query against the active ByteRover tree. Prefers the agent's initialized
    provider (honors memory.byterover.workdir via provider._cwd); falls back to the
    provider module's _run_brv, which resolves the same workdir from config. Returns the
    raw {success, output, error} envelope with a normalized memory_status field."""
    def _normalize(result: Dict[str, Any]) -> Dict[str, Any]:
        if not result.get("success"):
            err = str(result.get("error") or "")
            status = MEMORY_TIMEOUT if "timed out" in err else MEMORY_ERROR
            return {"success": False, "error": err, "memory_status": status}
        out = (result.get("output") or "").strip()
        if "No matching knowledge found" in out:
            return {"success": True, "output": out, "memory_status": MEMORY_EMPTY}
        return {"success": True, "output": out, "memory_status": MEMORY_AVAILABLE}

    try:
        provider = None
        manager = getattr(parent_agent, "_memory_manager", None)
        if manager is not None:
            provider = manager.get_provider("byterover")
        if provider is not None:
            return _normalize(provider._query(query))
        # No agent-scoped provider (memory disabled, or a direct test harness): resolve
        # the same workdir the provider would, via the provider module's own runner.
        from plugins.memory.byterover import _run_brv
        return _normalize(_run_brv(["query", "--", query[:5000]], timeout=timeout))
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}", "memory_status": MEMORY_ERROR}


# ---------------------------------------------------------------------------
# swarm_request
# ---------------------------------------------------------------------------

SWARM_REQUEST_SCHEMA = {
    "name": "swarm_request",
    "description": "Ask another worker to investigate or verify something. Creates a linked "
                   "Kanban task carrying a hermes-swarm/v1 protocol envelope, plus a comment "
                   "on the source task. Do NOT paste ByteRover content into the card — record "
                   "memory_queries as references for the target worker to run itself.",
    "parameters": {
        "type": "object",
        "properties": {
            "objective": {"type": "string", "description": "What the target worker should accomplish."},
            "target_profile": {"type": "string", "description": "Worker profile to route to "
                                "(e.g. opnory-verifier). Use swarm_route first if unsure."},
            "acceptance": {"type": "array", "items": {"type": "string"},
                           "description": "Concrete acceptance criteria for the request."},
            "memory_queries": {"type": "array", "items": {"type": "string"},
                               "description": "ByteRover queries the target should run (references, not content)."},
            "evidence_required": {"type": "boolean", "description": "If true, completion requires "
                                  "non-memory (live) evidence: test output, commit, file inspection, runtime result."},
            "source_task_id": {"type": "string", "description": "Task to link the request under. "
                               "Defaults to the current worker task (HERMES_KANBAN_TASK)."},
            "board": {"type": "string", "description": "Board slug; default resolves from env."},
        },
        "required": ["objective", "target_profile"],
    },
}


def _envelope(kind: str, **fields: Any) -> Dict[str, Any]:
    return {"protocol": PROTOCOL, "kind": kind,
            "source_profile": _identity(), "created_at": int(time.time()), **fields}


def swarm_request(args: dict, **kwargs) -> str:
    objective = (args.get("objective") or "").strip()
    target = (args.get("target_profile") or "").strip()
    if not objective:
        return _reject("objective is required")
    if not target:
        return _reject("target_profile is required")
    acceptance = [str(a).strip() for a in (args.get("acceptance") or []) if str(a).strip()]
    memory_queries = [str(q).strip() for q in (args.get("memory_queries") or []) if str(q).strip()]
    source_task = (args.get("source_task_id") or os.environ.get("HERMES_KANBAN_TASK") or "").strip()

    request_id = "swreq_" + hashlib.sha256(
        f"{objective}:{target}:{time.time_ns()}".encode()).hexdigest()[:12]
    envelope = _envelope(
        "request", request_id=request_id, objective=objective, target_profile=target,
        acceptance=acceptance, memory_queries=memory_queries,
        evidence_required=bool(args.get("evidence_required", True)),
        source_task=source_task or None,
    )

    try:
        with _board(args.get("board")) as (kb, conn):
            # Parentless by design: a swarm request must be spawnable while the source task
            # is still running, so NO dependency edge (a parents= link would gate it todo
            # until the source completes). creator_task_id records durable origin — the
            # same provenance primitive kanban_create uses — and the envelope carries the
            # source id for readers. initial_status left at the default sentinel; the
            # graph layer derives ready/todo.
            tid = kb.create_task(
                conn, title=f"[swarm] {objective[:180]}", assignee=target,
                body=json.dumps(envelope, indent=2),
                creator_task_id=source_task or None,
                created_by=_identity(),
            )
            # Comment on the SOURCE task so the requester's thread records the handoff.
            if source_task:
                kb.add_comment(conn, source_task, author=_identity(),
                               body=f"swarm_request {request_id} -> {target}: {objective[:500]}")
            return _ok(request_id=request_id, task_id=tid, target_profile=target,
                       source_task=source_task or None, status="ready")
    except Exception as e:
        return _reject(f"swarm_request failed: {e}")


# ---------------------------------------------------------------------------
# swarm_verify — two-stage verification
# ---------------------------------------------------------------------------

SWARM_VERIFY_SCHEMA = {
    "name": "swarm_verify",
    "description": "Two-stage independent verification. phase=inspect runs the ByteRover "
                   "query and returns an evidence receipt; phase=commit records the verdict "
                   "and REQUIRES live (non-memory) evidence for a pass — test output, git "
                   "commit/diff, file inspection, API/runtime result. Memory may support a "
                   "conclusion but can never be its only basis.",
    "parameters": {
        "type": "object",
        "properties": {
            "phase": {"type": "string", "enum": ["inspect", "commit"],
                      "description": "inspect: gather memory evidence receipt. commit: record verdict."},
            "request_id": {"type": "string", "description": "The swarm_request id being verified."},
            "memory_query": {"type": "string", "description": "[inspect] ByteRover query to run."},
            "verification_id": {"type": "string",
                                "description": "[commit] Receipt id from the inspect phase."},
            "verdict": {"type": "string", "enum": list(VERDICTS),
                        "description": "[commit] pass | fail | inconclusive | blocked."},
            "live_evidence": {"type": "array", "items": {"type": "string"},
                              "description": "[commit] Current-state evidence: test output, commit, "
                              "file inspection, runtime result. Required for pass."},
            "rationale": {"type": "string", "description": "[commit] Why this verdict."},
            "task_id": {"type": "string", "description": "Task to record the outcome on "
                        "(defaults to current worker task)."},
            "board": {"type": "string", "description": "Board slug; default resolves from env."},
        },
        "required": ["phase", "request_id"],
    },
}


def _issue_receipt(request_id: str, memory_status: str, digest: str, query: str) -> str:
    vid = "swv_" + hashlib.sha256(f"{request_id}:{time.time_ns()}".encode()).hexdigest()[:12]
    now = time.time()
    # TTL-evict stale receipts so the dict cannot grow unbounded in a long-lived process.
    for k in [k for k, v in _receipts.items() if now - v["issued_at"] > _RECEIPT_TTL_SECONDS]:
        _receipts.pop(k, None)
    _receipts[vid] = {"request_id": request_id, "memory_status": memory_status,
                      "digest": digest, "query": query, "issued_at": now}
    return vid


def swarm_verify(args: dict, **kwargs) -> str:
    phase = (args.get("phase") or "").strip().lower()
    request_id = (args.get("request_id") or "").strip()
    if not request_id:
        return _reject("request_id is required")
    import os
    task_id = (args.get("task_id") or os.environ.get("HERMES_KANBAN_TASK") or "").strip()

    if phase == "inspect":
        query = (args.get("memory_query") or "").strip() or f"swarm request {request_id} evidence and prior decisions"
        result = _brv_query_raw(query, parent_agent=kwargs.get("parent_agent"))
        status = result.get("memory_status", MEMORY_ERROR)
        digest = "sha256:" + hashlib.sha256((result.get("output") or result.get("error") or "").encode()).hexdigest()[:16]
        vid = _issue_receipt(request_id, status, digest, query)
        payload = {"request_id": request_id, "verification_id": vid,
                   "memory": {"status": status, "query": query, "digest": digest}}
        if result.get("success"):
            out = result.get("output") or ""
            payload["memory"]["digest_preview"] = out[:600]
        else:
            payload["memory"]["error"] = result.get("error")
            payload["note"] = ("Proceed to live inspection. A memory timeout/absence is NOT "
                               "evidence of anything — treat as MEMORY_UNAVAILABLE.")
        payload["instruction"] = "Now independently inspect live implementation/runtime evidence."
        return _ok(**payload)

    if phase == "commit":
        vid = (args.get("verification_id") or "").strip()
        verdict = (args.get("verdict") or "").strip().lower()
        live = [str(e).strip() for e in (args.get("live_evidence") or []) if str(e).strip()]
        receipt = _receipts.get(vid)
        if verdict not in VERDICTS:
            return _reject(f"verdict must be one of {VERDICTS}")
        if verdict == "pass" and not live:
            return _reject("swarm_verify refused: verdict=pass requires live_evidence (test output, "
                          "commit/diff, file inspection, or runtime result). ByteRover memory alone "
                          "cannot justify a pass — memory is evidence, not authority.")
        if not task_id:
            return _reject("commit requires a task to record on: pass task_id or run inside a "
                           "worker (HERMES_KANBAN_TASK). Verification records are Kanban comments.")
        record = {
            "protocol": PROTOCOL, "kind": "verification",
            "request_id": request_id, "verification_id": vid or None,
            "verdict": verdict, "live_evidence": live,
            "memory_status": (receipt or {}).get("memory_status", MEMORY_ERROR),
            "memory_digest": (receipt or {}).get("digest"),
            "rationale": (args.get("rationale") or "").strip(),
            "verifier": _identity(), "recorded_at": int(time.time()),
        }
        try:
            with _board(args.get("board")) as (kb, conn):
                kb.add_comment(conn, task_id, author=_identity(),
                               body=f"swarm_verify {request_id}: {verdict.upper()}\n" + json.dumps(record, indent=2))
                return _ok(request_id=request_id, verdict=verdict, recorded_on=task_id,
                           memory_status=record["memory_status"])
        except Exception as e:
            return _reject(f"swarm_verify commit failed: {e}")

    return _reject("phase must be 'inspect' or 'commit'")


# ---------------------------------------------------------------------------
# swarm_route — deterministic config-driven routing
# ---------------------------------------------------------------------------

SWARM_ROUTE_SCHEMA = {
    "name": "swarm_route",
    "description": "Resolve which worker profile should own a work type for a project, from "
                   "the configured routing table (plugins.entries.swarm-protocol.settings."
                   "projects.<project>.<work_type>). Deterministic: unknown project/role "
                   "returns ROUTE_UNRESOLVED rather than guessing. Routing is orchestration "
                   "policy, not reasoning.",
    "parameters": {
        "type": "object",
        "properties": {
            "project": {"type": "string", "description": "Project key, e.g. opnory."},
            "work_type": {"type": "string", "description": "Role key, e.g. verification, builder, security."},
            "request_id": {"type": "string", "description": "Optional request being routed."},
        },
        "required": ["project", "work_type"],
    },
}


def swarm_route(args: dict, **kwargs) -> str:
    project = (args.get("project") or "").strip()
    work_type = (args.get("work_type") or "").strip()
    if not project or not work_type:
        return _reject("project and work_type are required")
    settings = _plugin_settings()
    routing = (settings.get("projects") or {})
    entry = ((routing.get(project) or {}) if isinstance(routing, dict) else {}).get(work_type)
    if not entry:
        return _ok(route="ROUTE_UNRESOLVED", project=project, work_type=work_type,
                  hint="Configure plugins.entries.swarm-protocol.settings.projects.<project>.<work_type>")
    return _ok(route=entry, project=project, work_type=work_type,
               request_id=(args.get("request_id") or None))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    # ByteRover compatibility: Hermes currently hard-caps curate at 120s even though
    # ByteRover's own agentic task budget can run for ~10 minutes. Raise the floor
    # before any explicit or automatic curate runs in this process.
    _patch_byterover_curate_timeout()

    # Defense-in-depth guard: current Hermes already injects dispatcher worker
    # lifecycle tools. A dispatcher-owned worker persists the board-level status
    # constraint before model work begins.
    _install_task_status_guard()

    ctx.register_tool(name="swarm_request", toolset="swarm", schema=SWARM_REQUEST_SCHEMA, handler=swarm_request)
    ctx.register_tool(name="swarm_verify", toolset="swarm", schema=SWARM_VERIFY_SCHEMA, handler=swarm_verify)
    ctx.register_tool(name="swarm_route", toolset="swarm", schema=SWARM_ROUTE_SCHEMA, handler=swarm_route)
