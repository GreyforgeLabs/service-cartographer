from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime

import pytest

from service_cartographer.collectors import write_csv
from service_cartographer.formatters import format_report
from service_cartographer.models import InventoryItem, InventoryReport
from service_cartographer.privacy import sanitize_csv_cell


@pytest.mark.parametrize(
    "value",
    ["=CMD()", "+1", "-1", "@SUM(A1:A2)", "\t=CMD()", "\r@SUM()", "  +1"],
)
def test_csv_cell_sanitizer_neutralizes_formula_prefixes(value: str) -> None:
    assert sanitize_csv_cell(value) == "'" + value


def test_csv_cell_sanitizer_preserves_ordinary_values() -> None:
    assert sanitize_csv_cell("ordinary") == "ordinary"


@pytest.mark.parametrize(
    "field",
    [
        "suggested_action",
        "kind",
        "name",
        "path",
        "status",
        "active",
        "enabled",
        "last_activity",
        "reason",
    ],
)
def test_csv_report_applies_policy_to_every_string_column(field: str) -> None:
    values = {
        "suggested_action": "review",
        "kind": "wrapper",
        "name": "demo",
        "path": "/tmp/demo",
        "status": "present",
        "active": "",
        "enabled": "",
        "last_activity": "2026-01-01T00:00:00Z",
        "reason": "",
    }
    values[field] = " \t=CMD()"
    item = InventoryItem(**values)
    report = InventoryReport(
        schema="service-cartographer.report.v1",
        generated_at=datetime.now(UTC).isoformat(),
        host="redacted",
        roots=[],
        items=[item],
    )

    [row] = list(csv.DictReader(io.StringIO(format_report(report, output_format="csv"))))

    assert row[field] == "' \t=CMD()"


def test_json_remains_exact_machine_format() -> None:
    item = InventoryItem(kind="wrapper", name="=CMD()", path="\t@SUM()")
    report = InventoryReport(
        schema="service-cartographer.report.v1",
        generated_at="now",
        host="redacted",
        roots=[],
        items=[item],
    )

    rendered = json.loads(format_report(report, output_format="json"))

    assert rendered["items"][0]["name"] == "=CMD()"
    assert rendered["items"][0]["path"] == "\t@SUM()"


def test_low_level_csv_writer_uses_the_same_policy(tmp_path) -> None:
    destination = tmp_path / "report.csv"

    write_csv([{"kind": "=CMD()", "name": "ordinary"}], destination)

    [row] = list(csv.DictReader(destination.read_text(encoding="utf-8").splitlines()))
    assert row == {"kind": "'=CMD()", "name": "ordinary"}
