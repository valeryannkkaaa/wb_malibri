from __future__ import annotations

from wb_advert.constants import MIN_SHOWS_FOR_MANAGED
from wb_advert.schemas.optimizer import DecisionSuggestion

KEYWORD_CR_MIN_CLICKS = 30
CAMPAIGN_CR_MIN_CLICKS = 100
# Prior strength in clicks: equivalent sample size blended into CR estimate.
CR_PRIOR_STRENGTH_CLICKS = 50
# Cap keyword CR at this multiple of campaign CR to limit attribution noise (orders > clicks).
CR_WINSOR_CAMPAIGN_MULTIPLIER = 2.0
CPC_LIMIT_INSUFFICIENT_DATA = "недостаточно данных для лимита CPC"
CPC_PRIOR_ESTIMATE = "потолок оценён по приору, мало собственных данных"


def keyword_campaign_totals(keywords: list[dict] | None) -> tuple[int, int]:
    clicks = 0
    orders = 0
    for kw in keywords or []:
        clicks += int(kw.get("clicks") or 0)
        orders += int(kw.get("orders") or 0)
    return clicks, orders


def smooth_cr(
    orders: int,
    clicks: int,
    prior_cr: float,
    *,
    prior_strength: int = CR_PRIOR_STRENGTH_CLICKS,
) -> float:
    return (orders + prior_strength * prior_cr) / (clicks + prior_strength)


def resolve_cr_smoothed(
    kw_clicks: int,
    kw_orders: int,
    campaign_clicks: int,
    campaign_orders: int,
    global_cr_prior: float,
) -> float:
    campaign_cr = smooth_cr(campaign_orders, campaign_clicks, global_cr_prior)
    keyword_cr = smooth_cr(kw_orders, kw_clicks, campaign_cr)
    return min(keyword_cr, CR_WINSOR_CAMPAIGN_MULTIPLIER * campaign_cr)


def prior_estimate_alert_reason(kw_clicks: int) -> str | None:
    if kw_clicks < KEYWORD_CR_MIN_CLICKS:
        return CPC_PRIOR_ESTIMATE
    return None


def calc_max_cpc_kopecks(
    retail_price_rub: float,
    max_drr_pct: float,
    cr_fact: float,
) -> int | None:
    if retail_price_rub <= 0 or max_drr_pct <= 0 or cr_fact <= 0:
        return None
    return int(retail_price_rub * (max_drr_pct / 100) * cr_fact * 100)


def calc_keyword_max_cpc_kopecks(
    econ: dict,
    kw: dict,
    campaign_totals: tuple[int, int],
    global_cr_prior: float | None,
) -> tuple[int | None, str | None]:
    retail = econ.get("retail_price_rub")
    if not retail:
        return None, None

    if global_cr_prior is None:
        return None, CPC_LIMIT_INSUFFICIENT_DATA

    kw_clicks = int(kw.get("clicks") or 0)
    kw_orders = int(kw.get("orders") or 0)
    campaign_clicks, campaign_orders = campaign_totals

    cr_fact = resolve_cr_smoothed(
        kw_clicks,
        kw_orders,
        campaign_clicks,
        campaign_orders,
        global_cr_prior,
    )
    alert = prior_estimate_alert_reason(kw_clicks)

    max_drr = float(econ.get("max_drr_pct") or 15)
    return calc_max_cpc_kopecks(float(retail), max_drr, cr_fact), alert


def suggest_keyword_action(
    kw: dict,
    *,
    is_primary: bool,
    max_cpc_kopecks: int | None,
    max_bid_kopecks: int = 150_000,
) -> DecisionSuggestion | None:
    keyword = kw.get("keyword") or ""
    shows = int(kw.get("shows") or 0)
    clicks = int(kw.get("clicks") or 0)
    orders = int(kw.get("orders") or 0)
    spend = int(kw.get("spend_kopecks") or 0)
    ctr = kw.get("ctr_calculated")
    cpc = kw.get("cpc_calculated_kopecks")
    status = kw.get("status") or "pending_100_shows"
    bid = kw.get("current_bid_kopecks")

    base = {
        "shows": shows,
        "clicks": clicks,
        "orders": orders,
        "ctr": ctr,
        "cpc_kopecks": cpc,
        "status": status,
        "bid_kopecks": bid,
    }

    if status == "pending_100_shows" and shows >= MIN_SHOWS_FOR_MANAGED:
        return DecisionSuggestion(
            keyword=keyword,
            action="promote_managed",
            reason_code="MIN_SHOWS_REACHED",
            reason_text=f"≥{MIN_SHOWS_FOR_MANAGED} показов — можно перевести в managed",
            before_state=base,
            after_state={**base, "status": "managed"},
        )

    if status == "pending_100_shows":
        return None

    if shows >= 300 and clicks == 0:
        return DecisionSuggestion(
            keyword=keyword,
            action="exclude_keyword",
            reason_code="ZERO_CTR",
            reason_text="Много показов, 0 кликов — кандидат на исключение",
            before_state=base,
            after_state={**base, "status": "excluded"},
        )

    if cpc and max_cpc_kopecks and cpc > max_cpc_kopecks and clicks >= 5:
        new_bid = bid
        if bid:
            new_bid = max(int(bid * 0.9), int(bid - 500))
        return DecisionSuggestion(
            keyword=keyword,
            action="lower_bid",
            reason_code="OVERPAYING_CPC",
            reason_text=f"CPC {cpc/100:.2f}₽ выше max {max_cpc_kopecks/100:.2f}₽",
            before_state=base,
            after_state={**base, "bid_kopecks": new_bid},
        )

    if is_primary and orders >= 3 and ctr and ctr >= 5:
        return DecisionSuggestion(
            keyword=keyword,
            action="keep",
            reason_code="PRIMARY_PERFORMING",
            reason_text="Primary ключ с заказами и нормальным CTR",
            before_state=base,
            after_state=base,
        )

    if is_primary and shows >= 200 and orders == 0 and ctr and ctr < 2:
        return DecisionSuggestion(
            keyword=keyword,
            action="exclude_keyword",
            reason_code="PRIMARY_LOW_CTR",
            reason_text="Primary: низкий CTR без заказов",
            before_state=base,
            after_state={**base, "status": "excluded"},
        )

    if not is_primary and shows >= 100 and orders == 0 and (ctr is None or ctr < 1):
        return DecisionSuggestion(
            keyword=keyword,
            action="exclude_keyword",
            reason_code="SECONDARY_WEAK",
            reason_text="Secondary/longtail без конверсии",
            before_state=base,
            after_state={**base, "status": "excluded", "retest_after": "+30d"},
        )

    if is_primary and bid and orders >= 5 and cpc and max_cpc_kopecks and cpc < max_cpc_kopecks * 0.7:
        new_bid = min(int(bid * 1.05), max_bid_kopecks)
        if new_bid > bid:
            return DecisionSuggestion(
                keyword=keyword,
                action="raise_bid",
                reason_code="ROOM_TO_GROW",
                reason_text="Primary окупается — можно +5% ставки",
                before_state=base,
                after_state={**base, "bid_kopecks": new_bid},
            )

    return DecisionSuggestion(
        keyword=keyword,
        action="skip",
        reason_code="NO_RULE",
        reason_text="Недостаточно данных или в норме",
        before_state=base,
        after_state=base,
    )
