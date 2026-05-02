"""Output scrubbing helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([a-z0-9_]*(?:token|secret|password|passwd|api[_-]?key|private[_-]?key)"
    r"[a-z0-9_]*)=([^\s;&|]+)"
)


def redact_path(value: str, *, absolute_paths: bool = False) -> str:
    """Return a path with the current home directory shortened unless disabled."""

    if not value:
        return value
    if absolute_paths:
        return value

    home = str(Path.home())
    if value == home:
        return "~"
    if value.startswith(home + os.sep):
        return "~" + value[len(home) :]
    return value


def redact_command(value: str, *, absolute_paths: bool = False) -> str:
    """Redact home paths and obvious inline secret assignments from command text."""

    redacted = redact_path(value, absolute_paths=absolute_paths)
    return SECRET_ASSIGNMENT_RE.sub(r"\1=<redacted>", redacted)


def display_host(hostname: str, *, show_hostname: bool = False) -> str:
    """Hide the local hostname unless the caller explicitly requests it."""

    return hostname if show_hostname else "redacted"

