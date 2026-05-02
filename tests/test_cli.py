from __future__ import annotations

import json
from pathlib import Path

from service_cartographer.cli import main


def test_cli_json_scan_with_local_fixture(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    wrapper_dir = tmp_path / "bin"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "demo-wrapper"
    wrapper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    wrapper.chmod(0o755)

    code = main(
        [
            "scan",
            "--format",
            "json",
            "--systemd-scope",
            "off",
            "--no-cron",
            "--no-repos",
            "--repo-root",
            str(repo_root),
            "--env-root",
            str(repo_root),
            "--wrapper-dir",
            str(wrapper_dir),
        ]
    )

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    names = {item["name"] for item in data["items"]}
    assert names == {".env", "demo-wrapper"}
    assert "secret" not in json.dumps(data)


def test_cli_redacts_warnings(tmp_path: Path, capsys, monkeypatch) -> None:
    def fake_collect_repositories(_roots, *, max_depth: int, timeout: float):
        return [], [f"git failed under {Path.home()}/private TOKEN=abc123"]

    monkeypatch.setattr("service_cartographer.cli.collect_repositories", fake_collect_repositories)

    code = main(
        [
            "scan",
            "--format",
            "json",
            "--systemd-scope",
            "off",
            "--no-cron",
            "--no-env",
            "--no-wrappers",
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "abc123" not in output
    assert str(Path.home()) not in output
    assert "~/private" in output
    assert "TOKEN=<redacted>" in output


def test_cli_writes_markdown(tmp_path: Path) -> None:
    output = tmp_path / "report.md"
    code = main(
        [
            "scan",
            "--format",
            "markdown",
            "--output",
            str(output),
            "--systemd-scope",
            "off",
            "--no-cron",
            "--no-repos",
            "--no-env",
            "--wrapper-dir",
            str(tmp_path / "missing"),
        ]
    )

    assert code == 0
    assert "Keep / Retire Matrix" in output.read_text(encoding="utf-8")

