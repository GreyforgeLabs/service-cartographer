"""Command line interface for service-cartographer."""

from __future__ import annotations

import argparse
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path

from service_cartographer import __version__
from service_cartographer.classifier import classify_items
from service_cartographer.collectors import (
    collect_cron,
    collect_env_files,
    collect_repositories,
    collect_systemd,
    collect_wrappers,
)
from service_cartographer.formatters import format_report
from service_cartographer.models import InventoryItem, InventoryReport
from service_cartographer.privacy import display_host, redact_command, redact_path

DEFAULT_RETIRE_KEYWORDS = ["deprecated", "legacy", "retired", "obsolete"]
DEFAULT_KEEP_KEYWORDS: list[str] = []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="service-cartographer",
        description="Inventory local automation surfaces and produce a keep/retire matrix.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    scan = subparsers.add_parser("scan", help="scan local services and workflow artifacts")
    scan.add_argument("--format", choices=["markdown", "json", "csv"], default="markdown")
    scan.add_argument("--output", type=Path, help="write output to this path instead of stdout")
    scan.add_argument(
        "--focus",
        action="append",
        default=[],
        help="only keep items matching a token",
    )
    scan.add_argument(
        "--kind",
        action="append",
        default=[],
        help="only keep item kinds matching this name",
    )
    scan.add_argument("--stale-days", type=int, default=90)
    scan.add_argument("--timeout", type=float, default=5.0, help="seconds per external command")
    scan.add_argument(
        "--show-hostname",
        action="store_true",
        help="include the real local hostname",
    )
    scan.add_argument(
        "--absolute-paths",
        action="store_true",
        help="do not shorten home paths to ~",
    )
    scan.add_argument("--repo-root", action="append", type=Path, default=[])
    scan.add_argument("--repo-depth", type=int, default=2)
    scan.add_argument("--wrapper-dir", action="append", type=Path, default=[])
    scan.add_argument("--env-root", action="append", type=Path, default=[])
    scan.add_argument("--env-depth", type=int, default=2)
    scan.add_argument("--include-env-names", action="store_true")
    scan.add_argument(
        "--systemd-scope",
        choices=["user", "system", "off"],
        default="user",
        help="systemd scope to inspect",
    )
    scan.add_argument("--unit-dir", action="append", type=Path, default=[])
    scan.add_argument(
        "--no-systemd-discovered",
        action="store_true",
        help="only report unit files found on disk, not every systemctl-discovered unit",
    )
    scan.add_argument("--no-cron", action="store_true")
    scan.add_argument("--no-env", action="store_true")
    scan.add_argument("--no-repos", action="store_true")
    scan.add_argument("--no-wrappers", action="store_true")
    scan.add_argument("--retire-keyword", action="append", default=[])
    scan.add_argument("--keep-keyword", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["scan", *(argv or [])])
    if args.command == "scan":
        return scan(args)
    parser.error(f"unknown command: {args.command}")
    return 2


def scan(args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    warnings: list[str] = []
    items: list[InventoryItem] = []
    roots = _scan_roots(args)

    if args.systemd_scope != "off":
        systemd_items, systemd_warnings = collect_systemd(
            scope=args.systemd_scope,
            unit_dirs=_unit_dirs(args),
            include_discovered=not args.no_systemd_discovered,
            timeout=args.timeout,
        )
        items.extend(systemd_items)
        warnings.extend(systemd_warnings)

    if not args.no_cron:
        cron_items, cron_warnings = collect_cron(
            timeout=args.timeout,
            absolute_paths=args.absolute_paths,
        )
        items.extend(cron_items)
        warnings.extend(cron_warnings)

    if not args.no_wrappers:
        items.extend(collect_wrappers(_wrapper_dirs(args)))

    if not args.no_repos:
        repo_items, repo_warnings = collect_repositories(
            _repo_roots(args),
            max_depth=args.repo_depth,
            timeout=args.timeout,
        )
        items.extend(repo_items)
        warnings.extend(repo_warnings)

    if not args.no_env:
        items.extend(
            collect_env_files(
                _env_roots(args),
                max_depth=args.env_depth,
                include_names=args.include_env_names,
                warnings=warnings,
            )
        )

    items = _filter_items(items, focus=args.focus, kinds=args.kind)
    classify_items(
        items,
        stale_days=args.stale_days,
        retire_keywords=[*DEFAULT_RETIRE_KEYWORDS, *args.retire_keyword],
        keep_keywords=[*DEFAULT_KEEP_KEYWORDS, *args.keep_keyword],
        now=now,
    )
    items = [_redact_item(item, absolute_paths=args.absolute_paths) for item in items]
    items.sort(key=lambda item: (item.suggested_action, item.kind, item.name, item.path))

    report = InventoryReport(
        schema="service-cartographer.report.v1",
        generated_at=now.isoformat(),
        host=display_host(socket.gethostname(), show_hostname=args.show_hostname),
        roots=[redact_path(str(root), absolute_paths=args.absolute_paths) for root in roots],
        items=items,
        warnings=[
            redact_command(warning, absolute_paths=args.absolute_paths) for warning in warnings
        ],
    )
    rendered = format_report(report, output_format=args.format)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


def _scan_roots(args: argparse.Namespace) -> list[Path]:
    roots: list[Path] = []
    if not args.no_repos:
        roots.extend(_repo_roots(args))
    if not args.no_env:
        roots.extend(_env_roots(args))
    if not args.no_wrappers:
        roots.extend(_wrapper_dirs(args))
    if args.systemd_scope != "off":
        roots.extend(_unit_dirs(args))
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.expanduser())
        if key not in seen:
            deduped.append(root)
            seen.add(key)
    return deduped


def _repo_roots(args: argparse.Namespace) -> list[Path]:
    return args.repo_root or [Path.cwd()]


def _env_roots(args: argparse.Namespace) -> list[Path]:
    return args.env_root or _repo_roots(args)


def _wrapper_dirs(args: argparse.Namespace) -> list[Path]:
    if args.wrapper_dir:
        return args.wrapper_dir
    candidates = [Path("~/bin"), Path("~/.local/bin")]
    return [path for path in candidates if path.expanduser().is_dir()]


def _unit_dirs(args: argparse.Namespace) -> list[Path]:
    if args.unit_dir:
        return args.unit_dir
    if args.systemd_scope == "system":
        return [
            Path("/etc/systemd/system"),
            Path("/usr/lib/systemd/system"),
            Path("/lib/systemd/system"),
        ]
    return [
        Path("~/.config/systemd/user"),
        Path("~/.local/share/systemd/user"),
        Path("/etc/systemd/user"),
    ]


def _filter_items(
    items: list[InventoryItem],
    *,
    focus: list[str],
    kinds: list[str],
) -> list[InventoryItem]:
    focus_terms = [term.lower() for term in focus]
    kind_terms = {term.lower() for term in kinds}
    filtered: list[InventoryItem] = []
    for item in items:
        if kind_terms and item.kind.lower() not in kind_terms:
            continue
        if focus_terms and not any(term in item.searchable_text() for term in focus_terms):
            continue
        filtered.append(item)
    return filtered


def _redact_item(item: InventoryItem, *, absolute_paths: bool) -> InventoryItem:
    metadata = {}
    for key, value in item.metadata.items():
        if key == "command_preview":
            metadata[key] = redact_command(value, absolute_paths=absolute_paths)
        elif "path" in key:
            metadata[key] = redact_path(value, absolute_paths=absolute_paths)
        elif isinstance(value, str):
            metadata[key] = redact_command(value, absolute_paths=absolute_paths)
        else:
            metadata[key] = value
    return InventoryItem(
        kind=item.kind,
        name=item.name,
        path=redact_path(item.path, absolute_paths=absolute_paths),
        status=item.status,
        active=item.active,
        enabled=item.enabled,
        last_activity=item.last_activity,
        suggested_action=item.suggested_action,
        reason=item.reason,
        metadata=metadata,
    )


if __name__ == "__main__":
    raise SystemExit(main())
