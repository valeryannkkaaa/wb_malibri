from __future__ import annotations

from datetime import datetime, timezone

from wb_advert.constants import PENDING_NM_PREFIX
from wb_advert.import_data.csv_loader import load_pilot_skus
from wb_advert.optimizer.rules import (
    CPC_PRIOR_ESTIMATE,
    calc_keyword_max_cpc_kopecks,
    format_missing_bid_campaign_alert,
    format_prior_estimate_campaign_alert,
    keyword_campaign_totals,
    suggest_keyword_action,
)
from wb_advert.schemas.optimizer import DecisionSuggestion, OptimizeResult
from wb_advert.storage.keywords_store import load_keywords
from wb_advert.storage.pilot_store import (
    find_pilot_sku_by_advert,
    get_pilot_global_cr_prior,
    load_config,
    load_unit_economics,
    pilot_data_dir,
    primary_keyword_for_advert,
    resolve_product_retail_price,
)


def optimize_product(
    advert_id: int,
    *,
    mode: str | None = None,
    global_cr_prior: float | None = None,
) -> OptimizeResult:
    data_dir = pilot_data_dir()
    config = load_config(data_dir)
    optimizer_mode = mode or config.get("optimizer_mode", "suggest-only")

    sku = find_pilot_sku_by_advert(advert_id, data_dir)
    if not sku:
        return OptimizeResult(
            advert_id=advert_id,
            nm_id="",
            mode=optimizer_mode,
            decided_at=datetime.now(timezone.utc),
            skipped_reason="NOT_FOUND",
        )

    nm_id = sku.nm_id
    primary = (primary_keyword_for_advert(advert_id, data_dir) or "").strip().lower()
    kw_data = load_keywords(advert_id, data_dir)
    keywords = (kw_data.get("keywords") if kw_data else None) or []

    alerts: list[str] = []
    suggestions: list[DecisionSuggestion] = []

    econ_row = load_unit_economics(data_dir).get(nm_id, {})
    resolved_price = resolve_product_retail_price(nm_id, econ_row, data_dir)
    if not resolved_price:
        alerts.append("unit_economics не заполнена — CPC-лимиты не считаются")

    if not keywords:
        alerts.append("Нет keywords JSON — запустите backfill_keywords")

    campaign_totals = keyword_campaign_totals(keywords)
    if global_cr_prior is None:
        global_cr_prior = get_pilot_global_cr_prior(data_dir)

    prior_estimate_count = 0
    missing_bid_count = 0
    for kw in keywords:
        is_primary = (kw.get("keyword") or "").strip().lower() == primary if primary else False
        max_cpc, limit_alert = calc_keyword_max_cpc_kopecks(
            econ_row,
            kw,
            campaign_totals,
            global_cr_prior,
            resolved_price=resolved_price,
        )
        if limit_alert == CPC_PRIOR_ESTIMATE:
            prior_estimate_count += 1
        if not kw.get("current_bid_kopecks"):
            missing_bid_count += 1
        suggestion = suggest_keyword_action(
            kw,
            is_primary=is_primary,
            max_cpc_kopecks=max_cpc,
            cpc_prior_estimate=limit_alert == CPC_PRIOR_ESTIMATE,
        )
        if suggestion and suggestion.action != "skip":
            suggestions.append(suggestion)

    if prior_estimate_count:
        alerts.append(format_prior_estimate_campaign_alert(prior_estimate_count, len(keywords)))
    if missing_bid_count:
        alerts.append(format_missing_bid_campaign_alert(missing_bid_count, len(keywords)))

    return OptimizeResult(
        advert_id=advert_id,
        nm_id=nm_id,
        mode=optimizer_mode,
        decided_at=datetime.now(timezone.utc),
        suggestions=suggestions,
        alerts=alerts,
    )


def optimize_all() -> list[OptimizeResult]:
    data_dir = pilot_data_dir()
    global_cr_prior = get_pilot_global_cr_prior(data_dir)
    advert_ids = [
        sku.wb_campaign_search
        for sku in load_pilot_skus(data_dir / "pilot_skus.csv")
        if not (sku.nm_id or "").startswith(PENDING_NM_PREFIX)
    ]
    return [
        optimize_product(advert_id, global_cr_prior=global_cr_prior)
        for advert_id in sorted(advert_ids)
    ]
