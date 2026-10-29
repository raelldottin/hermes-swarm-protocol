"""Hindsight snapshot ingestion: authorized, deterministic, read-only and provenance-visible.

Snapshots here are synthetic JSON shaped like `GET /v1/default/banks/{bank_id}/memories/list`
(vectorize-io/hindsight@d952b6e6); no Hindsight server is involved.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hermes_swarm_protocol"))
import wiki_compiler as wiki
import wiki_records as records
from test_swarm_wiki import STATUSES, project  # noqa: F401  (project is a fixture)

SOURCE = "docs/decision.md"


def memory(mid, text="Issuer lookup is tenant scoped", source=SOURCE, sha=None, evidence="commit:abc1234", **extra):
    metadata = {"source_path": source, "source_sha256": sha, "evidence_ref": evidence}
    return {"id": mid, "text": text, "fact_type": "world", "metadata": metadata, "state": "valid", **extra}


def snapshot_doc(memories, project_name="p", bank="p-bank", captured_at="2026-10-28T00:00:00Z", total=None):
    return {"format": wiki.MEMORY_FORMAT, "project": project_name, "bank_id": bank, "captured_at": captured_at,
            "captured_by": "operator", "hindsight_revision": "d952b6e655fccab4581ee0722b51c5f103873d12",
            "memories": memories, "total": len(memories) if total is None else total}


def write_snapshot(root, doc):
    data = records.canonical(doc).encode()
    path = root / (records.byte_hash(data) + ".json")
    path.write_bytes(data)
    return path


@pytest.fixture
def memory_project(project):
    source = project["workspace"] / SOURCE
    source.parent.mkdir(parents=True)
    source.write_text("Decision: issuer lookup is tenant scoped.\n")
    project["sha"] = records.byte_hash(source.read_bytes())
    project["memory"] = project["workspace"].parent / "hindsight"
    project["memory"].mkdir()
    return project


def build(project, banks=("p-bank",), memory=True):
    inputs = wiki.snapshot(project["db"], project["tree"], project["raw"], project["rules"],
                           project["memory"] if memory else None)
    projection = wiki.Projection(inputs, "p", "fixture", project["workspace"], project["workspace"], STATUSES,
                                 ("maintainer",), (), banks)
    return projection, projection.render(), inputs


def page(files, name):
    return files["memory/snapshot-" + wiki.slug(name) + ".md"].decode()


def findings(projection):
    return {(f["class"], f["target"]) for f in projection.findings}


def test_without_memory_the_byterover_projection_is_unchanged(memory_project):
    (memory_project["tree"] / "node.md").write_text("---\nauthor: a\ncreatedAt: x\n---\nByteRover node\n")
    write_snapshot(memory_project["memory"], snapshot_doc([memory("m1", sha=memory_project["sha"])]))
    inputs = wiki.snapshot(memory_project["db"], memory_project["tree"], memory_project["raw"], memory_project["rules"])
    plain = wiki.Projection(inputs, "p", "fixture", memory_project["workspace"], memory_project["workspace"], STATUSES, ("maintainer",))
    _, without, _ = build(memory_project, memory=False)

    assert "memory" not in inputs and "memory" not in inputs["paths"]
    assert plain.render() == without
    assert not any(name.startswith("memory/") for name in without)
    assert b"Hindsight" not in without["index.md"] and b'"memory"' not in without["manifest.json"]


def test_authorized_snapshot_renders_with_typed_provenance_and_keeps_byterover(memory_project):
    (memory_project["tree"] / "node.md").write_text("---\nauthor: a\ncreatedAt: x\n---\nByteRover node\n")
    path = write_snapshot(memory_project["memory"], snapshot_doc([memory("m1", sha=memory_project["sha"])]))

    projection, files, _ = build(memory_project)

    text = page(files, path.name)
    assert "UNVERIFIED" in text and "Issuer lookup is tenant scoped" in text
    assert "Source docs/decision.md; " + memory_project["sha"] + "; original evidence commit:abc1234" in text
    assert records.byte_hash(path.read_bytes()) in text and "Generated memory, not original evidence" in text
    assert "architecture/knowledge-" + wiki.slug("node.md") + ".md" in files
    manifest = json.loads(files["manifest.json"])
    assert manifest["memory"] == {path.name: records.byte_hash(path.read_bytes())}
    assert manifest["memory_banks"] == ["p-bank"]
    assert b"## Memory navigation" in files["index.md"]
    assert not [f for f in projection.findings if f["target"].startswith(path.name)]
    wiki.validate_links(files)


def test_projection_is_deterministic_and_read_only(memory_project):
    memories = [memory("m2", sha=memory_project["sha"]), memory("m1", sha=memory_project["sha"])]
    write_snapshot(memory_project["memory"], snapshot_doc(memories))
    before = {p: p.read_bytes() for p in memory_project["memory"].iterdir()}

    first = build(memory_project)[1]
    second = build(memory_project)[1]

    assert first == second
    assert {p: p.read_bytes() for p in memory_project["memory"].iterdir()} == before
    body = next(v.decode() for k, v in first.items() if k.startswith("memory/"))
    assert body.index("### m1") < body.index("### m2")


def test_unauthorized_bank_and_other_project_are_refused(memory_project):
    other_bank = write_snapshot(memory_project["memory"], snapshot_doc([memory("m1", sha=memory_project["sha"])], bank="q-bank"))
    other_project = write_snapshot(memory_project["memory"], snapshot_doc([memory("m2", sha=memory_project["sha"])], project_name="q"))

    projection, files, _ = build(memory_project)

    assert ("unauthorized-memory-bank", other_bank.name) in findings(projection)
    assert ("project-boundary", other_project.name) in findings(projection)
    assert not any(name.startswith("memory/") for name in files)
    assert b"Issuer lookup" not in b"".join(files.values())


def test_changed_snapshot_is_visible_and_projects_no_memory_text(memory_project):
    path = write_snapshot(memory_project["memory"], snapshot_doc([memory("m1", sha=memory_project["sha"])]))
    path.write_bytes(records.canonical(snapshot_doc([memory("m1", text="Rewritten claim", sha=memory_project["sha"])])).encode())

    projection, files, _ = build(memory_project)

    assert ("changed-snapshot", path.name) in findings(projection)
    text = page(files, path.name)
    assert "CHANGED SNAPSHOT" in text and "Rewritten claim" not in text
    assert "CHANGED" in files["index.md"].decode()


def test_invalid_provenance_is_visible(memory_project):
    path = write_snapshot(memory_project["memory"], snapshot_doc([
        {"id": "m1", "text": "No metadata at all", "fact_type": "world"},
        memory("m2", sha="not-a-digest"),
        memory("m3", source="../outside.md", sha=memory_project["sha"]),
    ]))

    projection, files, _ = build(memory_project)

    for mid in ("m1", "m2", "m3"):
        assert ("invalid-provenance", path.name + "#" + mid) in findings(projection)
    assert page(files, path.name).count("INVALID PROVENANCE") == 3


def test_changed_or_missing_source_is_visible(memory_project):
    path = write_snapshot(memory_project["memory"], snapshot_doc([
        memory("m1", sha=memory_project["sha"]),
        memory("m2", source="docs/deleted.md", sha=memory_project["sha"]),
    ]))
    (memory_project["workspace"] / SOURCE).write_text("Decision: changed after retain.\n")

    projection, files, _ = build(memory_project)

    assert ("stale-memory-source", path.name + "#m1") in findings(projection)
    assert ("stale-memory-source", path.name + "#m2") in findings(projection)
    assert page(files, path.name).count("SOURCE CHANGED") == 2


def test_generated_and_invalidated_memories_are_labelled(memory_project):
    path = write_snapshot(memory_project["memory"], snapshot_doc([
        memory("m1", sha=memory_project["sha"], fact_type="observation", source_memory_ids=["m2"]),
        memory("m2", sha=memory_project["sha"], state="invalidated"),
    ]))

    _, files, _ = build(memory_project)

    text = page(files, path.name)
    assert "UNVERIFIED · GENERATED CONSOLIDATION" in text
    assert "UNVERIFIED · INVALIDATED" in text


@pytest.mark.parametrize("payload", [b"not json", b'{"format": "other"}', b'{"format": "hindsight-snapshot/v1"}'])
def test_malformed_snapshot_is_a_finding(memory_project, payload):
    (memory_project["memory"] / "bad.json").write_bytes(payload)

    projection, files, _ = build(memory_project)

    assert "invalid-memory-snapshot" in {f["class"] for f in projection.findings}
    assert not any(name.startswith("memory/") for name in files)


def test_empty_snapshot_and_bad_memories(memory_project):
    empty = write_snapshot(memory_project["memory"], snapshot_doc([], captured_at="2026-10-27T00:00:00Z"))
    dup = write_snapshot(memory_project["memory"], snapshot_doc([memory("m1", sha=memory_project["sha"]),
                                                                memory("m1", sha=memory_project["sha"]), {"id": 7}]))

    projection, files, _ = build(memory_project)

    assert "EMPTY SNAPSHOT" in page(files, empty.name)
    assert ("invalid-memory", dup.name + "#m1") in findings(projection)
    assert ("invalid-memory", dup.name + "#7") in findings(projection)


def test_memory_root_is_protected_from_output_and_publishes_atomically(memory_project):
    write_snapshot(memory_project["memory"], snapshot_doc([memory("m1", sha=memory_project["sha"])]))
    _, files, inputs = build(memory_project)

    with pytest.raises(ValueError, match="overlaps canonical inputs"):
        wiki.publish(memory_project["memory"] / "wiki", files, inputs, memory_project["workspace"])
    assert wiki.publish(memory_project["out"], files, inputs, memory_project["workspace"])
    assert wiki.publish(memory_project["out"], files, inputs, memory_project["workspace"], check=True)


def test_memory_root_must_be_a_real_directory(memory_project, tmp_path):
    link = tmp_path / "linked-memory"
    link.symlink_to(memory_project["memory"])
    for root in (link, tmp_path / "missing"):
        with pytest.raises(ValueError, match="Hindsight snapshot root"):
            wiki.snapshot(memory_project["db"], memory_project["tree"], memory_project["raw"], memory_project["rules"], root)


def test_cli_requires_explicit_bank_authorization(memory_project, tmp_path):
    fake_hermes = tmp_path / "hermes"
    (fake_hermes / "hermes_cli").mkdir(parents=True)
    (fake_hermes / "hermes_cli/__init__.py").write_text("")
    (fake_hermes / "hermes_cli/kanban_db.py").write_text("VALID_STATUSES = " + repr(sorted(STATUSES)) + "\n")
    write_snapshot(memory_project["memory"], snapshot_doc([memory("m1", sha=memory_project["sha"])]))
    base = [sys.executable, str(Path(__file__).resolve().parents[1] / "ops/build_wiki.py"), "--board", "fixture", "--project", "p",
            "--workspace", str(memory_project["workspace"]), "--db", str(memory_project["db"]), "--tree", str(memory_project["tree"]),
            "--rules", str(memory_project["rules"]), "--hermes-source", str(fake_hermes), "--memory", str(memory_project["memory"]),
            "--maintainer", "maintainer"]

    refused = subprocess.run(base + ["--out", str(tmp_path / "refused")], capture_output=True, text=True)
    allowed = subprocess.run(base + ["--out", str(tmp_path / "allowed"), "--memory-bank", "p-bank"], capture_output=True, text=True)

    assert "unauthorized-memory-bank" in refused.stderr
    assert "unauthorized-memory-bank" not in allowed.stderr
    assert json.loads(allowed.stdout)["pages"] > json.loads(refused.stdout)["pages"]


def test_partial_snapshot_is_visible_as_incomplete(memory_project):
    path = write_snapshot(memory_project["memory"], snapshot_doc([memory("m1", sha=memory_project["sha"])], total=150))

    projection, files, _ = build(memory_project)

    assert ("incomplete-memory-snapshot", path.name) in findings(projection)
    assert "INCOMPLETE SNAPSHOT: 1 of 150 memories" in page(files, path.name)
    assert "Issuer lookup is tenant scoped" in page(files, path.name)
    assert b"1 of 150 memories, INCOMPLETE" in files["index.md"]


@pytest.mark.parametrize("total", [None, -1, True, "1", 1.0])
def test_snapshot_without_an_integer_total_is_refused(memory_project, total):
    doc = snapshot_doc([memory("m1", sha=memory_project["sha"])])
    if total is None:
        del doc["total"]
    else:
        doc["total"] = total
    write_snapshot(memory_project["memory"], doc)

    projection, files, _ = build(memory_project)

    assert "invalid-memory-snapshot" in {f["class"] for f in projection.findings}
    assert not any(name.startswith("memory/") for name in files)
