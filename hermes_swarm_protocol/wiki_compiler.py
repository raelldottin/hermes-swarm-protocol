"""Deterministic, read-only knowledge projection and atomic local publication."""
from __future__ import annotations

import collections
import base64
import contextlib
import datetime as dt
import fcntl
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote as urlquote

import wiki_records as records

COMPILER_VERSION = 2
NOTICE = "Generated, untrusted projection. Kanban owns work state; ByteRover owns knowledge; original records and evidence govern."
REQUIRED = {
    "tasks": {"id", "title", "body", "status", "created_by", "created_at", "assignee", "completed_at"},
    "task_links": {"parent_id", "child_id"},
    "task_comments": {"id", "task_id", "author", "body", "created_at"},
    "task_events": {"id", "task_id", "run_id", "kind", "payload", "created_at"},
    "task_runs": {"id", "task_id", "profile", "started_at", "ended_at", "summary", "error", "status", "outcome"},
}


def source_text(value):
    if isinstance(value, bytes):
        return "SQLite BLOB: " + str(len(value)) + " bytes; sha256=" + records.byte_hash(value) + "; binary source, not interpreted as text"
    return str(value)


def board_snapshot_values(value):
    """Lossless typed SQLite BLOB encoding; text-only snapshots stay identical.

    SQLite scalar cells cannot contain mappings, so this tag cannot collide with
    a TEXT cell. Keep raw snapshot bytes unchanged and encode only for hashing.
    """
    if isinstance(value, bytes):
        return {"$sqlite_blob": {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}}
    if isinstance(value, dict):
        return {key: board_snapshot_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [board_snapshot_values(item) for item in value]
    return value


def board_snapshot_digest(tables):
    return records.digest(board_snapshot_values(tables))


def esc(value):
    value = html.escape(" ".join(source_text(value).splitlines()), quote=True)
    return re.sub(r"([\\`*_{}\[\]()#!|])", r"\\\1", value)


def quote(value):
    return "\n".join("> " + esc(line) for line in source_text(value).splitlines()) or "> (empty)"


def utc(value):
    try:
        return dt.datetime.fromtimestamp(float(value), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError, OverflowError, OSError):
        return "UNKNOWN_TIME"


def slug(value):
    return records.digest(str(value))[:24]


def anchor(table, row_id, phase=""):
    return "source-" + slug([table, str(row_id), phase])


def inventory(root, markdown=False, ignore_staging=False):
    root = Path(root)
    if root.is_symlink():
        raise ValueError("input root is a symlink: " + str(root))
    if not root.exists():
        return {}
    if not root.is_dir():
        raise ValueError("input root is not a directory")
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            if (Path(directory) / name).is_symlink():
                raise ValueError("input symlink is not allowed: " + name)
        for name in sorted(files):
            path = Path(directory) / name
            if ignore_staging and name.startswith(".capture-"):
                continue  # Reserved, uncommitted capture staging; never cited.
            if not markdown or path.suffix == ".md":
                if not path.is_file():
                    raise ValueError("input must be a regular file")
                name_in_root = path.relative_to(root).as_posix()
                result[name_in_root] = records.read_confined(root, name_in_root)
    return dict(sorted(result.items()))


def stable_inventory(root, markdown=False, ignore_staging=False):
    for _ in range(3):
        first = inventory(root, markdown, ignore_staging)
        if first == inventory(root, markdown, ignore_staging):
            return first
    raise ValueError("input changed during snapshot: " + str(root))


def snapshot(db, tree, raw, rules):
    db, tree, raw, rules = (Path(p).absolute() for p in (db, tree, raw, rules))
    if not db.is_file() or db.is_symlink() or not tree.is_dir() or not rules.is_file() or rules.is_symlink():
        raise ValueError("DB, knowledge tree and trusted rules must exist without root symlinks")
    with contextlib.closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, isolation_level=None)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        tables = {}
        try:
            for table, required in REQUIRED.items():
                columns = {row[1] for row in conn.execute("PRAGMA table_info(" + table + ")")}
                if not required <= columns:
                    raise ValueError("missing schema in " + table + ": " + ", ".join(sorted(required - columns)))
                order = "parent_id, child_id" if table == "task_links" else "id"
                tables[table] = [dict(row) for row in conn.execute("SELECT * FROM " + table + " ORDER BY " + order)]
        finally:
            conn.rollback()
    knowledge = stable_inventory(tree, True)
    artifacts = stable_inventory(raw, ignore_staging=True)
    rule_bytes = rules.read_bytes()
    if rule_bytes != rules.read_bytes() or not rule_bytes.strip():
        raise ValueError("rules changed during snapshot or are empty")
    return {"tables": tables, "knowledge": knowledge, "artifacts": artifacts,
            "rules": rule_bytes, "paths": {k: str(p.resolve()) for k, p in
            (("db", db), ("tree", tree), ("raw", raw), ("rules", rules))}}


def node(data):
    content = data.decode("utf-8")
    metadata = {}
    if content.startswith("---\n"):
        parts = content.split("\n---", 1)
        if len(parts) != 2:
            raise ValueError("unterminated knowledge frontmatter")
        from ruamel.yaml import YAML
        metadata = YAML(typ="safe").load(parts[0][4:]) or {}
        if not isinstance(metadata, dict):
            raise ValueError("frontmatter must be a mapping")
        content = parts[1].lstrip("\r\n")
    return metadata, content


def source(table, row):
    return table + "/" + str(row["id"])


class Projection:
    def __init__(self, inputs, project, board, workspace, repo, valid_statuses, maintainers=(), task_workspace_roots=()):
        if not valid_statuses:
            raise ValueError("installed Hermes statuses are required")
        self.inputs, self.project, self.board = inputs, project, board
        self.workspace, self.repo = Path(workspace).resolve(), Path(repo).resolve()
        self.task_workspace_roots = tuple(sorted({self.workspace, *(Path(p).expanduser().resolve() for p in task_workspace_roots)}))
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        self.repo_head = head.stdout.strip() if head.returncode == 0 else None
        self.maintainers = set(maintainers)
        self.findings = []
        self.tasks = {r["id"]: r for r in inputs["tables"]["tasks"]}
        self.events, self.event_sources, self.legacy = {}, {}, collections.defaultdict(list)
        self.nodes = {}
        self.invalid_nodes = set()
        self.valid_statuses = set(valid_statuses)
        self.ref_cache = {}
        self.load()

    def finding(self, kind, target, message):
        row = {"class": kind, "target": str(target), "message": str(message), "severity": "warning"}
        if not any(all(f[k] == row[k] for k in ("class", "target", "message")) for f in self.findings):
            self.findings.append(row)

    def load(self):
        for task in self.tasks.values():
            if task["status"] not in self.valid_statuses:
                self.finding("status-integrity", task["id"], "Unknown task status")
            if not task.get("created_by") or utc(task.get("created_at")) == "UNKNOWN_TIME":
                self.finding("missing-provenance", task["id"], "Task assertion lacks creator/time")
        for row in self.inputs["tables"]["task_comments"]:
            origin = source("task_comments", row)
            if row["task_id"] not in self.tasks:
                self.finding("stale-reference", origin, "Comment task missing")
            if not row.get("author") or utc(row.get("created_at")) == "UNKNOWN_TIME":
                self.finding("missing-provenance", origin, "Comment lacks author/time")
            try:
                event = records.decode_record(row)
                if event:
                    if event["project"] != self.project:
                        self.finding("project-boundary", origin, "Publication belongs to another project")
                        continue
                    event_id = event["event_id"]
                    if event_id in self.events:
                        self.finding("duplicate-publication", origin, "Repeated event ID; original retained")
                        continue
                    self.events[event_id] = event
                    self.event_sources[event_id] = row
                    continue
                if (row.get("body") or "").startswith("swarm_verify "):
                    body = row["body"]
                    record = json.loads(body[body.index("{"):])
                    if not isinstance(record, dict) or record.get("protocol") != "hermes-swarm/v1" or record.get("kind") != "verification":
                        raise ValueError("invalid legacy verification")
                    if record.get("verifier") != row["author"]:
                        raise ValueError("legacy verifier identity mismatch")
                    if record.get("verdict") not in {"pass", "fail", "inconclusive", "blocked"}:
                        raise ValueError("unknown legacy verdict")
                    if not isinstance(record.get("live_evidence"), list):
                        raise ValueError("invalid legacy live evidence")
                    self.legacy[row["task_id"]].append((row, record))
                    if record["verdict"] == "pass" and not any(isinstance(x, str) and x.strip() for x in record["live_evidence"]):
                        self.finding("invalid-verification", origin, "INVALID PASS: no live evidence")
            except (ValueError, KeyError, TypeError) as error:
                self.finding("invalid-publication", origin, str(error))
        for name, data in self.inputs["knowledge"].items():
            try:
                self.nodes[name] = node(data)
            except ImportError:
                raise
            except Exception as error:
                # Parsing a node is isolated; the original bytes remain cited.
                self.nodes[name] = ({}, "UNPARSEABLE NODE")
                self.invalid_nodes.add(name)
                self.finding("invalid-knowledge", name, str(error))
        self.superseded = set()
        for event in self.events.values():
            prior = self.events.get(event["data"].get("supersedes"))
            if not event["data"].get("supersedes"):
                continue
            if prior and prior["type"] == event["type"] and prior["topic"] == event["topic"] and (prior["actor"] == event["actor"] or event["actor"] in self.maintainers):
                self.superseded.add(prior["event_id"])
            else:
                self.finding("invalid-supersession", event["event_id"], "Corrections must preserve type/topic and original author or maintainer authority")
        self.audit()

    def ordered(self, kind=None):
        return sorted((e for e in self.events.values() if kind is None or e["type"] == kind),
                      key=lambda e: (self.event_sources[e["event_id"]]["created_at"], e["event_id"]))

    def event_workspace(self, target):
        event = self.events.get(target, {})
        workspace = Path(event.get("workspace", self.workspace))
        if workspace.is_symlink():
            raise ValueError("publication workspace is a symlink")
        workspace = workspace.resolve()
        if not any(workspace.is_relative_to(root) for root in self.task_workspace_roots):
            raise ValueError("publication workspace outside authorized roots")
        return workspace

    def reference(self, ref, target):
        cache_key = records.canonical([ref, self.events.get(target, {}).get("workspace", str(self.workspace))])
        if cache_key in self.ref_cache:
            valid, description = self.ref_cache[cache_key]
        else:
            kind = ref["kind"]
            valid = True
            description = records.canonical(ref)
            try:
                if kind in {"artifact", "knowledge"}:
                    files = self.inputs["artifacts" if kind == "artifact" else "knowledge"]
                    data = files.get(ref["path"])
                    valid = data is not None and records.byte_hash(data) == ref["sha256"]
                elif kind == "file":
                    workspace = self.event_workspace(target)
                    path = records.confined(workspace, ref["path"])
                    valid = path.is_file() and records.file_hash(workspace, ref["path"]) == ref["sha256"]
                elif kind == "record":
                    event = self.events.get(ref["event_id"])
                    valid = event is not None and event["payload_digest"] == ref["digest"]
                elif kind == "commit":
                    result = subprocess.run(["git", "-C", str(self.repo), "cat-file", "-e", ref["sha"] + "^{commit}"],
                                            capture_output=True, timeout=10)
                    valid = result.returncode == 0
                    if valid and ref.get("scope", "current") != "historical" and self.repo_head and not self.repo_head.startswith(ref["sha"]):
                        self.finding("stale-commit", target, "Historical commit exists; not current HEAD: " + ref["sha"])
                elif kind == "uri":
                    description += " (external citation; not fetched or independently validated)"
            except (OSError, ValueError, subprocess.SubprocessError):
                valid = False
            self.ref_cache[cache_key] = valid, description
        if not valid:
            self.finding("stale-reference", target, description)
        return valid

    def usable(self, event):
        refs = event["data"].get("live_evidence", [])
        try:
            workspace = self.event_workspace(event["event_id"])
            return any(records.live_reference(r, workspace, self.inputs["paths"]["tree"], self.events)
                       and self.reference(r, event["event_id"]) for r in refs)
        except (OSError, ValueError):
            return False

    def verifies(self, verification, claim):
        d = verification["data"]
        return (verification["event_id"] not in self.superseded
                and d["claim_id"] == claim["event_id"] and d["scope"] == claim["data"]["scope"]
                and verification["actor"] != claim["actor"] and self.usable(verification))

    def state(self, claim):
        if claim["event_id"] in self.superseded:
            return "SUPERSEDED"
        matches = [v for v in self.ordered("verification") if self.verifies(v, claim)]
        if not matches:
            return "UNVERIFIED"
        verdicts = {v["data"]["verdict"] for v in matches if v["data"]["verdict"] in {"pass", "fail", "blocked"}}
        if len(verdicts) > 1:
            for conflict in self.ordered("contradiction"):
                if conflict["event_id"] not in self.superseded and claim["event_id"] in conflict["data"]["claims"]:
                    resolution = self.resolved(conflict)
                    if resolution:
                        return "RECONCILED: " + resolution["data"]["disposition"].upper()
            return "CONFLICTED"
        return matches[-1]["data"]["verdict"].upper()

    def resolved(self, contradiction):
        for reconciliation in reversed(self.ordered("reconciliation")):
            if reconciliation["event_id"] not in self.superseded and reconciliation["data"]["contradiction_id"] == contradiction["event_id"] and self.valid_reconciliation(reconciliation):
                return reconciliation
        return None

    def valid_reconciliation(self, reconciliation):
        d = reconciliation["data"]
        conflict = self.events.get(d["contradiction_id"])
        if not conflict or conflict["type"] != "contradiction":
            return False
        support = [self.events.get(i) for i in d["supporting_records"]]
        claims = [self.events.get(i) for i in conflict["data"]["claims"]]
        if not all(claims) or not all(support) or any(c["type"] != "claim" for c in claims):
            return False
        return any(v["event_id"] not in self.superseded and v["type"] == "verification" and self.usable(v) and v["data"]["scope"] == d["scope"]
                   and v["data"]["verdict"] in {"pass", "fail", "partial"}
                   and v["data"]["claim_id"] in conflict["data"]["claims"]
                   and v["actor"] not in {c["actor"] for c in claims} for v in support)

    def accepted(self, event):
        d = event["data"]
        active = {i: e["payload_digest"] for i, e in self.events.items() if e["topic"] == event["topic"]
                  and e["type"] != "synthesis" and i not in self.superseded}
        return (event["actor"] in self.maintainers and d["node_path"] in self.inputs["knowledge"]
                and d["node_path"] not in self.invalid_nodes
                and records.byte_hash(self.inputs["knowledge"][d["node_path"]]) == d["node_sha256"]
                and d["source_digests"] == active
                and all(i in self.events and self.events[i]["payload_digest"] == h and i not in self.superseded
                        and self.events[i]["topic"] == event["topic"] for i, h in d["source_digests"].items())
                and all(self.reference(ref, i) for i in d["source_digests"]
                        for ref in self.event_evidence(self.events[i])))

    def event_evidence(self, event):
        d = event["data"]
        return d["evidence"] + d.get("live_evidence", []) + ([d["capture"]] if event["type"] == "artifact" else []) + d.get("parent_revisions", []) + [ref for result in d.get("acceptance_results", []) for ref in result["evidence"]]

    def valid_audit(self, event):
        try:
            return records.validate_audit_record(
                event, self.inputs["tables"], self.inputs["knowledge"], self.board, self.maintainers,
                self.reference, lambda ref, target: records.live_reference(ref, self.event_workspace(target), self.inputs["paths"]["tree"], self.events) and self.reference(ref, target),
                [e for i, e in self.events.items() if i not in self.superseded])
        except (ValueError, OSError, KeyError, TypeError):
            return False

    def provenance(self, target, relation):
        candidates = []
        for event in self.ordered("provenance"):
            d = event["data"]
            subject = d["subject"]
            key = (subject["path"] if subject["kind"] == "knowledge" else
                   "tasks/" + subject["id"] if subject["kind"] == "task" else
                   "task_events/" + str(subject["id"]))
            if key == target and d["relation"] == relation and event["event_id"] not in self.superseded and self.valid_audit(event):
                candidates.append(event)
        return candidates[-1] if candidates else None

    def request_assessment(self, tid):
        candidates = [e for e in self.ordered("request_assessment") if e["data"]["subject_task_id"] == tid and e["event_id"] not in self.superseded and self.valid_audit(e)]
        # Opposing unsuperseded assessments preserve uncertainty rather than latest-write wins.
        if {e["data"]["verdict"] for e in candidates} - {"pass"}:
            return None
        return candidates[-1] if candidates else None

    def synthesis_chain_contains(self, current, target):
        """Validate the entire author-bound predecessor chain before retiring history."""
        ancestors, visited = set(), {current["event_id"]}
        while current["data"].get("supersedes"):
            prior_id = current["data"]["supersedes"]
            prior = self.events.get(prior_id)
            if (not prior or prior_id in visited or prior_id not in self.superseded
                    or any(prior[key] != current[key] for key in ("type", "topic", "project", "actor"))):
                return False
            visited.add(prior_id)
            ancestors.add(prior_id)
            current = prior
        return target in ancestors

    def synthesis_history_successor(self, finding):
        """Retire obsolete node revisions, never lost original evidence or task links."""
        prior = self.events.get(finding["target"])
        if not prior or prior["type"] != "synthesis":
            return None
        if finding["class"] == "stale-reference":
            try:
                ref = json.loads(finding["message"])
            except (ValueError, TypeError):
                return None
            if (not isinstance(ref, dict) or ref.get("kind") != "knowledge"
                    or ref.get("path") != prior["data"]["node_path"]
                    or ref.get("sha256") != prior["data"]["node_sha256"]):
                return None
        elif finding["class"] != "stale-knowledge":
            return None
        for event in reversed(self.ordered("synthesis")):
            if (event["event_id"] not in self.superseded and self.accepted(event)
                    and all(self.reference(ref, event["event_id"]) for ref in self.event_evidence(event))
                    and all(tid in self.tasks for tid in event["data"].get("affected_task_ids", []))
                    and self.synthesis_chain_contains(event, prior["event_id"])):
                return event
        return None

    def finding_outcomes(self):
        for finding in self.findings:
            outcome, correction = "unresolved", None
            target, kind = finding["target"], finding["class"]
            if kind == "missing-provenance" and target in self.nodes:
                correction = self.provenance(target, "adoption")
                outcome = "adopted_current_revision" if correction else outcome
            elif kind == "orphan-topic":
                correction = self.provenance(target, "work_link")
                outcome = "linked" if correction else outcome
            elif kind == "missing-provenance" and (target.startswith(("task_events/", "tasks/")) or target in self.tasks):
                subject_target = "tasks/" + target if target in self.tasks else target
                correction = self.provenance(subject_target, "actor_attribution") or self.provenance(subject_target, "unknown_disclosure")
                if correction:
                    outcome = "attributed" if correction["data"]["relation"] == "actor_attribution" else "disclosed_unknown"
            elif kind in {"missing-independent-verification", "knowledge-gap"} and target in self.tasks:
                correction = self.request_assessment(target)
                outcome = "verified" if correction else outcome
            elif kind in {"stale-knowledge", "stale-reference"} and target in self.superseded:
                correction = self.synthesis_history_successor(finding)
                outcome = "superseded_history" if correction else outcome
            elif kind == "invalid-audit-record" and target in self.superseded:
                # A valid current successor may retire a stale annotation, while
                # both source-bound records remain in the immutable history.
                for event in self.ordered():
                    if event["type"] not in records.AUDIT_TYPES or event["event_id"] in self.superseded or not self.valid_audit(event):
                        continue
                    prior_id, visited = event["data"].get("supersedes"), set()
                    while prior_id in self.superseded and prior_id not in visited:
                        if prior_id == target:
                            correction, outcome = event, "superseded_history"
                            break
                        visited.add(prior_id)
                        prior_id = self.events[prior_id]["data"].get("supersedes")
            finding["outcome"] = outcome
            finding["audit_id"] = "audit_" + records.digest([kind, target, finding["message"]])[:16]
            if correction:
                finding["correction_event_id"] = correction["event_id"]

    @property
    def unresolved_findings(self):
        return [f for f in self.findings if f.get("outcome", "unresolved") == "unresolved"]

    def audit(self):
        for event in self.ordered():
            d, event_id = event["data"], event["event_id"]
            for ref in self.event_evidence(event):
                self.reference(ref, event_id)
            if event["type"] in records.AUDIT_TYPES and not self.valid_audit(event):
                self.finding("invalid-audit-record", event_id, "Untrusted author, changed subject, invalid derivation or incomplete independent assessment")
            links = list(d.get("claims", [])) + list(d.get("supporting_records", []))
            links += [d[k] for k in ("claim_id", "contradiction_id", "supersedes") if k in d]
            for link in links:
                if link not in self.events:
                    self.finding("stale-reference", event_id, "Missing event " + link)
            if event["type"] == "verification":
                claim = self.events.get(d["claim_id"])
                partial = (claim and claim["type"] == "claim" and d["verdict"] == "partial"
                           and event["actor"] != claim["actor"] and self.usable(event))
                full = (claim and claim["type"] == "claim" and d["scope"] == claim["data"]["scope"]
                        and event["actor"] != claim["actor"] and self.usable(event))
                if not claim or claim["type"] != "claim" or not (full or partial):
                    self.finding("invalid-verification", event_id, "Unknown target, self-verification, scope mismatch or unavailable live evidence")
            if event["type"] == "contradiction" and not self.resolved(event):
                self.finding("unresolved-contradiction", event_id, "Both sides retained; no supported reconciliation")
            if event["type"] == "reconciliation":
                if not self.valid_reconciliation(event):
                    self.finding("invalid-reconciliation", event_id, "No independent scoped evidence supports reconciliation")
            if event["type"] == "synthesis" and not self.accepted(event):
                self.finding("stale-knowledge", event_id, "Unaccepted author, changed node, missing/changed/superseded source or topic mismatch")
            for tid in d.get("affected_task_ids", []):
                if tid not in self.tasks:
                    self.finding("stale-reference", event_id, "Affected task missing: " + tid)
        for table in ("tasks", "task_comments", "task_runs"):
            for row in self.inputs["tables"][table]:
                prose = "\n".join(source_text(row.get(k) or "") for k in ("result", "body", "summary", "error"))
                for sha in re.findall(r"\bcommit\s*[:=]\s*([0-9a-f]{7,40})\b", prose):
                    self.reference({"kind": "commit", "sha": sha, "scope": "historical"}, "legacy-heuristic:" + source(table, row))
        for claim in self.ordered("claim"):
            state = self.state(claim)
            if state == "CONFLICTED":
                self.finding("unresolved-contradiction", claim["event_id"], "Opposing independent scoped verdicts")
            if claim["data"]["consequential"] and state not in {"PASS", "SUPERSEDED"}:
                self.finding("missing-independent-verification", claim["event_id"], state)
            refs = claim["data"]["evidence"]
            if claim["data"]["consequential"] and len({records.canonical(r) for r in refs}) < 2:
                self.finding("insufficient-sources", claim["event_id"], "Single-source consequential claim")
        for tid, task in self.tasks.items():
            entries = self.legacy[tid]
            verdicts = {v["verdict"] for _, v in entries if v["verdict"] in {"pass", "fail", "blocked"}}
            if len(verdicts) > 1:
                self.finding("unresolved-contradiction", tid, "Opposing legacy terminal verdicts")
            if entries and task["status"] == "done" and entries[-1][1]["verdict"] in {"fail", "blocked"}:
                self.finding("unresolved-contradiction", tid, "Done task has latest fail/blocked verification")
            try:
                envelope = json.loads(task.get("body") or "{}")
            except (ValueError, TypeError):
                envelope = {}
            if isinstance(envelope, dict) and envelope.get("protocol") == "hermes-swarm/v1" and envelope.get("evidence_required"):
                valid = [(r, v) for r, v in entries if v["verdict"] == "pass" and r["author"] != task.get("created_by") and any(isinstance(x, str) and x.strip() for x in v["live_evidence"])]
                if not valid or (entries and entries[-1][1]["verdict"] != "pass"):
                    self.finding("missing-independent-verification", tid, "Consequential request lacks latest independent pass")
                if envelope.get("acceptance") and not valid:
                    self.finding("knowledge-gap", tid, "Acceptance questions have no independently evidenced answer")
        accepted_paths = {e["data"]["node_path"] for e in self.ordered("synthesis") if self.accepted(e)}
        referenced_nodes = {r["path"] for e in self.events.values() if e["type"] not in records.AUDIT_TYPES for r in e["data"]["evidence"] + e["data"].get("live_evidence", []) if r["kind"] == "knowledge"}
        for name, (meta, _) in self.nodes.items():
            if not meta.get("author") or not (meta.get("createdAt") or meta.get("updatedAt")):
                if name not in accepted_paths:
                    self.finding("missing-provenance", name, "Knowledge assertion lacks author/time; node timestamp alone is not authorship")
            if name not in accepted_paths | referenced_nodes:
                self.finding("orphan-topic", name, "No canonical publication links this node to work")
            related = meta.get("related", [])
            if not isinstance(related, list):
                self.finding("missing-cross-link", name, "related must be a list")
                continue
            for link in related:
                try:
                    target = self.related_path(name, link)
                except ValueError:
                    self.finding("missing-cross-link", name, "Unsafe related reference")
                    continue
                if target not in self.nodes:
                    self.finding("missing-cross-link", name, "Missing related node: " + target)
                else:
                    other = self.nodes[target][0]
                    tokens = []
                    for candidate in (meta, other):
                        words = []
                        for field in ("keywords", "tags"):
                            values = candidate.get(field, []) or []
                            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                                self.finding("invalid-knowledge", name, field + " must be a text array")
                            else:
                                words += values
                        tokens.append(set(words))
                    keywords = tokens[0] & tokens[1]
                    summaries = [str(m.get("summary", "")).lower() for m in (meta, other)]
                    if keywords and bool(re.search(r"\b(not|never|absent)\b", summaries[0])) != bool(re.search(r"\b(not|never|absent)\b", summaries[1])):
                        self.finding("contradiction-candidate", name, "Keyword polarity differs; human review required: " + target)

    def page(self, title):
        return "# " + esc(title) + "\n\n> " + NOTICE + "\n\n"

    def related_path(self, name, link):
        if not isinstance(link, str) or Path(link).is_absolute() or "\\" in link:
            raise ValueError("unsafe related reference")
        local = os.path.normpath(str(Path(name).parent / link))
        rooted = os.path.normpath(link)
        candidate = local if local in self.nodes or rooted not in self.nodes else rooted
        return records.relative(candidate)

    def event_path(self, event):
        category = "claims" if event["type"] == "claim" else "decisions" if event["type"] == "decision" else "investigations"
        return category + "/record-" + slug(event["event_id"]) + ".md"

    def topic_path(self, topic):
        synth = [e for e in self.ordered("synthesis") if e["topic"] == topic and self.accepted(e)]
        category = synth[-1]["data"]["category"] if synth else "investigations"
        return category + "/topic-" + slug(topic) + ".md"

    def task_path(self, tid):
        return "investigations/task-" + slug(tid) + ".md"

    def node_path(self, name):
        return "architecture/knowledge-" + slug(name) + ".md"

    def link(self, label, path, parent=False):
        return "[" + esc(label) + "](" + ("../" if parent else "") + path + ")"

    def evidence_text(self, ref, event_id):
        label = esc(records.canonical(ref))
        if not self.reference(ref, event_id):
            return label + " — UNAVAILABLE / CHANGED"
        if ref["kind"] in {"artifact", "knowledge", "file"}:
            root = self.inputs["paths"]["raw" if ref["kind"] == "artifact" else "tree"] if ref["kind"] != "file" else str(self.event_workspace(event_id))
            target = Path(root) / ref["path"]
            return label + " · [original](" + urlquote(target.as_posix(), safe="/") + ")"
        if ref["kind"] == "record" and ref["event_id"] in self.events:
            return label + " · " + self.link("source record", self.event_path(self.events[ref["event_id"]]), True)
        if ref["kind"] == "uri":
            return label + " (external citation; not fetched)"
        return label

    def render_event(self, event):
        d, event_id = event["data"], event["event_id"]
        row = self.event_sources[event_id]
        body = self.page(event["type"] + ": " + event["topic"])
        body += "## Current synthesis and scope\n\n" + esc(d.get("scope", "Recorded observation; no inferred scope")) + "\n\n"
        body += "## Claims\n\n" + quote(d.get("assertion", d.get("conclusion", d.get("impact", records.canonical(d))))) + "\n\n"
        body += "## Provenance\n\n" + esc(event["actor"]) + "; " + utc(row["created_at"]) + "; " + esc(source("task_comments", row)) + "; " + esc(event_id) + "; digest " + event["payload_digest"] + "\n\n"
        task_link = self.link(event["task_id"], self.task_path(event["task_id"]), True) if event["task_id"] in self.tasks else esc(event["task_id"] + " (missing task)")
        body += "## Linked work and knowledge\n\n" + task_link + " · " + self.link(event["topic"], self.topic_path(event["topic"]), True) + " · " + self.link("History", "log.md#" + anchor("task_comments", row["id"]), True) + "\n\n"
        for tid in d.get("affected_task_ids", []):
            body += "- Affected work: " + (self.link(tid, self.task_path(tid), True) if tid in self.tasks else esc(tid + " (missing)")) + "\n"
        for key in ("claim_id", "contradiction_id", "supersedes"):
            if d.get(key) in self.events:
                body += "- " + esc(key) + ": " + self.link(d[key], self.event_path(self.events[d[key]]), True) + "\n"
        for tid in d.get("source_task_ids", []) + ([d["subject_task_id"]] if "subject_task_id" in d else []):
            if tid in self.tasks:
                body += "- Source work (provenance, not dependency): " + self.link(tid, self.task_path(tid), True) + "\n"
        if event["type"] in records.AUDIT_TYPES:
            body += "\nAudit record: " + ("VALID" if self.valid_audit(event) else "INVALID / STALE") + ". Adoption identifies a current reviewer; historical actors and claim verification remain separate.\n"
        body += "## Verification state\n\n" + ("SUPERSEDED" if event_id in self.superseded else self.state(event) if event["type"] == "claim" else "Recorded " + esc(d.get("verdict", "observation; not verification authority"))) + "\n\n"
        if event["type"] == "claim":
            for verification in self.ordered("verification"):
                if verification["data"]["claim_id"] == event_id:
                    body += "- " + self.link(verification["actor"] + ": " + verification["data"]["verdict"] + " / " + verification["data"]["scope"], self.event_path(verification), True) + "\n"
        body += "\n## Contradictions\n\n"
        conflicts = [e for e in self.ordered("contradiction") if event_id in e["data"]["claims"] or e["event_id"] == event_id]
        if not conflicts:
            body += "No explicit linked contradiction. Mechanical findings remain in lint report."
        for conflict in conflicts:
            resolution = self.resolved(conflict)
            body += "- " + self.link(conflict["event_id"], self.event_path(conflict), True) + " — "
            body += self.link("supported reconciliation: " + resolution["data"]["disposition"], self.event_path(resolution), True) if resolution else "UNRESOLVED"
            body += "\n"
            for claim_id in conflict["data"]["claims"]:
                side = self.events.get(claim_id)
                if side and side["type"] == "claim":
                    body += "\n" + quote(side["data"]["assertion"]) + "\n\nSource: " + self.link(claim_id, self.event_path(side), True) + "; " + esc(side["actor"]) + "\n"
        body += "\n\n## Evidence references\n\n"
        evidence = self.event_evidence(event)
        if event["type"] == "synthesis":
            evidence += [{"kind": "knowledge", "path": d["node_path"], "sha256": d["node_sha256"]}]
        body += "\n".join("- " + self.evidence_text(r, event_id) for r in evidence) or "No evidence references recorded."
        for key in ("claims", "supporting_records"):
            for target in d.get(key, []):
                if target in self.events:
                    body += "\n- " + self.link(target, self.event_path(self.events[target]), True)
        for target in d.get("source_digests", {}):
            if target in self.events:
                body += "\n- " + self.link(target, self.event_path(self.events[target]), True)
        return body + "\n"

    def log(self):
        entries = []
        tables = self.inputs["tables"]
        def add(table, row, timestamp, kind, content, phase=""):
            try:
                time_value = float(timestamp) if timestamp is not None else 0
            except (ValueError, TypeError):
                time_value = 0
                self.finding("missing-provenance", source(table, row), "Invalid lifecycle timestamp")
            actor = row.get("author") or row.get("profile") or (row.get("created_by") if table == "tasks" else None)
            if table == "task_events":
                actor = next((r.get("profile") for r in tables["task_runs"] if r["id"] == row.get("run_id")), None)
                try:
                    payload = json.loads(row.get("payload") or "{}")
                except (ValueError, TypeError):
                    payload = {}
                if not actor and isinstance(payload, dict):
                    actor = next((payload[k] for k in ("author", "actor", "by", "profile") if isinstance(payload.get(k), str) and payload[k].strip()), None)
                if not actor and row.get("kind") == "created":
                    actor = self.tasks.get(row.get("task_id"), {}).get("created_by")
            if not actor:
                self.finding("missing-provenance", source(table, row), "Lifecycle actor unknown")
            entries.append({"time": time_value, "actor": actor or "UNKNOWN_AUTHOR", "table": table, "id": str(row["id"]), "phase": phase,
                            "task": row.get("task_id", row["id"]), "kind": kind, "text": content,
                            "anchor": anchor(table, row["id"], phase), "run": row.get("run_id")})
        for task in self.tasks.values():
            add("tasks", task, task["created_at"], "created", task["title"], "created")
            if task.get("completed_at"):
                add("tasks", task, task["completed_at"], "completed", task.get("result") or task["title"], "completed")
        for row in tables["task_comments"]:
            publication = next((e for i, e in self.events.items() if self.event_sources[i]["id"] == row["id"]), None)
            if publication:
                d = publication["data"]
                summary = d.get("assertion", d.get("conclusion", d.get("impact", d.get("explanation", d.get("rationale", publication["topic"])))))
                add("task_comments", row, row["created_at"], publication["type"], summary)
            else:
                add("task_comments", row, row["created_at"], "comment", source_text(row.get("author") or "UNKNOWN_AUTHOR") + ": " + source_text(row.get("body") or ""))
        for row in tables["task_events"]:
            add("task_events", row, row["created_at"], row["kind"], row.get("payload") or "")
        for row in tables["task_runs"]:
            if row.get("started_at") is not None:
                add("task_runs", row, row["started_at"], "run-start", row.get("profile") or "UNKNOWN_AUTHOR", "start")
            if row.get("ended_at") is not None:
                add("task_runs", row, row["ended_at"], "run-end", row.get("summary") or row.get("error") or row.get("outcome") or "", "end")
        entries.sort(key=lambda e: (e["time"], e["table"], e["id"], e["phase"]))
        body = self.page("Chronological history")
        i = 0
        while i < len(entries):
            entry = entries[i]
            group = [entry]
            if entry["kind"] == "heartbeat" and entry["run"]:
                while i + len(group) < len(entries):
                    other = entries[i + len(group)]
                    if other["kind"] != "heartbeat" or other["run"] != entry["run"] or other["task"] != entry["task"]:
                        break
                    group.append(other)
            body += "\n" + "\n".join('<a id="' + e["anchor"] + '"></a>' for e in group) + "\n\n"
            summary = " ".join(source_text(entry["text"]).split())[:160]
            if len(group) > 1:
                summary = str(len(group)) + " heartbeats; first " + utc(entry["time"]) + "; last " + utc(group[-1]["time"])
            body += "- " + utc(entry["time"]) + " · " + esc(entry["kind"]) + " · " + esc(entry["actor"]) + " · "
            body += (self.link(entry["task"], self.task_path(entry["task"])) if entry["task"] in self.tasks else esc(entry["task"])) + " · " + esc(summary) + "\n"
            body += "  Sources: " + esc(", ".join(e["table"] + "/" + e["id"] for e in group)) + "\n"
            i += len(group)
        return body

    def render(self):
        files = {"log.md": self.log()}
        topics = sorted({e["topic"] for e in self.events.values()})
        for event in self.ordered():
            files[self.event_path(event)] = self.render_event(event)
        for topic in topics:
            events = [e for e in self.ordered() if e["topic"] == topic]
            synth = [e for e in events if e["type"] == "synthesis" and self.accepted(e)]
            body = self.page(topic) + "## Current synthesis and scope\n\n"
            if synth:
                latest = synth[-1]
                name = latest["data"]["node_path"]
                metadata, content = self.nodes[name]
                body += "Accepted canonical ByteRover revision: " + esc(name) + "; " + latest["data"]["node_sha256"] + ".\n\n"
                body += self.link("Canonical knowledge node", self.node_path(name), True) + " · " + self.link("Acceptance and cited sources", self.event_path(latest), True) + "\n\n"
                body += quote(metadata.get("summary", "")) + "\n\n" + quote(content) + "\n\n"
            else:
                body += "UNSYNTHESIZED: structured overview; no accepted current ByteRover synthesis.\n\n"
            body += "## Claims\n\n" + "\n".join("- " + self.link(e["data"].get("assertion", e["type"]), self.event_path(e), True) + (" — " + self.state(e) if e["type"] == "claim" else "") for e in events) + "\n\n"
            for section in ("Provenance", "Linked work and knowledge", "Verification state", "Contradictions", "Evidence references"):
                body += "## " + section + "\n\nSee linked canonical record pages and " + self.link("lint findings", "lint-report.md", True) + ".\n\n"
            files[self.topic_path(topic)] = body
        for tid, task in sorted(self.tasks.items()):
            body = self.page(task["title"]) + "## Current synthesis and scope\n\nCanonical task status: " + esc(task["status"]) + ".\n\n"
            if task.get("block_kind") or task.get("last_failure_error"):
                body += "Recorded block/failure: " + quote(str(task.get("block_kind") or "") + "\n" + str(task.get("last_failure_error") or "")) + "\n\n"
            body += "## Claims\n\n" + quote(task.get("body") or task["title"]) + "\n\n"
            for run in self.inputs["tables"]["task_runs"]:
                if run["task_id"] == tid:
                    body += quote(run.get("summary") or run.get("error") or "") + "\n\n" + esc("task_runs/" + str(run["id"])) + "; " + esc(run.get("profile") or "UNKNOWN_AUTHOR") + "; " + utc(run.get("ended_at") or run.get("started_at")) + "\n\n"
            body += "## Provenance\n\n" + esc(task.get("created_by") or "UNKNOWN_AUTHOR") + "; " + utc(task["created_at"]) + "; " + esc(self.inputs["paths"]["db"] + ":tasks/" + tid) + "\n\n"
            body += "## Linked work and knowledge\n\n"
            try:
                envelope = json.loads(task.get("body") or "{}")
            except (ValueError, TypeError):
                envelope = {}
            if isinstance(envelope, dict) and envelope.get("protocol") == "hermes-swarm/v1" and envelope.get("source_task"):
                origin = envelope["source_task"]
                if isinstance(origin, str) and origin in self.tasks:
                    body += "- Request origin (provenance, not dependency): " + self.link(origin, self.task_path(origin), True) + "\n"
            for link in self.inputs["tables"]["task_links"]:
                if tid in {link["parent_id"], link["child_id"]}:
                    other = link["child_id"] if link["parent_id"] == tid else link["parent_id"]
                    body += "- Dependency: " + (self.link(other, self.task_path(other), True) if other in self.tasks else esc(other)) + "\n"
                    if other not in self.tasks:
                        self.finding("stale-reference", tid, "Missing dependency task: " + other)
            for event in self.ordered():
                if event["task_id"] == tid:
                    body += "- " + self.link(event["event_id"], self.event_path(event), True) + "\n"
            body += "\n## Verification state\n\n"
            entries = self.legacy[tid]
            assessment = self.request_assessment(tid)
            body += "Historical request independently assessed: PASS · " + self.link(assessment["event_id"], self.event_path(assessment), True) + "\n" if assessment else "UNVERIFIED\n" if not entries else "Legacy request assessments (scope cannot be inferred):\n"
            for row, verdict in entries:
                body += "\n" + quote(records.canonical(verdict)) + "\n\n" + esc(source("task_comments", row)) + "; " + esc(row["author"]) + "; " + utc(row["created_at"]) + "\n"
            body += "\n## Contradictions\n\n" + self.link("Audit findings", "lint-report.md", True) + "\n\n## Evidence references\n\n" + self.link("Task creation / history", "log.md#" + anchor("tasks", tid, "created"), True) + "\n"
            for row in self.inputs["tables"]["task_comments"]:
                if row["task_id"] == tid and (not isinstance(row.get("body"), str) or not (row.get("body") or "").startswith(records.PREFIX)):
                    body += "\n" + quote(row.get("body") or "") + "\n\n" + esc(source("task_comments", row)) + "; " + esc(row.get("author") or "UNKNOWN_AUTHOR") + "; " + utc(row["created_at"]) + "\n"
            files[self.task_path(tid)] = body
        for name, (meta, content) in sorted(self.nodes.items()):
            body = self.page(meta.get("title", name)) + "## Current synthesis and scope\n\nCanonical knowledge node; not independently verified.\n\n"
            body += "## Claims\n\n" + quote(meta.get("summary", "")) + "\n\n" + quote(content) + "\n\n"
            body += "## Provenance\n\n" + esc(name) + "; " + records.byte_hash(self.inputs["knowledge"][name]) + "; " + esc(meta.get("author", "UNKNOWN_AUTHOR")) + "; " + esc(meta.get("updatedAt", meta.get("createdAt", "UNKNOWN_TIME"))) + "\n\n"
            body += "## Linked work and knowledge\n\n"
            for relation in ("adoption", "work_link", "derivation"):
                annotation = self.provenance(name, relation)
                if annotation:
                    body += "- " + esc(relation) + " by " + esc(annotation["actor"]) + " (current annotation, not original authorship): " + self.link(annotation["event_id"], self.event_path(annotation), True) + "\n"
            for e in self.ordered("synthesis"):
                if e["data"]["node_path"] == name:
                    body += "- " + self.link(e["event_id"], self.event_path(e), True) + "\n"
            for link in meta.get("related", []) if isinstance(meta.get("related", []), list) else []:
                try:
                    target = self.related_path(name, link)
                except ValueError:
                    continue
                if target in self.nodes:
                    body += "- " + self.link(target, self.node_path(target), True) + "\n"
            body += "\n## Verification state\n\nUNVERIFIED as an independent source.\n\n## Contradictions\n\n" + self.link("Lint findings", "lint-report.md", True) + "\n\n## Evidence references\n\n" + esc(self.inputs["paths"]["tree"] + "/" + name) + "\n"
            files[self.node_path(name)] = body
        self.finding_outcomes()
        self.findings.sort(key=lambda f: (f["class"], f["target"], f["message"]))
        files["lint-report.md"] = self.page("Lint report") + "Original source findings and current outcomes; a disclosed unknown is not recovered authorship.\n\n" + ("\n".join("- **" + f["outcome"] + "** · " + f["class"] + " · " + esc(f["target"]) + " · Original finding: " + esc(f["message"]) + (" · " + self.link("Canonical correction", self.event_path(self.events[f["correction_event_id"]])) if f.get("correction_event_id") else "") for f in self.findings) or "No findings.") + "\n"
        counts = collections.Counter(t["status"] for t in self.tasks.values())
        index = self.page(self.project + " — " + self.board) + "Canonical inputs: " + esc(records.canonical(self.inputs["paths"])) + "\n\n"
        fingerprints = {"board": board_snapshot_digest(self.inputs["tables"]),
                        "knowledge": records.digest({p: records.byte_hash(b) for p, b in self.inputs["knowledge"].items()}),
                        "raw": records.digest({p: records.byte_hash(b) for p, b in self.inputs["artifacts"].items()}),
                        "rules": records.byte_hash(self.inputs["rules"])}
        index += "Input revision fingerprints: " + esc(records.canonical(fingerprints)) + " · " + self.link("Full input manifest", "manifest.json") + "\n\n"
        index += "Kanban: work · ByteRover: knowledge · swarm: coordination · wiki: projection\n\n"
        index += "## Work state\n\n" + esc(records.canonical(dict(sorted(counts.items())))) + "\n\n"
        verdicts = collections.Counter(e["data"]["verdict"] for e in self.ordered("verification"))
        verdicts.update(v["verdict"] for entries in self.legacy.values() for _, v in entries)
        index += "Recorded verdicts (not independent verification counts): " + esc(records.canonical(dict(sorted(verdicts.items())))) + "\n\n"
        index += "## Current topics\n\n"
        for topic in topics:
            claims = [e for e in self.ordered("claim") if e["topic"] == topic]
            status = "; ".join(e["data"]["assertion"][:160] + " / " + self.state(e) for e in claims[-3:]) or "No structured claim"
            independent = {v["actor"] for v in self.ordered("verification") for c in claims if v["data"]["verdict"] == "pass" and self.verifies(v, c)}
            index += "- " + self.link(topic, self.topic_path(topic)) + " — " + esc(status) + "; " + str(len(independent)) + " distinct independent live-evidence verifier profiles.\n"
        index += "\n## Work navigation\n\n"
        for tid, task in sorted(self.tasks.items()):
            index += "- " + self.link(task["title"], self.task_path(tid)) + " — " + esc(task["status"])
            if task.get("block_kind"):
                index += "; recorded blocker: " + esc(task["block_kind"])
            index += "\n"
        index += "\n## Knowledge navigation\n\n"
        for name, (metadata, content) in sorted(self.nodes.items()):
            summary = str(metadata.get("summary") or content).strip().split("\n\n", 1)[0][:160]
            index += "- " + self.link(metadata.get("title", name), self.node_path(name)) + " — " + esc(summary) + " (canonical memory; not independent verification).\n"
        index += "\n## Navigation\n\n" + self.link("History", "log.md") + " · " + self.link("Lint", "lint-report.md") + " · " + self.link("Digest", "digest.md") + "\n\n"
        index += "digest → index → topic → ByteRover → original evidence → independent verification\n\n## All pages\n\n"
        index += "\n".join("- " + self.link(path, path) for path in sorted(files) if path not in {"log.md", "lint-report.md"}) + "\n"
        files["index.md"] = index
        files["digest.md"] = self.page("Swarm digest") + esc(records.canonical(dict(sorted(counts.items())))) + "; " + str(len(self.unresolved_findings)) + " unresolved audit findings.\n\n" + self.link("Read current topics", "index.md#current-topics") + "\n"
        manifests = {
            "compiler_version": COMPILER_VERSION, "schema_version": records.LATEST_VERSION,
            "supported_schema_versions": [records.VERSION, records.LATEST_VERSION],
            "audit_outcomes": self.findings,
            "compiler_source_sha256": records.byte_hash(Path(__file__).read_bytes()),
            "schema_source_sha256": records.byte_hash(Path(records.__file__).read_bytes()),
            "project": self.project, "board": self.board, "sources": self.inputs["paths"],
            "board_snapshot_sha256": board_snapshot_digest(self.inputs["tables"]),
            "tree": {p: records.byte_hash(b) for p, b in self.inputs["knowledge"].items()},
            "raw": {p: records.byte_hash(b) for p, b in self.inputs["artifacts"].items()},
            "rules_sha256": records.byte_hash(self.inputs["rules"]),
            "maintainers": sorted(self.maintainers), "workspace": str(self.workspace), "repo": str(self.repo),
            "task_workspace_roots": [str(p) for p in self.task_workspace_roots],
            "repo_head": self.repo_head, "reference_state": {records.digest(k): {"available": v[0]} for k, v in sorted(self.ref_cache.items())},
            "statuses": sorted(self.valid_statuses),
            "files": {p: records.byte_hash(s.encode()) for p, s in sorted(files.items())},
        }
        files["manifest.json"] = records.canonical(manifests) + "\n"
        return {p: s.encode("utf-8") for p, s in sorted(files.items())}


def validate_links(files):
    for name, content in files.items():
        if not name.endswith(".md"):
            continue
        for link in re.findall(r"(?<!\\)\[[^\n]*?\]\(([^)]+)\)", content.decode("utf-8")):
            target, _, fragment = link.partition("#")
            if target.startswith("/") or re.match(r"^[a-z]+:", target):
                continue  # Typed original references were checked against source roots.
            resolved = os.path.normpath(str(Path(name).parent / target)) if target else name
            if resolved not in files:
                raise ValueError("broken generated cross-link: " + name + " -> " + link)
            if fragment.startswith("source-") and ('id="' + fragment + '"').encode() not in files[resolved]:
                raise ValueError("broken history anchor: " + link)


def ensure_output(out, inputs, workspace):
    out = Path(out).absolute()
    workspace = Path(workspace).resolve()
    protected = [Path(inputs["paths"][k]).resolve() for k in ("db", "tree", "raw", "rules")]
    resolved = out.resolve()
    for path in protected:
        if resolved == path or path in resolved.parents or resolved in path.parents:
            raise ValueError("output overlaps canonical inputs")
    if resolved == workspace or resolved in workspace.parents:
        raise ValueError("output cannot contain the workspace")
    # Only the final owned symlink is allowed; parents must be ordinary directories.
    for parent in out.parents:
        if parent.is_symlink():
            raise ValueError("output parent symlink is not allowed")
    if out.is_symlink():
        generations = out.parent / ("." + out.name + "-generations")
        if out.resolve().parent != generations.resolve() or generations.is_symlink():
            raise ValueError("refusing foreign output symlink")
    return out


def output_files(out):
    if not Path(out).exists():
        return {}
    return inventory(Path(out).resolve())


def publish(out, files, inputs, workspace, check=False):
    validate_links(files)
    out = ensure_output(out, inputs, workspace)
    if check:
        return output_files(out) == files
    out.parent.mkdir(parents=True, exist_ok=True)
    lock = out.parent / ("." + out.name + ".lock")
    generations = out.parent / ("." + out.name + "-generations")
    if lock.is_symlink() or generations.is_symlink():
        raise ValueError("foreign publication infrastructure symlink")
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    stage = None
    temporary_link = None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another compiler owns this output")
        if out.is_symlink():
            target = out.resolve()
            if target.parent != generations.resolve() or not target.is_dir() or not (target / "manifest.json").is_file():
                raise ValueError("refusing foreign output symlink")
            current = output_files(out)
            manifest = json.loads(current.get("manifest.json", b"{}"))
            if set(current) != set(manifest.get("files", {})) | {"manifest.json"}:
                raise ValueError("unknown user files in generated output")
        elif out.exists():
            raise ValueError("output exists and is not an owned generated symlink; choose a new output")
        generations.mkdir(mode=0o700, exist_ok=True)
        identifier = records.digest({p: records.byte_hash(b) for p, b in files.items()})
        destination = generations / identifier
        if destination.exists():
            if destination.is_symlink() or inventory(destination) != files:
                raise ValueError("existing generation has been modified")
        else:
            stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=generations))
            for name, content in files.items():
                path = stage / records.relative(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.rename(stage, destination)
            stage = None
        temporary_link = out.parent / ("." + out.name + ".next-" + str(os.getpid()))
        os.symlink(os.path.relpath(destination, out.parent), temporary_link)
        os.replace(temporary_link, out)
        temporary_link = None
        return True
    finally:
        if temporary_link is not None:
            temporary_link.unlink(missing_ok=True)
        if stage is not None:
            shutil.rmtree(stage)
        os.close(descriptor)
