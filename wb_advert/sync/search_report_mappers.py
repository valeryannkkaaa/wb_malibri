from __future__ import annotations

from typing import Any

_METRIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("frequency", "frequency"),
    ("median_position", "medianPosition"),
    ("avg_position", "avgPosition"),
    ("visibility", "visibility"),
    ("open_card", "openCard"),
    ("add_to_cart", "addToCart"),
    ("orders", "orders"),
    ("open_to_cart", "openToCart"),
    ("cart_to_order", "cartToOrder"),
)


def _metric_values(block: Any) -> tuple[Any, Any]:
    if not isinstance(block, dict):
        return None, None
    return block.get("current"), block.get("percentile")


def map_search_text_item(row: dict[str, Any]) -> dict[str, Any]:
    """Flatten one WB search-text row for storage (no nested current/percentile blocks)."""
    out: dict[str, Any] = {"text": row.get("text") or ""}

    week_frequency = row.get("weekFrequency")
    if week_frequency is not None:
        out["week_frequency"] = week_frequency

    for flat_key, api_key in _METRIC_FIELDS:
        current, percentile = _metric_values(row.get(api_key))
        if current is not None:
            out[flat_key] = current
        if percentile is not None:
            out[f"{flat_key}_percentile"] = percentile

    price = row.get("price")
    if isinstance(price, dict):
        if price.get("minPrice") is not None:
            out["min_price"] = price["minPrice"]
        if price.get("maxPrice") is not None:
            out["max_price"] = price["maxPrice"]

    rating = row.get("rating")
    if rating is not None:
        out["rating"] = rating

    feedback_rating = row.get("feedbackRating")
    if feedback_rating is not None:
        out["feedback_rating"] = feedback_rating

    return out


def extract_search_text_items(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        raw = data.get("items") or data.get("searchTexts") or []
    elif isinstance(data, list):
        raw = data
    else:
        raw = payload.get("items") or []
    return [item for item in raw if isinstance(item, dict)]
