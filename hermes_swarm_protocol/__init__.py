"""swarm-protocol — coordination over Kanban + ByteRover; disposable wiki projection.

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

Coordination storage: existing Kanban cards/comments. Wiki publications are comments;
raw captures are immutable evidence files. Generated wiki output is non-authoritative.
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


def _patch_byterover_curate_response() -> bool:
    """Reject an observed CLI parse failure even when ByteRover exits zero."""
    if _active_memory_provider() != "byterover":
        return False
    try:
        from functools import wraps
        from plugins.memory import byterover as brv
        provider = getattr(brv, "ByteRoverMemoryProvider", None)
        original = getattr(provider, "_curate", None)
        if not callable(original) or getattr(original, "_swarm_response_guard", False):
            return False

        @wraps(original)
        def curate(self, content):
            result = original(self, content)
            output = result.get("output") if isinstance(result, dict) else None
            if isinstance(output, str) and result.get("success") and any(
                line.strip().startswith("Response parsing failed:") or line.strip() == "Not Found"
                for line in output.splitlines()
            ):
                return {**result, "success": False,
                        "error": "ByteRover curate reported a provider or response parsing failure despite a zero exit status"}
            return result

        curate._swarm_response_guard = True
        provider._curate = curate
        return True
    except Exception:
        logger.exception("swarm-protocol could not guard ByteRover curate responses")
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
# Wiki publications: canonical comments and immutable evidence, never wiki edits
# ---------------------------------------------------------------------------

def _wiki_records():
    # User-plugin loaders and the existing tests load __init__.py under arbitrary
    # module names; do not depend on a package-relative import being available.
    import importlib.util
    import sys
    source = Path(__file__).resolve().with_name("wiki_records.py")
    name = "_hermes_swarm_wiki_records_" + hashlib.sha256(str(source).encode() + source.read_bytes()).hexdigest()[:16]
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[name] = module
    return sys.modules[name]


def _wiki_configuration(args):
    project = args.get("project")
    if not isinstance(project, str) or Path(project).name != project or project in {"", ".", ".."} or "\\" in project:
        raise ValueError("project must be a path-safe name")
    cfg = (_plugin_settings().get("wiki_projects") or {}).get(project)
    actor = _identity()
    if not isinstance(cfg, dict) or not cfg.get("workspace") or not cfg.get("knowledge_tree"):
        raise ValueError("configure wiki_projects.<project>.workspace and knowledge_tree first")
    if actor not in set(cfg.get("profiles", [])) | set(cfg.get("maintainers", [])):
        raise ValueError("runtime profile is not an authorized project publisher")
    if args.get("board") and args["board"] != cfg.get("board"):
        raise ValueError("project board mismatch")
    return cfg, actor


def _wiki_context(args, kb, conn):
    cfg, actor = _wiki_configuration(args)
    runtime_task = os.environ.get("HERMES_KANBAN_TASK")
    task_id = args.get("task_id") or runtime_task
    if not task_id or (runtime_task and runtime_task != task_id):
        raise ValueError("publication must bind the runtime task")
    task = conn.execute("SELECT workspace_path FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task or not task[0]:
        raise ValueError("publication requires a task with an explicit workspace")
    workspace = Path(cfg["workspace"]).expanduser()
    if workspace.is_symlink() or not workspace.is_dir():
        raise ValueError("configured workspace must exist without a root symlink")
    workspace = workspace.resolve()
    task_workspace = Path(task[0])
    if task_workspace.is_symlink():
        raise ValueError("task workspace cannot be a symlink")
    task_workspace = task_workspace.resolve()
    allowed = [workspace] + [Path(p).expanduser().resolve() for p in cfg.get("task_workspaces", [])]
    if not any(task_workspace.is_relative_to(root) for root in allowed):
        raise ValueError("task is outside configured project workspace")
    records = _wiki_records()
    rules = records.confined(workspace, ".swarm/SWARM_WIKI.md")
    if not rules.is_file():
        raise ValueError("install trusted .swarm/SWARM_WIKI.md maintenance rules first")
    cfg = dict(cfg, workspace=workspace, task_workspace=task_workspace, knowledge_tree=Path(cfg["knowledge_tree"]).expanduser())
    if cfg["knowledge_tree"].is_symlink() or not cfg["knowledge_tree"].is_dir():
        raise ValueError("configured knowledge tree must exist without a root symlink")
    return cfg, actor, task_id


def _wiki_validate(data, kind, topic, cfg, actor, conn):
    records = _wiki_records()
    existing = {}
    for row in conn.execute("SELECT id, task_id, author, body, created_at FROM task_comments ORDER BY id"):
        try:
            event = records.decode_record(dict(zip(("id", "task_id", "author", "body", "created_at"), row)))
        except (ValueError, KeyError, TypeError):
            continue
        if event:
            existing[event["event_id"]] = event
    superseded = set()
    for event in existing.values():
        prior = existing.get(event["data"].get("supersedes"))
        if prior and prior["type"] == event["type"] and prior["topic"] == event["topic"] and prior["project"] == event["project"]:
            if prior["actor"] == event["actor"] or event["actor"] in cfg.get("maintainers", []):
                superseded.add(prior["event_id"])
    evidence = data["evidence"] + data.get("live_evidence", [])
    if kind == "artifact":
        evidence += [data["capture"]]
    def validate_ref(ref, workspace):
        if ref["kind"] in {"artifact", "file", "knowledge"}:
            root = cfg["workspace"] / ".swarm/raw" if ref["kind"] == "artifact" else cfg["knowledge_tree"] if ref["kind"] == "knowledge" else workspace
            path = records.confined(root, ref["path"])
            if not path.is_file() or records.file_hash(root, ref["path"]) != ref["sha256"]:
                raise ValueError("missing or changed evidence reference")
        elif ref["kind"] == "record":
            event = existing.get(ref["event_id"])
            if not event or event["project"] != cfg["project"] or event["payload_digest"] != ref["digest"]:
                raise ValueError("missing or changed source record")
        elif ref["kind"] == "commit":
            import subprocess
            result = subprocess.run(["git", "-C", str(cfg.get("repo", cfg["workspace"])), "cat-file", "-e", ref["sha"] + "^{commit}"], capture_output=True, timeout=10)
            if result.returncode:
                raise ValueError("commit evidence is unavailable in configured repo")
    def source_workspace(event):
        workspace = Path(event.get("workspace", cfg["workspace"]))
        if workspace.is_symlink():
            raise ValueError("source workspace cannot be a symlink")
        workspace = workspace.resolve()
        roots = [cfg["workspace"]] + [Path(p).expanduser().resolve() for p in cfg.get("task_workspaces", [])]
        if not any(workspace.is_relative_to(root) for root in roots):
            raise ValueError("source workspace outside configured roots")
        return workspace

    def usable(event):
        if event["event_id"] in superseded:
            return False
        workspace = source_workspace(event)
        for ref in event["data"].get("live_evidence", []):
            if records.live_reference(ref, workspace, cfg["knowledge_tree"], existing):
                try:
                    validate_ref(ref, workspace)
                    return True
                except (ValueError, OSError):
                    continue
        return False

    for ref in evidence:
        validate_ref(ref, cfg["task_workspace"])
    if kind in records.AUDIT_TYPES:
        if not cfg.get("board"):
            raise ValueError("audit publications require an explicitly configured board")
        tables = records.audit_tables(conn)
        knowledge = {}
        paths = [data["subject"]["path"]] if kind == "provenance" and data["subject"]["kind"] == "knowledge" else []
        paths += [r["path"] for r in data.get("parent_revisions", [])]
        for path in paths:
            knowledge[path] = records.read_confined(cfg["knowledge_tree"], path)
        def available(ref, _):
            try:
                validate_ref(ref, cfg["task_workspace"])
                return True
            except (ValueError, OSError):
                return False
        def live(ref, event_id):
            return records.live_reference(ref, cfg["task_workspace"], cfg["knowledge_tree"], existing) and available(ref, event_id)
        records.validate_audit_record(
            {"type": kind, "data": data, "actor": actor}, tables, knowledge,
            cfg["board"], cfg.get("maintainers", []), available, live,
            [e for i, e in existing.items() if i not in superseded and e["project"] == cfg["project"]])
    links = data.get("claims", []) + data.get("supporting_records", [])
    links += [data[k] for k in ("claim_id", "contradiction_id", "supersedes") if k in data]
    for link in links:
        event = existing.get(link)
        if not event or event["project"] != cfg["project"] or event["topic"] != topic:
            raise ValueError("linked record missing or outside project/topic")
    if data.get("supersedes"):
        prior = existing[data["supersedes"]]
        if prior["type"] != kind or (prior["actor"] != actor and actor not in cfg.get("maintainers", [])):
            raise ValueError("supersession requires the same type and original author or maintainer")
    if kind == "verification":
        claim = existing[data["claim_id"]]
        if claim["type"] != "claim":
            raise ValueError("verification target must be a claim")
        if data["verdict"] == "pass" and (claim["actor"] == actor or claim["data"]["scope"] != data["scope"]):
            raise ValueError("pass requires a different profile and the original claim scope")
        if data["verdict"] == "pass" and not any(records.live_reference(r, cfg["task_workspace"], cfg["knowledge_tree"], existing) for r in data["live_evidence"]):
            raise ValueError("memory/wiki captures cannot supply sole live evidence")
    if kind == "contradiction" and any(existing[i]["type"] != "claim" for i in data["claims"]):
        raise ValueError("contradiction targets must be claims")
    if kind == "reconciliation":
        conflict = existing[data["contradiction_id"]]
        if conflict["type"] != "contradiction":
            raise ValueError("reconciliation target must be a contradiction")
        authors = {existing[i]["actor"] for i in conflict["data"]["claims"]}
        if not any(existing[i]["type"] == "verification" and existing[i]["actor"] not in authors
                   and existing[i]["data"]["claim_id"] in conflict["data"]["claims"]
                   and existing[i]["data"]["scope"] == data["scope"]
                   and existing[i]["data"]["verdict"] in {"pass", "fail", "partial"}
                   and usable(existing[i])
                   for i in data["supporting_records"]):
            raise ValueError("reconciliation requires independent scoped live evidence")
    for task_id in data.get("affected_task_ids", []):
        if conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone() is None:
            raise ValueError("affected task missing")
    if kind == "route":
        target = ((_plugin_settings().get("projects") or {}).get(cfg["project"]) or {}).get(data["role"])
        if data["outcome"] != ("ROUTE_RESOLVED" if target else "ROUTE_UNRESOLVED") or (target and data.get("target_profile") != target):
            raise ValueError("route publication must match current configured routing")
    if kind == "synthesis":
        if actor not in cfg.get("maintainers", []):
            raise ValueError("only configured maintainers can accept synthesis")
        path = records.confined(cfg["knowledge_tree"], data["node_path"])
        if not path.is_file() or records.file_hash(cfg["knowledge_tree"], data["node_path"]) != data["node_sha256"]:
            raise ValueError("accepted ByteRover node revision is missing or changed")
        sources = {i: e["payload_digest"] for i, e in existing.items()
                   if e["project"] == cfg["project"] and e["topic"] == topic and e["type"] != "synthesis"}
        sources = {i: h for i, h in sources.items() if i not in superseded}
        if data["source_digests"] != sources:
            raise ValueError("synthesis must cite every active publication for this topic")
        for event_id in sources:
            event = existing[event_id]
            workspace = source_workspace(event)
            refs = event["data"]["evidence"] + event["data"].get("live_evidence", [])
            if event["type"] == "artifact":
                refs += [event["data"]["capture"]]
            for ref in refs:
                validate_ref(ref, workspace)


SWARM_PUBLISH_SCHEMA = {
    "name": "swarm_publish",
    "description": "Publish a structured claim, scoped verification, contradiction, reconciliation, decision, consequence, route or accepted ByteRover synthesis as a canonical Kanban comment. Never edits wiki pages. Identity comes from runtime; use a stable publication_key for retries.",
    "parameters": {"type": "object", "properties": {
        "project": {"type": "string"}, "topic": {"type": "string"},
        "type": {"type": "string", "enum": ["claim", "verification", "contradiction", "reconciliation", "decision", "consequence", "route", "synthesis", "provenance", "request_assessment"]},
        "publication_key": {"type": "string"}, "data": {"type": "object"},
        "task_id": {"type": "string"}, "board": {"type": "string"}},
        "required": ["project", "topic", "type", "publication_key", "data"]},
}


def swarm_publish(args: dict, **kwargs) -> str:
    try:
        records = _wiki_records()
        if args.get("type") == "artifact":
            raise ValueError("use swarm_capture for raw provenance")
        project = args.get("project")
        configured, _ = _wiki_configuration(args)
        records.payload(args.get("type"), args.get("data"))
        with _board(args.get("board") or configured.get("board")) as (kb, conn):
            cfg, actor, task_id = _wiki_context(args, kb, conn)
            cfg["project"] = project
            record = records.make_record(project, task_id, actor, args.get("publication_key"),
                                         args.get("topic"), args.get("type"), args.get("data"), int(time.time()), str(cfg["task_workspace"]))
            event, comment_id, duplicate = records.append_record(
                conn, kb.add_comment, record,
                validate=lambda: _wiki_validate(record["data"], record["type"], record["topic"], cfg, actor, conn))
            return _ok(event_id=event["event_id"], payload_digest=event["payload_digest"], comment_id=comment_id,
                       recorded_on=task_id, duplicate=duplicate)
    except Exception as error:
        return _reject(f"swarm_publish failed: {error}")


SWARM_CAPTURE_SCHEMA = {
    "name": "swarm_capture",
    "description": "Capture an original task workspace or configured knowledge file as immutable content-addressed raw evidence in shared project storage and publish its provenance. Memory snapshots are context, never sole live proof.",
    "parameters": {"type": "object", "properties": {
        "project": {"type": "string"}, "topic": {"type": "string"},
        "publication_key": {"type": "string"}, "source_path": {"type": "string"},
        "source_kind": {"type": "string", "enum": ["workspace", "knowledge"], "default": "workspace"},
        "category": {"type": "string", "enum": ["evidence", "test-results", "source-snapshots"]},
        "media_type": {"type": "string"}, "task_id": {"type": "string"}, "board": {"type": "string"}},
        "required": ["project", "topic", "publication_key", "source_path", "category"]},
}


def swarm_capture(args: dict, **kwargs) -> str:
    try:
        records = _wiki_records()
        project = args.get("project")
        configured, _ = _wiki_configuration(args)
        with _board(args.get("board") or configured.get("board")) as (kb, conn):
            cfg, actor, task_id = _wiki_context(args, kb, conn)
            cfg["project"] = project
            # Validate all user text before creating an immutable artifact.
            for key in ("publication_key", "topic", "source_path"):
                records.text(args.get(key), key)
            records.payload("artifact", {"capture": {"kind": "artifact", "path": "evidence/preflight", "sha256": "0" * 64},
                                         "media_type": args.get("media_type") or "application/octet-stream",
                                         "source_path": args["source_path"]})
            source_kind = args.get("source_kind", "workspace")
            if source_kind not in {"workspace", "knowledge"}:
                raise ValueError("source_kind must be workspace or knowledge")
            source_root = cfg["knowledge_tree"] if source_kind == "knowledge" else cfg["task_workspace"]
            ref = records.capture(cfg["workspace"], args["source_path"], args["category"], source_root=source_root)
            source_origin = "knowledge" if source_kind == "knowledge" else records.origin(source_root, cfg["knowledge_tree"], args["source_path"])
            record = records.make_record(project, task_id, actor, args["publication_key"], args["topic"],
                                         "artifact", {"capture": ref, "media_type": args.get("media_type") or "application/octet-stream",
                                                      "source_path": args["source_path"], "source_root": str(source_root),
                                                      "source_origin": source_origin}, int(time.time()), str(cfg["task_workspace"]))
            event, comment_id, duplicate = records.append_record(
                conn, kb.add_comment, record,
                validate=lambda: _wiki_validate(record["data"], "artifact", record["topic"], cfg, actor, conn))
            return _ok(event_id=event["event_id"], payload_digest=event["payload_digest"], evidence=ref,
                       comment_id=comment_id, duplicate=duplicate)
    except Exception as error:
        return _reject(f"swarm_capture failed: {error}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    # ByteRover compatibility: Hermes currently hard-caps curate at 120s even though
    # ByteRover's own agentic task budget can run for ~10 minutes. Raise the floor
    # before any explicit or automatic curate runs in this process.
    _patch_byterover_curate_timeout()
    _patch_byterover_curate_response()

    # Defense-in-depth guard: current Hermes already injects dispatcher worker
    # lifecycle tools. A dispatcher-owned worker persists the board-level status
    # constraint before model work begins.
    _install_task_status_guard()

    ctx.register_tool(name="swarm_request", toolset="swarm", schema=SWARM_REQUEST_SCHEMA, handler=swarm_request)
    ctx.register_tool(name="swarm_verify", toolset="swarm", schema=SWARM_VERIFY_SCHEMA, handler=swarm_verify)
    ctx.register_tool(name="swarm_route", toolset="swarm", schema=SWARM_ROUTE_SCHEMA, handler=swarm_route)
    ctx.register_tool(name="swarm_publish", toolset="swarm", schema=SWARM_PUBLISH_SCHEMA, handler=swarm_publish)
    ctx.register_tool(name="swarm_capture", toolset="swarm", schema=SWARM_CAPTURE_SCHEMA, handler=swarm_capture)
