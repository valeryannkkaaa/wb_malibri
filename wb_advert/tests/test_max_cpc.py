"""Tests for CPC ceiling formula and CR ladder (issue #11)."""

from __future__ import annotations

from wb_advert.optimizer.rules import (
    CAMPAIGN_CR_MIN_CLICKS,
    KEYWORD_CR_MIN_CLICKS,
    calc_max_cpc_kopecks,
    resolve_cr_fact,
)


def test_calc_max_cpc_multiplies_by_cr_not_divides():
    """Regression: old formula divided by CR and inflated the ceiling ~400x at 5% CR."""
    retail = 179.0
    max_drr_pct = 15.0
    cr_fact = 0.285

    result = calc_max_cpc_kopecks(retail, max_drr_pct, cr_fact)
    assert result == 765

    wrong_division = int(retail * (max_drr_pct / 100) / cr_fact * 100)
    assert result != wrong_division
    assert wrong_division > result * 10


def test_calc_max_cpc_uses_retail_not_margin():
    """Base is revenue; margin_pct must not affect the ceiling."""
    retail = 275.0
    max_drr_pct = 15.0
    cr_fact = 0.167

    result = calc_max_cpc_kopecks(retail, max_drr_pct, cr_fact)
    assert result == 688

    margin_based_wrong = int(retail * 0.11 * (max_drr_pct / 100) / cr_fact * 100)
    assert result != margin_based_wrong


def test_resolve_cr_fact_uses_keyword_cr_at_threshold():
    cr = resolve_cr_fact(
        kw_clicks=KEYWORD_CR_MIN_CLICKS,
        kw_orders=9,
        campaign_clicks=500,
        campaign_orders=50,
    )
    assert cr == 0.3


def test_resolve_cr_fact_falls_back_to_campaign_cr():
    cr = resolve_cr_fact(
        kw_clicks=KEYWORD_CR_MIN_CLICKS - 1,
        kw_orders=0,
        campaign_clicks=CAMPAIGN_CR_MIN_CLICKS,
        campaign_orders=20,
    )
    assert cr == 0.2


def test_resolve_cr_fact_none_when_campaign_below_threshold():
    assert (
        resolve_cr_fact(
            kw_clicks=10,
            kw_orders=5,
            campaign_clicks=CAMPAIGN_CR_MIN_CLICKS - 1,
            campaign_orders=10,
        )
        is None
    )


def test_resolve_cr_fact_none_on_zero_clicks_not_default_cr():
    assert resolve_cr_fact(0, 0, 0, 0) is None
    assert calc_max_cpc_kopecks(179.0, 15.0, 0.0) is None
    assert calc_max_cpc_kopecks(179.0, 15.0, -0.05) is None


def test_calc_max_cpc_respects_max_drr_pct_from_economics():
    retail = 100.0
    cr_fact = 0.1

    low_drr = calc_max_cpc_kopecks(retail, 10.0, cr_fact)
    high_drr = calc_max_cpc_kopecks(retail, 20.0, cr_fact)

    assert low_drr == 100
    assert high_drr == 200
    assert high_drr == low_drr * 2
