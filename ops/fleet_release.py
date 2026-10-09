#!/usr/bin/env python3
"""Review scoped fleet configuration changes and pin a validated plugin commit.

Plans contain source hashes and owned changes, never complete configuration data.
Applying a plan requires its SHA-256 confirmation; all files are preflighted before
any replacement. No model calls, tasks, or fleet workloads are executed here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


class UniqueLoader(yaml.SafeLoader):
    """Reject silent YAML last-key-wins configuration corruption."""


def _unique_mapping(loader, node, deep=False):
    explicit = set()
    for key_node, value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            continue
        key = loader.construct_object(key_node, deep=deep)
        if key in explicit:
            raise ValueError("duplicate YAML key")
        explicit.add(key)
    # YAML merge overrides are valid; reject duplicate authored keys, not merges.
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def plan_sha256(plan):
    return _sha(json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError("invalid project or profile identity")
    return value


def _path(value, *, directory=False):
    value = os.fspath(value)
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in value):
        raise ValueError("paths must be absolute without traversal or control characters")
    if path.is_symlink():
        raise ValueError("symlink path refused")
    # Reject links below the platform's canonical /tmp or /var aliases too.
    canonical_parent = path.parent.resolve()
    if canonical_parent != path.parent and any(p.is_symlink() for p in path.parents if p.parent not in (Path("/"), Path("/private"))):
        raise ValueError("symlink ancestor refused")
    if len(path.parts) < 3 or path == Path.home():
        raise ValueError("broad root refused")
    if directory and not path.is_dir():
        raise ValueError("reviewed directory must already exist")
    return path


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(label + " must be a mapping")
    return value


def _inventory(inventory):
    projects = _mapping(inventory.get("projects", inventory), "inventory projects")
    if not projects:
        raise ValueError("empty inventory")
    result = {}
    for project, cfg in projects.items():
        _name(project)
        _mapping(cfg, "project")
        _name(cfg["board"])
        for key in ("workspace", "knowledge_tree", "repo"):
            _path(cfg[key], directory=True)
        roots = cfg.get("task_workspaces", [])
        if not isinstance(roots, list):
            raise ValueError("task_workspaces must be an explicit list")
        for root in roots:
            _path(root, directory=True)
        for key in ("profiles", "maintainers"):
            if not isinstance(cfg.get(key), list) or not cfg[key]:
                raise ValueError(key + " must be a nonempty explicit list")
            for identity in cfg[key]:
                _name(identity)
        result[project] = copy.deepcopy(cfg)
        result[project]["task_workspaces"] = copy.deepcopy(roots)
    return result


def _load_config(raw):
    try:
        data = yaml.load(raw, Loader=UniqueLoader)
    except yaml.YAMLError:
        # Parser exceptions can include raw values; suppress their text.
        raise ValueError("invalid configuration YAML") from None
    return _mapping(data, "configuration")


def _updated(raw, changes):
    data = _load_config(raw)
    plugins = copy.deepcopy(_mapping(data.get("plugins"), "plugins"))
    enabled = plugins.get("enabled", [])
    if not isinstance(enabled, list) or "swarm-protocol" not in enabled:
        raise ValueError("swarm-protocol must already be enabled")
    entries = copy.deepcopy(_mapping(plugins.get("entries", {}), "plugin entries"))
    entry = copy.deepcopy(_mapping(entries.get("swarm-protocol", {}), "plugin entry"))
    settings = copy.deepcopy(_mapping(entry.get("settings", {}), "plugin settings"))
    current = copy.deepcopy(_mapping(settings.get("wiki_projects", {}), "wiki projects"))
    if set(current) - set(changes["wiki_projects"]):
        raise ValueError("existing unauthorized wiki project mapping requires explicit review")
    for project, config in changes["wiki_projects"].items():
        merged = copy.deepcopy(_mapping(current.get(project, {}), "wiki project"))
        merged.update(copy.deepcopy(config))
        current[project] = merged
    settings["wiki_projects"] = current
    if changes["byterover_timeout"]:
        memory = copy.deepcopy(_mapping(data.get("memory"), "memory"))
        if memory.get("provider") != "byterover" or not isinstance(memory.get("byterover"), dict):
            raise ValueError("ByteRover configuration changed")
        byterover = copy.deepcopy(memory["byterover"])
        byterover["curate_timeout"] = 600
        memory["byterover"] = byterover
        data["memory"] = memory
        settings["byterover_curate_timeout_seconds"] = 600
    entry["settings"] = settings
    entries["swarm-protocol"] = entry
    plugins["entries"] = entries
    data["plugins"] = plugins
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True).encode()


def plan_configs(inventory, identity_paths):
    projects = _inventory(inventory)
    rows, seen_paths, seen_identities = [], set(), set()
    for identity, value in identity_paths:
        _name(identity)
        path = _path(value)
        if not path.is_file():
            raise ValueError("configuration must be an existing regular file")
        if path.resolve() in seen_paths or identity in seen_identities:
            raise ValueError("duplicate configuration path or identity")
        seen_paths.add(path.resolve())
        seen_identities.add(identity)
        authorized = {name: cfg for name, cfg in projects.items() if identity == "default" or identity in set(cfg["profiles"]) | set(cfg["maintainers"])}
        if not authorized:
            raise ValueError("profile has no reviewed project membership")
        raw = path.read_bytes()
        data = _load_config(raw)
        memory = data.get("memory", {})
        timeout = isinstance(memory, dict) and memory.get("provider") == "byterover" and isinstance(memory.get("byterover"), dict)
        changes = {"wiki_projects": {name: {key: copy.deepcopy(cfg[key]) for key in ("board", "workspace", "repo", "knowledge_tree", "task_workspaces", "profiles", "maintainers")} for name, cfg in authorized.items()}, "byterover_timeout": timeout}
        updated = _updated(raw, changes)
        rows.append({"identity": identity, "path": str(path), "before_sha256": _sha(raw), "after_sha256": _sha(updated), "changes": changes})
    if not rows:
        raise ValueError("no configurations selected")
    return {"version": 1, "inventory": projects, "inventory_sha256": plan_sha256(projects), "configs": rows}


def _stage(path, raw, mode):
    fd, name = tempfile.mkstemp(prefix=".swarm-release-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        stream = os.fdopen(fd, "wb")
        fd = None
        with stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if fd is not None:
            os.close(fd)
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def apply_plan(plan, *, expected_sha256, backup_root):
    digest = plan_sha256(plan)
    if expected_sha256 != digest:
        raise ValueError("explicit plan SHA-256 confirmation mismatch")
    if plan.get("version") != 1:
        raise ValueError("unsupported plan version")
    _inventory(plan["inventory"])
    if plan["inventory_sha256"] != plan_sha256(plan["inventory"]):
        raise ValueError("inventory review hash mismatch")
    # Rebuild the intended mapping rather than trusting arbitrary changes in JSON.
    rows = plan["configs"]
    if len({row["path"] for row in rows}) != len(rows) or len({row["identity"] for row in rows}) != len(rows):
        raise ValueError("duplicate plan identity or path")
    pending = []
    for row in rows:
        path = _path(row["path"])
        if not path.is_file():
            raise ValueError("configuration must be an existing regular file")
        raw = path.read_bytes()
        current = _sha(raw)
        if current not in (row["before_sha256"], row["after_sha256"]):
            raise ValueError("configuration drift; review a new plan")
        recalculated = plan_configs({"projects": plan["inventory"]}, [(row["identity"], path)])["configs"][0]
        if row["changes"] != recalculated["changes"] or row["after_sha256"] != recalculated["after_sha256"]:
            raise ValueError("plan does not match reviewed inventory")
        if current != row["after_sha256"]:
            pending.append((path, raw, _updated(raw, row["changes"]), stat.S_IMODE(path.stat().st_mode)))
    if not pending:
        return {"plan_sha256": digest, "changed": [], "backups": []}
    root = _path(backup_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    staged, replaced, backups = [], [], []
    try:
        for index, (path, raw, updated, mode) in enumerate(pending):
            backup = root / (digest + "-" + str(index) + ".bak")
            if backup.exists() or backup.is_symlink():
                if backup.is_symlink() or backup.read_bytes() != raw or stat.S_IMODE(backup.stat().st_mode) != 0o600:
                    raise ValueError("private backup collision")
            else:
                fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            backups.append(str(backup))
            staged.append(_stage(path, updated, mode))
        # Catch changes during staging before beginning the replacement transaction.
        for path, raw, _, _ in pending:
            if _path(path).read_bytes() != raw:
                raise ValueError("configuration drift during staging")
        for stage, row in zip(staged, pending):
            path, raw, updated, mode = row
            if _path(path).read_bytes() != raw:
                raise ValueError("configuration drift during apply")
            os.replace(stage, path)
            replaced.append(row)
            _sync_directory(path.parent)
    except BaseException:
        for path, raw, updated, mode in reversed(replaced):
            if not path.is_symlink() and path.read_bytes() == updated:
                recovery = _stage(path, raw, mode)
                try:
                    os.replace(recovery, path)
                    _sync_directory(path.parent)
                finally:
                    recovery.unlink(missing_ok=True)
        raise
    finally:
        for stage in staged:
            stage.unlink(missing_ok=True)
    return {"plan_sha256": digest, "changed": [str(row[0]) for row in pending], "backups": backups}


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise ValueError("Git release verification failed")
    return result.stdout


def verify_release(path, commit, *, immutable=False):
    path = _path(path, directory=True)
    if _git(path, "rev-parse", "HEAD").decode().strip() != commit:
        raise ValueError("release commit mismatch")
    if _git(path, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
        raise ValueError("release must be clean, including ignored files")
    # Compare worktree bytes with commit objects; index flags must not hide changes.
    expected_files, expected_directories = {Path(".git")}, {Path(".")}
    for entry in _git(path, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        relative = Path(os.fsdecode(name))
        expected_files.add(relative)
        expected_directories.update(relative.parents)
        target = path / relative
        if kind != b"blob" or mode not in (b"100644", b"100755") or target.is_symlink() or not target.is_file():
            raise ValueError("release must contain only clean regular tracked files")
        if target.read_bytes() != _git(path, "cat-file", "blob", object_id.decode()):
            raise ValueError("release must match clean commit bytes")
        if bool(target.stat().st_mode & 0o111) != (mode == b"100755"):
            raise ValueError("release file mode mismatch")
        if target.stat().st_nlink != 1:
            raise ValueError("release hardlink refused")
    # Git does not report empty untracked directories; exact releases reject them.
    for directory, dirs, files in os.walk(path):
        if immutable and Path(directory).stat().st_mode & 0o222:
            raise ValueError("release directory must be immutable")
        for name in dirs + files:
            target = Path(directory) / name
            relative = target.relative_to(path)
            if target.is_symlink() or relative not in expected_files | expected_directories:
                raise ValueError("release must be clean without unexpected paths")
            if immutable and target.stat().st_mode & 0o222:
                raise ValueError("release paths must be immutable")
    if not (path / "hermes_swarm_protocol/plugin.yaml").is_file():
        raise ValueError("commit lacks swarm-protocol plugin")


def _atomic_symlink(link, target):
    previous = os.readlink(link) if link.is_symlink() else None
    if link.exists() and not link.is_symlink():
        raise ValueError("plugin destination must be a symlink or absent")
    fd, temporary = tempfile.mkstemp(prefix=".swarm-link-", dir=link.parent)
    os.close(fd)
    temporary = Path(temporary)
    temporary.unlink()
    try:
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, link)
        try:
            _sync_directory(link.parent)
        except BaseException:
            # A failed durability report must not leave an unreported activation.
            if link.is_symlink() and os.readlink(link) == target:
                if previous is None:
                    link.unlink()
                else:
                    temporary.symlink_to(previous, target_is_directory=True)
                    os.replace(temporary, link)
                try:
                    _sync_directory(link.parent)
                except OSError:
                    pass  # Preserve the original failure after restoring the target.
            raise
    finally:
        temporary.unlink(missing_ok=True)


def install_release(repo, commit, *, release_root, plugin_link):
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("full Git commit SHA required")
    repo = _path(repo, directory=True)
    if _git(repo, "rev-parse", "--verify", commit + "^{commit}").decode().strip() != commit:
        raise ValueError("release commit mismatch")
    root = _path(release_root)
    link = Path(plugin_link)
    # A plugin symlink is the only symlink explicitly allowed as an output.
    _path(link.parent, directory=True)
    if link.exists() and not link.is_symlink():
        raise ValueError("plugin destination must be a symlink or absent")
    if not link.is_absolute() or ".." in link.parts or any(ord(c) < 32 for c in str(link)):
        raise ValueError("invalid plugin link path")
    previous = os.readlink(link) if link.is_symlink() else None
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    release = root / commit
    if release.is_symlink():
        raise ValueError("release symlink refused")
    if release.exists():
        verify_release(release, commit, immutable=True)
    else:
        _git(repo, "worktree", "add", "--detach", str(release), commit)
        verify_release(release, commit)
    # Files and directories are read-only. Python cache writes stay outside release.
    for directory, dirs, files in os.walk(release):
        for filename in files:
            path = Path(directory) / filename
            os.chmod(path, 0o555 if path.stat().st_mode & 0o111 else 0o444)
        os.chmod(directory, 0o555)
    verify_release(release, commit, immutable=True)
    target = str(release / "hermes_swarm_protocol")
    if previous != target:
        if (os.readlink(link) if link.is_symlink() else None) != previous or (link.exists() and not link.is_symlink()):
            raise ValueError("plugin link drift")
        _atomic_symlink(link, target)
    return {"commit": commit, "release": str(release), "target": target, "previous_target": previous, "changed": previous != target}


def rollback_release(plugin_link, previous_target, *, expected_target):
    link = Path(plugin_link)
    _path(link.parent, directory=True)
    if not link.is_absolute() or ".." in link.parts or any(ord(c) < 32 for c in str(link)):
        raise ValueError("invalid plugin link path")
    if not link.is_symlink() or os.readlink(link) != expected_target:
        raise ValueError("plugin link drift; rollback refused")
    if previous_target is None:
        link.unlink()
        _sync_directory(link.parent)
    else:
        _atomic_symlink(link, previous_target)


def _private_json(path, data):
    path = _path(path)
    if path.exists():
        raise ValueError("plan output already exists")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {"plan", "apply", "install", "rollback", "-h", "--help"}:
        argv.insert(0, "plan")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="dry-run; output only owned changes and hashes")
    plan.add_argument("--inventory", required=True)
    plan.add_argument("--config", action="append", required=True, metavar="IDENTITY=ABSOLUTE_PATH")
    plan.add_argument("--output", required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--confirm-sha256", required=True)
    apply.add_argument("--backup-root", required=True)
    install = sub.add_parser("install")
    install.add_argument("--repo", required=True)
    install.add_argument("--commit", required=True)
    install.add_argument("--release-root", default=str(Path.home() / ".hermes/releases/swarm-protocol"))
    install.add_argument("--plugin-link", default=str(Path.home() / ".hermes/plugins/swarm-protocol"))
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--plugin-link", required=True)
    rollback.add_argument("--expected-target", required=True)
    rollback.add_argument("--previous-target")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            inventory = json.loads(_path(args.inventory).read_text())
            pairs = [item.split("=", 1) for item in args.config]
            if any(len(pair) != 2 for pair in pairs):
                raise ValueError("--config requires IDENTITY=ABSOLUTE_PATH")
            result = plan_configs(inventory, pairs)
            _private_json(args.output, result)
            print(json.dumps({"plan": args.output, "plan_sha256": plan_sha256(result), "configs": len(result["configs"])}))
        elif args.command == "apply":
            result = apply_plan(json.loads(_path(args.plan).read_text()), expected_sha256=args.confirm_sha256, backup_root=args.backup_root)
            print(json.dumps(result))
        elif args.command == "install":
            print(json.dumps(install_release(args.repo, args.commit, release_root=args.release_root, plugin_link=args.plugin_link)))
        else:
            rollback_release(args.plugin_link, args.previous_target, expected_target=args.expected_target)
            print(json.dumps({"rolled_back": True}))
    except (ValueError, OSError, KeyError, TypeError):
        # Never expose YAML values, subprocess diagnostics, or configuration contents.
        parser.exit(2, "fleet release refused; verify paths, reviewed hashes, and clean commit\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
