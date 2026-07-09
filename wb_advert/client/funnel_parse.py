from __future__ import annotations

from typing import Any


def extract_avg_prices(data: Any) -> dict[int, float]:
    """Parse sales-funnel v3 response → nm_id → avgPrice (selected period)."""
    if not isinstance(data, dict):
        return {}
    products = (data.get("data") or {}).get("products") or []
    out: dict[int, float] = {}
    for item in products:
        if not isinstance(item, dict):
            continue
        product = item.get("product") or {}
        nm_id = product.get("nmId") or product.get("nm_id")
        if not nm_id:
            continue
        stat = item.get("statistic") or {}
        selected = stat.get("selected") or {}
        avg = selected.get("avgPrice")
        if avg is None:
            past = stat.get("past") or {}
            avg = past.get("avgPrice")
        if avg is not None and float(avg) > 0:
            out[int(nm_id)] = float(avg)
    return out
