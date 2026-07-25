"""Tests for dashboard recommendation summaries and max CPC prior flag (issue #14)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wb_advert.optimizer.rules import CPC_PRIOR_ESTIMATE, calc_keyword_max_cpc_kopecks, keyword_campaign_totals
from wb_advert.optimizer.summary import (
    pick_display_suggestion,
    recommendation_needs_attention,
    summarize_campaign,
)
from wb_advert.storage.pilot_store import build_product_rows, get_pilot_global_cr_prior

ADVERT_ID = 900_001
NM_ID = "900001001"
PRIMARY_KEYWORD = "main keyword"


def _patch_pilot_data_dir(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> None:
    monkeypatch.setattr("wb_advert.storage.pilot_store.pilot_data_dir", lambda: data_dir)


def _write_pilot_fixture(
    data_dir: Path,
    *,
    keywords: list[dict],
    primary_keyword: str = PRIMARY_KEYWORD,
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
                f"{NM_ID},,200,11,15.0,,,balanced",
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "config.yaml").write_text(
        "optimizer_mode: suggest-only\nallow_wb_writes: false\n",
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


def _keyword(
    *,
    keyword: str,
    clicks: int,
    orders: int = 0,
    cpc_kopecks: int = 500,
) -> dict:
    return {
        "keyword": keyword,
        "shows": 1000,
        "clicks": clicks,
        "orders": orders,
        "spend_kopecks": clicks * cpc_kopecks,
        "ctr_calculated": 10.0,
        "cpc_calculated_kopecks": cpc_kopecks,
        "current_bid_kopecks": 2000,
        "status": "managed",
    }


def test_pick_display_suggestion_prefers_primary_over_higher_priority_secondary() -> None:
    suggestions = [
        {
            "keyword": PRIMARY_KEYWORD,
            "action": "raise_bid",
            "reason_text": "CPC ниже потолка, есть запас",
        },
        {
            "keyword": "secondary keyword",
            "action": "lower_bid",
            "reason_text": "CPC выше max",
        },
    ]

    picked = pick_display_suggestion(suggestions, primary_keyword=PRIMARY_KEYWORD)

    assert picked is not None
    assert picked["action"] == "raise_bid"
    assert picked["keyword"] == PRIMARY_KEYWORD


def test_pick_display_suggestion_falls_back_to_highest_priority_without_primary_action() -> None:
    suggestions = [
        {
            "keyword": PRIMARY_KEYWORD,
            "action": "skip",
            "reason_text": "Недостаточно данных",
        },
        {
            "keyword": "secondary keyword",
            "action": "lower_bid",
            "reason_text": "CPC выше max",
        },
        {
            "keyword": "another secondary",
            "action": "raise_bid",
            "reason_text": "CPC ниже потолка",
        },
    ]

    picked = pick_display_suggestion(suggestions, primary_keyword=PRIMARY_KEYWORD)

    assert picked is not None
    assert picked["action"] == "lower_bid"


def test_summarize_campaign_keeps_actionable_count_and_shows_primary_action() -> None:
    suggestions = [
        {"keyword": PRIMARY_KEYWORD, "action": "raise_bid", "reason_text": "CPC ниже потолка"},
        {"keyword": "kw2", "action": "lower_bid", "reason_text": "CPC выше max"},
        {"keyword": "kw3", "action": "exclude_keyword", "reason_text": "Слабый ключ"},
        {"keyword": "kw4", "action": "lower_bid", "reason_text": "CPC выше max"},
        {"keyword": "kw5", "action": "promote_managed", "reason_text": "Готов к managed"},
    ]

    summary = summarize_campaign(
        advert_id=ADVERT_ID,
        nm_id=NM_ID,
        primary_keyword=PRIMARY_KEYWORD,
        suggestions=suggestions,
    )

    assert summary["action"] == "raise_bid"
    assert summary["actionable_count"] == 5
    assert summary["summary"].startswith("Поднять ставку")
    assert "ещё 4 действия" in summary["summary"]


def test_summarize_campaign_primary_keep_with_other_actions_mentions_count() -> None:
    suggestions = [
        {"keyword": PRIMARY_KEYWORD, "action": "keep", "reason_text": "Primary ключ с заказами и нормальным CTR"},
        {"keyword": "kw2", "action": "lower_bid", "reason_text": "CPC выше max"},
        {"keyword": "kw3", "action": "exclude_keyword", "reason_text": "Слабый ключ"},
        {"keyword": "kw4", "action": "promote_managed", "reason_text": "Готов к managed"},
    ]

    summary = summarize_campaign(
        advert_id=31_314_341,
        nm_id=NM_ID,
        primary_keyword=PRIMARY_KEYWORD,
        suggestions=suggestions,
    )

    assert summary["action"] == "keep"
    assert summary["actionable_count"] == 3
    assert summary["summary"] != "В норме"
    assert "ещё 3 действия" in summary["summary"]


def test_summarize_campaign_single_non_primary_action_not_lost_when_primary_keep() -> None:
    suggestions = [
        {"keyword": PRIMARY_KEYWORD, "action": "keep", "reason_text": "Primary ключ с заказами и нормальным CTR"},
        {"keyword": "secondary keyword", "action": "lower_bid", "reason_text": "CPC выше max"},
    ]

    summary = summarize_campaign(
        advert_id=36_713_559,
        nm_id=NM_ID,
        primary_keyword=PRIMARY_KEYWORD,
        suggestions=suggestions,
    )

    assert summary["action"] == "keep"
    assert summary["actionable_count"] == 1
    assert summary["summary"] != "В норме"
    assert "ещё 1 действие" in summary["summary"]


def test_summarize_campaign_actionable_count_independent_of_displayed_action() -> None:
    suggestions = [
        {"keyword": PRIMARY_KEYWORD, "action": "raise_bid", "reason_text": "CPC ниже потолка"},
        {"keyword": "kw2", "action": "lower_bid", "reason_text": "CPC выше max"},
        {"keyword": "kw3", "action": "exclude_keyword", "reason_text": "Слабый ключ"},
    ]

    summary = summarize_campaign(
        advert_id=ADVERT_ID,
        nm_id=NM_ID,
        primary_keyword=PRIMARY_KEYWORD,
        suggestions=suggestions,
    )

    assert summary["action"] == "raise_bid"
    assert summary["actionable_count"] == 3
    assert "ещё 2 действия" in summary["summary"]


def test_recommendation_needs_attention_follows_actionable_count() -> None:
    assert recommendation_needs_attention({"actionable_count": 0}) is False
    assert recommendation_needs_attention({"actionable_count": 1}) is True
    assert recommendation_needs_attention({"actionable_count": 3}) is True

    summary = summarize_campaign(
        advert_id=31_314_341,
        nm_id=NM_ID,
        primary_keyword=PRIMARY_KEYWORD,
        suggestions=[
            {"keyword": PRIMARY_KEYWORD, "action": "keep", "reason_text": "В норме по primary"},
            {"keyword": "kw2", "action": "lower_bid", "reason_text": "CPC выше max"},
        ],
    )

    assert summary["needs_attention"] is True
    assert recommendation_needs_attention(summary) is True


def test_build_product_rows_max_cpc_is_prior_matches_calc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keywords = [
        _keyword(keyword=PRIMARY_KEYWORD, clicks=3, orders=1),
        _keyword(keyword="filler", clicks=500, orders=100),
    ]
    _write_pilot_fixture(tmp_path, keywords=keywords)
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    row = build_product_rows(tmp_path)[0]
    global_cr = get_pilot_global_cr_prior(tmp_path)
    primary_kw = keywords[0]
    _, prior_alert = calc_keyword_max_cpc_kopecks(
        {"retail_price_rub": "200", "max_drr_pct": "15.0"},
        primary_kw,
        keyword_campaign_totals(keywords),
        global_cr,
    )

    assert prior_alert == CPC_PRIOR_ESTIMATE
    assert row["max_cpc_is_prior"] is True


def test_build_product_rows_max_cpc_is_prior_false_with_enough_clicks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keywords = [
        _keyword(keyword=PRIMARY_KEYWORD, clicks=40, orders=10),
        _keyword(keyword="filler", clicks=500, orders=100),
    ]
    _write_pilot_fixture(tmp_path, keywords=keywords)
    _patch_pilot_data_dir(monkeypatch, tmp_path)

    row = build_product_rows(tmp_path)[0]
    global_cr = get_pilot_global_cr_prior(tmp_path)
    primary_kw = keywords[0]
    _, prior_alert = calc_keyword_max_cpc_kopecks(
        {"retail_price_rub": "200", "max_drr_pct": "15.0"},
        primary_kw,
        keyword_campaign_totals(keywords),
        global_cr,
    )

    assert prior_alert is None
    assert row["max_cpc_is_prior"] is False
