"""Report formatters."""

from __future__ import annotations

import csv
import io
import json

from service_cartographer.models import InventoryReport


def format_report(report: InventoryReport, *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    if output_format == "markdown":
        return markdown_report(report)
    if output_format == "csv":
        return csv_report(report)
    msg = f"unsupported format: {output_format}"
    raise ValueError(msg)


def markdown_report(report: InventoryReport) -> str:
    lines = [
        "# Service Cartographer Report",
        "",
        f"- Generated: `{report.generated_at}`",
        f"- Host: `{report.host}`",
        f"- Items: `{len(report.items)}`",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
    ]
    for key, value in sorted(report.summary().items()):
        lines.append(f"| `{_escape(key)}` | {value} |")
    if report.warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in report.warnings:
            lines.append(f"- {_escape(warning)}")
    lines.extend(
        [
            "",
            "## Keep / Retire Matrix",
            "",
            "| Action | Kind | Name | Status | Last activity | Path | Reason |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for item in report.items:
        status = ", ".join(
            part
            for part in [
                f"status={item.status}" if item.status else "",
                f"active={item.active}" if item.active else "",
                f"enabled={item.enabled}" if item.enabled else "",
            ]
            if part
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape(item.suggested_action),
                    _escape(item.kind),
                    _escape(item.name),
                    _escape(status),
                    _escape(item.last_activity),
                    _escape(item.path),
                    _escape(item.reason),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def csv_report(report: InventoryReport) -> str:
    output = io.StringIO()
    fields = [
        "suggested_action",
        "kind",
        "name",
        "path",
        "status",
        "active",
        "enabled",
        "last_activity",
        "reason",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in report.items:
        row = {field: getattr(item, field) for field in fields}
        writer.writerow(row)
    return output.getvalue()


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|")

