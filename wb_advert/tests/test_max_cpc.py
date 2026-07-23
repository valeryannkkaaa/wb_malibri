"""Tests for CPC ceiling formula and CR ladder (issue #11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wb_advert.optimizer.engine import optimize_product
from wb_advert.optimizer.rules import (
    CAMPAIGN_CR_MIN_CLICKS,
    CPC_LIMIT_INSUFFICIENT_DATA,
    CPC_ZERO_CONVERSION,
    KEYWORD_CR_MIN_CLICKS,
    calc_keyword_max_cpc_kopecks,
    calc_max_cpc_kopecks,
    keyword_campaign_totals,
    resolve_cr_fact,
)
from wb_advert.storage.keywords_store import load_keywords
from wb_advert.storage.pilot_store import build_product_rows

ADVERT_ID = 900_001
NM_ID = "900001001"
PRIMARY_KEYWORD = "main keyword"


def _patch_pilot_data_dir(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> None:
    monkeypatch.setattr("wb_advert.storage.pilot_store.pilot_data_dir", lambda: data_dir)
    monkeypatch.setattr("wb_advert.optimizer.engine.pilot_data_dir", lambda: data_dir)


def _write_pilot_fixture(
    data_dir: Path,
    *,
    keywords: list[dict],
    primary_keyword: str = PRIMARY_KEYWORD,
    retail_price_rub: str = "200",
    max_drr_pct: str = "15.0",
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "pilot_skus.csv").write_text(
        "\n".join(
            [
                "nm_id,product_name,project_id,wb_campaign_search,wb_campaign_unified,schedule,primary_keyword,target_grade,notes",
                f"{NM_ID},Test,1,{ADVERT_ID},,always_on,{primary_keyword},top_1_3,",
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "unit_economics.csv").write_text(
        "\n".join(
            [
                "nm_id,cost_price_rub,retail_price_rub,margin_pct,max_drr_pct,wb_commission_pct,logistics_rub,volume_priority",
                f"{NM_ID},,{retail_price_rub},11,{max_drr_pct},,,balanced",
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "config.yaml").write_text(
        "\n".join(
            [
                "optimizer_mode: suggest-only",
                "allow_wb_writes: false",
                "parser:",
                "  region: Moscow",
                "  dest: '-1257786'",
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "last_sync_report.json").write_text(
        json.dumps({"campaigns": [], "primary_keywords": {}}),
        encoding="utf-8",
    )
    sync_dir = data_dir / "sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    (sync_dir / f"keywords_{ADVERT_ID}.json").write_text(
        json.dumps(
            {
                "wb_campaign_id": ADVERT_ID,
                "nm_id": int(NM_ID),
                "synced_at": "2026-07-06T11:41:17+00:00",
                "keywords": keywords,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _managed_keyword(
    *,
    keyword: str,
    clicks: int,
    orders: int,
    cpc_kopecks: int,
    shows: int = 1000,
    ctr: float = 10.0,
    bid_kopecks: int = 2000,
) -> dict:
    return {
        "keyword": keyword,
        "shows": shows,
        "clicks": clicks,
        "orders": orders,
        "spend_kopecks": clicks * cpc_kopecks,
        "ctr_calculated": ctr,
        "cpc_calculated_kopecks": cpc_kopecks,
        "current_bid_kopecks": bid_kopecks,
        "status": "managed",
    }


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
    cr, reason = resolve_cr_fact(
        kw_clicks=KEYWORD_CR_MIN_CLICKS,
        kw_orders=9,
        campaign_clicks=500,
        campaign_orders=50,
    )
    assert cr == 0.3
    assert reason is None


def test_resolve_cr_fact_falls_back_to_campaign_cr():
    cr, reason = resolve_cr_fact(
        kw_clicks=KEYWORD_CR_MIN_CLICKS - 1,
        kw_orders=0,
        campaign_clicks=CAMPAIGN_CR_MIN_CLICKS,
        campaign_orders=20,
    )
    assert cr == 0.2
    assert reason is None


def test_resolve_cr_fact_none_when_campaign_below_threshold():
    cr, reason = resolve_cr_fact(
        kw_clicks=10,
        kw_orders=5,
        campaign_clicks=CAMPAIGN_CR_MIN_CLICKS - 1,
        campaign_orders=10,
    )
    assert cr is None
    assert reason == CPC_LIMIT_INSUFFICIENT_DATA


def test_resolve_cr_fact_none_on_zero_clicks_not_default_cr():
    cr, reason = resolve_cr_fact(0, 0, 0, 0)
    assert cr is None
    assert reason == CPC_LIMIT_INSUFFICIENT_DATA
    assert calc_max_cpc_kopecks(179.0, 15.0, 0.0) is None
    assert calc_max_cpc_kopecks(179.0, 15.0, -0.05) is None


def test_resolve_cr_fact_none_when_keyword_has_clicks_but_no_orders():
    cr, reason = resolve_cr_fact(
        kw_clicks=KEYWORD_CR_MIN_CLICKS,
        kw_orders=0,
        campaign_clicks=500,
        campaign_orders=50,
    )
    assert cr is None
    assert reason == CPC_ZERO_CONVERSION


def test_resolve_cr_fact_none_when_campaign_has_clicks_but_no_orders():
    cr, reason = resolve_cr_fact(
        kw_clicks=10,
        kw_orders=0,
        campaign_clicks=CAMPAIGN_CR_MIN_CLICKS,
        campaign_orders=0,
    )
    assert cr is None
    assert reason == CPC_ZERO_CONVERSION


def test_calc_keyword_max_cpc_alerts_on_zero_keyword_conversion():
    econ = {"retail_price_rub": "179", "max_drr_pct": "15"}
    kw = {"keyword": "тест", "clicks": KEYWORD_CR_MIN_CLICKS, "orders": 0}
    max_cpc, alert = calc_keyword_max_cpc_kopecks(econ, kw, (500, 50))
    assert max_cpc is None
    assert alert == CPC_ZERO_CONVERSION


def test_calc_keyword_max_cpc_alerts_on_zero_campaign_conversion():
    econ = {"retail_price_rub": "179", "max_drr_pct": "15"}
    kw = {"keyword": "тест", "clicks": 10, "orders": 0}
    max_cpc, alert = calc_keyword_max_cpc_kopecks(
        econ,
        kw,
        (CAMPAIGN_CR_MIN_CLICKS, 0),
    )
    assert max_cpc is None
    assert alert == CPC_ZERO_CONVERSION


def test_calc_max_cpc_respects_max_drr_pct_from_economics():
    retail = 100.0
    cr_fact = 0.1

    low_drr = calc_max_cpc_kopecks(retail, 10.0, cr_fact)
    high_drr = calc_max_cpc_kopecks(retail, 20.0, cr_fact)

    assert low_drr == 100
    assert high_drr == 200
    assert high_drr == low_drr * 2


def test_optimize_product_applies_cpc_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_pilot_fixture(
        tmp_path,
        keywords=[
            _managed_keyword(
                keyword=PRIMARY_KEYWORD,
                clicks=40,
                orders=10,
                cpc_kopecks=1500,
            ),
        ],
    )
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    result = optimize_product(ADVERT_ID)
    overpaying = [s for s in result.suggestions if s.reason_code == "OVERPAYING_CPC"]

    assert len(overpaying) == 1
    assert overpaying[0].keyword == PRIMARY_KEYWORD


def test_optimize_product_does_not_flag_overpaying_without_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pilot_fixture(
        tmp_path,
        keywords=[
            _managed_keyword(
                keyword=PRIMARY_KEYWORD,
                clicks=40,
                orders=10,
                cpc_kopecks=1500,
            ),
        ],
        retail_price_rub="",
    )
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    result = optimize_product(ADVERT_ID)

    assert not any(s.reason_code == "OVERPAYING_CPC" for s in result.suggestions)


def test_optimize_product_alerts_only_keywords_without_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pilot_fixture(
        tmp_path,
        keywords=[
            _managed_keyword(
                keyword="burner",
                clicks=KEYWORD_CR_MIN_CLICKS,
                orders=0,
                cpc_kopecks=500,
            ),
            _managed_keyword(
                keyword="ok",
                clicks=5,
                orders=0,
                cpc_kopecks=300,
            ),
            _managed_keyword(
                keyword="filler",
                clicks=120,
                orders=12,
                cpc_kopecks=300,
            ),
        ],
        primary_keyword="ok",
    )
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    result = optimize_product(ADVERT_ID)

    assert any("burner" in alert and CPC_ZERO_CONVERSION in alert for alert in result.alerts)
    assert not any("ok:" in alert for alert in result.alerts)
    assert not any("filler:" in alert for alert in result.alerts)
    assert not any(alert.endswith(CPC_LIMIT_INSUFFICIENT_DATA) for alert in result.alerts)


def test_optimize_product_and_dashboard_share_primary_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pilot_fixture(
        tmp_path,
        keywords=[
            _managed_keyword(
                keyword=PRIMARY_KEYWORD,
                clicks=40,
                orders=10,
                cpc_kopecks=500,
            ),
        ],
    )
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    row = build_product_rows(tmp_path)[0]
    ceiling_kopecks = int(float(row["max_cpc_rub"]) * 100)

    keywords = load_keywords(ADVERT_ID, tmp_path)["keywords"]
    keywords[0]["cpc_calculated_kopecks"] = ceiling_kopecks + 100
    (tmp_path / "sync" / f"keywords_{ADVERT_ID}.json").write_text(
        json.dumps(
            {
                "wb_campaign_id": ADVERT_ID,
                "nm_id": int(NM_ID),
                "synced_at": "2026-07-06T11:41:17+00:00",
                "keywords": keywords,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    over_result = optimize_product(ADVERT_ID)
    assert any(s.reason_code == "OVERPAYING_CPC" for s in over_result.suggestions)

    keywords[0]["cpc_calculated_kopecks"] = max(ceiling_kopecks - 100, 1)
    (tmp_path / "sync" / f"keywords_{ADVERT_ID}.json").write_text(
        json.dumps(
            {
                "wb_campaign_id": ADVERT_ID,
                "nm_id": int(NM_ID),
                "synced_at": "2026-07-06T11:41:17+00:00",
                "keywords": keywords,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    under_result = optimize_product(ADVERT_ID)
    assert not any(s.reason_code == "OVERPAYING_CPC" for s in under_result.suggestions)


def test_build_product_rows_uses_campaign_cr_when_primary_missing(tmp_path: Path) -> None:
    _write_pilot_fixture(
        tmp_path,
        keywords=[
            _managed_keyword(
                keyword="actual keyword",
                clicks=150,
                orders=15,
                cpc_kopecks=400,
            ),
        ],
        primary_keyword="missing primary",
    )

    row = build_product_rows(tmp_path)[0]

    assert row["max_cpc_rub"] == 3.0


def test_keyword_campaign_totals_handles_missing_keywords_key() -> None:
    assert keyword_campaign_totals(None) == (0, 0)
