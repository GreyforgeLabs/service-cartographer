"""Core data structures for service-cartographer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class InventoryItem:
    """One discovered automation or workflow artifact."""

    kind: str
    name: str
    path: str = ""
    status: str = ""
    active: str = ""
    enabled: str = ""
    last_activity: str = ""
    suggested_action: str = "review"
    reason: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def searchable_text(self) -> str:
        parts = [
            self.kind,
            self.name,
            self.path,
            self.status,
            self.active,
            self.enabled,
            self.reason,
            " ".join(f"{key}={value}" for key, value in self.metadata.items()),
        ]
        return " ".join(part for part in parts if part).lower()

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "status": self.status,
            "active": self.active,
            "enabled": self.enabled,
            "last_activity": self.last_activity,
            "suggested_action": self.suggested_action,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class InventoryReport:
    """A complete scan result."""

    schema: str
    generated_at: str
    host: str
    roots: list[str]
    items: list[InventoryItem]
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {"total": len(self.items)}
        for item in self.items:
            counts[item.kind] = counts.get(item.kind, 0) + 1
            action_key = f"action:{item.suggested_action}"
            counts[action_key] = counts.get(action_key, 0) + 1
        return counts

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "generated_at": self.generated_at,
            "host": self.host,
            "roots": list(self.roots),
            "summary": self.summary(),
            "warnings": list(self.warnings),
            "items": [item.to_dict() for item in self.items],
        }
