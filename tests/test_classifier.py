from __future__ import annotations

from datetime import UTC, datetime

from service_cartographer.classifier import classify_items
from service_cartographer.models import InventoryItem


def test_active_unit_is_keep_candidate() -> None:
    item = InventoryItem(kind="systemd_unit", name="demo.service", active="active")
    classify_items(
        [item],
        stale_days=90,
        retire_keywords=[],
        keep_keywords=[],
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert item.suggested_action == "keep_candidate"


def test_old_source_timestamp_never_implies_retirement() -> None:
    item = InventoryItem(
        kind="wrapper",
        name="old-tool",
        last_activity="2025-01-01T00:00:00+00:00",
    )
    classify_items(
        [item],
        stale_days=90,
        retire_keywords=[],
        keep_keywords=[],
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert item.suggested_action == "review"
    assert "verify actual use" in item.reason


def test_active_legacy_unit_is_kept_even_with_retire_keyword() -> None:
    item = InventoryItem(kind="systemd_unit", name="legacy.service", active="active")
    classify_items(
        [item],
        stale_days=90,
        retire_keywords=["legacy"],
        keep_keywords=[],
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert item.suggested_action == "keep_candidate"


def test_operator_retire_keyword_marks_inactive_item() -> None:
    item = InventoryItem(kind="wrapper", name="retire-this", status="executable")
    classify_items(
        [item],
        stale_days=90,
        retire_keywords=["retire-this"],
        keep_keywords=[],
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert item.suggested_action == "retire_candidate"
