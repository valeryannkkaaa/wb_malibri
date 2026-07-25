from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def rotate_sort_key(
    last_attempt_at: str | None,
    *,
    canonical_synced_at: str | None = None,
) -> str:
    """Sort key for rotation: last attempt first, else last successful snapshot."""
    if last_attempt_at:
        return str(last_attempt_at)
    return canonical_synced_at or ""


def pick_rotate_batch(
    entities: list[T],
    *,
    entity_id: Callable[[T], int],
    report_by_id: dict[int, dict],
    canonical_synced_at: Callable[[int], str | None],
    limit: int = 1,
) -> list[T]:
    """Pick entities least recently attempted (issue #9 rotation model)."""

    def sort_key(entity: T) -> str:
        eid = entity_id(entity)
        row = report_by_id.get(eid)
        attempt = (row or {}).get("last_attempt_at")
        canonical = canonical_synced_at(eid)
        return rotate_sort_key(attempt, canonical_synced_at=canonical)

    return sorted(entities, key=sort_key)[: max(limit, 1)]
