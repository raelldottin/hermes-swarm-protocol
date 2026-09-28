"""Regression tests for the fleet memory migration — the four invariants from the
2026-09-28 config incident. Each test reproduces one failure that actually happened;
the guard under test is the fix.

Run:  python -m pytest tests/test_migrate_fleet_memory.py -q
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "ops" / "migrate_fleet_memory.py"


def _load_module(tmp_path, monkeypatch, home):
    """Load the ops script with PROFILES_ROOT pinned at a sandbox fleet."""
    monkeypatch.setenv("HERMES_HOME", str(home))
    spec = importlib.util.spec_from_file_location("mfm_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sandbox_fleet(tmp_path, monkeypatch):
    """Two profiles: a worker (old-format memory block) and a root (no memory block)."""
    home = tmp_path / "fleet"
    (home / ".hermes" / "profiles").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    # PROFILES_ROOT is Path.home()/.hermes/profiles — pin Path.home to the sandbox
    real_home = Path.home
    monkeypatch.setattr(Path, "home", lambda: home)

    worker_cfg = home / ".hermes" / "profiles" / "opnory-builder" / "config.yaml"
    worker_cfg.parent.mkdir(parents=True)
    worker_cfg.write_text(
        "memory:\n"
        "  memory_enabled: false\n"
        "  user_profile_enabled: false\n"
        "  write_approval: false\n"
        "  memory_char_limit: 2200\n"
        "  user_char_limit: 1375\n"
        "  provider: byterover\n"
        "  flush_min_turns: 6\n"
        "  nudge_interval: 10\n"
    )
    root_cfg = home / ".hermes" / "profiles" / "opnory" / "config.yaml"
    root_cfg.parent.mkdir(parents=True)
    root_cfg.write_text("agent:\n  model: z-ai/glm-5.3\n")
    return home, worker_cfg, root_cfg


# ---------------------------------------------------------------------------
# Invariant 1: a migration preserves unknown / pre-existing memory.* keys
# ---------------------------------------------------------------------------

def test_migration_preserves_preexisting_memory_keys(tmp_path, monkeypatch):
    home, worker_cfg, _ = _sandbox_fleet(tmp_path, monkeypatch)
    mod = _load_module(tmp_path, monkeypatch, home)
    tree = home / "shared-tree"

    info = mod.migrate_profile("opnory-builder", tree, apply=True, stamp="20260928-000000")
    assert info["status"] == "migrated", info
    text = worker_cfg.read_text()
    assert "  write_approval: false" in text
    assert "  memory_char_limit: 2200" in text
    assert "  user_char_limit: 1375" in text
    assert "  flush_min_turns: 6" in text
    assert "  nudge_interval: 10" in text
    # policy keys set to the worker policy
    assert "memory_enabled: true" in text
    assert f"workdir: {tree}" in text
    assert "auto_extract: true" in text


# ---------------------------------------------------------------------------
# Invariant 2: HERMES_HOME pollution must not change the fleet root
# ---------------------------------------------------------------------------

def test_hermes_home_pollution_does_not_move_fleet_root(tmp_path, monkeypatch):
    home, worker_cfg, _ = _sandbox_fleet(tmp_path, monkeypatch)
    # worker sessions export HERMES_HOME=<profile dir> — the script must ignore it
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes" / "profiles" / "opnory-builder"))
    mod = _load_module(tmp_path, monkeypatch, home)
    assert mod.PROFILES_ROOT == home / ".hermes" / "profiles"
    assert all(str(t).startswith(str(home / ".hermes")) for t in mod.PROJECT_MEMORY.values())
    # and the polluted run still migrates the real (sandbox) worker config
    info = mod.migrate_profile("opnory-builder", mod.PROJECT_MEMORY["opnory"], apply=True,
                               stamp="20260928-000001")
    assert info["status"] == "migrated", info
    assert "workdir:" in worker_cfg.read_text()


# ---------------------------------------------------------------------------
# Invariant 3: backup discovery matches ONLY the exact filename pattern the script writes
# ---------------------------------------------------------------------------

def test_backup_discovery_matches_exact_pattern_only(tmp_path, monkeypatch):
    home, worker_cfg, _ = _sandbox_fleet(tmp_path, monkeypatch)
    mod = _load_module(tmp_path, monkeypatch, home)
    pdir = worker_cfg.parent
    # exact-pattern backups (ours)
    (pdir / "config.20260927-221148.bak").write_text("ours-old")
    (pdir / "config.20260928-033553.bak").write_text("ours-newer")
    # foreign backups that must NEVER be picked (the incident: pre-GLM rollback)
    (pdir / "config.yaml.pre-glm53-20260924-135603.bak").write_text("foreign-1")
    (pdir / "config.broken-state-20260928.snap").write_text("foreign-2")
    (pdir / "config.yaml.20260927.bak").write_text("foreign-3")

    found = mod.find_backups(pdir)
    names = [p.name for p in found]
    assert names == ["config.20260927-221148.bak", "config.20260928-033553.bak"], names
    assert all("foreign" not in p.read_text() for p in found)


def test_migrate_writes_backup_in_exact_pattern(tmp_path, monkeypatch):
    home, worker_cfg, _ = _sandbox_fleet(tmp_path, monkeypatch)
    mod = _load_module(tmp_path, monkeypatch, home)
    original = worker_cfg.read_text()
    info = mod.migrate_profile("opnory-builder", mod.PROJECT_MEMORY["opnory"], apply=True,
                               stamp="20260928-120000")
    import re as _re
    backup = Path(info["backup"])
    assert _re.fullmatch(r"config\.\d{8}-\d{6}\.bak", backup.name), backup.name
    assert mod.find_backups(worker_cfg.parent) == [backup]
    assert backup.read_text() == original  # pristine pre-state, byte-for-byte


# ---------------------------------------------------------------------------
# Invariant 4: post-migration audit rejects duplicate/ambiguous memory blocks
# ---------------------------------------------------------------------------

def test_migration_refuses_ambiguous_memory_blocks(tmp_path, monkeypatch):
    home, worker_cfg, _ = _sandbox_fleet(tmp_path, monkeypatch)
    mod = _load_module(tmp_path, monkeypatch, home)
    # reproduce the incident shape: original block + appended second block
    worker_cfg.write_text(
        "memory:\n"
        "  memory_enabled: true\n"
        "  provider: byterover\n"
        "  write_approval: false\n"
        "memory:\n"
        "  memory_enabled: true\n"
        "  provider: byterover\n"
        "  byterover:\n"
        "    workdir: /wrong/path\n"
        "    auto_extract: true\n"
    )
    info = mod.migrate_profile("opnory-builder", home / "shared-tree", apply=True,
                               stamp="20260928-000002")
    assert info["status"] == "ambiguous-memory-blocks", info
    assert "error" in info
    # and the file is NOT modified (no silent last-wins migration on top of ambiguity)
    assert worker_cfg.read_text().count("memory:") == 2


def test_audit_reports_ambiguity_as_a_failure_row(tmp_path, monkeypatch):
    home, worker_cfg, _ = _sandbox_fleet(tmp_path, monkeypatch)
    mod = _load_module(tmp_path, monkeypatch, home)
    worker_cfg.write_text("memory:\n  memory_enabled: true\nmemory:\n  memory_enabled: false\n")
    rows = mod.audit()
    row = next(r for r in rows if r["profile"] == "opnory-builder")
    assert row["blocks"] == 2 and row["enabled"] is False, row


def test_audit_on_a_clean_fleet_reports_single_blocks(tmp_path, monkeypatch):
    home, _, _ = _sandbox_fleet(tmp_path, monkeypatch)
    mod = _load_module(tmp_path, monkeypatch, home)
    rows = mod.audit()
    row = next(r for r in rows if r["profile"] == "opnory-builder")
    assert row["blocks"] == 1
