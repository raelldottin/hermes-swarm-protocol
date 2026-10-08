"""Versioned publications and immutable captures; no Hermes or model dependency."""
from __future__ import annotations

import hashlib
import json
import os
import re
import contextlib
import stat
import uuid
from pathlib import Path

PROTOCOL = "hermes-swarm/wiki-v1"
PREFIX = PROTOCOL + "\n"
VERSION = 1
LATEST_VERSION = 2
AUDIT_PROTOCOL = "hermes-swarm/wiki-v2"
AUDIT_PREFIX = AUDIT_PROTOCOL + "\n"
AUDIT_TYPES = {"provenance", "request_assessment"}
LIVE_KINDS = {"artifact", "file", "commit", "runtime"}
FIELDS = {
    "claim": ({"assertion", "scope"}, {"consequential", "confidence"}),
    "verification": ({"claim_id", "verdict", "scope", "rationale", "live_evidence"}, {"memory_status", "memory_digest"}),
    "contradiction": ({"claims", "scope", "explanation"}, set()),
    "reconciliation": ({"contradiction_id", "disposition", "scope", "conclusion", "supporting_records"}, set()),
    "decision": ({"conclusion", "rationale"}, {"claims"}),
    "consequence": ({"claims", "affected_task_ids", "impact"}, set()),
    "route": ({"role", "outcome"}, {"target_profile", "request_id"}),
    "artifact": ({"capture", "media_type", "source_path"}, {"source_origin", "source_root"}),
    "synthesis": ({"node_path", "node_sha256", "source_digests", "category"}, set()),
    "provenance": ({"subject", "relation", "rationale"}, {"source_task_ids", "parent_revisions", "attributed_actor", "producer"}),
    "request_assessment": ({"subject_task_id", "request_id", "request_digest", "artifact_commit", "scope", "rationale", "acceptance_results", "verdict", "live_evidence"}, set()),
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def byte_hash(data):
    return hashlib.sha256(data).hexdigest()


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " must be non-empty text")
    if len(value) > 100_000:
        raise ValueError(name + " exceeds 100000 characters")
    return value


def relative(value):
    text(value, "path")
    p = Path(value)
    if p.is_absolute() or ".." in p.parts or str(p) == "." or "\\" in value:
        raise ValueError("path must be a confined relative path")
    return p.as_posix()


def sha256(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("expected a lowercase SHA-256")
    return value


def refs(values):
    if not isinstance(values, list):
        raise ValueError("evidence must be an array")
    result = []
    shapes = {
        "artifact": {"path", "sha256"}, "file": {"path", "sha256"},
        "knowledge": {"path", "sha256"}, "commit": {"sha"},
        "runtime": {"text"}, "record": {"event_id", "digest"}, "uri": {"uri"},
    }
    for ref in values:
        if not isinstance(ref, dict) or ref.get("kind") not in shapes:
            raise ValueError("invalid evidence kind")
        required = shapes[ref["kind"]]
        optional = {"scope"} if ref["kind"] == "commit" else set()
        if not required | {"kind"} <= set(ref) or set(ref) - (required | {"kind"} | optional):
            raise ValueError("invalid evidence fields")
        if "scope" in ref and ref["scope"] not in {"current", "historical"}:
            raise ValueError("invalid commit reference scope")
        for key in required:
            text(ref[key], key)
        if "path" in ref:
            relative(ref["path"])
        if "sha256" in ref:
            sha256(ref["sha256"])
        if "digest" in ref:
            sha256(ref["digest"])
        if ref["kind"] == "commit" and not re.fullmatch(r"[0-9a-f]{7,40}", ref["sha"]):
            raise ValueError("invalid commit SHA")
        if ref["kind"] == "uri" and not re.match(r"^(https?|test)://", ref["uri"]):
            raise ValueError("unsupported citation URI")
        result.append(dict(ref))
    return result


def payload(kind, data):
    if kind not in FIELDS or not isinstance(data, dict):
        raise ValueError("unknown publication type")
    required, optional = FIELDS[kind]
    allowed = required | optional | {"evidence", "supersedes"}
    if not required <= set(data) or set(data) - allowed:
        raise ValueError("missing/unknown payload fields: " + kind)
    result = dict(data)
    result["evidence"] = refs(data.get("evidence", []))
    for key in required | optional | {"supersedes"}:
        if key not in data:
            continue
        value = data[key]
        if key in {"claims", "affected_task_ids", "supporting_records", "source_task_ids"}:
            if not isinstance(value, list) or not value:
                raise ValueError(key + " must be a non-empty array")
            for item in value:
                text(item, key)
        elif key == "subject":
            result[key] = audit_subject(value)
        elif key == "parent_revisions":
            result[key] = refs(value)
            if not value or any(r["kind"] != "knowledge" for r in value):
                raise ValueError("derivation parents must be knowledge revisions")
        elif key == "acceptance_results":
            if not isinstance(value, list) or not value:
                raise ValueError("assessment requires criterion results")
            for item in value:
                if not isinstance(item, dict) or set(item) != {"index", "criterion_digest", "verdict", "rationale", "evidence"}:
                    raise ValueError("invalid criterion result fields")
                if type(item["index"]) is not int or item["index"] < 0:
                    raise ValueError("invalid criterion index")
                sha256(item["criterion_digest"])
                text(item["rationale"], "criterion rationale")
                if item["verdict"] not in {"pass", "fail", "partial", "inconclusive", "blocked"}:
                    raise ValueError("invalid criterion verdict")
                refs(item["evidence"])
        elif key == "request_digest":
            sha256(value)
        elif key == "live_evidence":
            result[key] = refs(value)
        elif key == "capture":
            result[key] = refs([value])[0]
            if result[key]["kind"] != "artifact":
                raise ValueError("capture must reference a raw artifact")
        elif key == "source_digests":
            if not isinstance(value, dict) or not value:
                raise ValueError("source_digests must bind source event IDs to digests")
            for event_id, event_digest in value.items():
                text(event_id, "event_id")
                sha256(event_digest)
        elif key == "consequential":
            if not isinstance(value, bool):
                raise ValueError("consequential must be boolean")
        elif key == "confidence":
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not 0 <= value <= 1:
                raise ValueError("confidence must be between 0 and 1")
        else:
            text(value, key)
    if kind == "claim":
        result.setdefault("consequential", False)
    if kind == "contradiction" and len(set(data["claims"])) < 2:
        raise ValueError("contradiction requires two distinct claims")
    if kind == "verification":
        if data["verdict"] not in {"pass", "fail", "partial", "inconclusive", "blocked"}:
            raise ValueError("invalid verdict")
        if data["verdict"] == "pass" and not any(r["kind"] in LIVE_KINDS for r in result["live_evidence"]):
            raise ValueError("pass requires non-memory live evidence")
        if data.get("memory_status") and data["memory_status"] not in {"MEMORY_AVAILABLE", "MEMORY_EMPTY", "MEMORY_TIMEOUT", "MEMORY_ERROR"}:
            raise ValueError("invalid memory status")
    if kind == "reconciliation" and data["disposition"] not in {"resolved", "narrowed", "withdrawn"}:
        raise ValueError("invalid reconciliation disposition")
    if kind == "route":
        if data["outcome"] not in {"ROUTE_RESOLVED", "ROUTE_UNRESOLVED"}:
            raise ValueError("invalid route outcome")
        if data["outcome"] == "ROUTE_RESOLVED":
            text(data.get("target_profile"), "target_profile")
        elif "target_profile" in data:
            raise ValueError("an unresolved route cannot name a guessed profile")
    if kind == "synthesis":
        relative(data["node_path"])
        sha256(data["node_sha256"])
        if data["category"] not in {"architecture", "investigations"}:
            raise ValueError("invalid synthesis category")
    if kind == "artifact":
        relative(data["source_path"])
        if data.get("source_origin") and data["source_origin"] not in {"workspace", "knowledge", "wiki"}:
            raise ValueError("invalid source origin")
    if kind == "provenance":
        if data["relation"] not in {"adoption", "work_link", "derivation", "producer_observation", "actor_attribution", "unknown_disclosure"}:
            raise ValueError("invalid provenance relation")
        if data["relation"] in {"adoption", "work_link", "derivation"} and result["subject"]["kind"] != "knowledge":
            raise ValueError("knowledge relation requires knowledge subject")
        if data["relation"] == "producer_observation" and result["subject"]["kind"] != "task_event":
            raise ValueError("producer observation requires event subject")
        if data["relation"] in {"actor_attribution", "unknown_disclosure"} and result["subject"]["kind"] not in {"task_event", "task"}:
            raise ValueError("identity relation requires event or task subject")
        if data["relation"] == "actor_attribution" and not data.get("attributed_actor"):
            raise ValueError("attribution requires actor")
        if data["relation"] != "actor_attribution" and "attributed_actor" in data:
            raise ValueError("only attribution may assert a historical actor")
        if data["relation"] == "work_link" and not data.get("source_task_ids"):
            raise ValueError("work link requires canonical task IDs")
        if data["relation"] == "derivation" and not data.get("parent_revisions"):
            raise ValueError("derivation requires explicit parent revisions")
    if kind == "request_assessment":
        if not re.fullmatch(r"[0-9a-f]{40}", data["artifact_commit"]):
            raise ValueError("assessment requires full artifact commit")
        if data["verdict"] not in {"pass", "fail", "partial", "inconclusive", "blocked"}:
            raise ValueError("invalid assessment verdict")
    canonical(result)  # Reject non-JSON values and NaN before any mutation.
    return result


def audit_subject(value):
    if not isinstance(value, dict):
        raise ValueError("subject must be a typed object")
    if value.get("kind") == "knowledge":
        if set(value) != {"kind", "path", "sha256"}:
            raise ValueError("invalid knowledge subject")
        relative(value["path"])
    elif value.get("kind") == "task_event":
        if set(value) != {"kind", "id", "board", "sha256"} or type(value["id"]) is not int or value["id"] < 1:
            raise ValueError("invalid task event subject")
        text(value["board"], "board")
    elif value.get("kind") == "task":
        if set(value) != {"kind", "id", "board", "sha256"}:
            raise ValueError("invalid task subject")
        text(value["id"], "task id")
        text(value["board"], "board")
    else:
        raise ValueError("unsupported audit subject")
    sha256(value["sha256"])
    return dict(value)


def is_publication(body):
    return isinstance(body, str) and body.startswith((PREFIX, AUDIT_PREFIX))


def make_record(project, task_id, actor, key, topic, kind, data, recorded_at, workspace=None, schema_version=None):
    for name, value in (("project", project), ("task", task_id), ("actor", actor), ("key", key), ("topic", topic)):
        text(value, name)
    if not isinstance(recorded_at, int) or isinstance(recorded_at, bool) or recorded_at < 0:
        raise ValueError("invalid recorded time")
    body = payload(kind, data)
    version = schema_version if schema_version is not None else LATEST_VERSION if kind in AUDIT_TYPES else VERSION
    if version not in {VERSION, LATEST_VERSION} or (kind in AUDIT_TYPES and version != LATEST_VERSION):
        raise ValueError("unsupported publication schema")
    record = {
        "protocol": AUDIT_PROTOCOL if version == LATEST_VERSION else PROTOCOL, "schema_version": version,
        "event_id": "swe_" + digest([project, task_id, actor, key])[:32],
        "project": project, "task_id": task_id, "actor": actor,
        "publication_key": key, "topic": topic, "type": kind,
        "recorded_at": recorded_at, "data": body,
        "payload_digest": digest({"type": kind, "topic": topic, "data": body}),
    }
    if workspace is not None:
        text(workspace, "workspace")
        if not Path(workspace).is_absolute():
            raise ValueError("publication workspace must be absolute")
        record["workspace"] = workspace
    return record


def decode_record(comment):
    body = comment.get("body") or ""
    if not isinstance(body, str):
        raise ValueError("comment body must be text")
    if not is_publication(body):
        return None
    prefix = AUDIT_PREFIX if body.startswith(AUDIT_PREFIX) else PREFIX
    record = json.loads(body[len(prefix):])
    if not isinstance(record, dict) or type(record.get("schema_version")) is not int or (record.get("protocol"), record.get("schema_version")) not in {(PROTOCOL, VERSION), (AUDIT_PROTOCOL, LATEST_VERSION)}:
        raise ValueError("unsupported publication schema")
    if prefix != record["protocol"] + "\n":
        raise ValueError("publication prefix does not match protocol")
    expected = make_record(record["project"], record["task_id"], record["actor"],
                           record["publication_key"], record["topic"], record["type"],
                           record["data"], record["recorded_at"], record.get("workspace"), record["schema_version"])
    if record != expected or record["actor"] != comment.get("author") or record["task_id"] != comment.get("task_id"):
        raise ValueError("publication identity or digest mismatch")
    return record


def append_record(conn, add_comment, record, validate=None):
    """Serialize idempotency checks and the canonical write under one transaction."""
    if conn.in_transaction:
        raise ValueError("publication requires an independent write transaction")
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = conn.execute("SELECT id, task_id, author, body, created_at FROM task_comments WHERE task_id=? ORDER BY id",
                            (record["task_id"],)).fetchall()
        for row in rows:
            comment = dict(zip(("id", "task_id", "author", "body", "created_at"), row))
            try:
                old = decode_record(comment)
            except (ValueError, KeyError, TypeError):
                continue
            if old and old["event_id"] == record["event_id"]:
                if old["payload_digest"] != record["payload_digest"]:
                    raise ValueError("publication key already used with different payload")
                conn.commit()
                return old, comment["id"], True
        if validate is not None:
            validate()
        prefix = AUDIT_PREFIX if record["schema_version"] == LATEST_VERSION else PREFIX
        comment_id = add_comment(conn, record["task_id"], author=record["actor"], body=prefix + canonical(record))
        conn.commit()
        return record, comment_id, False
    except BaseException:
        conn.rollback()
        raise


def audit_tables(conn):
    result = {}
    for table in ("tasks", "task_events", "task_runs"):
        cursor = conn.execute("SELECT * FROM " + table)
        names = [column[0] for column in cursor.description]
        result[table] = [dict(zip(names, row)) for row in cursor]
    return result


def original_event_actor(row, tables):
    run = next((r for r in tables["task_runs"] if r["id"] == row.get("run_id")), None)
    if run and run.get("profile"):
        return run["profile"]
    try:
        data = json.loads(row.get("payload") or "{}")
    except (ValueError, TypeError):
        data = {}
    if isinstance(data, dict):
        for key in ("author", "actor", "by", "profile"):
            if isinstance(data.get(key), str) and data[key].strip():
                return data[key]
    if row.get("kind") == "created":
        task = next((t for t in tables["tasks"] if t["id"] == row["task_id"]), {})
        return task.get("created_by")
    return None


def validate_audit_record(event, tables, knowledge, board, maintainers, reference, live, events=()):
    """Shared fail-closed audit validation for publishers and read-only projection."""
    d = event["data"]
    tasks = {t["id"]: t for t in tables["tasks"]}
    event_id = event.get("event_id", "incoming")
    def available(ref):
        if not reference(ref, event_id):
            raise ValueError("audit evidence is missing or changed")
    for ref in d["evidence"] + d.get("live_evidence", []):
        available(ref)
    if event["type"] == "provenance":
        if event["actor"] not in maintainers:
            raise ValueError("only configured maintainers may annotate provenance")
        subject = d["subject"]
        if len(set(d.get("source_task_ids", []))) != len(d.get("source_task_ids", [])) or any(t not in tasks for t in d.get("source_task_ids", [])):
            raise ValueError("source tasks must be unique and exist on this board")
        if subject["kind"] == "knowledge":
            data = knowledge.get(subject["path"])
            if data is None or byte_hash(data) != subject["sha256"]:
                raise ValueError("provenance subject revision changed")
            for parent in d.get("parent_revisions", []):
                data = knowledge.get(parent["path"])
                if data is None or byte_hash(data) != parent["sha256"]:
                    raise ValueError("derivation parent revision changed")
                available(parent)
            graph = {}
            for prior in [*events, event]:
                if prior["type"] == "provenance" and prior["data"]["subject"]["kind"] == "knowledge":
                    pd = prior["data"]
                    graph.setdefault(pd["subject"]["path"], set()).update(r["path"] for r in pd.get("parent_revisions", []))
            def visit(path, ancestors):
                if path in ancestors:
                    raise ValueError("cyclic knowledge derivation")
                for parent in graph.get(path, []):
                    visit(parent, ancestors | {path})
            visit(subject["path"], set())
        elif subject["kind"] == "task":
            row = tasks.get(subject["id"])
            if subject["board"] != board or not row or digest(row) != subject["sha256"]:
                raise ValueError("task subject missing, changed or outside board")
            actor = row.get("created_by")
            if d["relation"] not in {"actor_attribution", "unknown_disclosure"}:
                raise ValueError("task subjects only support creator provenance")
            if d["relation"] == "actor_attribution" and (not actor or d["attributed_actor"] != actor):
                raise ValueError("historical attribution lacks canonical identity evidence")
            if d["relation"] == "unknown_disclosure" and actor:
                raise ValueError("an actor with canonical identity is not unknown")
        else:
            row = next((e for e in tables["task_events"] if e["id"] == subject["id"]), None)
            if subject["board"] != board or not row or digest(row) != subject["sha256"]:
                raise ValueError("event subject is missing, changed or outside board")
            actor = original_event_actor(row, tables)
            if d["relation"] == "actor_attribution" and (not actor or d["attributed_actor"] != actor):
                raise ValueError("historical attribution lacks canonical identity evidence")
            if d["relation"] == "unknown_disclosure" and actor:
                raise ValueError("an actor with canonical identity is not unknown")
    elif event["type"] == "request_assessment":
        task = tasks.get(d["subject_task_id"])
        if not task:
            raise ValueError("assessed task is missing")
        try:
            request = json.loads(task.get("body") or "{}")
        except (ValueError, TypeError) as error:
            raise ValueError("invalid legacy request") from error
        if not isinstance(request, dict) or request.get("protocol") != "hermes-swarm/v1" or request.get("kind") != "request" or request.get("request_id") != d["request_id"] or digest(request) != d["request_digest"]:
            raise ValueError("assessment does not bind the exact legacy request")
        if d["scope"] != "request:" + d["request_id"] + "@" + d["artifact_commit"]:
            raise ValueError("assessment scope must bind request and frozen commit")
        if event["actor"] in {task.get("created_by"), request.get("target_profile"), task.get("assignee")}:
            raise ValueError("request assessment requires an independent verifier")
        criteria = request.get("acceptance", [])
        results = d["acceptance_results"]
        if not criteria or len(results) != len(criteria) or {r["index"] for r in results} != set(range(len(criteria))):
            raise ValueError("assessment must cover every acceptance criterion exactly once")
        available({"kind": "commit", "sha": d["artifact_commit"], "scope": "historical"})
        for result in results:
            if result["criterion_digest"] != digest(criteria[result["index"]]):
                raise ValueError("assessment criterion text changed")
            for ref in result["evidence"]:
                available(ref)
            if result["verdict"] == "pass" and not any(live(ref, event_id) for ref in result["evidence"]):
                raise ValueError("criterion pass requires available non-memory evidence")
        all_pass = all(r["verdict"] == "pass" for r in results)
        if (d["verdict"] == "pass") != all_pass:
            raise ValueError("aggregate assessment does not match criterion coverage")
        if d["verdict"] == "pass" and not any(live(ref, event_id) for ref in d["live_evidence"]):
            raise ValueError("assessment pass requires available non-memory evidence")
    else:
        raise ValueError("unsupported audit record type")
    return True


def confined(root, rel):
    root = Path(root)
    if root.is_symlink():
        raise ValueError("source root cannot be a symlink")
    root = root.resolve()
    path = root / relative(rel)
    cursor = path
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError("symlink traversal is not allowed")
        cursor = cursor.parent
    if not path.resolve().is_relative_to(root):
        raise ValueError("reference escapes source root")
    return path


def _directory_fd(root, parts, create=False):
    root = Path(root)
    if root.is_symlink():
        raise ValueError("source root cannot be a symlink")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root, flags)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def open_confined(root, rel):
    """Anchor every untrusted path component, including concurrent replacements."""
    confined(root, rel)
    parts = Path(relative(rel)).parts
    directory = _directory_fd(root, parts[:-1])
    try:
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("source must be a regular file")
    return descriptor


def read_confined(root, rel):
    with os.fdopen(open_confined(root, rel), "rb") as stream:
        return stream.read()


def file_hash(root, rel):
    with os.fdopen(open_confined(root, rel), "rb") as stream:
        h = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
        return h.hexdigest()


def capture(workspace, source, category, source_root=None):
    if category not in {"evidence", "test-results", "source-snapshots"}:
        raise ValueError("invalid artifact category")
    workspace = Path(workspace)
    if workspace.is_symlink():
        raise ValueError("workspace root cannot be a symlink")
    workspace = workspace.resolve()
    relative(source)
    with contextlib.ExitStack() as stack:
        descriptor = open_confined(source_root or workspace, source)
        stack.callback(os.close, descriptor)
        before = os.fstat(descriptor)
        # Directory descriptors prevent a concurrent worker from redirecting
        # source/destination parents through symlinks after validation.
        raw = _directory_fd(workspace, (".swarm", "raw", category), create=True)
        stack.callback(os.close, raw)
        temporary = ".capture-" + uuid.uuid4().hex
        temporary_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=raw)
        def cleanup():
            try:
                os.unlink(temporary, dir_fd=raw)
            except FileNotFoundError:
                pass
        stack.callback(cleanup)
        h = hashlib.sha256()
        with os.fdopen(temporary_fd, "wb") as stream:
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
            after = os.fstat(descriptor)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("capture source changed during read")
            sha = h.hexdigest()
            os.fchmod(stream.fileno(), 0o400)
            try:
                os.link(temporary, sha, src_dir_fd=raw, dst_dir_fd=raw, follow_symlinks=False)
            except FileExistsError:
                pass  # Verify the existing content; never replace it.
            try:
                check = os.open(sha, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=raw)
                with os.fdopen(check, "rb") as captured:
                    if not stat.S_ISREG(os.fstat(captured.fileno()).st_mode):
                        raise ValueError("existing raw artifact is corrupt")
                    actual = hashlib.sha256()
                    for chunk in iter(lambda: captured.read(1024 * 1024), b""):
                        actual.update(chunk)
                    if actual.hexdigest() != sha:
                        raise ValueError("existing raw artifact is corrupt")
            except OSError as error:
                raise ValueError("existing raw artifact is corrupt") from error
        return {"kind": "artifact", "path": category + "/" + sha, "sha256": sha}


def origin(workspace, tree, rel):
    path = (Path(workspace) / relative(rel)).resolve()
    knowledge = Path(tree).resolve()
    if path == knowledge or knowledge in path.parents:
        return "knowledge"
    for parent in path.parents:
        if parent.name == ".wiki-generations":
            return "wiki"
        if re.fullmatch(r"\..+-generations", parent.name):
            try:
                manifest = json.loads((parent / path.relative_to(parent).parts[0] / "manifest.json").read_text())
                if "compiler_source_sha256" in manifest and "sources" in manifest:
                    return "wiki"
            except (ValueError, OSError, IndexError):
                pass
    return "workspace"


def live_reference(ref, workspace, tree, events):
    if ref["kind"] not in LIVE_KINDS:
        return False
    memory_hashes = set()
    for event in events.values():
        if event["type"] != "artifact":
            continue
        d = event["data"]
        source_origin = d.get("source_origin") or origin(d.get("source_root", workspace), tree, d["source_path"])
        if source_origin in {"knowledge", "wiki"}:
            memory_hashes.add(d["capture"]["sha256"])
    if ref.get("sha256") in memory_hashes:
        return False
    if ref["kind"] == "file" and origin(workspace, tree, ref["path"]) != "workspace":
        return False
    return True
