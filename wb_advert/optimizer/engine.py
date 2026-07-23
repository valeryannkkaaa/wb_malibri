from __future__ import annotations

from datetime import datetime, timezone

from wb_advert.optimizer.rules import (
    CAMPAIGN_CR_MIN_CLICKS,
    CPC_LIMIT_INSUFFICIENT_DATA,
    calc_max_cpc_kopecks,
    keyword_campaign_totals,
    resolve_cr_fact,
    suggest_keyword_action,
)
from wb_advert.schemas.optimizer import DecisionSuggestion, OptimizeResult
from wb_advert.storage.keywords_store import load_keywords
from wb_advert.storage.pilot_store import get_product_detail, load_config, load_unit_economics, pilot_data_dir


def optimize_product(advert_id: int, *, mode: str | None = None) -> OptimizeResult:
    data_dir = pilot_data_dir()
    config = load_config(data_dir)
    optimizer_mode = mode or config.get("optimizer_mode", "suggest-only")

    product = get_product_detail(advert_id, data_dir)
    if not product:
        return OptimizeResult(
            advert_id=advert_id,
            nm_id="",
            mode=optimizer_mode,
            decided_at=datetime.now(timezone.utc),
            skipped_reason="NOT_FOUND",
        )

    nm_id = product["nm_id"]
    primary = (product.get("primary_keyword") or "").strip().lower()
    kw_data = load_keywords(advert_id, data_dir)
    keywords = kw_data.get("keywords") if kw_data else []

    alerts: list[str] = []
    suggestions: list[DecisionSuggestion] = []

    econ_row = load_unit_economics(data_dir).get(nm_id, {})
    retail = econ_row.get("retail_price_rub")
    max_drr = float(econ_row.get("max_drr_pct") or 15)
    if not retail:
        alerts.append("unit_economics не заполнена — CPC-лимиты не считаются")

    if not keywords:
        alerts.append("Нет keywords JSON — запустите backfill_keywords")

    campaign_clicks, campaign_orders = keyword_campaign_totals(keywords)
    if retail and campaign_clicks < CAMPAIGN_CR_MIN_CLICKS:
        alerts.append(CPC_LIMIT_INSUFFICIENT_DATA)

    for kw in keywords:
        is_primary = (kw.get("keyword") or "").strip().lower() == primary if primary else False
        max_cpc: int | None = None
        if retail:
            cr_fact = resolve_cr_fact(
                int(kw.get("clicks") or 0),
                int(kw.get("orders") or 0),
                campaign_clicks,
                campaign_orders,
            )
            if cr_fact is not None:
                max_cpc = calc_max_cpc_kopecks(float(retail), max_drr, cr_fact)
        suggestion = suggest_keyword_action(
            kw,
            is_primary=is_primary,
            max_cpc_kopecks=max_cpc,
        )
        if suggestion and suggestion.action != "skip":
            suggestions.append(suggestion)

    return OptimizeResult(
        advert_id=advert_id,
        nm_id=nm_id,
        mode=optimizer_mode,
        decided_at=datetime.now(timezone.utc),
        suggestions=suggestions,
        alerts=alerts,
    )


def optimize_all() -> list[OptimizeResult]:
    from wb_advert.storage.pilot_store import build_product_rows

    return [optimize_product(row["advert_id"]) for row in build_product_rows()]
