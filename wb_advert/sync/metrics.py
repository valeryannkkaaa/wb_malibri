from __future__ import annotations


def calc_ctr(clicks: int, views: int) -> float | None:
    if views <= 0:
        return None
    return round(clicks / views * 100, 4)


def calc_cpc_kopecks(spend_kopecks: int, clicks: int) -> int | None:
    if clicks <= 0:
        return None
    return spend_kopecks // clicks


def rub_to_kopecks(rub: float) -> int:
    return int(round(rub * 100))


def cpc_api_to_kopecks(cpc_rub: float) -> int:
    """WB normquery/fullstats often return CPC in rubles."""
    return rub_to_kopecks(cpc_rub)


def pick_primary_keyword(keywords: list) -> str | None:
    """Best primary keyword: highest orders, then shows, then clicks."""
    if not keywords:
        return None
    pool = [k for k in keywords if getattr(k, "status", None) == "managed"] or list(keywords)
    best = max(pool, key=lambda k: (k.orders, k.shows, k.clicks))
    return best.keyword
