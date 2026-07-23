from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PRICE_SOURCE_FUNNEL = "funnel"
PRICE_SOURCE_SEARCH_REPORT = "search_report"
PRICE_SOURCE_CSV = "csv"

PRICE_SOURCE_LABELS: dict[str, str] = {
    PRICE_SOURCE_FUNNEL: "воронка WB",
    PRICE_SOURCE_SEARCH_REPORT: "поисковый отчёт WB",
    PRICE_SOURCE_CSV: "CSV (ручной ввод)",
}


@dataclass(frozen=True)
class ResolvedRetailPrice:
    value_rub: float
    source: str
    buyout_percent: float | None = None


def price_source_label(source: str | None) -> str:
    if not source:
        return "—"
    return PRICE_SOURCE_LABELS.get(source, source)


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _funnel_rows(funnel: dict | None) -> list[dict]:
    if not funnel:
        return []
    rows = funnel.get("days") or funnel.get("items") or []
    return [row for row in rows if isinstance(row, dict)]


def extract_funnel_avg_order_rub(funnel: dict | None) -> float | None:
    total_orders = 0
    total_sum = 0.0
    for row in _funnel_rows(funnel):
        orders = _safe_int(row.get("ordersCount"))
        order_sum = _safe_float(row.get("ordersSumRub"))
        if orders is None or order_sum is None:
            continue
        total_orders += orders
        total_sum += order_sum
    if total_orders <= 0:
        return None
    return total_sum / total_orders


def extract_funnel_buyout_percent(funnel: dict | None) -> float | None:
    weighted_buyout = 0.0
    weighted_orders = 0

    for row in _funnel_rows(funnel):
        buyout_pct = _safe_float(row.get("buyoutPercent"))
        orders = _safe_int(row.get("ordersCount"))
        if buyout_pct is not None and orders is not None and orders > 0:
            weighted_buyout += buyout_pct * orders
            weighted_orders += orders

    if weighted_orders > 0:
        return weighted_buyout / weighted_orders

    total_orders_sum = 0.0
    total_buyouts_sum = 0.0
    for row in _funnel_rows(funnel):
        orders_sum = _safe_float(row.get("ordersSumRub"))
        buyouts_sum = _safe_float(row.get("buyoutsSumRub"))
        if orders_sum is not None and buyouts_sum is not None:
            total_orders_sum += orders_sum
            total_buyouts_sum += buyouts_sum

    if total_orders_sum > 0:
        return total_buyouts_sum / total_orders_sum * 100
    return None


def extract_search_report_min_price_rub(search_report: dict | None) -> float | None:
    if not search_report:
        return None
    prices: list[float] = []
    for item in search_report.get("items") or []:
        if not isinstance(item, dict):
            continue
        price = _safe_float(item.get("min_price"))
        if price is not None:
            prices.append(price)
    if not prices:
        return None
    return min(prices)


def resolve_retail_price(
    econ: dict,
    *,
    funnel: dict | None = None,
    search_report: dict | None = None,
) -> ResolvedRetailPrice | None:
    """Single source of truth for retail price priority: funnel → search report → CSV."""
    buyout_percent = extract_funnel_buyout_percent(funnel)

    funnel_price = extract_funnel_avg_order_rub(funnel)
    if funnel_price is not None:
        return ResolvedRetailPrice(
            value_rub=funnel_price,
            source=PRICE_SOURCE_FUNNEL,
            buyout_percent=buyout_percent,
        )

    search_price = extract_search_report_min_price_rub(search_report)
    if search_price is not None:
        return ResolvedRetailPrice(
            value_rub=search_price,
            source=PRICE_SOURCE_SEARCH_REPORT,
            buyout_percent=buyout_percent,
        )

    csv_price = _safe_float(econ.get("retail_price_rub"))
    if csv_price is not None:
        return ResolvedRetailPrice(
            value_rub=csv_price,
            source=PRICE_SOURCE_CSV,
            buyout_percent=buyout_percent,
        )
    return None
