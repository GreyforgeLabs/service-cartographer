from __future__ import annotations

from pathlib import Path

from service_cartographer.collectors import (
    collect_env_files,
    collect_wrappers,
    parse_systemctl_unit_files,
    parse_systemctl_units,
)


def test_parse_systemctl_unit_files() -> None:
    output = "alpha.service enabled enabled\nbeta.timer disabled disabled\n"
    assert parse_systemctl_unit_files(output) == {
        "alpha.service": "enabled",
        "beta.timer": "disabled",
    }


def test_parse_systemctl_units() -> None:
    output = (
        "alpha.service loaded active running Alpha Service\n"
        "beta.timer loaded inactive dead Beta\n"
    )
    assert parse_systemctl_units(output) == {
        "alpha.service": "active",
        "beta.timer": "inactive",
    }


def test_collect_env_files_does_not_emit_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("API_TOKEN=secret-value\nPUBLIC_NAME=demo\n", encoding="utf-8")

    [item] = collect_env_files([tmp_path], max_depth=1, include_names=True)

    assert item.metadata["var_count"] == "2"
    assert "API_TOKEN" in item.metadata["var_names"]
    assert "secret-value" not in str(item.to_dict())


def test_collect_wrappers_records_executables(tmp_path: Path) -> None:
    wrapper = tmp_path / "my-tool"
    wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)
    ignored = tmp_path / "notes.txt"
    ignored.write_text("not executable\n", encoding="utf-8")

    items = collect_wrappers([tmp_path])

    assert [item.name for item in items] == ["my-tool"]
    assert items[0].metadata["shebang"] == "#!/usr/bin/env bash"
