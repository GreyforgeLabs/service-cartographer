from __future__ import annotations

import sys
from pathlib import Path

import pytest

from service_cartographer import collectors
from service_cartographer.collectors import (
    CommandResult,
    collect_cron,
    collect_env_files,
    collect_repositories,
    collect_systemd,
    collect_wrappers,
    find_env_files,
    find_git_repositories,
    parse_systemctl_unit_files,
    parse_systemctl_units,
    probe_executable_version,
    resolve_approved_executable,
    run_command,
)


def test_parse_systemctl_unit_files() -> None:
    output = "alpha.service enabled enabled\nbeta.timer disabled disabled\n"
    assert parse_systemctl_unit_files(output) == {
        "alpha.service": "enabled",
        "beta.timer": "disabled",
    }


def test_parse_systemctl_units() -> None:
    output = (
        "alpha.service loaded active running Alpha Service\nbeta.timer loaded inactive dead Beta\n"
    )
    assert parse_systemctl_units(output) == {
        "alpha.service": "active",
        "beta.timer": "inactive",
    }


def test_find_git_repositories_detects_root_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)

    assert find_git_repositories([repo], max_depth=1) == [repo]


def test_find_git_repositories_supports_worktree_and_bare_layouts(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: /outside/not-read\n", encoding="utf-8")
    bare = tmp_path / "bare.git"
    (bare / "objects").mkdir(parents=True)
    (bare / "refs").mkdir()
    (bare / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    found = find_git_repositories([tmp_path], max_depth=2)

    assert worktree in found
    assert bare in found


def test_find_git_repositories_rejects_symlink_marker(tmp_path: Path) -> None:
    external = tmp_path / "external.git"
    external.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").symlink_to(external, target_is_directory=True)

    assert find_git_repositories([repo], max_depth=1) == []


def test_collect_env_files_does_not_emit_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("API_TOKEN=secret-value\nPUBLIC_NAME=demo\n", encoding="utf-8")

    [item] = collect_env_files([tmp_path], max_depth=1, include_names=True)

    assert item.metadata["var_count"] == "2"
    assert "API_TOKEN" in item.metadata["var_names"]
    assert "secret-value" not in str(item.to_dict())


def test_find_env_files_rejects_external_and_internal_symlinks(tmp_path: Path) -> None:
    external = tmp_path.parent / f"{tmp_path.name}-external.env"
    external.write_text("TOKEN=outside\n", encoding="utf-8")
    internal = tmp_path / "real.env"
    internal.write_text("TOKEN=inside\n", encoding="utf-8")
    (tmp_path / ".env.external").symlink_to(external)
    (tmp_path / ".env.internal").symlink_to(internal)

    found = find_env_files([tmp_path], max_depth=1)

    assert found == [internal]


def test_env_read_is_bounded_and_disappearance_is_recorded(tmp_path: Path, monkeypatch) -> None:
    large = tmp_path / ".env.large"
    large.write_bytes(b"FIRST=ok\n" + b"X" * (collectors.MAX_ENV_BYTES + 10))
    gone = tmp_path / ".env.gone"
    gone.write_text("GONE=yes\n", encoding="utf-8")
    healthy = tmp_path / ".env.healthy"
    healthy.write_text("HEALTHY=yes\n", encoding="utf-8")
    real_env_names = collectors._env_names

    def disappear_then_read(path, *, warnings=None):
        if path == gone and path.exists():
            path.unlink()
        return real_env_names(path, warnings=warnings)

    monkeypatch.setattr(collectors, "_env_names", disappear_then_read)
    warnings: list[str] = []

    items = collect_env_files([tmp_path], max_depth=1, include_names=True, warnings=warnings)

    by_name = {item.name: item for item in items}
    assert "HEALTHY" in by_name[".env.healthy"].metadata["var_names"]
    assert "FIRST" in by_name[".env.large"].metadata["var_names"]
    assert any("env-file-truncated" in warning for warning in warnings)
    assert any("inventory-race" in warning for warning in warnings)


def test_env_permission_error_does_not_abort_other_inventory(tmp_path: Path, monkeypatch) -> None:
    denied = tmp_path / ".env.denied"
    denied.write_text("DENIED=yes\n", encoding="utf-8")
    healthy = tmp_path / ".env.healthy"
    healthy.write_text("HEALTHY=yes\n", encoding="utf-8")
    real_open = collectors.os.open

    def deny_one(path, flags, *args, **kwargs):
        if Path(path) == denied:
            raise PermissionError(13, "permission denied", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(collectors.os, "open", deny_one)
    warnings: list[str] = []

    items = collect_env_files([tmp_path], max_depth=1, include_names=True, warnings=warnings)

    assert any(item.name == ".env.healthy" for item in items)
    assert any("inventory-error" in warning and ".env.denied" in warning for warning in warnings)


def test_collect_wrappers_records_executables(tmp_path: Path) -> None:
    wrapper = tmp_path / "my-tool"
    wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)
    ignored = tmp_path / "notes.txt"
    ignored.write_text("not executable\n", encoding="utf-8")

    items = collect_wrappers([tmp_path])

    assert [item.name for item in items] == ["my-tool"]
    assert items[0].metadata["shebang"] == "#!/usr/bin/env bash"


@pytest.mark.parametrize("name", ["systemctl", "crontab", "git"])
def test_resolver_ignores_path_spoofing(tmp_path: Path, monkeypatch, name: str) -> None:
    approved_dir = tmp_path / "approved"
    attacker_dir = tmp_path / "attacker"
    approved_dir.mkdir()
    attacker_dir.mkdir()
    approved = approved_dir / name
    attacker = attacker_dir / name
    for path, marker in ((approved, "approved"), (attacker, "attacker")):
        path.write_text(f"#!/bin/sh\necho {marker}\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.setitem(collectors.APPROVED_EXECUTABLES, name, (str(approved),))
    monkeypatch.setenv("PATH", str(attacker_dir))

    selected = resolve_approved_executable(name)

    assert selected == str(approved.resolve())
    assert selected != str(attacker)


def test_resolver_skips_when_approved_executable_is_absent(monkeypatch) -> None:
    monkeypatch.setitem(
        collectors.APPROVED_EXECUTABLES,
        "git",
        ("/definitely/missing/service-cartographer/git",),
    )

    assert resolve_approved_executable("git") is None


def test_run_command_uses_minimal_environment_and_distinct_statuses(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("PRIVATE_SCANNER_VALUE", "must-not-leak")
    environment = run_command(
        [sys.executable, "-c", "import os; print(os.getenv('PRIVATE_SCANNER_VALUE', 'clean'))"],
        timeout=2,
    )
    nonzero = run_command([sys.executable, "-c", "raise SystemExit(7)"], timeout=2)
    timed_out = run_command([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.05)
    denied = tmp_path / "denied"
    denied.write_text("no shebang\n", encoding="utf-8")
    denied.chmod(0o600)
    permission = run_command([str(denied)], timeout=2)

    assert environment.stdout.strip() == "clean"
    assert nonzero.status == "nonzero" and nonzero.code == 7
    assert timed_out.status == "timeout" and timed_out.code == 124
    assert permission.status == "exec-error" and permission.code == 126


def test_external_collectors_record_executable_version(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(collectors, "resolve_approved_executable", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(
        collectors,
        "probe_executable_version",
        lambda _name, _path, *, timeout: "tool 1.2.3",
    )

    def fake_run(args, *, timeout):
        if "status" in args:
            return CommandResult(0, "", "", args[0])
        if "log" in args:
            return CommandResult(0, "2026-01-01T00:00:00Z\n", "", args[0])
        return CommandResult(0, "main\n", "", args[0])

    monkeypatch.setattr(collectors, "run_command", fake_run)

    [item], warnings = collect_repositories([repo], max_depth=1, timeout=1)

    assert warnings == []
    assert item.metadata["executable"] == "/usr/bin/tool"
    assert item.metadata["executable_version"] == "tool 1.2.3"

    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    (unit_dir / "demo.service").write_text("[Service]\n", encoding="utf-8")
    systemd_items, systemd_warnings = collect_systemd(
        scope="user",
        unit_dirs=[unit_dir],
        include_discovered=False,
        timeout=1,
    )
    assert systemd_warnings == []
    assert systemd_items[0].metadata["executable_version"] == "tool 1.2.3"

    monkeypatch.setattr(
        collectors,
        "run_command",
        lambda args, *, timeout: CommandResult(0, "* * * * * echo ok\n", "", args[0]),
    )
    cron_items, cron_warnings = collect_cron(timeout=1, absolute_paths=False)
    assert cron_warnings == []
    assert cron_items[0].metadata["executable_version"] == "tool 1.2.3"


def test_probe_executable_version_is_bounded(tmp_path: Path) -> None:
    executable = tmp_path / "tool"
    executable.write_text("#!/bin/sh\nprintf 'tool 1.2.3\\n'\n", encoding="utf-8")
    executable.chmod(0o755)

    assert probe_executable_version("tool", str(executable), timeout=1) == "tool 1.2.3"
