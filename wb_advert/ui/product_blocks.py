"""Product page data blocks (competitors, search report, funnel)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from wb_advert.storage.competitors_store import (
    build_competitors_display,
    load_latest_competitors_snapshot,
)
from wb_advert.storage.funnel_store import load_funnel
from wb_advert.storage.pilot_store import pilot_data_dir
from wb_advert.storage.search_report_store import load_search_report


def percentile_class(value: object) -> str:
    """Map percentile to existing dashboard classes."""
    if value is None or value == "":
        return "muted"
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return "muted"
    if pct >= 70:
        return "pos-ok"
    if pct <= 30:
        return "warn"
    return ""


def funnel_period_summary(rows: list[dict], days: int) -> dict | None:
    """Aggregate funnel metrics for the last N calendar days (or fewer if history is shorter)."""
    dated_rows: list[tuple[date, dict]] = []
    for row in rows:
        dt_raw = row.get("dt")
        if not dt_raw:
            continue
        try:
            dated_rows.append((date.fromisoformat(str(dt_raw)), row))
        except ValueError:
            continue
    if not dated_rows:
        return None

    dated_rows.sort(key=lambda item: item[0])
    last_dt = dated_rows[-1][0]
    cutoff = last_dt - timedelta(days=days - 1)
    window = [row for row_dt, row in dated_rows if row_dt >= cutoff]
    if not window:
        return None

    orders = sum(int(row.get("orders_count") or 0) for row in window)
    revenue = sum(float(row.get("orders_sum_rub") or 0) for row in window)
    avg_check = round(revenue / orders, 2) if orders else None

    def _weighted_avg_by_orders(field: str) -> float | None:
        weighted_sum = 0.0
        weighted_orders = 0
        for row in window:
            value = row.get(field)
            row_orders = int(row.get("orders_count") or 0)
            if value is None or row_orders <= 0:
                continue
            weighted_sum += float(value) * row_orders
            weighted_orders += row_orders
        if weighted_orders <= 0:
            return None
        return round(weighted_sum / weighted_orders, 1)

    def _weighted_buyout_percent() -> float | None:
        weighted_sum = 0.0
        weighted_orders = 0
        for row in window:
            buyout_pct = row.get("buyout_percent")
            row_orders = int(row.get("orders_count") or 0)
            if buyout_pct is not None and row_orders > 0:
                weighted_sum += float(buyout_pct) * row_orders
                weighted_orders += row_orders
        if weighted_orders > 0:
            return round(weighted_sum / weighted_orders, 1)

        total_orders_sum = 0.0
        total_buyouts_sum = 0.0
        for row in window:
            orders_sum = row.get("orders_sum_rub")
            buyouts_sum = row.get("buyouts_sum_rub")
            if orders_sum is not None and buyouts_sum is not None:
                total_orders_sum += float(orders_sum)
                total_buyouts_sum += float(buyouts_sum)
        if total_orders_sum > 0:
            return round(total_buyouts_sum / total_orders_sum * 100, 1)
        return None

    return {
        "days": len(window),
        "orders": orders,
        "revenue": round(revenue, 2),
        "avg_check": avg_check,
        "add_to_cart_conversion": _weighted_avg_by_orders("add_to_cart_conversion"),
        "cart_to_order_conversion": _weighted_avg_by_orders("cart_to_order_conversion"),
        "buyout_percent": _weighted_buyout_percent(),
    }


def build_funnel_display(nm_id: int | str, data_dir: Path | None = None) -> dict:
    data = load_funnel(nm_id, data_dir)
    rows = (data or {}).get("rows") or []
    if not rows:
        return {"available": False}

    sorted_rows = sorted(rows, key=lambda row: str(row.get("dt") or ""), reverse=True)
    return {
        "available": True,
        "synced_at": data.get("synced_at") if data else None,
        "summary_7d": funnel_period_summary(rows, 7),
        "summary_30d": funnel_period_summary(rows, 30),
        "recent_rows": sorted_rows[:14],
    }


def build_search_report_display(nm_id: int | str, data_dir: Path | None = None) -> dict:
    data = load_search_report(int(nm_id), data_dir)
    items = (data or {}).get("items") or []
    if not items:
        return {"available": False}

    top_items = sorted(items, key=lambda item: -(item.get("week_frequency") or 0))[:20]
    return {
        "available": True,
        "synced_at": data.get("synced_at") if data else None,
        "keywords": top_items,
    }


def build_product_extra_blocks(nm_id: int | str, data_dir: Path | None = None) -> dict:
    root = data_dir or pilot_data_dir()
    snapshot = load_latest_competitors_snapshot(nm_id, root)
    return {
        "competitors": build_competitors_display(snapshot),
        "search_report": build_search_report_display(nm_id, root),
        "funnel": build_funnel_display(nm_id, root),
    }
