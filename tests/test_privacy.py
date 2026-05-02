from __future__ import annotations

from pathlib import Path

from service_cartographer.privacy import redact_command, redact_path


def test_redact_command_hides_common_secret_forms() -> None:
    command = (
        "TOKEN=abc123 deploy --password hunter2 --api-key=dummy-key-value "
        "-H 'Authorization: Bearer bearer-token'"
    )

    redacted = redact_command(command)

    assert "abc123" not in redacted
    assert "hunter2" not in redacted
    assert "dummy-key-value" not in redacted
    assert "bearer-token" not in redacted
    assert "TOKEN=<redacted>" in redacted
    assert "--password <redacted>" in redacted
    assert "--api-key=<redacted>" in redacted
    assert "Bearer <redacted>" in redacted


def test_redact_path_shortens_home_by_default() -> None:
    home_path = str(Path.home() / "project")

    assert redact_path(home_path, absolute_paths=False) == "~/project"
    assert redact_path(home_path, absolute_paths=True) == home_path
