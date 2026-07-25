"""Tests for API retail price and buyout in CPC ceiling (issue #18)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wb_advert.optimizer.engine import optimize_product
from wb_advert.optimizer.retail_price import (
    PRICE_SOURCE_CSV,
    PRICE_SOURCE_FUNNEL,
    PRICE_SOURCE_SEARCH_REPORT,
    ResolvedRetailPrice,
    extract_funnel_avg_order_rub,
    extract_funnel_buyout_percent,
    extract_search_report_min_price_rub,
    resolve_retail_price,
)
from wb_advert.optimizer.rules import calc_keyword_max_cpc_kopecks, calc_max_cpc_kopecks
from wb_advert.storage.pilot_store import (
    build_product_rows,
    get_pilot_global_cr_prior,
    resolve_product_retail_price,
)
from wb_advert.tests.test_max_cpc import (
    ADVERT_ID,
    NM_ID,
    PRIMARY_KEYWORD,
    _managed_keyword,
    _patch_pilot_data_dir,
    _write_pilot_fixture,
)

GLOVES_NM_ID = "624468743"
GLOVES_ADVERT_ID = 31275686


def _write_funnel(
    data_dir: Path,
    nm_id: str | int,
    *,
    rows: list[dict],
) -> None:
    sync_dir = data_dir / "sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    (sync_dir / f"funnel_{nm_id}.json").write_text(
        json.dumps(
            {
                "nm_id": int(nm_id),
                "synced_at": "2026-07-23T10:00:00+00:00",
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_search_report(
    data_dir: Path,
    nm_id: str | int,
    *,
    min_price: float,
) -> None:
    sync_dir = data_dir / "sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    (sync_dir / f"search_report_{nm_id}.json").write_text(
        json.dumps(
            {
                "nm_id": int(nm_id),
                "synced_at": "2026-07-23T10:00:00+00:00",
                "period": {"start": "2026-07-16", "end": "2026-07-22"},
                "items": [
                    {"text": "перчатки для уборки", "min_price": min_price},
                    {"text": "перчатки резиновые", "min_price": min_price + 50},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _gloves_funnel_rows() -> list[dict]:
    return [
        {
            "dt": "2026-07-16",
            "orders_count": 181,
            "orders_sum_rub": 38915,
            "buyouts_sum_rub": 30745,
            "buyout_percent": 95,
        },
        {
            "dt": "2026-07-17",
            "orders_count": 163,
            "orders_sum_rub": 35045,
            "buyouts_sum_rub": 25370,
            "buyout_percent": 97,
        },
    ]


def test_funnel_price_overrides_csv() -> None:
    funnel = {"rows": _gloves_funnel_rows()}
    econ = {"retail_price_rub": "179", "max_drr_pct": "15"}

    resolved = resolve_retail_price(econ, funnel=funnel)

    assert resolved is not None
    assert resolved.source == PRICE_SOURCE_FUNNEL
    assert resolved.value_rub == pytest.approx(38915 / 181, abs=0.01)


def test_search_report_used_when_funnel_missing() -> None:
    search_report = {"items": [{"text": "test", "min_price": 215}]}
    econ = {"retail_price_rub": "179", "max_drr_pct": "15"}

    resolved = resolve_retail_price(econ, search_report=search_report)

    assert resolved is not None
    assert resolved.source == PRICE_SOURCE_SEARCH_REPORT
    assert resolved.value_rub == 215


def test_csv_fallback_when_api_data_missing() -> None:
    econ = {"retail_price_rub": "179", "max_drr_pct": "15"}

    resolved = resolve_retail_price(econ)

    assert resolved is not None
    assert resolved.source == PRICE_SOURCE_CSV
    assert resolved.value_rub == 179


def test_buyout_percent_applied_to_ceiling() -> None:
    retail = 215.0
    max_drr_pct = 15.0
    cr_fact = 0.30

    without_buyout = calc_max_cpc_kopecks(retail, max_drr_pct, cr_fact)
    with_buyout = calc_max_cpc_kopecks(retail, max_drr_pct, cr_fact, buyout_percent=95)

    assert without_buyout is not None
    assert with_buyout is not None
    assert with_buyout < without_buyout
    assert with_buyout == pytest.approx(int(without_buyout * 0.95), abs=1)


def test_buyout_not_invented_when_missing() -> None:
    funnel = {
        "rows": [
            {"orders_count": 10, "orders_sum_rub": 2000},
        ]
    }
    econ = {"retail_price_rub": "179", "max_drr_pct": "15"}

    resolved = resolve_retail_price(econ, funnel=funnel)

    assert resolved is not None
    assert resolved.buyout_percent is None

    cr = 0.2
    without_buyout = calc_max_cpc_kopecks(resolved.value_rub, 15, cr)
    with_none = calc_max_cpc_kopecks(resolved.value_rub, 15, cr, buyout_percent=None)
    assert without_buyout == with_none


def test_extract_funnel_metrics_from_issue_sample() -> None:
    funnel = {"rows": _gloves_funnel_rows()}

    assert extract_funnel_avg_order_rub(funnel) == pytest.approx(215, abs=0.5)
    assert extract_funnel_buyout_percent(funnel) == pytest.approx(95, abs=1)


def test_extract_search_report_min_price() -> None:
    report = {
        "items": [
            {"text": "a", "min_price": 215},
            {"text": "b", "min_price": 250},
        ]
    }

    assert extract_search_report_min_price_rub(report) == 215


def test_regression_empty_api_matches_csv_ceiling(
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
    _write_pilot_fixture(tmp_path, keywords=keywords, extra_campaigns=extra, retail_price_rub="200")
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    econ = {"retail_price_rub": "200", "max_drr_pct": "15.0"}
    kw = keywords[0]
    global_cr = get_pilot_global_cr_prior(tmp_path)
    campaign_totals = (40, 10)
    resolved = resolve_retail_price(econ)
    expected, _ = calc_keyword_max_cpc_kopecks(
        econ,
        kw,
        campaign_totals,
        global_cr,
        resolved_price=resolved,
    )
    row = build_product_rows(tmp_path)[0]

    assert expected is not None
    assert row["max_cpc_rub"] == pytest.approx(expected / 100, abs=0.01)
    assert row["price_source"] == PRICE_SOURCE_CSV
    assert row["buyout_percent"] is None


def test_pilot_csv_ceilings_match_explicit_formula_without_api_files() -> None:
    """Regression: without API files, ceilings follow CSV price and no buyout adjustment."""
    from wb_advert.import_data.csv_loader import load_pilot_skus
    from wb_advert.storage.keywords_store import load_keywords
    from wb_advert.storage.pilot_store import load_unit_economics

    data_dir = Path("data/pilot")
    rows = build_product_rows(data_dir)
    economics = load_unit_economics(data_dir)
    global_cr = get_pilot_global_cr_prior(data_dir)

    for sku in load_pilot_skus(data_dir / "pilot_skus.csv"):
        row = next(r for r in rows if r["nm_id"] == sku.nm_id)
        assert row["price_source"] == PRICE_SOURCE_CSV
        assert row["buyout_percent"] is None

        kw_file = load_keywords(sku.wb_campaign_search, data_dir)
        keywords = (kw_file.get("keywords") if kw_file else None) or []
        campaign_totals = (
            sum(int(k.get("clicks") or 0) for k in keywords),
            sum(int(k.get("orders") or 0) for k in keywords),
        )
        primary_label = (sku.primary_keyword or "").strip().lower()
        primary_kw = next(
            (k for k in keywords if (k.get("keyword") or "").strip().lower() == primary_label),
            {},
        )
        expected, _ = calc_keyword_max_cpc_kopecks(
            economics.get(sku.nm_id, {}),
            primary_kw,
            campaign_totals,
            global_cr,
            resolved_price=resolve_retail_price(economics.get(sku.nm_id, {})),
        )
        if expected is None:
            assert row["max_cpc_rub"] is None
        else:
            assert row["max_cpc_rub"] == pytest.approx(expected / 100, abs=0.01)


def test_gloves_ceiling_with_api_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wb_advert.import_data.csv_loader import load_pilot_skus
    from wb_advert.optimizer.rules import keyword_campaign_totals
    from wb_advert.storage.keywords_store import load_keywords
    from wb_advert.storage.pilot_store import load_unit_economics

    data_dir = Path("data/pilot")
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name in ("pilot_skus.csv", "unit_economics.csv", "config.yaml", "last_sync_report.json"):
        (tmp_path / name).write_bytes((data_dir / name).read_bytes())
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    for path in data_dir.glob("sync/keywords_*.json"):
        (sync_dir / path.name).write_bytes(path.read_bytes())
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    baseline = next(r for r in build_product_rows(tmp_path) if r["advert_id"] == GLOVES_ADVERT_ID)
    assert baseline["price_source"] == PRICE_SOURCE_CSV
    baseline_ceiling = baseline["max_cpc_rub"]

    _write_funnel(tmp_path, GLOVES_NM_ID, rows=_gloves_funnel_rows())
    with_api = next(r for r in build_product_rows(tmp_path) if r["advert_id"] == GLOVES_ADVERT_ID)

    sku = next(s for s in load_pilot_skus(tmp_path / "pilot_skus.csv") if s.wb_campaign_search == GLOVES_ADVERT_ID)
    economics = load_unit_economics(tmp_path)
    econ = economics[sku.nm_id]
    keywords = load_keywords(GLOVES_ADVERT_ID, tmp_path)["keywords"]
    campaign_totals = keyword_campaign_totals(keywords)
    primary_label = (sku.primary_keyword or "").strip().lower()
    primary_kw = next(
        (k for k in keywords if (k.get("keyword") or "").strip().lower() == primary_label),
        {},
    )
    resolved = resolve_product_retail_price(sku.nm_id, econ, tmp_path)
    expected_kopecks, _ = calc_keyword_max_cpc_kopecks(
        econ,
        primary_kw,
        campaign_totals,
        get_pilot_global_cr_prior(tmp_path),
        resolved_price=resolved,
    )

    assert with_api["price_source"] == PRICE_SOURCE_FUNNEL
    assert with_api["price_rub"] == pytest.approx(215, abs=0.5)
    assert with_api["buyout_percent"] == pytest.approx(96, abs=1)
    assert with_api["max_cpc_rub"] > baseline_ceiling
    assert with_api["max_cpc_rub"] == pytest.approx(expected_kopecks / 100, abs=0.01)
    # Acceptance ratio from issue: ~215/179 price uplift minus ~5% buyout.
    assert with_api["max_cpc_rub"] / baseline_ceiling == pytest.approx((215 / 179) * 0.96, abs=0.03)


def test_engine_and_dashboard_share_resolved_price_ceiling(
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
    _write_pilot_fixture(tmp_path, keywords=keywords, extra_campaigns=extra, retail_price_rub="179")
    _write_funnel(tmp_path, NM_ID, rows=_gloves_funnel_rows())
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    row = build_product_rows(tmp_path)[0]
    ceiling_kopecks = int(float(row["max_cpc_rub"]) * 100)

    keywords_data = json.loads((tmp_path / "sync" / f"keywords_{ADVERT_ID}.json").read_text())["keywords"]
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

    result = optimize_product(ADVERT_ID)
    assert any(s.reason_code == "OVERPAYING_CPC" for s in result.suggestions)
    assert row["price_source"] == PRICE_SOURCE_FUNNEL


def test_search_report_fallback_ceiling(
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
    _write_pilot_fixture(tmp_path, keywords=keywords, extra_campaigns=extra, retail_price_rub="179")
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    csv_row = build_product_rows(tmp_path)[0]
    csv_ceiling = csv_row["max_cpc_rub"]

    _write_search_report(tmp_path, NM_ID, min_price=215)
    search_row = build_product_rows(tmp_path)[0]

    assert search_row["price_source"] == PRICE_SOURCE_SEARCH_REPORT
    assert search_row["price_rub"] == 215
    assert search_row["max_cpc_rub"] > csv_ceiling


def test_build_product_rows_exposes_price_source_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keywords = [_managed_keyword(keyword=PRIMARY_KEYWORD, clicks=40, orders=10, cpc_kopecks=500)]
    extra = [(900_002, [_managed_keyword(keyword="filler", clicks=500, orders=100, cpc_kopecks=300)])]
    _write_pilot_fixture(tmp_path, keywords=keywords, extra_campaigns=extra, retail_price_rub="179")
    _write_funnel(tmp_path, NM_ID, rows=_gloves_funnel_rows())
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    row = build_product_rows(tmp_path)[0]

    assert row["price_rub"] is not None
    assert row["price_source"] == PRICE_SOURCE_FUNNEL
    assert row["price_source_label"] == "воронка WB"


def test_resolve_product_retail_price_loads_files(tmp_path: Path) -> None:
    econ = {"retail_price_rub": "179", "max_drr_pct": "15"}
    _write_funnel(tmp_path, GLOVES_NM_ID, rows=_gloves_funnel_rows())

    resolved = resolve_product_retail_price(GLOVES_NM_ID, econ, tmp_path)

    assert isinstance(resolved, ResolvedRetailPrice)
    assert resolved.source == PRICE_SOURCE_FUNNEL
