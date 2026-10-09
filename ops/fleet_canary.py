#!/usr/bin/env python3
"""Bounded fleet runtime probes and canonical, model-free publication canaries.

Profile checks discover the installed plugin in fresh Hermes processes. Board
canaries require --execute, create one blocked maintenance task, and never dispatch
work or call a model. Existing historical findings are outside this probe's claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

TOOLS = ("swarm_request", "swarm_verify", "swarm_route", "swarm_publish", "swarm_capture")
CONFIG_KEYS = ("board", "workspace", "knowledge_tree", "repo", "task_workspaces", "profiles", "maintainers")
TABLES = ("tasks", "task_events", "task_runs", "task_comments", "task_links", "task_attachments", "kanban_notify_subs")
MARKER = "FLEET_CANARY_JSON:"


def digest(content):
    return hashlib.sha256(content).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def isolated_env(hermes_root, agent_root, profile, extra=None):
    """Preserve provider credentials in environment without reading or printing them."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", profile):
        raise ValueError("invalid profile name")
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("HERMES_KANBAN_") or key in {"SWARM_PROTOCOL_PLUGIN_DIR", "HERMES_HOME", "HERMES_PROFILE", "HERMES_PROFILE_NAME"}:
            env.pop(key)
    home = Path(hermes_root) if profile == "default" else Path(hermes_root) / "profiles" / profile
    env.update(HERMES_HOME=str(home), HERMES_PROFILE=profile, HERMES_PROFILE_NAME=profile,
               PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(agent_root))
    env.update(extra or {})
    return env


def child(options, profile, mode, payload=None, extra=None):
    cmd = [options.python, str(Path(__file__).resolve()), mode,
           "--hermes-root", options.hermes_root, "--agent-root", options.agent_root,
           "--release-sha", options.release_sha, "--profile", profile]
    result = subprocess.run(cmd, input=json.dumps(payload or {}), text=True,
                            capture_output=True, timeout=120,
                            env=isolated_env(options.hermes_root, options.agent_root, profile, extra))
    outputs = [line[len(MARKER):] for line in result.stdout.splitlines() if line.startswith(MARKER)]
    if len(outputs) != 1:
        raise RuntimeError("isolated probe did not return exactly one structured result")
    response = json.loads(outputs[0])
    if result.returncode or not response.get("ok"):
        raise RuntimeError("isolated probe failed: " + str(response.get("error_type", "process_error")))
    return response


def discovery():
    import model_tools  # noqa: F401 - load public built-in and plugin tool registry
    from hermes_cli.plugins import discover_plugins
    from tools.registry import registry
    discover_plugins(force=True)
    return registry


def runtime_probe(expected_sha, hermes_root):
    """Allowlisted facts only; provider construction performs no recall/curation."""
    import yaml
    from hermes_cli.profiles import current_profile_name
    registry = discovery()
    entries = {name: registry.get_entry(name) for name in TOOLS}
    if any(entry is None for entry in entries.values()):
        raise RuntimeError("missing_swarm_tool")
    origins = {str(Path(entry.handler.__globals__["__file__"]).resolve()) for entry in entries.values()}
    if len(origins) != 1:
        raise RuntimeError("mixed_plugin_origins")
    origin = Path(origins.pop())
    expected_origin = Path(hermes_root) / "releases/swarm-protocol" / expected_sha / "hermes_swarm_protocol/__init__.py"
    if origin != expected_origin.resolve():
        raise RuntimeError("unexpected_release_installation_path")
    repo = origin.parent.parent
    actual_sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    blob = subprocess.check_output(["git", "-C", str(repo), "show", actual_sha + ":hermes_swarm_protocol/__init__.py"])
    if actual_sha != expected_sha or origin.read_bytes() != blob:
        raise RuntimeError("unvalidated_plugin_origin")
    cfg = yaml.safe_load((Path(os.environ["HERMES_HOME"]) / "config.yaml").read_text()) or {}
    settings = cfg.get("plugins", {}).get("entries", {}).get("swarm-protocol", {}).get("settings", {})
    from plugins.memory.byterover import ByteRoverMemoryProvider
    provider = ByteRoverMemoryProvider()
    projects = {key: {k: value[k] for k in CONFIG_KEYS if k in value}
                for key, value in settings.get("wiki_projects", {}).items() if isinstance(value, dict)}
    return {"ok": True, "profile": current_profile_name(), "tools": list(TOOLS),
            "plugin_origin": str(origin), "release_sha": actual_sha,
            "origin_sha256": digest(blob), "wiki_projects": projects,
            "provider_curate_timeout": provider._curate_timeout,
            "provider_auto_extract": provider._auto_extract,
            "plugin_curate_timeout": settings.get("byterover_curate_timeout_seconds"),
            "configured_auto_extract": cfg.get("memory", {}).get("byterover", {}).get("auto_extract")}


def expected_mappings(options, inventory):
    reviewed = getattr(options, "reviewed_plan", None)
    if reviewed:
        mappings = json.loads(Path(reviewed).read_text())["inventory"]
    else:
        mappings = {fleet["project_key"]: {
            "board": fleet["board"], "workspace": fleet["workspace"], "repo": fleet["repo"],
            "knowledge_tree": fleet["knowledge_tree"],
            "task_workspaces": [fleet["task_workspace_root"]] if fleet["task_workspace_root_exists"] else [],
            "profiles": sorted(set(fleet["profiles"]) | set(fleet.get("existing_role_profiles", []))),
            "maintainers": fleet["proposed_maintainers"],
        } for fleet in inventory["fleets"]}
    if set(mappings) != {fleet["project_key"] for fleet in inventory["fleets"]}:
        raise RuntimeError("reviewed project inventory mismatch")
    return {key: {field: value[field] for field in CONFIG_KEYS} for key, value in mappings.items()}


def check_project_mappings(report, profile, mappings):
    expected = {key: cfg for key, cfg in mappings.items()
                if profile in set(cfg["profiles"]) | set(cfg["maintainers"])}
    actual = report["wiki_projects"]
    if set(actual) != set(expected):
        raise RuntimeError("authorized fleet project set mismatch")
    for key, cfg in expected.items():
        owned = {field: actual[key].get(field) for field in CONFIG_KEYS}
        if owned != cfg:
            raise RuntimeError("owned fleet project mapping mismatch")


def profile_report(options, inventory):
    mappings = expected_mappings(options, inventory)
    profiles = sorted({"default"} | {p for f in inventory["fleets"] for p in f["profiles"]})
    expected_auto = {p: not (p in {"default", "alepes", "la", "opnory", "tachikoma", "tunory"}) for p in profiles}
    reports = []
    expected_origin = str((Path(options.hermes_root) / "releases/swarm-protocol" / options.release_sha / "hermes_swarm_protocol/__init__.py").resolve())
    for profile in profiles:
        report = child(options, profile, "_probe")
        if report["profile"] != profile or report["plugin_origin"] != expected_origin:
            raise RuntimeError("profile identity or immutable installation path mismatch")
        if report["provider_curate_timeout"] != 600 or report["plugin_curate_timeout"] != 600:
            raise RuntimeError("effective curation deadline mismatch")
        if report["provider_auto_extract"] != expected_auto[profile]:
            raise RuntimeError("extraction policy changed")
        check_project_mappings(report, profile, mappings)
        reports.append(report)
    return {"ok": True, "profile_count": len(reports), "release_sha": options.release_sha, "profiles": reports}


def board_snapshot(path, *, include_internal=False):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("BEGIN")
        available = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = {}
        tables = sorted(available) if include_internal else TABLES
        for table in tables:
            if table not in available:
                raise RuntimeError("canonical board table missing")
            normalized = ([{"bytes_sha256": digest(v)} if isinstance(v, bytes) else v for v in row]
                          for row in conn.execute('SELECT * FROM "' + table.replace('"', '""') + '"'))
            rows[table] = Counter(digest(encoded(row)) for row in normalized)
        if include_internal:
            rows["__schema__"] = Counter(digest(encoded(list(row))) for row in conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master"))
        return rows
    finally:
        conn.close()


def preserved(before, after):
    if any(before[table] - after[table] for table in before):
        raise RuntimeError("pre-existing canonical board rows changed")
    return {table: {"before": sum(before[table].values()), "after": sum(after[table].values())} for table in before}


def raw_snapshot(root):
    root = Path(root)
    if root.is_symlink():
        return {".": "symlink:" + os.readlink(root)}
    if not root.exists():
        return {".": "absent"}
    snapshot = {".": "dir"}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        snapshot[relative] = ("symlink:" + os.readlink(path) if path.is_symlink()
                              else "dir" if path.is_dir() else digest(path.read_bytes()))
    return snapshot


def negative_state(inventory):
    return {"boards": {fleet["board"]: board_snapshot(fleet["task_source"], include_internal=True) for fleet in inventory["fleets"]},
            "raw": {fleet["project_key"]: raw_snapshot(Path(fleet["workspace"]) / ".swarm/raw") for fleet in inventory["fleets"]}}


def rejected_without_changes(operation, inventory):
    before = negative_state(inventory)
    try:
        result = operation()
    finally:
        after = negative_state(inventory)
        if before != after:
            raise RuntimeError("denied operation changed board or raw evidence state")
    require_reply(result, accepted=False)
    return {"zero_persisted_writes": True, "boards_checked": len(before["boards"]), "raw_roots_checked": len(before["raw"])}


def stable_fixture(report, project):
    return {"schema_version": 1, "release_sha": report["release_sha"],
            "plugin_origin": report["plugin_origin"], "origin_sha256": report["origin_sha256"],
            "profile": report["profile"], "tools": report["tools"], "project": project,
            "configuration": report["wiki_projects"][project],
            "provider_curate_timeout": report["provider_curate_timeout"],
            "provider_auto_extract": report["provider_auto_extract"]}


def fresh_evidence_check(fixture, source, raw, reference):
    """A verdict requires fresh recomputation and both immutable/raw byte checks."""
    expected = encoded(fixture)
    for path in (Path(source), Path(raw)):
        if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
            raise RuntimeError("fresh runtime evidence does not match capture")
    if reference.get("sha256") != digest(expected):
        raise RuntimeError("capture hash mismatch")


def sanitized_tool_reply(result):
    reply = json.loads(result) if isinstance(result, str) else result
    if not isinstance(reply, dict):
        raise RuntimeError("unstructured tool response")
    fields = ("ok", "event_id", "payload_digest", "comment_id", "recorded_on", "duplicate", "evidence")
    safe = {key: reply[key] for key in fields if key in reply}
    if "error" in reply:
        if not isinstance(reply["error"], str) or not reply["error"].strip() or ("ok" in reply and reply["ok"] is not False):
            raise RuntimeError("ambiguous tool rejection")
        if any(key in reply for key in fields if key != "ok"):
            raise RuntimeError("mixed success and rejection fields")
        return {"ok": False, "error_reported": True}
    return safe


def creation_observation(task, runs):
    state = {"status": task.status, "run_count": len(runs), "observed_blocked_no_runs": False,
             "reused_completed": False}
    if task.status == "blocked" and not runs:
        state["observed_blocked_no_runs"] = True
    elif task.status == "done":
        state["reused_completed"] = True
    else:
        raise RuntimeError("canary task is runnable or dispatched before publication")
    return state


def actor_action(options, payload):
    from tools.registry import registry  # runtime_probe already performed public discovery
    action = payload["action"]
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    if action in {"create", "complete"}:
        conn = kbc.connect(board=payload["board"])
        try:
            if action == "create":
                tid = kb.create_task(conn, title=payload["title"], created_by="default", assignee="default",
                                     workspace_kind="dir", workspace_path=payload["workspace"],
                                     initial_status="blocked", idempotency_key=payload["key"], board=payload["board"])
                return {"ok": True, "task_id": tid,
                        "creation_observation": creation_observation(kb.get_task(conn, tid), kb.list_runs(conn, tid))}
            kb.complete_task(conn, payload["task_id"], summary="Immutable release and fleet publication canary passed; no model calls.", fire_lifecycle_hook=False)
            return {"ok": kb.get_task(conn, payload["task_id"]).status == "done"}
        finally:
            conn.close()
    if action == "verify":
        fresh = child(options, "default", "_probe")
        fixture = stable_fixture(fresh, payload["project"])
        root = Path(fixture["configuration"]["workspace"]) / ".swarm/raw"
        raw = root / payload["reference"]["path"]
        if root.is_symlink() or raw.is_symlink() or not raw.resolve().is_relative_to(root.resolve()):
            raise RuntimeError("raw capture outside workspace")
        fresh_evidence_check(fixture, payload["source"], raw, payload["reference"])
        args = payload["args"]
        args["data"]["rationale"] = "Fresh isolated runtime discovery reproduced the fixture; original and raw bytes plus SHA256 independently checked."
        result = registry.get_entry("swarm_publish").handler(args)
    else:
        result = registry.get_entry(payload["tool"]).handler(payload["args"])
    # Preserve the standard Hermes error envelope without exposing its text.
    return {"ok": True, "reply": sanitized_tool_reply(result)}


def require_reply(result, *, duplicate=None, accepted=True):
    reply = result["reply"]
    if not isinstance(reply.get("ok"), bool) or reply["ok"] != accepted:
        raise RuntimeError("canonical tool acceptance mismatch")
    if duplicate is not None and reply.get("duplicate") != duplicate:
        raise RuntimeError("canonical idempotency mismatch")
    return reply


def board_canary(options, inventory):
    fleet = next(f for f in inventory["fleets"] if f["board"] == options.board)
    report = child(options, "default", "_probe")
    if report["profile"] != "default" or report["provider_curate_timeout"] != 600 or report["plugin_curate_timeout"] != 600:
        raise RuntimeError("default-profile canary deadline or identity mismatch")
    check_project_mappings(report, "default", expected_mappings(options, inventory))
    fixture = stable_fixture(report, fleet["project_key"])
    cfg = fixture["configuration"]
    scratch_root = next((Path(p) for p in cfg.get("task_workspaces", []) if Path(p).is_dir()), Path(cfg["workspace"]) / ".swarm/maintenance")
    scratch = scratch_root / ("fleet-canary-" + options.release_sha)
    key = "fleet-canary:" + options.release_sha + ":" + fleet["board"]
    plan = {"board": fleet["board"], "project": fleet["project_key"], "workspace": str(scratch), "key": key}
    if not options.execute:
        return {"ok": True, "executed": False, "plan": plan}
    before = board_snapshot(fleet["task_source"])
    if scratch_root.is_symlink() or scratch.is_symlink():
        raise RuntimeError("canary scratch root must not be a symlink")
    scratch.mkdir(parents=True, exist_ok=True)
    source = scratch / "fixture.json"
    content = encoded(fixture)
    if source.exists() and source.read_bytes() != content:
        raise RuntimeError("existing canary fixture differs")
    if not source.exists():
        with source.open("xb") as stream:
            stream.write(content)
    creation = child(options, "default", "_actor", {"action": "create", "board": fleet["board"],
                     "workspace": str(scratch), "title": "Swarm Wiki fleet release canary", "key": key})
    tid = creation["task_id"]
    extra = {"HERMES_KANBAN_TASK": tid}
    base = {"project": fleet["project_key"], "topic": "deployment/fleet-canary", "task_id": tid}
    capture_args = dict(base, publication_key=key + ":capture", source_path="fixture.json", category="test-results", media_type="application/json")
    capture = require_reply(child(options, "default", "_actor", {"action": "tool", "tool": "swarm_capture", "args": capture_args}, extra))
    wrong_board = next(f["board"] for f in inventory["fleets"] if f["board"] != fleet["board"])
    wrong_board_proof = rejected_without_changes(lambda: child(options, "default", "_actor", {"action": "tool", "tool": "swarm_capture", "args": dict(capture_args, board=wrong_board)}, extra), inventory)
    misleading = dict(extra, HERMES_KANBAN_BOARD=wrong_board)
    require_reply(child(options, "default", "_actor", {"action": "tool", "tool": "swarm_capture", "args": capture_args}, misleading), duplicate=True)
    claim_args = dict(base, type="claim", publication_key=key + ":claim", data={"assertion": "Fresh default-profile discovery reproduces this board's explicit wiki configuration and validated release tools.", "scope": fleet["board"], "evidence": [capture["evidence"]]})
    claim = require_reply(child(options, "default", "_actor", {"action": "tool", "tool": "swarm_publish", "args": claim_args}, extra))
    require_reply(child(options, "default", "_actor", {"action": "tool", "tool": "swarm_publish", "args": claim_args}, extra), duplicate=True)
    role = fleet.get("existing_project_role_map", {}).get("verification")
    verifier = role if role in fleet["profiles"] else next(p for p in fleet["profiles"] if p.endswith("-verifier"))
    args = dict(base, type="verification", publication_key=key + ":verification", data={"claim_id": claim["event_id"], "scope": fleet["board"], "verdict": "pass", "rationale": "pending fresh source checks", "live_evidence": [capture["evidence"]]})
    verification_payload = {"action": "verify", "project": fleet["project_key"], "source": str(source), "reference": capture["evidence"], "args": args}
    verified = require_reply(child(options, verifier, "_actor", verification_payload, extra))
    require_reply(child(options, verifier, "_actor", verification_payload, extra), duplicate=True)
    authorized = set(cfg.get("profiles", [])) | set(cfg.get("maintainers", []))
    outsider = next(p for f in inventory["fleets"] for p in f["profiles"] if p not in authorized)
    outsider_proof = rejected_without_changes(lambda: child(options, outsider, "_actor", {"action": "tool", "tool": "swarm_capture", "args": capture_args}, extra), inventory)
    preserved(before, board_snapshot(fleet["task_source"]))
    child(options, "default", "_actor", {"action": "complete", "board": fleet["board"], "task_id": tid}, extra)
    counts = preserved(before, board_snapshot(fleet["task_source"]))
    return {"ok": True, "executed": True, "plan": plan, "task_id": tid, "capture": capture,
            "claim": claim, "verification": verified, "verifier": verifier,
            "denied_outsider": outsider, "wrong_board_denied": True, "omitted_board_routes_configured": True,
            "creation_observation": creation["creation_observation"],
            "negative_checks": {"wrong_board": wrong_board_proof, "outsider": outsider_proof},
            "retries_duplicate": True, "preexisting_rows_preserved": counts,
            "historical_findings_claim": "No historical findings adopted or independently verified by this canary."}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("profile-check", "board-canary", "_probe", "_actor"))
    p.add_argument("--inventory", default=str(Path(__file__).resolve().parents[1] / "docs/swarm-wiki-fleet-inventory.json"))
    p.add_argument("--reviewed-plan", help="Frozen fleet-config-plan.json; compares its owned inventory mappings")
    p.add_argument("--hermes-root", default=str(Path.home() / ".hermes"))
    p.add_argument("--agent-root", default=str(Path.home() / ".hermes/hermes-agent"))
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--release-sha", required=True)
    p.add_argument("--profile", default="default")
    p.add_argument("--board")
    p.add_argument("--execute", action="store_true")
    return p


def main(argv=None):
    options = parser().parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", options.release_sha):
        raise ValueError("release SHA must be a full lowercase Git commit")
    try:
        # Discovery can write ordinary plugin cache entries and logs; it never calls a model.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if options.command == "_probe":
                result = runtime_probe(options.release_sha, options.hermes_root)
            elif options.command == "_actor":
                runtime_probe(options.release_sha, options.hermes_root)
                result = actor_action(options, json.load(sys.stdin))
            else:
                inventory = json.loads(Path(options.inventory).read_text())
                result = profile_report(options, inventory) if options.command == "profile-check" else board_canary(options, inventory)
    except Exception as error:
        result = {"ok": False, "error_type": type(error).__name__}
    prefix = MARKER if options.command.startswith("_") else ""
    print(prefix + json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
