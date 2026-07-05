from __future__ import annotations

from wb_advert.constants import MIN_SHOWS_FOR_MANAGED
from wb_advert.schemas.optimizer import DecisionSuggestion


def calc_max_cpc_kopecks(
    retail_price_rub: float,
    cost_price_rub: float,
    logistics_rub: float,
    commission_pct: float,
    max_drr_pct: float,
    *,
    expected_cr: float = 0.05,
) -> int | None:
    if retail_price_rub <= 0 or expected_cr <= 0:
        return None
    commission = retail_price_rub * (commission_pct / 100)
    margin_pool = retail_price_rub - cost_price_rub - logistics_rub - commission
    if margin_pool <= 0:
        return None
    max_spend_per_order = margin_pool * (max_drr_pct / 100)
    return int(max_spend_per_order / expected_cr * 100)


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
