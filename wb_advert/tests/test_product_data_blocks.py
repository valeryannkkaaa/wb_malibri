"""Tests for product page data blocks (issue #19)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wb_advert.storage.funnel_store import save_funnel
from wb_advert.storage.search_report_store import save_search_report
from wb_advert.ui.jinja_env import templates
from wb_advert.ui.product_blocks import build_product_extra_blocks, funnel_period_summary


ADVERT_ID = 900_019
NM_ID = 900019001


def _minimal_product_context() -> dict:
    return {
        "advert_id": ADVERT_ID,
        "nm_id": NM_ID,
        "primary_keyword": "перчатки для уборки",
        "target_grade": "top_1_3",
        "schedule": "always_on",
        "stock_quantity": 12,
        "keywords": [],
    }


def _render_product_page(**overrides) -> str:
    context = {
        "p": _minimal_product_context(),
        "opt": {"suggestions": [], "alerts": [], "mode": "suggest-only"},
        "keywords_sorted": [],
        "position_history": [],
        "pos_chart_json": json.dumps({"labels": [], "values": []}),
        "ctr_chart_json": json.dumps({"labels": [], "values": []}),
        "active": "dashboard",
    }
    context.update(overrides)
    return templates.env.get_template("product.html").render(**context)


def test_funnel_period_summary_uses_available_days_when_history_shorter_than_window() -> None:
    rows = [
        {
            "dt": "2026-07-21",
            "orders_count": 10,
            "orders_sum_rub": 1000,
            "add_to_cart_conversion": 20,
            "cart_to_order_conversion": 50,
            "buyout_percent": 90,
        },
        {
            "dt": "2026-07-22",
            "orders_count": 20,
            "orders_sum_rub": 3000,
            "add_to_cart_conversion": 30,
            "cart_to_order_conversion": 60,
            "buyout_percent": 80,
        },
        {
            "dt": "2026-07-23",
            "orders_count": 30,
            "orders_sum_rub": 6000,
            "add_to_cart_conversion": 40,
            "cart_to_order_conversion": 70,
            "buyout_percent": 70,
        },
    ]

    summary_7d = funnel_period_summary(rows, 7)
    summary_30d = funnel_period_summary(rows, 30)

    assert summary_7d is not None
    assert summary_7d["days"] == 3
    assert summary_7d["orders"] == 60
    assert summary_7d["revenue"] == 10000
    assert summary_7d["avg_check"] == round(10000 / 60, 2)
    assert summary_7d["add_to_cart_conversion"] == 33.3
    assert summary_7d["cart_to_order_conversion"] == 63.3
    assert summary_7d["buyout_percent"] == 76.7
    assert summary_30d == summary_7d


def test_funnel_period_summary_weights_percent_fields_by_orders() -> None:
    rows = [
        {
            "dt": "2026-07-22",
            "orders_count": 1,
            "orders_sum_rub": 100,
            "buyout_percent": 50,
            "add_to_cart_conversion": 10,
            "cart_to_order_conversion": 10,
        },
        {
            "dt": "2026-07-23",
            "orders_count": 100,
            "orders_sum_rub": 10000,
            "buyout_percent": 95,
            "add_to_cart_conversion": 90,
            "cart_to_order_conversion": 90,
        },
    ]

    summary = funnel_period_summary(rows, 7)

    assert summary is not None
    assert summary["buyout_percent"] == 94.6
    assert summary["buyout_percent"] > 90
    assert summary["cart_to_order_conversion"] == 89.2
    assert summary["add_to_cart_conversion"] == 89.2


def test_funnel_period_summary_limits_to_requested_window() -> None:
    rows = [
        {"dt": f"2026-07-{day:02d}", "orders_count": day, "orders_sum_rub": day * 100}
        for day in range(1, 11)
    ]

    summary_7d = funnel_period_summary(rows, 7)

    assert summary_7d is not None
    assert summary_7d["days"] == 7
    assert summary_7d["orders"] == sum(range(4, 11))
    assert summary_7d["revenue"] == sum(day * 100 for day in range(4, 11))


def test_product_page_renders_without_any_extra_data_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("wb_advert.ui.product_blocks.pilot_data_dir", lambda: tmp_path)

    html = _render_product_page()

    assert "Соседи по выдаче" in html
    assert "Поисковые запросы" in html
    assert "Динамика продаж" in html
    assert "Данных по соседям в выдаче пока нет" in html
    assert "Поисковый отчёт для этой карточки ещё не загружен" in html
    assert "История воронки для этой карточки ещё не загружена" in html
    assert "Кампания 900019" in html


def test_product_page_renders_with_partial_data_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("wb_advert.ui.product_blocks.pilot_data_dir", lambda: tmp_path)
    sync_dir = tmp_path / "sync"
    competitors_dir = sync_dir / "competitors"
    competitors_dir.mkdir(parents=True)
    (competitors_dir / "competitors_2026-07-23.jsonl").write_text(
        json.dumps(
            {
                "nm_id": NM_ID,
                "keyword": "перчатки для уборки",
                "our_in_slice": True,
                "competitors_slice": [
                    {
                        "nm_id": 111,
                        "position": 1,
                        "brand": "Other",
                        "price_rub": 99.0,
                        "rating": 4.5,
                        "feedbacks": 10,
                        "is_ours": False,
                    },
                    {
                        "nm_id": NM_ID,
                        "position": 2,
                        "brand": "Dora",
                        "price_rub": 136.0,
                        "rating": 4.9,
                        "feedbacks": 2236,
                        "is_ours": True,
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    save_search_report(
        NM_ID,
        period={"start": "2026-07-16", "end": "2026-07-22"},
        items=[
            {
                "text": "перчатки для уборки",
                "week_frequency": 9915,
                "median_position": 1,
                "visibility": 100,
                "orders": 398,
                "cart_to_order": 54,
                "orders_percentile": 85,
            }
        ],
        data_dir=tmp_path,
    )

    html = _render_product_page()
    blocks = build_product_extra_blocks(NM_ID, tmp_path)

    assert blocks["competitors"]["available"] is True
    assert blocks["search_report"]["available"] is True
    assert blocks["funnel"]["available"] is False
    assert "дороже медианы соседей" in html
    assert "перчатки для уборки" in html
    assert 'class="pos-ok"' in html
    assert "История воронки для этой карточки ещё не загружена" in html


def test_product_page_renders_with_all_data_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("wb_advert.ui.product_blocks.pilot_data_dir", lambda: tmp_path)
    save_funnel(
        NM_ID,
        period={"start": "2026-07-16", "end": "2026-07-23"},
        rows=[
            {
                "dt": "2026-07-22",
                "orders_count": 20,
                "orders_sum_rub": 3000,
                "buyouts_count": 15,
                "buyout_percent": 80,
                "add_to_cart_conversion": 30,
                "cart_to_order_conversion": 60,
            },
            {
                "dt": "2026-07-23",
                "orders_count": 30,
                "orders_sum_rub": 6000,
                "buyouts_count": 20,
                "buyout_percent": 70,
                "add_to_cart_conversion": 40,
                "cart_to_order_conversion": 70,
            },
        ],
        data_dir=tmp_path,
    )

    html = _render_product_page()
    blocks = build_product_extra_blocks(NM_ID, tmp_path)

    assert blocks["funnel"]["available"] is True
    assert blocks["funnel"]["summary_7d"]["orders"] == 50
    assert "Сводка · 7 дней" in html
    assert "2026-07-23" in html
    assert "Данных по соседям в выдаче пока нет" in html
