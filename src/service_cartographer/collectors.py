"""Read-only collectors for local workflow surfaces."""

from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from service_cartographer.models import InventoryItem
from service_cartographer.privacy import redact_command

ENV_NAME_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
SKIP_DIRS = {
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "target",
    "venv",
}
ENV_PATTERNS = {".env", ".envrc"}
ENV_SUFFIXES = {".env"}


@dataclass(slots=True)
class CommandResult:
    code: int
    stdout: str
    stderr: str


def collect_systemd(
    *,
    scope: str,
    unit_dirs: Iterable[Path],
    include_discovered: bool,
    timeout: float,
) -> tuple[list[InventoryItem], list[str]]:
    """Collect systemd unit files and systemctl state without mutating anything."""

    items: dict[str, InventoryItem] = {}
    warnings: list[str] = []

    for unit_dir in unit_dirs:
        expanded = unit_dir.expanduser()
        if not expanded.exists():
            continue
        for path in sorted(expanded.glob("*.*")):
            if path.suffix not in {".service", ".timer", ".socket", ".path"}:
                continue
            items[path.name] = InventoryItem(
                kind="systemd_unit",
                name=path.name,
                path=str(path),
                last_activity=_mtime_iso(path),
                metadata={"scope": scope, "source": "unit_file"},
            )

    if scope == "off" or shutil.which("systemctl") is None:
        return list(items.values()), warnings

    unit_file_args = ["systemctl"]
    unit_args = ["systemctl"]
    if scope == "user":
        unit_file_args.append("--user")
        unit_args.append("--user")
    unit_file_args.extend(["list-unit-files", "--no-legend", "--no-pager"])
    unit_args.extend(["list-units", "--all", "--no-legend", "--no-pager"])

    unit_file_result = run_command(unit_file_args, timeout=timeout)
    if unit_file_result.code == 0:
        for name, enabled in parse_systemctl_unit_files(unit_file_result.stdout).items():
            item = items.get(name)
            if item is None:
                if not include_discovered:
                    continue
                item = InventoryItem(
                    kind="systemd_unit",
                    name=name,
                    metadata={"scope": scope, "source": "systemctl"},
                )
                items[name] = item
            item.enabled = enabled
    elif unit_file_result.stderr.strip():
        warnings.append(f"systemctl list-unit-files failed: {unit_file_result.stderr.strip()}")

    unit_result = run_command(unit_args, timeout=timeout)
    if unit_result.code == 0:
        for name, active in parse_systemctl_units(unit_result.stdout).items():
            item = items.get(name)
            if item is None:
                if not include_discovered:
                    continue
                item = InventoryItem(
                    kind="systemd_unit",
                    name=name,
                    metadata={"scope": scope, "source": "systemctl"},
                )
                items[name] = item
            item.active = active
    elif unit_result.stderr.strip():
        warnings.append(f"systemctl list-units failed: {unit_result.stderr.strip()}")

    return sorted(items.values(), key=lambda item: (item.kind, item.name)), warnings


def parse_systemctl_unit_files(output: str) -> dict[str, str]:
    states: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "." in parts[0]:
            states[parts[0]] = parts[1]
    return states


def parse_systemctl_units(output: str) -> dict[str, str]:
    states: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split(maxsplit=4)
        if len(parts) >= 4 and "." in parts[0]:
            states[parts[0]] = parts[2]
    return states


def collect_cron(*, timeout: float, absolute_paths: bool) -> tuple[list[InventoryItem], list[str]]:
    """Collect current user's crontab entries."""

    if shutil.which("crontab") is None:
        return [], ["crontab command not found"]

    result = run_command(["crontab", "-l"], timeout=timeout)
    if result.code != 0:
        stderr = result.stderr.strip().lower()
        if "no crontab" in stderr or "no crontab for" in stderr:
            return [], []
        return [], [f"crontab -l failed: {result.stderr.strip()}"]

    items: list[InventoryItem] = []
    for index, line in enumerate(result.stdout.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or _looks_like_cron_env(stripped):
            continue
        schedule, command = _split_cron_line(stripped)
        preview = redact_command(command, absolute_paths=absolute_paths)
        if len(preview) > 160:
            preview = preview[:157] + "..."
        items.append(
            InventoryItem(
                kind="cron_job",
                name=f"user-crontab:{index}",
                status="present",
                metadata={"schedule": schedule, "command_preview": preview},
            )
        )
    return items, []


def collect_wrappers(wrapper_dirs: Iterable[Path]) -> list[InventoryItem]:
    """Collect executable files from explicit wrapper directories."""

    items: list[InventoryItem] = []
    for wrapper_dir in wrapper_dirs:
        expanded = wrapper_dir.expanduser()
        if not expanded.is_dir():
            continue
        for path in sorted(expanded.iterdir()):
            if not path.is_file() or not os.access(path, os.X_OK):
                continue
            metadata = {"size_bytes": str(path.stat().st_size)}
            shebang = _read_shebang(path)
            if shebang:
                metadata["shebang"] = shebang
            items.append(
                InventoryItem(
                    kind="wrapper",
                    name=path.name,
                    path=str(path),
                    status="executable",
                    last_activity=_mtime_iso(path),
                    metadata=metadata,
                )
            )
    return items


def collect_repositories(
    repo_roots: Iterable[Path],
    *,
    max_depth: int,
    timeout: float,
) -> tuple[list[InventoryItem], list[str]]:
    """Find Git repositories under the requested roots and collect lightweight state."""

    items: list[InventoryItem] = []
    warnings: list[str] = []
    if shutil.which("git") is None:
        return [], ["git command not found"]

    for repo in find_git_repositories(repo_roots, max_depth=max_depth):
        metadata: dict[str, str] = {}
        branch = run_command(
            ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            timeout=timeout,
        )
        if branch.code == 0:
            metadata["branch"] = branch.stdout.strip()
        status = run_command(["git", "-C", str(repo), "status", "--porcelain"], timeout=timeout)
        repo_status = "unknown"
        if status.code == 0:
            dirty_lines = [line for line in status.stdout.splitlines() if line.strip()]
            repo_status = "dirty" if dirty_lines else "clean"
            metadata["dirty_count"] = str(len(dirty_lines))
        else:
            warnings.append(f"git status failed for {repo}: {status.stderr.strip()}")
        last_commit = run_command(
            ["git", "-C", str(repo), "log", "-1", "--format=%cI"],
            timeout=timeout,
        )
        last_activity = last_commit.stdout.strip() if last_commit.code == 0 else _mtime_iso(repo)
        items.append(
            InventoryItem(
                kind="repository",
                name=repo.name,
                path=str(repo),
                status=repo_status,
                last_activity=last_activity,
                metadata=metadata,
            )
        )

    return sorted(items, key=lambda item: item.path), warnings


def find_git_repositories(repo_roots: Iterable[Path], *, max_depth: int) -> list[Path]:
    repos: list[Path] = []
    seen: set[Path] = set()
    for root in repo_roots:
        expanded = root.expanduser().resolve()
        if not expanded.exists():
            continue
        for dirpath, dirnames, _filenames in os.walk(expanded):
            current = Path(dirpath)
            try:
                relative = current.relative_to(expanded)
            except ValueError:
                relative = Path()
            depth = 0 if str(relative) == "." else len(relative.parts)
            dirnames[:] = [
                name for name in dirnames if name not in SKIP_DIRS and not name.startswith(".cache")
            ]
            if ".git" in dirnames:
                resolved = current.resolve()
                if resolved not in seen:
                    repos.append(current)
                    seen.add(resolved)
                dirnames[:] = []
                continue
            if depth >= max_depth:
                dirnames[:] = []
    return repos


def collect_env_files(
    env_roots: Iterable[Path],
    *,
    max_depth: int,
    include_names: bool,
) -> list[InventoryItem]:
    """Find env-like files and record metadata without reading or outputting values."""

    items: list[InventoryItem] = []
    for path in find_env_files(env_roots, max_depth=max_depth):
        names = _env_names(path)
        metadata = {"var_count": str(len(names))}
        if include_names and names:
            metadata["var_names"] = ",".join(names[:40])
        items.append(
            InventoryItem(
                kind="env_file",
                name=path.name,
                path=str(path),
                status="present",
                last_activity=_mtime_iso(path),
                metadata=metadata,
            )
        )
    return sorted(items, key=lambda item: item.path)


def find_env_files(env_roots: Iterable[Path], *, max_depth: int) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for root in env_roots:
        expanded = root.expanduser().resolve()
        if not expanded.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(expanded):
            current = Path(dirpath)
            relative = current.relative_to(expanded)
            depth = 0 if str(relative) == "." else len(relative.parts)
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            for filename in filenames:
                candidate = current / filename
                if _is_env_file(candidate):
                    resolved = candidate.resolve()
                    if resolved not in seen:
                        files.append(candidate)
                        seen.add(resolved)
            if depth >= max_depth:
                dirnames[:] = []
    return files


def run_command(args: list[str], *, timeout: float) -> CommandResult:
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(code=124, stdout="", stderr=str(exc))
    return CommandResult(code=result.returncode, stdout=result.stdout, stderr=result.stderr)


def write_csv(rows: Iterable[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row_list = list(rows)
    fieldnames = list(row_list[0].keys()) if row_list else ["kind", "name"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(row_list)


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def _looks_like_cron_env(line: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", line))


def _split_cron_line(line: str) -> tuple[str, str]:
    parts = line.split()
    if not parts:
        return "", ""
    if parts[0].startswith("@"):
        return parts[0], " ".join(parts[1:])
    if len(parts) >= 6:
        return " ".join(parts[:5]), " ".join(parts[5:])
    return "unknown", line


def _read_shebang(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            first = handle.readline().strip()
    except OSError:
        return ""
    return first if first.startswith("#!") else ""


def _is_env_file(path: Path) -> bool:
    name = path.name
    if name in ENV_PATTERNS:
        return True
    if name.startswith(".env."):
        return True
    return any(name.endswith(suffix) for suffix in ENV_SUFFIXES)


def _env_names(path: Path) -> list[str]:
    names: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                match = ENV_NAME_RE.match(line)
                if match:
                    names.append(match.group(1))
    except OSError:
        return []
    return sorted(set(names))
