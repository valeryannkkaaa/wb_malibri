"""Target grade boundaries for position vs goal checks (UI only, not optimizer)."""

from __future__ import annotations

# Upper inclusive position bound per target_grade (schemas + GRADE_RU).
TARGET_GRADE_MAX_POSITION: dict[str, int] = {
    "top_1_3": 3,
    "pos_4_10": 10,
    "pos_10_20": 20,
}


def position_meets_target(
    target_grade: str | None,
    parsed_position: int | float | str | None,
) -> bool | None:
    """Return True if organic position meets target grade, False if worse, None if unknown."""
    if target_grade not in TARGET_GRADE_MAX_POSITION:
        return None
    if parsed_position is None:
        return None
    try:
        pos = int(parsed_position)
    except (TypeError, ValueError):
        return None
    return pos <= TARGET_GRADE_MAX_POSITION[target_grade]
