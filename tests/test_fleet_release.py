"""Fixture-only deployment safety checks; never touch the live fleet."""
import copy
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def writable_cleanup(tmp_path):
    yield
    # Owner tampering is simulated below; release files otherwise stay read-only.
    for directory, dirs, files in os.walk(tmp_path):
        os.chmod(directory, 0o700)
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                os.chmod(path, 0o600)


def module():
    spec = importlib.util.spec_from_file_location("fleet_release", Path(__file__).resolve().parents[1] / "ops/fleet_release.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def fleet(tmp_path):
    projects = {}
    for name in ("alpha", "beta"):
        paths = {}
        for key in ("workspace", "knowledge_tree", "repo", "tasks"):
            path = tmp_path / name / key
            path.mkdir(parents=True)
            paths[key] = str(path)
        projects[name] = dict(board=name, workspace=paths["workspace"], knowledge_tree=paths["knowledge_tree"], repo=paths["repo"], task_workspaces=[paths["tasks"]], profiles=[name + "-worker"], maintainers=["default", name + "-worker"])
    config = {"model": {"name": "existing"}, "plugins": {"enabled": ["other", "swarm-protocol"], "entries": {"other": {"unchanged": 5}, "swarm-protocol": {"settings": {"projects": {"alpha": {"roles": {"builder": "alpha-worker"}}}, "arbitrary": 7}}}}, "memory": {"provider": "byterover", "memory_enabled": True, "write_approval": False, "byterover": {"workdir": projects["alpha"]["knowledge_tree"], "auto_extract": False, "custom": 12}}}
    pairs = []
    for identity in ("default", "alpha-worker", "beta-worker"):
        path = tmp_path / (identity + ".yaml")
        data = copy.deepcopy(config)
        if identity != "default":
            data["memory"]["byterover"]["auto_extract"] = True
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        pairs.append((identity, path))
    return {"projects": projects}, pairs, tmp_path / "backups"


def test_additive_authorized_plan_preserves_every_unrelated_value(fleet):
    m = module()
    inventory, pairs, backups = fleet
    before = [yaml.safe_load(path.read_text()) for _, path in pairs]
    plan = m.plan_configs(inventory, pairs)
    assert "existing" not in str(plan)  # no full configuration disclosure
    result = m.apply_plan(plan, expected_sha256=m.plan_sha256(plan), backup_root=backups)
    assert len(result["changed"]) == 3
    for (identity, path), original in zip(pairs, before):
        data = yaml.safe_load(path.read_text())
        settings = data["plugins"]["entries"]["swarm-protocol"]["settings"]
        expected = {"alpha", "beta"} if identity == "default" else {identity.split("-")[0]}
        assert set(settings.pop("wiki_projects")) == expected
        assert settings.pop("byterover_curate_timeout_seconds") == 600
        assert data["memory"]["byterover"].pop("curate_timeout") == 600
        assert data == original
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in backups.iterdir())
    assert m.apply_plan(plan, expected_sha256=m.plan_sha256(plan), backup_root=backups)["changed"] == []


def test_no_memory_roots_or_timeout_invented(fleet):
    m = module()
    inventory, pairs, backups = fleet
    path = pairs[0][1]
    data = yaml.safe_load(path.read_text())
    data.pop("memory")
    path.write_text(yaml.safe_dump(data))
    plan = m.plan_configs(inventory, pairs)
    m.apply_plan(plan, expected_sha256=m.plan_sha256(plan), backup_root=backups)
    after = yaml.safe_load(path.read_text())
    assert "memory" not in after
    assert "byterover_curate_timeout_seconds" not in after["plugins"]["entries"]["swarm-protocol"]["settings"]


def test_drift_and_unconfirmed_plan_leave_all_configs_untouched(fleet):
    m = module()
    inventory, pairs, backups = fleet
    plan = m.plan_configs(inventory, pairs)
    pairs[-1][1].write_text(pairs[-1][1].read_text() + "\n# external change\n")
    before = [path.read_bytes() for _, path in pairs]
    with pytest.raises(ValueError, match="confirmation"):
        m.apply_plan(plan, expected_sha256="0" * 64, backup_root=backups)
    with pytest.raises(ValueError, match="drift"):
        m.apply_plan(plan, expected_sha256=m.plan_sha256(plan), backup_root=backups)
    assert [path.read_bytes() for _, path in pairs] == before
    assert not backups.exists()


@pytest.mark.parametrize("bad", ["/", "/tmp/../escape", "relative/path", "/tmp/line\nbreak"])
def test_reject_malicious_inventory_paths(fleet, bad):
    m = module()
    inventory, pairs, _ = fleet
    inventory["projects"]["alpha"]["workspace"] = bad
    with pytest.raises(ValueError):
        m.plan_configs(inventory, pairs)


def test_reject_symlink_config_and_inventory(fleet, tmp_path):
    m = module()
    inventory, pairs, _ = fleet
    link = tmp_path / "linked.yaml"
    link.symlink_to(pairs[0][1])
    with pytest.raises(ValueError, match="symlink"):
        m.plan_configs(inventory, [("default", link)])
    root = tmp_path / "linked-root"
    root.symlink_to(inventory["projects"]["alpha"]["workspace"], target_is_directory=True)
    inventory["projects"]["alpha"]["workspace"] = str(root)
    with pytest.raises(ValueError, match="symlink"):
        m.plan_configs(inventory, pairs)


def test_duplicate_yaml_and_disabled_plugin_refused(fleet):
    m = module()
    inventory, pairs, _ = fleet
    pairs[0][1].write_text("memory: {}\nmemory: {}\n")
    with pytest.raises(ValueError, match="duplicate"):
        m.plan_configs(inventory, pairs)
    pairs[0][1].write_text("plugins: {enabled: []}\n")
    with pytest.raises(ValueError, match="enabled"):
        m.plan_configs(inventory, pairs)


def test_unmapped_profile_and_foreign_wiki_mapping_refused(fleet):
    m = module()
    inventory, pairs, _ = fleet
    with pytest.raises(ValueError, match="membership"):
        m.plan_configs(inventory, [("outsider", pairs[0][1])])
    data = yaml.safe_load(pairs[1][1].read_text())
    data["plugins"]["entries"]["swarm-protocol"]["settings"]["wiki_projects"] = {"beta": inventory["projects"]["beta"]}
    pairs[1][1].write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="unauthorized"):
        m.plan_configs(inventory, pairs)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q")
    plugin = repo / "hermes_swarm_protocol"
    plugin.mkdir()
    (plugin / "plugin.yaml").write_text("name: swarm-protocol\n")
    (plugin / "__init__.py").write_text("VALUE = 1\n")
    (repo / ".gitignore").write_text("ignored\n")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    return repo, git(repo, "rev-parse", "HEAD")


def test_exact_release_idempotency_and_atomic_rollback(source_repo, tmp_path):
    m = module()
    repo, commit = source_repo
    root = tmp_path / "releases"
    link = tmp_path / "plugins" / "swarm-protocol"
    link.parent.mkdir()
    old = tmp_path / "old-plugin"
    old.mkdir()
    link.symlink_to(old, target_is_directory=True)
    result = m.install_release(repo, commit, release_root=root, plugin_link=link)
    assert result["previous_target"] == str(old)
    assert link.resolve() == root / commit / "hermes_swarm_protocol"
    assert git(root / commit, "rev-parse", "HEAD") == commit
    assert m.install_release(repo, commit, release_root=root, plugin_link=link)["changed"] is False
    m.rollback_release(link, result["previous_target"], expected_target=result["target"])
    assert os.readlink(link) == str(old)


def test_refuse_short_sha_dirty_or_ignored_release_and_real_plugin_directory(source_repo, tmp_path):
    m = module()
    repo, commit = source_repo
    root, link = tmp_path / "releases", tmp_path / "plugin"
    with pytest.raises(ValueError, match="full"):
        m.install_release(repo, commit[:8], release_root=root, plugin_link=link)
    m.install_release(repo, commit, release_root=root, plugin_link=link)
    release = root / commit
    os.chmod(release, 0o755)
    (release / "ignored").write_text("not part of release")
    with pytest.raises(ValueError, match="clean"):
        m.install_release(repo, commit, release_root=root, plugin_link=link)
    (release / "ignored").unlink()
    os.chmod(release / "hermes_swarm_protocol/__init__.py", 0o644)
    (release / "hermes_swarm_protocol/__init__.py").write_text("changed\n")
    with pytest.raises(ValueError, match="clean"):
        m.install_release(repo, commit, release_root=root, plugin_link=link)
    directory = tmp_path / "real-plugin"
    directory.mkdir()
    with pytest.raises(ValueError, match="symlink"):
        m.install_release(repo, commit, release_root=root, plugin_link=directory)


def test_apply_replaces_atomically_and_rolls_back_on_replace_failure(fleet, monkeypatch):
    m = module()
    inventory, pairs, backups = fleet
    plan = m.plan_configs(inventory, pairs)
    before = [path.read_bytes() for _, path in pairs]
    real_replace = m.os.replace
    calls = []
    def fail_second(source, destination):
        calls.append(destination)
        if len(calls) == 2:
            raise OSError("fixture replacement failure")
        return real_replace(source, destination)
    monkeypatch.setattr(m.os, "replace", fail_second)
    with pytest.raises(OSError, match="fixture"):
        m.apply_plan(plan, expected_sha256=m.plan_sha256(plan), backup_root=backups)
    assert [path.read_bytes() for _, path in pairs] == before


def test_release_verification_does_not_trust_assume_unchanged_index(source_repo, tmp_path):
    m = module()
    repo, commit = source_repo
    root, link = tmp_path / "releases", tmp_path / "plugin"
    m.install_release(repo, commit, release_root=root, plugin_link=link)
    release = root / commit
    git(release, "update-index", "--assume-unchanged", "hermes_swarm_protocol/__init__.py")
    target = release / "hermes_swarm_protocol/__init__.py"
    os.chmod(target, 0o644)
    target.write_text("tampered\n")
    assert git(release, "status", "--porcelain") == ""
    with pytest.raises(ValueError, match="clean commit bytes"):
        m.install_release(repo, commit, release_root=root, plugin_link=link)


def test_plan_tampering_and_rollback_drift_refused(fleet, tmp_path):
    m = module()
    inventory, pairs, backups = fleet
    plan = m.plan_configs(inventory, pairs)
    plan["configs"][1]["changes"]["wiki_projects"]["beta"] = inventory["projects"]["beta"]
    with pytest.raises(ValueError, match="reviewed inventory"):
        m.apply_plan(plan, expected_sha256=m.plan_sha256(plan), backup_root=backups)
    assert not backups.exists()
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "external-change")
    with pytest.raises(ValueError, match="drift"):
        m.rollback_release(link, None, expected_target="/previous/release")
    assert link.is_symlink()


def test_release_rejects_untracked_empty_directory(source_repo, tmp_path):
    m = module()
    repo, commit = source_repo
    root, link = tmp_path / "releases", tmp_path / "plugin"
    m.install_release(repo, commit, release_root=root, plugin_link=link)
    release = root / commit
    os.chmod(release, 0o755)
    (release / "unexpected-empty").mkdir()
    os.chmod(release, 0o555)
    assert git(release, "status", "--porcelain") == ""
    with pytest.raises(ValueError, match="unexpected paths"):
        m.install_release(repo, commit, release_root=root, plugin_link=link)


def test_distinct_repo_is_reconciled_without_dropping_custom_project_settings(fleet):
    m = module()
    inventory, pairs, backups = fleet
    path = pairs[0][1]
    data = yaml.safe_load(path.read_text())
    settings = data["plugins"]["entries"]["swarm-protocol"]["settings"]
    settings["wiki_projects"] = {"alpha": {"repo": "/stale/repository", "custom_project_setting": 9}}
    path.write_text(yaml.safe_dump(data))
    assert inventory["projects"]["alpha"]["repo"] != inventory["projects"]["alpha"]["workspace"]
    plan = m.plan_configs(inventory, pairs)
    m.apply_plan(plan, expected_sha256=m.plan_sha256(plan), backup_root=backups)
    project = yaml.safe_load(path.read_text())["plugins"]["entries"]["swarm-protocol"]["settings"]["wiki_projects"]["alpha"]
    assert project["repo"] == inventory["projects"]["alpha"]["repo"]
    assert project["workspace"] == inventory["projects"]["alpha"]["workspace"]
    assert project["custom_project_setting"] == 9


def test_cli_defaults_to_private_dry_run_plan(fleet, tmp_path, capsys):
    m = module()
    inventory, pairs, _ = fleet
    inventory_path, output = tmp_path / "inventory.json", tmp_path / "plan.json"
    import json
    inventory_path.write_text(json.dumps(inventory))
    before = pairs[0][1].read_bytes()
    assert m.main(["--inventory", str(inventory_path), "--config", "default=" + str(pairs[0][1]), "--output", str(output)]) == 0
    assert output.stat().st_mode & 0o777 == 0o600
    assert pairs[0][1].read_bytes() == before
    assert "model" not in capsys.readouterr().out


def test_activation_fsync_failure_restores_previous_target(source_repo, tmp_path, monkeypatch):
    m = module()
    repo, commit = source_repo
    root, link = tmp_path / "releases", tmp_path / "plugin"
    previous = str(tmp_path / "old-plugin")
    link.symlink_to(previous, target_is_directory=True)
    actual_sync = m._sync_directory
    attempts = []
    def fail_once(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise OSError("fixture fsync failure")
        actual_sync(path)
    monkeypatch.setattr(m, "_sync_directory", fail_once)
    with pytest.raises(OSError, match="fixture fsync"):
        m.install_release(repo, commit, release_root=root, plugin_link=link)
    assert os.readlink(link) == previous
    m.verify_release(root / commit, commit, immutable=True)
    assert m.install_release(repo, commit, release_root=root, plugin_link=link)["changed"] is True


def test_existing_writable_release_refused_and_installed_tree_has_no_write_bits(source_repo, tmp_path):
    m = module()
    repo, commit = source_repo
    root, link = tmp_path / "releases", tmp_path / "plugin"
    m.install_release(repo, commit, release_root=root, plugin_link=link)
    release = root / commit
    m.verify_release(release, commit, immutable=True)
    target = release / "hermes_swarm_protocol/__init__.py"
    os.chmod(target, 0o644)
    assert git(release, "status", "--porcelain") == ""
    with pytest.raises(ValueError, match="immutable"):
        m.install_release(repo, commit, release_root=root, plugin_link=link)


def test_valid_yaml_merge_overrides_preserve_parsed_configuration(fleet):
    m = module()
    inventory, pairs, backups = fleet
    path = pairs[0][1]
    path.write_text("defaults: &defaults\n  retries: 3\n  enabled: false\ntransport:\n  <<: *defaults\n  enabled: true\nplugins:\n  enabled: [swarm-protocol]\n  entries: {}\n")
    before = yaml.safe_load(path.read_text())
    plan = m.plan_configs(inventory, [("default", path)])
    m.apply_plan(plan, expected_sha256=m.plan_sha256(plan), backup_root=backups)
    after = yaml.safe_load(path.read_text())
    assert after["transport"] == before["transport"] == {"retries": 3, "enabled": True}
    assert after["defaults"] == before["defaults"]
