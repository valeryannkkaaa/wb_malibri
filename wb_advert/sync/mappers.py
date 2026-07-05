from __future__ import annotations

from typing import Any

from wb_advert.constants import MIN_SHOWS_FOR_MANAGED
from wb_advert.schemas.sync import KeywordMetrics
from wb_advert.sync.metrics import calc_ctr, calc_cpc_kopecks, cpc_api_to_kopecks


def map_normquery_stats(
    stats_payload: dict[str, Any],
    bids_payload: dict[str, Any] | None = None,
) -> list[KeywordMetrics]:
    bid_by_query: dict[str, int] = {}
    if bids_payload:
        for b in bids_payload.get("bids") or []:
            q = (b.get("norm_query") or "").lower()
            if q and b.get("bid"):
                bid_by_query[q] = int(b["bid"])

    rows: list[KeywordMetrics] = []
    blocks = stats_payload.get("stats") if isinstance(stats_payload, dict) else []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        inner = block.get("stats") or block.get("stat") or []
        if isinstance(inner, dict):
            inner = [inner]
        for item in inner:
            if not isinstance(item, dict):
                continue
            keyword = item.get("norm_query") or item.get("normQuery") or ""
            views = int(item.get("views") or 0)
            clicks = int(item.get("clicks") or 0)
            orders = int(item.get("orders") or 0)
            cpc_rub = float(item.get("cpc") or 0)
            spend_k = cpc_api_to_kopecks(cpc_rub) * clicks if clicks and cpc_rub else 0
            ctr = item.get("ctr")
            if ctr is None:
                ctr = calc_ctr(clicks, views)
            elif isinstance(ctr, (int, float)) and ctr > 1:
                ctr = float(ctr) / 100 if ctr > 100 else float(ctr)

            status = "managed" if views >= MIN_SHOWS_FOR_MANAGED else "pending_100_shows"
            rows.append(
                KeywordMetrics(
                    keyword=keyword,
                    shows=views,
                    clicks=clicks,
                    spend_kopecks=spend_k,
                    orders=orders,
                    ctr_calculated=float(ctr) if ctr is not None else None,
                    cpc_calculated_kopecks=calc_cpc_kopecks(spend_k, clicks)
                    or (cpc_api_to_kopecks(cpc_rub) if cpc_rub else None),
                    current_bid_kopecks=bid_by_query.get(keyword.lower()),
                    status=status,
                )
            )
    return rows
