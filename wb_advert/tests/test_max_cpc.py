"""Tests for CPC ceiling formula and CR prior smoothing (issues #11, #13)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wb_advert.optimizer.engine import optimize_all, optimize_product
from wb_advert.optimizer.rules import (
    CAMPAIGN_CR_MIN_CLICKS,
    CPC_LIMIT_INSUFFICIENT_DATA,
    CPC_PRIOR_ESTIMATE,
    CR_PRIOR_STRENGTH_CLICKS,
    CR_WINSOR_CAMPAIGN_MULTIPLIER,
    KEYWORD_CR_MIN_CLICKS,
    calc_keyword_max_cpc_kopecks,
    calc_max_cpc_kopecks,
    keyword_campaign_totals,
    resolve_cr_smoothed,
    smooth_cr,
)
from wb_advert.storage.keywords_store import load_keywords
from wb_advert.storage.pilot_store import (
    build_dashboard,
    build_product_rows,
    build_product_rows_with_prior,
    get_pilot_global_cr_prior,
    primary_keyword_for_advert,
)

ADVERT_ID = 900_001
NM_ID = "900001001"
PRIMARY_KEYWORD = "main keyword"
GLOBAL_CR = 0.218


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
    extra_campaigns: list[tuple[int, list[dict]]] | None = None,
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
    if extra_campaigns:
        sku_lines = [
            "nm_id,product_name,project_id,wb_campaign_search,wb_campaign_unified,schedule,primary_keyword,target_grade,notes",
            f"{NM_ID},Test,1,{ADVERT_ID},,always_on,{primary_keyword},top_1_3,",
        ]
        econ_lines = [
            "nm_id,cost_price_rub,retail_price_rub,margin_pct,max_drr_pct,wb_commission_pct,logistics_rub,volume_priority",
            f"{NM_ID},,{retail_price_rub},11,{max_drr_pct},,,balanced",
        ]
        for idx, (extra_advert_id, extra_keywords) in enumerate(extra_campaigns, start=2):
            extra_nm = f"90000100{idx}"
            sku_lines.append(
                f"{extra_nm},Extra,1,{extra_advert_id},,always_on,extra,top_1_3,"
            )
            econ_lines.append(f"{extra_nm},,200,11,{max_drr_pct},,,balanced")
            (sync_dir / f"keywords_{extra_advert_id}.json").write_text(
                json.dumps(
                    {
                        "wb_campaign_id": extra_advert_id,
                        "nm_id": int(extra_nm),
                        "synced_at": "2026-07-06T11:41:17+00:00",
                        "keywords": extra_keywords,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        (data_dir / "pilot_skus.csv").write_text("\n".join(sku_lines), encoding="utf-8")
        (data_dir / "unit_economics.csv").write_text("\n".join(econ_lines), encoding="utf-8")


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


def test_high_volume_keyword_smoothed_cr_matches_raw_within_one_percent():
    kw_clicks = 300
    kw_orders = 60
    raw_cr = kw_orders / kw_clicks
    global_cr = 0.20
    campaign_clicks = 500
    campaign_orders = 100

    smoothed = resolve_cr_smoothed(
        kw_clicks,
        kw_orders,
        campaign_clicks,
        campaign_orders,
        global_cr,
    )

    assert abs(smoothed - raw_cr) / raw_cr < 0.01


def test_low_volume_keyword_cr_pulls_toward_campaign_cr():
    global_cr = 0.20
    campaign_clicks = 200
    campaign_orders = 30
    campaign_cr = smooth_cr(campaign_orders, campaign_clicks, global_cr)

    kw_clicks = 10
    kw_orders = 2
    raw_kw_cr = kw_orders / kw_clicks

    smoothed = resolve_cr_smoothed(
        kw_clicks,
        kw_orders,
        campaign_clicks,
        campaign_orders,
        global_cr,
    )

    assert abs(smoothed - campaign_cr) < abs(raw_kw_cr - campaign_cr)
    assert smoothed < raw_kw_cr


def test_low_volume_campaign_cr_pulls_toward_global_prior():
    """Regression for campaign 33206346: 3 clicks, 66.7% raw CR must not dominate."""
    global_cr = GLOBAL_CR
    campaign_clicks = 3
    campaign_orders = 2
    raw_campaign_cr = campaign_orders / campaign_clicks

    smoothed_campaign_cr = smooth_cr(campaign_orders, campaign_clicks, global_cr)

    assert smoothed_campaign_cr < raw_campaign_cr
    assert abs(smoothed_campaign_cr - global_cr) < abs(raw_campaign_cr - global_cr)

    econ = {"retail_price_rub": "457", "max_drr_pct": "15"}
    kw = {"keyword": "перчатки", "clicks": campaign_clicks, "orders": campaign_orders}
    with_global, _ = calc_keyword_max_cpc_kopecks(
        econ,
        kw,
        (campaign_clicks, campaign_orders),
        global_cr,
    )
    without_global, _ = calc_keyword_max_cpc_kopecks(
        econ,
        kw,
        (campaign_clicks, campaign_orders),
        raw_campaign_cr,
    )

    assert with_global is not None
    assert without_global is not None
    assert with_global < without_global
    assert with_global == pytest.approx(1832, abs=5)
    assert without_global == pytest.approx(4570, abs=5)


def test_zero_clicks_do_not_break_smoothing():
    global_cr = GLOBAL_CR
    campaign_clicks = 0
    campaign_orders = 0
    kw_clicks = 0
    kw_orders = 0

    smoothed = resolve_cr_smoothed(
        kw_clicks,
        kw_orders,
        campaign_clicks,
        campaign_orders,
        global_cr,
    )

    assert smoothed == pytest.approx(global_cr)

    econ = {"retail_price_rub": "234", "max_drr_pct": "15"}
    kw = {"keyword": "губка", "clicks": 0, "orders": 0}
    max_cpc, alert = calc_keyword_max_cpc_kopecks(
        econ,
        kw,
        (campaign_clicks, campaign_orders),
        global_cr,
    )

    assert max_cpc is not None
    assert max_cpc > 0
    assert alert == CPC_PRIOR_ESTIMATE


def test_no_global_data_returns_none_and_alert():
    econ = {"retail_price_rub": "179", "max_drr_pct": "15"}
    kw = {"keyword": "тест", "clicks": 0, "orders": 0}

    max_cpc, alert = calc_keyword_max_cpc_kopecks(econ, kw, (0, 0), None)

    assert max_cpc is None
    assert alert == CPC_LIMIT_INSUFFICIENT_DATA


def test_prior_alert_only_for_keys_below_trust_thresholds():
    econ = {"retail_price_rub": "200", "max_drr_pct": "15"}
    global_cr = 0.20

    _, alert_low_kw = calc_keyword_max_cpc_kopecks(
        econ,
        {"keyword": "a", "clicks": KEYWORD_CR_MIN_CLICKS - 1, "orders": 0},
        (CAMPAIGN_CR_MIN_CLICKS - 1, 5),
        global_cr,
    )
    _, alert_low_kw_large_campaign = calc_keyword_max_cpc_kopecks(
        econ,
        {"keyword": "b", "clicks": KEYWORD_CR_MIN_CLICKS - 1, "orders": 0},
        (CAMPAIGN_CR_MIN_CLICKS + 200, 20),
        global_cr,
    )
    _, alert_kw_ok = calc_keyword_max_cpc_kopecks(
        econ,
        {"keyword": "c", "clicks": KEYWORD_CR_MIN_CLICKS, "orders": 3},
        (CAMPAIGN_CR_MIN_CLICKS - 1, 5),
        global_cr,
    )

    assert alert_low_kw == CPC_PRIOR_ESTIMATE
    assert alert_low_kw_large_campaign == CPC_PRIOR_ESTIMATE
    assert alert_kw_ok is None


def test_orders_above_clicks_ceiling_limited_by_winsor():
    """Regression: микрофибра 30х30 — 15 clicks, 28 orders; winsor caps inflated CR."""
    global_cr = 0.24916154276131916
    campaign_clicks = 335
    campaign_orders = 85
    kw_clicks = 15
    kw_orders = 28

    campaign_cr = smooth_cr(campaign_orders, campaign_clicks, global_cr)
    raw_smoothed_kw = smooth_cr(kw_orders, kw_clicks, campaign_cr)
    assert raw_smoothed_kw > CR_WINSOR_CAMPAIGN_MULTIPLIER * campaign_cr

    cr_fact = resolve_cr_smoothed(
        kw_clicks,
        kw_orders,
        campaign_clicks,
        campaign_orders,
        global_cr,
    )
    assert cr_fact == pytest.approx(CR_WINSOR_CAMPAIGN_MULTIPLIER * campaign_cr)

    econ = {"retail_price_rub": "330", "max_drr_pct": "15"}
    kw = {"keyword": "салфетки из микрофибры 30х30", "clicks": kw_clicks, "orders": kw_orders}
    max_cpc, _ = calc_keyword_max_cpc_kopecks(
        econ,
        kw,
        (campaign_clicks, campaign_orders),
        global_cr,
    )

    assert max_cpc == pytest.approx(2506, abs=5)
    assert max_cpc < 3000


def test_winsor_constant_is_two():
    assert CR_WINSOR_CAMPAIGN_MULTIPLIER == 2.0


def test_calc_max_cpc_respects_max_drr_pct_from_economics():
    retail = 100.0
    cr_fact = 0.1

    low_drr = calc_max_cpc_kopecks(retail, 10.0, cr_fact)
    high_drr = calc_max_cpc_kopecks(retail, 20.0, cr_fact)

    assert low_drr == 100
    assert high_drr == 200
    assert high_drr == low_drr * 2


def test_optimize_product_applies_cpc_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    keywords = [
        _managed_keyword(
            keyword=PRIMARY_KEYWORD,
            clicks=40,
            orders=10,
            cpc_kopecks=1500,
        ),
    ]
    extra = [(900_002, [_managed_keyword(keyword="filler", clicks=500, orders=100, cpc_kopecks=300)])]
    _write_pilot_fixture(tmp_path, keywords=keywords, extra_campaigns=extra)
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    result = optimize_product(ADVERT_ID)
    overpaying = [s for s in result.suggestions if s.reason_code == "OVERPAYING_CPC"]

    assert len(overpaying) == 1
    assert overpaying[0].keyword == PRIMARY_KEYWORD


def test_optimize_product_does_not_flag_overpaying_without_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keywords = [
        _managed_keyword(
            keyword=PRIMARY_KEYWORD,
            clicks=40,
            orders=10,
            cpc_kopecks=1500,
        ),
    ]
    extra = [(900_002, [_managed_keyword(keyword="filler", clicks=500, orders=100, cpc_kopecks=300)])]
    _write_pilot_fixture(tmp_path, keywords=keywords, extra_campaigns=extra, retail_price_rub="")
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    result = optimize_product(ADVERT_ID)

    assert not any(s.reason_code == "OVERPAYING_CPC" for s in result.suggestions)


def test_optimize_product_alerts_on_prior_estimate_keywords(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keywords = [
        _managed_keyword(
            keyword="low-trust",
            clicks=KEYWORD_CR_MIN_CLICKS - 1,
            orders=0,
            cpc_kopecks=500,
        ),
        _managed_keyword(
            keyword="trusted",
            clicks=KEYWORD_CR_MIN_CLICKS,
            orders=3,
            cpc_kopecks=300,
        ),
    ]
    _write_pilot_fixture(tmp_path, keywords=keywords, primary_keyword="trusted")
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    result = optimize_product(ADVERT_ID)

    assert any("low-trust" in alert and CPC_PRIOR_ESTIMATE in alert for alert in result.alerts)
    assert not any("trusted:" in alert for alert in result.alerts)


def test_optimize_product_alerts_prior_estimate_in_large_campaign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keywords = [
        _managed_keyword(
            keyword="sparse primary",
            clicks=15,
            orders=5,
            cpc_kopecks=500,
        ),
        _managed_keyword(
            keyword="filler",
            clicks=320,
            orders=80,
            cpc_kopecks=300,
        ),
    ]
    _write_pilot_fixture(tmp_path, keywords=keywords, primary_keyword="sparse primary")
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    result = optimize_product(ADVERT_ID)

    assert any("sparse primary" in alert and CPC_PRIOR_ESTIMATE in alert for alert in result.alerts)
    assert not any("filler:" in alert for alert in result.alerts)


def test_optimize_product_and_dashboard_share_primary_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keywords = [
        _managed_keyword(
            keyword=PRIMARY_KEYWORD,
            clicks=40,
            orders=10,
            cpc_kopecks=500,
        ),
    ]
    extra = [(900_002, [_managed_keyword(keyword="filler", clicks=500, orders=100, cpc_kopecks=300)])]
    _write_pilot_fixture(tmp_path, keywords=keywords, extra_campaigns=extra)
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    row = build_product_rows(tmp_path)[0]
    ceiling_kopecks = int(float(row["max_cpc_rub"]) * 100)

    keywords_data = load_keywords(ADVERT_ID, tmp_path)["keywords"]
    keywords_data[0]["cpc_calculated_kopecks"] = ceiling_kopecks + 100
    (tmp_path / "sync" / f"keywords_{ADVERT_ID}.json").write_text(
        json.dumps(
            {
                "wb_campaign_id": ADVERT_ID,
                "nm_id": int(NM_ID),
                "synced_at": "2026-07-06T11:41:17+00:00",
                "keywords": keywords_data,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    over_result = optimize_product(ADVERT_ID)
    assert any(s.reason_code == "OVERPAYING_CPC" for s in over_result.suggestions)

    keywords_data[0]["cpc_calculated_kopecks"] = max(ceiling_kopecks - 100, 1)
    (tmp_path / "sync" / f"keywords_{ADVERT_ID}.json").write_text(
        json.dumps(
            {
                "wb_campaign_id": ADVERT_ID,
                "nm_id": int(NM_ID),
                "synced_at": "2026-07-06T11:41:17+00:00",
                "keywords": keywords_data,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    under_result = optimize_product(ADVERT_ID)
    assert not any(s.reason_code == "OVERPAYING_CPC" for s in under_result.suggestions)


def test_engine_and_build_product_rows_agree_on_primary_max_cpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keywords = [
        _managed_keyword(
            keyword=PRIMARY_KEYWORD,
            clicks=40,
            orders=10,
            cpc_kopecks=500,
        ),
        _managed_keyword(
            keyword="secondary",
            clicks=5,
            orders=0,
            cpc_kopecks=400,
        ),
    ]
    extra = [(900_002, [_managed_keyword(keyword="filler", clicks=500, orders=100, cpc_kopecks=300)])]
    _write_pilot_fixture(tmp_path, keywords=keywords, extra_campaigns=extra)
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    row = build_product_rows(tmp_path)[0]
    global_cr = get_pilot_global_cr_prior(tmp_path)
    primary_kw = next(k for k in keywords if k["keyword"] == PRIMARY_KEYWORD)
    campaign_totals = keyword_campaign_totals(keywords)
    engine_ceiling, _ = calc_keyword_max_cpc_kopecks(
        {"retail_price_rub": "200", "max_drr_pct": "15.0"},
        primary_kw,
        campaign_totals,
        global_cr,
    )

    assert engine_ceiling is not None
    assert row["max_cpc_rub"] == pytest.approx(engine_ceiling / 100, abs=0.01)


def test_build_product_rows_uses_campaign_cr_when_primary_missing(tmp_path: Path) -> None:
    keywords = [
        _managed_keyword(
            keyword="actual keyword",
            clicks=150,
            orders=15,
            cpc_kopecks=400,
        ),
    ]
    extra = [(900_002, [_managed_keyword(keyword="filler", clicks=500, orders=100, cpc_kopecks=300)])]
    _write_pilot_fixture(tmp_path, keywords=keywords, extra_campaigns=extra, primary_keyword="missing primary")

    row = build_product_rows(tmp_path)[0]

    assert row["max_cpc_rub"] is not None
    assert row["max_cpc_rub"] > 0


def test_low_traffic_campaigns_get_ceiling_on_pilot_data() -> None:
    """Acceptance: previously rejected low-traffic pilot cards now receive a ceiling."""
    rows = build_product_rows(Path("data/pilot"))
    by_advert = {row["advert_id"]: row for row in rows}

    for advert_id in (36713559, 37636194, 33206346, 35098216, 37328842):
        assert by_advert[advert_id]["max_cpc_rub"] is not None, advert_id


def test_pilot_microfiber_ceiling_winsorized_on_real_data() -> None:
    rows = build_product_rows(Path("data/pilot"))
    by_advert = {row["advert_id"]: row["max_cpc_rub"] for row in rows}
    assert by_advert[36713559] == pytest.approx(25.06, abs=0.10)


def test_pilot_ceilings_match_smoothing_formula_on_real_data() -> None:
    """Acceptance: build_product_rows ceilings follow the two-level prior formula on pilot data."""
    from wb_advert.import_data.csv_loader import load_pilot_skus
    from wb_advert.storage.keywords_store import load_keywords
    from wb_advert.storage.pilot_store import get_pilot_global_cr_prior, load_unit_economics

    data_dir = Path("data/pilot")
    global_cr = get_pilot_global_cr_prior(data_dir)
    assert global_cr is not None

    economics = load_unit_economics(data_dir)
    by_advert = {row["advert_id"]: row["max_cpc_rub"] for row in build_product_rows(data_dir)}

    for sku in load_pilot_skus(data_dir / "pilot_skus.csv"):
        kw_file = load_keywords(sku.wb_campaign_search, data_dir)
        keywords = (kw_file.get("keywords") if kw_file else None) or []
        campaign_totals = keyword_campaign_totals(keywords)
        primary_label = (sku.primary_keyword or "").strip().lower()
        primary_kw = next(
            (k for k in keywords if (k.get("keyword") or "").strip().lower() == primary_label),
            {},
        )
        expected_kopecks, _ = calc_keyword_max_cpc_kopecks(
            economics.get(sku.nm_id, {}),
            primary_kw,
            campaign_totals,
            global_cr,
        )
        assert expected_kopecks is not None, sku.wb_campaign_search
        assert by_advert[sku.wb_campaign_search] == pytest.approx(expected_kopecks / 100, abs=0.01)


def test_keyword_campaign_totals_handles_missing_keywords_key() -> None:
    assert keyword_campaign_totals(None) == (0, 0)


def test_prior_strength_constant_is_fifty():
    assert CR_PRIOR_STRENGTH_CLICKS == 50


def _write_multi_card_fixture(tmp_path: Path, *, card_count: int) -> None:
    sku_lines = [
        "nm_id,product_name,project_id,wb_campaign_search,wb_campaign_unified,schedule,primary_keyword,target_grade,notes",
    ]
    econ_lines = [
        "nm_id,cost_price_rub,retail_price_rub,margin_pct,max_drr_pct,wb_commission_pct,logistics_rub,volume_priority",
    ]
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    keywords = [
        _managed_keyword(keyword=PRIMARY_KEYWORD, clicks=40, orders=10, cpc_kopecks=500),
    ]
    for idx in range(card_count):
        advert_id = 910_000 + idx
        nm_id = f"910000{idx}"
        sku_lines.append(
            f"{nm_id},Test,1,{advert_id},,always_on,{PRIMARY_KEYWORD},top_1_3,",
        )
        econ_lines.append(f"{nm_id},,200,11,15.0,,,balanced")
        (sync_dir / f"keywords_{advert_id}.json").write_text(
            json.dumps(
                {
                    "wb_campaign_id": advert_id,
                    "nm_id": int(nm_id),
                    "synced_at": "2026-07-06T11:41:17+00:00",
                    "keywords": keywords,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pilot_skus.csv").write_text("\n".join(sku_lines), encoding="utf-8")
    (tmp_path / "unit_economics.csv").write_text("\n".join(econ_lines), encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
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
    (tmp_path / "last_sync_report.json").write_text(
        json.dumps({"campaigns": [], "primary_keywords": {}}),
        encoding="utf-8",
    )


def _install_load_keywords_counter(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    import wb_advert.optimizer.engine as engine_module
    import wb_advert.storage.keywords_store as keywords_store
    import wb_advert.storage.pilot_store as pilot_store_module

    original_load = keywords_store.load_keywords
    load_count = [0]

    def counting_load(advert_id: int, data_dir=None):
        load_count[0] += 1
        return original_load(advert_id, data_dir)

    monkeypatch.setattr(keywords_store, "load_keywords", counting_load)
    monkeypatch.setattr(engine_module, "load_keywords", counting_load)
    monkeypatch.setattr(pilot_store_module, "load_keywords", counting_load)
    return load_count


def test_optimize_all_reads_keywords_at_most_twice_per_card(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card_count = 3
    _write_multi_card_fixture(tmp_path, card_count=card_count)
    _patch_pilot_data_dir(monkeypatch, tmp_path)
    load_count = _install_load_keywords_counter(monkeypatch)

    results = optimize_all()

    assert len(results) == card_count
    assert load_count[0] == card_count * 2


def test_build_dashboard_cold_reads_keywords_at_most_twice_per_card(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card_count = 3
    _write_multi_card_fixture(tmp_path, card_count=card_count)
    _patch_pilot_data_dir(monkeypatch, tmp_path)
    load_count = _install_load_keywords_counter(monkeypatch)

    dashboard = build_dashboard(tmp_path)

    assert dashboard["product_count"] == card_count
    assert load_count[0] == card_count * 2


def test_optimize_product_and_build_product_rows_agree_on_primary_keyword() -> None:
    data_dir = Path("data/pilot")
    rows, _ = build_product_rows_with_prior(data_dir)

    for row in rows:
        assert row["primary_keyword"] == primary_keyword_for_advert(row["advert_id"], data_dir)


def test_primary_keyword_falls_back_to_sync_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_primary = "from sync report"
    _write_pilot_fixture(
        tmp_path,
        keywords=[_managed_keyword(keyword=sync_primary, clicks=40, orders=10, cpc_kopecks=500)],
        primary_keyword="",
    )
    (tmp_path / "last_sync_report.json").write_text(
        json.dumps(
            {
                "campaigns": [{"wb_campaign_id": ADVERT_ID, "top_keyword": sync_primary}],
                "primary_keywords": {},
            }
        ),
        encoding="utf-8",
    )
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    row = build_product_rows(tmp_path)[0]
    assert row["primary_keyword"] == sync_primary
    assert primary_keyword_for_advert(ADVERT_ID, tmp_path) == sync_primary

    result = optimize_product(ADVERT_ID)
    performing = [s for s in result.suggestions if s.reason_code == "PRIMARY_PERFORMING"]
    assert len(performing) == 1
    assert performing[0].keyword == sync_primary
