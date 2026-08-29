"""Read-only collectors for local workflow surfaces."""

from __future__ import annotations

import csv
import errno
import os
import re
import stat
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from service_cartographer.models import InventoryItem
from service_cartographer.privacy import redact_command, sanitize_csv_cell

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
APPROVED_EXECUTABLES = {
    "crontab": ("/usr/bin/crontab", "/bin/crontab"),
    "git": ("/usr/bin/git", "/bin/git"),
    "systemctl": ("/usr/bin/systemctl", "/bin/systemctl"),
}
VERSION_ARGUMENTS = {
    "crontab": ("--version",),
    "git": ("--version",),
    "systemctl": ("--version",),
}
SAFE_SUBPROCESS_ENV = {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"}
MAX_ENV_BYTES = 64 * 1024
MAX_ENV_LINES = 1000


@dataclass(slots=True)
class CommandResult:
    code: int
    stdout: str
    stderr: str
    executable: str = ""
    status: str = "ok"


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

    systemctl = resolve_approved_executable("systemctl")
    if scope == "off" or systemctl is None:
        if scope != "off":
            warnings.append("systemctl approved executable not found")
        return list(items.values()), warnings

    executable_version = probe_executable_version("systemctl", systemctl, timeout=timeout)
    for item in items.values():
        item.metadata.update({"executable": systemctl, "executable_version": executable_version})

    unit_file_args = [systemctl]
    unit_args = [systemctl]
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
                    metadata={
                        "scope": scope,
                        "source": "systemctl",
                        "executable": unit_file_result.executable,
                        "executable_version": executable_version,
                    },
                )
                items[name] = item
            item.metadata["executable"] = unit_file_result.executable
            item.metadata["executable_version"] = executable_version
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
                    metadata={
                        "scope": scope,
                        "source": "systemctl",
                        "executable": unit_result.executable,
                        "executable_version": executable_version,
                    },
                )
                items[name] = item
            item.metadata["executable"] = unit_result.executable
            item.metadata["executable_version"] = executable_version
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

    crontab = resolve_approved_executable("crontab")
    if crontab is None:
        return [], ["crontab approved executable not found"]

    executable_version = probe_executable_version("crontab", crontab, timeout=timeout)
    result = run_command([crontab, "-l"], timeout=timeout)
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
                metadata={
                    "schedule": schedule,
                    "command_preview": preview,
                    "executable": result.executable,
                    "executable_version": executable_version,
                },
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
    git = resolve_approved_executable("git")
    if git is None:
        return [], ["git approved executable not found"]
    executable_version = probe_executable_version("git", git, timeout=timeout)

    for repo in find_git_repositories(repo_roots, max_depth=max_depth, warnings=warnings):
        metadata: dict[str, str] = {
            "executable": git,
            "executable_version": executable_version,
        }
        branch = run_command(
            [git, "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            timeout=timeout,
        )
        if branch.code == 0:
            metadata["branch"] = branch.stdout.strip()
        status = run_command([git, "-C", str(repo), "status", "--porcelain"], timeout=timeout)
        repo_status = "unknown"
        if status.code == 0:
            dirty_lines = [line for line in status.stdout.splitlines() if line.strip()]
            repo_status = "dirty" if dirty_lines else "clean"
            metadata["dirty_count"] = str(len(dirty_lines))
        else:
            warnings.append(f"git status failed for {repo}: {status.stderr.strip()}")
        last_commit = run_command(
            [git, "-C", str(repo), "log", "-1", "--format=%cI"],
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


def find_git_repositories(
    repo_roots: Iterable[Path],
    *,
    max_depth: int,
    warnings: list[str] | None = None,
) -> list[Path]:
    repos: list[Path] = []
    seen: set[Path] = set()
    for root in repo_roots:
        try:
            expanded = root.expanduser().resolve(strict=True)
        except FileNotFoundError:
            continue
        except OSError as exc:
            _record_inventory_error(warnings, root, exc)
            continue

        def walk_error(exc: OSError, scan_root: Path = expanded) -> None:
            _record_inventory_error(warnings, Path(exc.filename or scan_root), exc)

        for dirpath, dirnames, _filenames in os.walk(expanded, onerror=walk_error):
            current = Path(dirpath)
            try:
                relative = current.relative_to(expanded)
            except ValueError:
                relative = Path()
            depth = 0 if str(relative) == "." else len(relative.parts)
            if _has_safe_git_marker(current, warnings) or _looks_like_bare_git_repo(
                current, warnings
            ):
                try:
                    resolved = current.resolve(strict=True)
                except OSError as exc:
                    _record_inventory_error(warnings, current, exc)
                    dirnames[:] = []
                    continue
                if resolved not in seen:
                    repos.append(current)
                    seen.add(resolved)
                dirnames[:] = []
                continue
            dirnames[:] = [
                name for name in dirnames if name not in SKIP_DIRS and not name.startswith(".cache")
            ]
            if depth >= max_depth:
                dirnames[:] = []
    return repos


def collect_env_files(
    env_roots: Iterable[Path],
    *,
    max_depth: int,
    include_names: bool,
    warnings: list[str] | None = None,
) -> list[InventoryItem]:
    """Find env-like files and record metadata without reading or outputting values."""

    items: list[InventoryItem] = []
    for path in find_env_files(env_roots, max_depth=max_depth, warnings=warnings):
        names = _env_names(path, warnings=warnings)
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


def find_env_files(
    env_roots: Iterable[Path],
    *,
    max_depth: int,
    warnings: list[str] | None = None,
) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for root in env_roots:
        try:
            expanded = root.expanduser().resolve(strict=True)
        except FileNotFoundError:
            continue
        except OSError as exc:
            _record_inventory_error(warnings, root, exc)
            continue

        def walk_error(exc: OSError, scan_root: Path = expanded) -> None:
            _record_inventory_error(warnings, Path(exc.filename or scan_root), exc)

        for dirpath, dirnames, filenames in os.walk(expanded, onerror=walk_error):
            current = Path(dirpath)
            relative = current.relative_to(expanded)
            depth = 0 if str(relative) == "." else len(relative.parts)
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            for filename in filenames:
                candidate = current / filename
                if not _is_env_file(candidate):
                    continue
                try:
                    metadata = candidate.lstat()
                    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                        continue
                    resolved = candidate.resolve(strict=True)
                    resolved.relative_to(expanded)
                except FileNotFoundError as exc:
                    _record_inventory_error(warnings, candidate, exc)
                    continue
                except (OSError, ValueError) as exc:
                    if isinstance(exc, OSError):
                        _record_inventory_error(warnings, candidate, exc)
                    continue
                if resolved not in seen:
                    files.append(candidate)
                    seen.add(resolved)
            if depth >= max_depth:
                dirnames[:] = []
    return files


def run_command(args: list[str], *, timeout: float) -> CommandResult:
    executable = str(args[0]) if args else ""
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=SAFE_SUBPROCESS_ENV,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            code=124, stdout="", stderr=str(exc), executable=executable, status="timeout"
        )
    except OSError as exc:
        code = 126 if exc.errno in {errno.EACCES, errno.EPERM} else 127
        return CommandResult(
            code=code, stdout="", stderr=str(exc), executable=executable, status="exec-error"
        )
    return CommandResult(
        code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        executable=executable,
        status="ok" if result.returncode == 0 else "nonzero",
    )


def resolve_approved_executable(name: str) -> str | None:
    for candidate in APPROVED_EXECUTABLES.get(name, ()):
        try:
            path = Path(candidate).resolve(strict=True)
        except OSError:
            continue
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def probe_executable_version(name: str, path: str, *, timeout: float) -> str:
    """Return a bounded version diagnostic for an approved executable."""

    args = VERSION_ARGUMENTS.get(name, ("--version",))
    result = run_command([path, *args], timeout=timeout)
    if result.status != "ok":
        return f"unavailable:{result.status}:{result.code}"
    for line in [*result.stdout.splitlines(), *result.stderr.splitlines()]:
        cleaned = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", line).split())
        if cleaned:
            return cleaned[:160]
    return "unavailable:empty"


def write_csv(rows: Iterable[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row_list = list(rows)
    fieldnames = list(row_list[0].keys()) if row_list else ["kind", "name"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            [{key: sanitize_csv_cell(value) for key, value in row.items()} for row in row_list]
        )


def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except FileNotFoundError:
        return ""


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


def _env_names(path: Path, *, warnings: list[str] | None = None) -> list[str]:
    try:
        initial = path.lstat()
        if stat.S_ISLNK(initial.st_mode) or not stat.S_ISREG(initial.st_mode):
            return []
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        _record_inventory_error(warnings, path, exc)
        return []
    except OSError as exc:
        _record_inventory_error(warnings, path, exc)
        return []

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not _same_file_identity(initial, metadata):
            return []
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            raw = handle.read(MAX_ENV_BYTES + 1)
    except OSError as exc:
        _record_inventory_error(warnings, path, exc)
        return []
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if len(raw) > MAX_ENV_BYTES and warnings is not None:
        warnings.append(f"env-file-truncated: {path}: exceeds {MAX_ENV_BYTES} bytes")
    text = raw[:MAX_ENV_BYTES].decode("utf-8", errors="ignore")
    names: list[str] = []
    for line in text.splitlines()[:MAX_ENV_LINES]:
        match = ENV_NAME_RE.match(line)
        if match:
            names.append(match.group(1))
    return sorted(set(names))


def _lstat_matches(path: Path, predicate, warnings: list[str] | None) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        _record_inventory_error(warnings, path, exc)
        return False
    return predicate(metadata.st_mode)


def _has_safe_git_marker(path: Path, warnings: list[str] | None) -> bool:
    marker = path / ".git"
    try:
        metadata = marker.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        _record_inventory_error(warnings, marker, exc)
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return False
    if stat.S_ISDIR(metadata.st_mode):
        return True
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
        return False
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(marker, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or not _same_file_identity(metadata, opened):
                return False
            return handle.read(4096).lstrip().startswith(b"gitdir:")
    except OSError as exc:
        _record_inventory_error(warnings, marker, exc)
        return False


def _looks_like_bare_git_repo(path: Path, warnings: list[str] | None = None) -> bool:
    return (
        _lstat_matches(path / "HEAD", stat.S_ISREG, warnings)
        and _lstat_matches(path / "objects", stat.S_ISDIR, warnings)
        and (
            _lstat_matches(path / "refs", stat.S_ISDIR, warnings)
            or _lstat_matches(path / "packed-refs", stat.S_ISREG, warnings)
        )
    )


def _record_inventory_error(warnings: list[str] | None, path: Path, error: OSError) -> None:
    if warnings is None:
        return
    status = "inventory-race" if error.errno == errno.ENOENT else "inventory-error"
    warnings.append(f"{status}: {path}: {error.strerror or type(error).__name__}")


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, left.st_mode) == (right.st_dev, right.st_ino, right.st_mode)
