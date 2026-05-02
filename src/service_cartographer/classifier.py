"""Conservative keep/review/retire hints for discovered artifacts."""

from __future__ import annotations

from datetime import UTC, datetime

from service_cartographer.models import InventoryItem


def classify_items(
    items: list[InventoryItem],
    *,
    stale_days: int,
    retire_keywords: list[str],
    keep_keywords: list[str],
    now: datetime | None = None,
) -> list[InventoryItem]:
    """Annotate inventory items with conservative action hints."""

    current = now or datetime.now(UTC)
    retire_terms = [term.lower() for term in retire_keywords]
    keep_terms = [term.lower() for term in keep_keywords]

    for item in items:
        text = item.searchable_text()
        if any(term in text for term in keep_terms):
            item.suggested_action = "keep_candidate"
            item.reason = "matched keep keyword"
            continue
        if any(term in text for term in retire_terms):
            item.suggested_action = "retire_candidate"
            item.reason = "matched retire keyword"
            continue

        enabled = item.enabled.lower()
        active = item.active.lower()
        status = item.status.lower()
        age_days = _age_days(item.last_activity, current)

        if active in {"active", "running"} or enabled in {"enabled", "static", "generated"}:
            item.suggested_action = "keep_candidate"
            item.reason = "active or enabled"
        elif item.kind == "cron_job":
            item.suggested_action = "review"
            item.reason = "scheduled command needs owner decision"
        elif item.kind == "repository" and status == "dirty":
            item.suggested_action = "keep_candidate"
            item.reason = "repository has local changes"
        elif age_days is not None and age_days >= stale_days:
            if item.kind in {"systemd_unit", "repository", "wrapper", "env_file"}:
                item.suggested_action = "retire_candidate"
                item.reason = f"no recent activity for {age_days} days"
            else:
                item.suggested_action = "review"
                item.reason = f"stale for {age_days} days"
        else:
            item.suggested_action = "review"
            item.reason = "needs owner decision"

    return items


def _age_days(value: str, now: datetime) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0, (now - parsed).days)
