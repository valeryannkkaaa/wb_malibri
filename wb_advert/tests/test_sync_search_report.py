"""Tests for WB search-report sync (issue #15)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from wb_advert.client.base import HttpResult
from wb_advert.schemas.wb_api import PilotSkuRow
from wb_advert.scripts.sync_search_report import (
    merge_search_report_row,
    pick_rotate_nm_ids,
)
from wb_advert.storage.search_report_store import (
    load_search_report,
    save_search_report,
    search_report_path,
)
from wb_advert.sync.search_report_mappers import map_search_text_item
from wb_advert.sync.search_report_worker import MAX_PAGES, PAGE_SIZE, SearchReportWorker


def _sample_wb_row() -> dict:
    return {
        "text": "перчатки для уборки",
        "frequency": {"current": 9915, "percentile": 88},
        "weekFrequency": 9915,
        "medianPosition": {"current": 1, "percentile": 99},
        "avgPosition": {"current": 2, "percentile": 95},
        "visibility": {"current": 100, "percentile": 90},
        "openCard": {"current": 500, "percentile": 80},
        "addToCart": {"current": 210, "percentile": 75},
        "orders": {"current": 398, "percentile": 85},
        "openToCart": {"current": 42, "percentile": 70},
        "cartToOrder": {"current": 54, "percentile": 65},
        "price": {"minPrice": 120, "maxPrice": 250},
        "rating": 4.8,
        "feedbackRating": 4.7,
    }


def test_map_search_text_item_flattens_nested_fields() -> None:
    flat = map_search_text_item(_sample_wb_row())

    assert flat["text"] == "перчатки для уборки"
    assert flat["frequency"] == 9915
    assert flat["frequency_percentile"] == 88
    assert flat["week_frequency"] == 9915
    assert flat["median_position"] == 1
    assert flat["median_position_percentile"] == 99
    assert flat["open_to_cart"] == 42
    assert flat["cart_to_order"] == 54
    assert flat["min_price"] == 120
    assert flat["max_price"] == 250
    assert flat["rating"] == 4.8
    assert flat["feedback_rating"] == 4.7
    assert "current" not in json.dumps(flat)


def test_map_search_text_item_handles_missing_median_position() -> None:
    row = _sample_wb_row()
    del row["medianPosition"]

    flat = map_search_text_item(row)

    assert "median_position" not in flat
    assert "median_position_percentile" not in flat
    assert flat["avg_position"] == 2


def _sku(nm_id: str) -> PilotSkuRow:
    return PilotSkuRow(nm_id=nm_id, wb_campaign_search=1)


def _write_search_report_sync_report(path: Path, products: list[dict]) -> None:
    path.write_text(
        json.dumps({"synced_at": "2026-07-21T16:00:00+00:00", "products": products}),
        encoding="utf-8",
    )


def test_pick_rotate_nm_ids_prefers_never_attempted(tmp_path: Path) -> None:
    report = tmp_path / "last_search_report_sync.json"
    _write_search_report_sync_report(
        report,
        [
            {"nm_id": 111, "items": 10, "last_attempt_at": "2026-07-06T11:00:00+00:00"},
            {"nm_id": 333, "items": 10, "last_attempt_at": "2026-07-21T16:00:00+00:00"},
        ],
    )
    ready = [_sku("111"), _sku("222"), _sku("333")]

    picked = pick_rotate_nm_ids(ready, report, limit=1)

    assert [int(s.nm_id) for s in picked] == [222]


def test_pick_rotate_nm_ids_failed_attempt_does_not_block_queue(tmp_path: Path) -> None:
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    (sync_dir / "search_report_35704170.json").write_text(
        json.dumps({"synced_at": "2026-07-06T11:40:03+00:00"}),
        encoding="utf-8",
    )
    report = tmp_path / "last_search_report_sync.json"
    _write_search_report_sync_report(
        report,
        [
            {
                "nm_id": 35704170,
                "items": 0,
                "last_attempt_at": "2026-07-21T17:00:00+00:00",
            },
            {"nm_id": 31275686, "items": 39},
            {"nm_id": 33206165, "items": 46},
        ],
    )
    ready = [_sku("35704170"), _sku("31275686"), _sku("33206165")]

    picked = pick_rotate_nm_ids(ready, report, limit=3)

    assert int(picked[0].nm_id) != 35704170


def test_failed_attempt_preserves_saved_search_report(tmp_path: Path) -> None:
    period = {"start": "2026-07-16", "end": "2026-07-22"}
    save_search_report(
        624468743,
        period=period,
        items=[{"text": "перчатки для уборки", "orders": 398}],
        data_dir=tmp_path,
    )
    before = load_search_report(624468743, tmp_path)
    assert before is not None

    merged = merge_search_report_row(
        {"nm_id": 624468743, "items": 1, "synced_at": before["synced_at"]},
        {
            "nm_id": 624468743,
            "items": 0,
            "errors": ["search-texts: HTTP 500 server error"],
        },
        now="2026-07-23T12:00:00+00:00",
    )

    assert merged["items"] == 0
    assert merged["last_attempt_at"] == "2026-07-23T12:00:00+00:00"
    assert merged["synced_at"] == before["synced_at"]
    assert load_search_report(624468743, tmp_path) == before


def test_empty_response_does_not_erase_saved_search_report(tmp_path: Path) -> None:
    period = {"start": "2026-07-16", "end": "2026-07-22"}
    save_search_report(
        624468743,
        period=period,
        items=[{"text": "перчатки резиновые", "orders": 16}],
        data_dir=tmp_path,
    )
    before_mtime = search_report_path(624468743, tmp_path).read_text(encoding="utf-8")

    result = save_search_report(624468743, period=period, items=[], data_dir=tmp_path)

    assert result is None
    assert search_report_path(624468743, tmp_path).read_text(encoding="utf-8") == before_mtime


def test_fetch_nm_search_texts_paginates_with_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    class FakeAnalytics:
        def search_report_product_search_texts(self, begin, end, nm_ids, *, limit=50, offset=0, **kwargs):
            calls.append(offset)
            if offset == 0:
                payload = {"data": {"items": [{"text": f"kw{i}"} for i in range(50)]}}
            else:
                payload = {"data": {"items": [{"text": "extra keyword"}]}}
            return HttpResult(200, json.dumps(payload))

    worker = SearchReportWorker(analytics=FakeAnalytics())
    items, errors = worker.fetch_nm_search_texts(
        624468743,
        date(2026, 7, 16),
        date(2026, 7, 22),
    )

    assert errors == []
    assert len(items) == 51
    assert calls == [0, 50]


def test_fetch_nm_search_texts_http_error_does_not_return_partial_data() -> None:
    class FakeAnalytics:
        def search_report_product_search_texts(self, begin, end, nm_ids, *, limit=50, offset=0, **kwargs):
            if offset == 0:
                payload = {"data": {"items": [{"text": f"kw{i}"} for i in range(50)]}}
                return HttpResult(200, json.dumps(payload))
            return HttpResult(500, "server error")

    worker = SearchReportWorker(analytics=FakeAnalytics())
    items, errors = worker.fetch_nm_search_texts(
        624468743,
        date(2026, 7, 16),
        date(2026, 7, 22),
    )

    assert items == []
    assert errors and "HTTP 500" in errors[0]


def test_fetch_nm_search_texts_stops_at_max_pages_when_api_never_short_pages() -> None:
    calls: list[int] = []

    class FakeAnalytics:
        def search_report_product_search_texts(self, begin, end, nm_ids, *, limit=50, offset=0, **kwargs):
            calls.append(offset)
            payload = {"data": {"items": [{"text": f"kw{offset}-{i}"} for i in range(PAGE_SIZE)]}}
            return HttpResult(200, json.dumps(payload))

    worker = SearchReportWorker(analytics=FakeAnalytics())
    items, errors = worker.fetch_nm_search_texts(
        624468743,
        date(2026, 7, 16),
        date(2026, 7, 22),
    )

    assert len(calls) == MAX_PAGES
    assert len(items) == MAX_PAGES * PAGE_SIZE
    assert errors
    assert "pagination stopped" in errors[0]
