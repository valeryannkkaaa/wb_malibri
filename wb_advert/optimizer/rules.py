from __future__ import annotations

from wb_advert.constants import MIN_SHOWS_FOR_MANAGED
from wb_advert.schemas.optimizer import DecisionSuggestion

KEYWORD_CR_MIN_CLICKS = 30
CAMPAIGN_CR_MIN_CLICKS = 100
CPC_LIMIT_INSUFFICIENT_DATA = "недостаточно данных для лимита CPC"


def keyword_campaign_totals(keywords: list[dict]) -> tuple[int, int]:
    clicks = 0
    orders = 0
    for kw in keywords:
        clicks += int(kw.get("clicks") or 0)
        orders += int(kw.get("orders") or 0)
    return clicks, orders


def resolve_cr_fact(
    kw_clicks: int,
    kw_orders: int,
    campaign_clicks: int,
    campaign_orders: int,
) -> float | None:
    if kw_clicks >= KEYWORD_CR_MIN_CLICKS:
        if kw_clicks <= 0:
            return None
        return kw_orders / kw_clicks
    if campaign_clicks >= CAMPAIGN_CR_MIN_CLICKS:
        if campaign_clicks <= 0:
            return None
        return campaign_orders / campaign_clicks
    return None


def calc_max_cpc_kopecks(
    retail_price_rub: float,
    max_drr_pct: float,
    cr_fact: float,
) -> int | None:
    if retail_price_rub <= 0 or max_drr_pct <= 0 or cr_fact <= 0:
        return None
    return int(retail_price_rub * (max_drr_pct / 100) * cr_fact * 100)


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
