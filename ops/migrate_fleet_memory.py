#!/usr/bin/env python3
"""Fleet memory migration: point Kanban worker profiles at shared ByteRover trees.

Two modes:
  audit (default)   Show current memory config for every profile — no writes.
  --apply           Write memory.{memory_enabled,provider,byterover.workdir} for
                    profiles matched by the PROJECT_MEMORY mapping, after a
                    timestamped backup and with a full dry-run diff.

Boundaries:
  - Explicit profile->tree mapping only; profiles not in the mapping are untouched.
  - YAML round-trip via ruamel-style ordered dict edit (PyYAML + custom dumper to
    preserve key order and inline style of unrelated keys).
  - idempotent: re-running --apply produces no diff.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

# The fleet is machine-global: always ~/.hermes, NEVER a per-profile HERMES_HOME
# (worker sessions export HERMES_HOME=<profile>; the profiles tree and the shared
# byterover trees both live under the real home).
FLEET_ROOT = Path.home() / ".hermes"
PROFILES_ROOT = FLEET_ROOT / "profiles"

# Project->shared tree. Workers are mapped by prefix. A worker sees the tree of its project.
PROJECT_MEMORY: dict[str, str] = {
    "opnory": str(FLEET_ROOT / "byterover-projects" / "opnory"),
    "alepes": str(FLEET_ROOT / "byterover-projects" / "alepes"),
    "tachikoma": str(FLEET_ROOT / "byterover-projects" / "tachikoma"),
    "tunory": str(FLEET_ROOT / "byterover-projects" / "tunory"),
}

WORKER_PREFIXES: dict[str, tuple[str, ...]] = {
    "opnory": ("opnory-", "home-lab-"),
    "alepes": ("alepes-"),
    "tachikoma": ("tachikoma-"),
    "tunory": ("tunory-"),
}

SKIP_PROFILES: tuple[str, ...] = (".deleted",)
# The root profile names themselves (project orchestrators) are not workers; leave them
# to the operator (they run in the same gateway as the fleet). Add them to the mapping
# if you want the orchestrator to share the tree too.
ROOT_PROJECT_PROFILES: tuple[str, ...] = ("opnory", "alepes", "tachikoma", "tunory")


def project_for_profile(profile: str, *, include_roots: bool = False) -> str | None:
    """Mapping rule, single source of truth for both audit and apply.

    Roots map to their own project (opnory -> opnory) but only when include_roots
    is set — the default plan touches workers only.
    """
    if profile in SKIP_PROFILES:
        return None
    if profile in ROOT_PROJECT_PROFILES:
        return profile if include_roots else None
    for project, prefixes in WORKER_PREFIXES.items():
        if profile.startswith(tuple(prefixes) if isinstance(prefixes, tuple) else (prefixes,)):
            return project
    return None


def _load_yaml_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def count_memory_blocks(lines: list[str]) -> int:
    """Top-level `memory:` keys. More than one is ambiguous — YAML last-wins silently picks
    the final block, which is exactly how a wrong workdir went live fleet-wide (2026-09-28
    incident). Callers must refuse instead of relying on last-wins."""
    return sum(1 for ln in lines if re.match(r"^memory:\s*$", ln))


def find_backups(profile_dir: Path) -> list[Path]:
    """Backups written by THIS script: exact pattern ``config.<YYYYMMDD-HHMMSS>.bak``.

    Deliberately excludes foreign backup files (``config.yaml.pre-glm53-*.bak``,
    ``*.snap``, …). Restoring from a foreign backup rolls back unrelated config — the
    2026-09-28 incident restored pre-GLM backups this way and regressed 26 profiles.
    Verify backup identity by content markers when recovering, never by filename alone.
    """
    return sorted(
        (p for p in profile_dir.glob("config.*.bak")
         if re.fullmatch(r"config\.\d{8}-\d{6}\.bak", p.name)),
        key=lambda p: p.name,
    )


def _save_backup(path: Path, stamp: str) -> Path:
    backup = path.with_suffix(f".{stamp}.bak")
    shutil.copy2(path, backup)
    return backup


def _set_memory_block(lines: list[str], *, enabled: bool, workdir: str, auto_extract: bool = True) -> list[str]:
    """Rewrite the top-level `memory:` block, preserving everything outside it.

    PRESERVES every pre-existing memory key (write_approval, memory_char_limit, …): we only
    overwrite the four policy keys (memory_enabled, provider, byterover.workdir,
    byterover.auto_extract) and keep the rest verbatim — both their values and their order.
    Roots use auto_extract=False (read-mostly): retrieval yes, automatic curation no.
    """
    out, i, n = [], 0, len(lines)
    # find the top-level memory: key
    while i < n and not re.match(r"^memory:\s*$", lines[i]):
        out.append(lines[i])
        i += 1
    if i >= n:  # no memory block -> append a fresh one
        return out + ["", "memory:", "  memory_enabled: true", "  user_profile_enabled: false",
                      "  provider: byterover", "  byterover:", f"    workdir: {workdir}",
                      f"    auto_extract: {'true' if auto_extract else 'false'}", ""]
    # collect the old block, then re-emit with the policy keys set
    old: list[str] = []
    i += 1
    while i < n and (lines[i].startswith("  ") or lines[i].strip() == ""):
        old.append(lines[i])
        i += 1
    # split the old block into byterover sub-block vs the rest
    old_byterover: list[str] = []
    rest: list[str] = []
    j = 0
    while j < len(old):
        if re.match(r"^  byterover:\s*$", old[j]):
            j += 1
            while j < len(old) and (old[j].startswith("    ") or old[j].strip() == ""):
                old_byterover.append(old[j])
                j += 1
        else:
            rest.append(old[j])
            j += 1
    # policy keys we own; everything else keeps its old value+position
    def _strip_keys(rows: list[str], keys: tuple[str, ...], indent: str) -> list[str]:
        return [r for r in rows if not any(re.match(rf"^{indent}{k}:\s", r) for k in keys)]

    rest = _strip_keys(rest, ("memory_enabled", "provider", "user_profile_enabled"), "  ")
    old_byterover = _strip_keys(old_byterover, ("workdir", "auto_extract"), "    ")
    block = (["memory:",
              "  memory_enabled: true",
              "  user_profile_enabled: false",
              "  provider: byterover"]
             + rest
             + ["  byterover:",
                f"    workdir: {workdir}"]
             + old_byterover
             + [f"    auto_extract: {'true' if auto_extract else 'false'}"])
    return out + block + lines[i:]


def migrate_profile(profile: str, tree: Path, *, apply: bool, stamp: str, auto_extract: bool = True) -> dict:
    cfg_path = PROFILES_ROOT / profile / "config.yaml"
    info = {"profile": profile, "config": str(cfg_path), "tree": str(tree)}
    if not cfg_path.exists():
        info["status"] = "missing-config"
        return info
    lines = _load_yaml_lines(cfg_path)
    # Ambiguity guard FIRST: two top-level memory: blocks mean YAML last-wins picks one
    # silently. Refuse rather than migrate on top of an ambiguous file.
    n_blocks = count_memory_blocks(lines)
    if n_blocks > 1:
        info["status"] = "ambiguous-memory-blocks"
        info["error"] = (f"{n_blocks} top-level memory: blocks (YAML last-wins would pick one "
                         f"silently) — resolve manually, then re-run")
        return info
    # idempotence probe: does the target state already hold? (workdir + enabled + the
    # desired auto_extract policy — a root left at auto_extract:true is NOT done)
    joined = "\n".join(lines)
    auto_line = f"auto_extract: {'true' if auto_extract else 'false'}"
    if (f"workdir: {tree}" in joined and auto_line in joined
            and re.search(r"^\s*memory_enabled:\s*true", joined, re.M)):
        info["status"] = "already-migrated"
        return info
    new_lines = _set_memory_block(lines, enabled=True, workdir=str(tree), auto_extract=auto_extract)
    info["before"] = _memory_block_text(lines)
    info["after"] = _memory_block_text(new_lines)
    if apply:
        backup = _save_backup(cfg_path, stamp)
        cfg_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        info["backup"] = str(backup)
        info["status"] = "migrated"
    else:
        info["status"] = "dry-run"
    return info


def _memory_block_text(lines: list[str]) -> str:
    """Extract the top-level memory: block for the diff display."""
    out, active = [], False
    for ln in lines:
        if re.match(r"^memory:\s*$", ln):
            active = True
            out.append(ln)
            continue
        if active:
            if ln.startswith("  ") or ln.strip() == "":
                out.append(ln)
            else:
                break
    return "\n".join(out).strip()


def audit(show_all: bool = True) -> list[dict]:
    """Current memory state of every profile, read-only (yaml-parsed, block-scoped)."""
    rows = []
    for d in sorted(PROFILES_ROOT.iterdir()):
        if not d.is_dir() or d.name in SKIP_PROFILES:
            continue
        cfg = d / "config.yaml"
        if not cfg.exists():
            continue
        try:
            text = cfg.read_text(encoding="utf-8")
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            text, data = "", {}
        mem = data.get("memory") or {}
        byt = mem.get("byterover") or {}
        project = project_for_profile(d.name)
        is_root = d.name in ROOT_PROJECT_PROFILES
        rows.append({
            "profile": d.name,
            "role": "root" if is_root else ("worker" if project else "-"),
            "project": (d.name if is_root else (project or "-")),
            "blocks": count_memory_blocks(text.splitlines()),
            "enabled": mem.get("memory_enabled", "<unset>"),
            "auto_extract": byt.get("auto_extract", "<unset>"),
            "provider": mem.get("provider", "<unset>"),
            "workdir": byt.get("workdir", "-"),
            "target_tree": PROJECT_MEMORY.get(project) if project else "-",
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Write changes (default is audit/dry-run)")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    ap.add_argument("--roots", action="store_true",
                    help="Target the four root orchestrator profiles instead, read-mostly "
                         "(auto_extract: false — retrieval on, automatic curation off)")
    ap.add_argument("--only", default=None,
                    help="Comma-separated profile filter applied to the plan (e.g. opnory)")
    args = ap.parse_args(argv)

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    rows = audit()
    if args.roots:
        plan = [dict(r, target_tree=PROJECT_MEMORY[r["profile"]]) for r in rows
                if r["profile"] in ROOT_PROJECT_PROFILES]
    else:
        plan = [r for r in rows if r["target_tree"] != "-"]
    if args.only:
        keep = {p.strip() for p in args.only.split(",") if p.strip()}
        plan = [r for r in plan if r["profile"] in keep]

    if args.json:
        payload = {"mode": "apply" if args.apply else "audit", "profiles": rows}
        if args.apply:
            payload["results"] = [
                migrate_profile(r["profile"], Path(r["target_tree"]), apply=True, stamp=stamp,
                                auto_extract=r["profile"] not in ROOT_PROJECT_PROFILES)
                for r in plan
            ]
        print(json.dumps(payload, indent=2))
        return 0

    print(f"{'profile':<24} {'role':<7} {'enabled':<9} {'auto_ex':<8} {'provider':<11} {'workdir':<42} {'target_tree'}")
    for r in rows:
        print(f"{r['profile']:<24} {r['role']:<7} {str(r['enabled']):<9} {str(r['auto_extract']):<8} "
              f"{str(r['provider']):<11} {str(r['workdir']):<42} {r['target_tree']}")

    if not args.apply:
        print(f"\n[audit] {len(plan)} profile(s) in plan ({'roots' if args.roots else 'workers'}). "
              f"Re-run with --apply to write.")
        return 0

    results = []
    for r in plan:
        results.append(migrate_profile(r["profile"], Path(r["target_tree"]), apply=True, stamp=stamp,
                                       auto_extract=r["profile"] not in ROOT_PROJECT_PROFILES))
    for info in results:
        before, after = info.get("before", ""), info.get("after", "")
        print(f"\n=== {info['profile']}: {info['status']}")
        if before != after:
            import difflib
            print("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                                "before", "after")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
