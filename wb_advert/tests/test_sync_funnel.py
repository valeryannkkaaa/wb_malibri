"""Tests for WB nm-report funnel sync (issue #17)."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from pathlib import Path

from wb_advert.client.base import HttpResult
from wb_advert.schemas.wb_api import PilotSkuRow
from wb_advert.scripts.sync_funnel import (
    compute_funnel_period,
    merge_funnel_row,
    pick_rotate_nm_ids,
)
from wb_advert.storage.funnel_store import (
    funnel_path,
    load_funnel,
    merge_funnel_rows,
    save_funnel,
)
from wb_advert.sync.funnel_mappers import (
    extract_csv_from_zip,
    map_funnel_csv_row,
    parse_funnel_csv,
)
from wb_advert.sync.funnel_worker import FunnelWorker, INITIAL_LOOKBACK_DAYS


def _sample_csv_row() -> dict[str, str]:
    return {
        "nmID": "624468743",
        "dt": "2026-07-16",
        "openCardCount": "1130",
        "addToCartCount": "297",
        "ordersCount": "181",
        "ordersSumRub": "38915",
        "buyoutsCount": "143",
        "buyoutsSumRub": "30745",
        "cancelCount": "7",
        "cancelSumRub": "1505",
        "addToCartConversion": "26",
        "cartToOrderConversion": "61",
        "buyoutPercent": "95",
        "addToWishlist": "24",
        "currency": "RUB",
    }


def _csv_text(rows: list[dict[str, str]] | None = None) -> str:
    rows = rows or [_sample_csv_row()]
    header = ",".join(rows[0].keys())
    lines = [header]
    for row in rows:
        lines.append(",".join(row.values()))
    return "\n".join(lines)


def _zip_with_csv(csv_text: str, name: str = "report.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, csv_text)
    return buf.getvalue()


def test_map_funnel_csv_row_flattens_fields() -> None:
    flat = map_funnel_csv_row(_sample_csv_row())

    assert flat["nm_id"] == 624468743
    assert flat["dt"] == "2026-07-16"
    assert flat["open_card_count"] == 1130
    assert flat["orders_sum_rub"] == 38915
    assert flat["buyout_percent"] == 95
    assert flat["currency"] == "RUB"


def test_merge_funnel_rows_keeps_old_and_dedupes_by_dt() -> None:
    existing = [
        {"dt": "2026-07-15", "orders_count": 10},
        {"dt": "2026-07-16", "orders_count": 100},
    ]
    new_rows = [
        {"dt": "2026-07-16", "orders_count": 181},
        {"dt": "2026-07-17", "orders_count": 163},
    ]

    merged = merge_funnel_rows(existing, new_rows)

    assert [r["dt"] for r in merged] == ["2026-07-15", "2026-07-16", "2026-07-17"]
    assert merged[1]["orders_count"] == 181
    assert merged[0]["orders_count"] == 10


def test_compute_funnel_period_initial_lookback(tmp_path: Path) -> None:
    start, end = compute_funnel_period(624468743, tmp_path, end=date(2026, 7, 23))

    assert end == date(2026, 7, 23)
    assert (end - start).days == INITIAL_LOOKBACK_DAYS


def test_compute_funnel_period_incremental_from_last_row(tmp_path: Path) -> None:
    save_funnel(
        624468743,
        period={"start": "2025-07-23", "end": "2026-07-22"},
        rows=[{"dt": "2026-07-20", "orders_count": 1}, {"dt": "2026-07-22", "orders_count": 2}],
        data_dir=tmp_path,
    )

    start, end = compute_funnel_period(624468743, tmp_path, end=date(2026, 7, 23))

    assert start == date(2026, 7, 22)
    assert end == date(2026, 7, 23)


def test_save_funnel_incremental_merges_without_duplicates(tmp_path: Path) -> None:
    save_funnel(
        624468743,
        period={"start": "2026-07-15", "end": "2026-07-16"},
        rows=[{"dt": "2026-07-16", "orders_count": 100}],
        data_dir=tmp_path,
    )
    save_funnel(
        624468743,
        period={"start": "2026-07-16", "end": "2026-07-17"},
        rows=[
            {"dt": "2026-07-16", "orders_count": 181},
            {"dt": "2026-07-17", "orders_count": 163},
        ],
        data_dir=tmp_path,
    )

    data = load_funnel(624468743, tmp_path)
    assert data is not None
    assert len(data["rows"]) == 2
    assert data["rows"][0]["orders_count"] == 181


def test_poll_timeout_does_not_erase_saved_funnel(tmp_path: Path) -> None:
    period = {"start": "2026-07-16", "end": "2026-07-22"}
    save_funnel(
        624468743,
        period=period,
        rows=[{"dt": "2026-07-16", "orders_count": 181}],
        data_dir=tmp_path,
    )
    before = funnel_path(624468743, tmp_path).read_text(encoding="utf-8")

    class PendingAnalytics:
        def nm_report_download_status(self, download_ids):
            payload = {"data": [{"id": download_ids[0], "status": "PROCESSING"}]}
            return HttpResult(200, json.dumps(payload))

    worker = FunnelWorker(
        analytics=PendingAnalytics(),
        max_poll_attempts=2,
        poll_interval_sec=0,
    )
    rows, errors, pending = worker.fetch_nm_funnel(
        624468743,
        date(2026, 7, 16),
        date(2026, 7, 22),
        pending_download_id="existing-uuid",
    )

    assert rows == []
    assert pending == "existing-uuid"
    assert any("timeout" in e for e in errors)
    assert funnel_path(624468743, tmp_path).read_text(encoding="utf-8") == before


def test_bad_zip_does_not_erase_saved_funnel(tmp_path: Path) -> None:
    save_funnel(
        624468743,
        period={"start": "2026-07-16", "end": "2026-07-22"},
        rows=[{"dt": "2026-07-16", "orders_count": 181}],
        data_dir=tmp_path,
    )
    before = funnel_path(624468743, tmp_path).read_text(encoding="utf-8")

    class BadZipAnalytics:
        def nm_report_download_status(self, download_ids):
            payload = {"data": [{"id": download_ids[0], "status": "SUCCESS"}]}
            return HttpResult(200, json.dumps(payload))

        def nm_report_download_file(self, download_id):
            return 200, b"not-a-zip", None

    worker = FunnelWorker(analytics=BadZipAnalytics(), poll_interval_sec=0)
    rows, errors, pending = worker.fetch_nm_funnel(
        624468743,
        date(2026, 7, 16),
        date(2026, 7, 22),
        pending_download_id="done-uuid",
    )

    assert rows == []
    assert pending is None
    assert any("invalid or empty zip" in e for e in errors)
    assert funnel_path(624468743, tmp_path).read_text(encoding="utf-8") == before


def test_empty_csv_does_not_erase_saved_funnel(tmp_path: Path) -> None:
    save_funnel(
        624468743,
        period={"start": "2026-07-16", "end": "2026-07-22"},
        rows=[{"dt": "2026-07-16", "orders_count": 181}],
        data_dir=tmp_path,
    )
    before = funnel_path(624468743, tmp_path).read_text(encoding="utf-8")
    zip_bytes = _zip_with_csv("nmID,dt\n")

    class EmptyCsvAnalytics:
        def nm_report_download_status(self, download_ids):
            payload = {"data": [{"id": download_ids[0], "status": "SUCCESS"}]}
            return HttpResult(200, json.dumps(payload))

        def nm_report_download_file(self, download_id):
            return 200, zip_bytes, None

    worker = FunnelWorker(analytics=EmptyCsvAnalytics(), poll_interval_sec=0)
    rows, errors, pending = worker.fetch_nm_funnel(
        624468743,
        date(2026, 7, 16),
        date(2026, 7, 22),
        pending_download_id="done-uuid",
    )

    assert rows == []
    assert pending is None
    assert any("empty CSV" in e for e in errors)
    assert funnel_path(624468743, tmp_path).read_text(encoding="utf-8") == before


def test_fetch_nm_funnel_full_cycle_with_fake_client() -> None:
    download_id = "test-uuid"
    csv_text = _csv_text(
        [
            _sample_csv_row(),
            {**_sample_csv_row(), "dt": "2026-07-17", "ordersCount": "163"},
        ],
    )
    zip_bytes = _zip_with_csv(csv_text)
    calls: list[str] = []

    class FakeAnalytics:
        def nm_report_create_download(self, report_id, nm_ids, start, end, **kwargs):
            calls.append("create")
            assert report_id == download_id or report_id  # worker generates uuid
            assert nm_ids == [624468743]
            return HttpResult(200, "{}")

        def nm_report_download_status(self, download_ids):
            calls.append("status")
            payload = {"data": [{"id": download_ids[0], "status": "SUCCESS"}]}
            return HttpResult(200, json.dumps(payload))

        def nm_report_download_file(self, report_id):
            calls.append("download")
            return 200, zip_bytes, None

    worker = FunnelWorker(analytics=FakeAnalytics(), poll_interval_sec=0)
    rows, errors, pending = worker.fetch_nm_funnel(
        624468743,
        date(2026, 7, 16),
        date(2026, 7, 22),
    )

    assert pending is None
    assert errors == []
    assert len(rows) == 2
    assert rows[0]["dt"] == "2026-07-16"
    assert calls[0] == "create"
    assert "status" in calls
    assert calls[-1] == "download"


def test_fetch_nm_funnel_resumes_pending_without_create() -> None:
    calls: list[str] = []

    class FakeAnalytics:
        def nm_report_create_download(self, *args, **kwargs):
            calls.append("create")
            return HttpResult(200, "{}")

        def nm_report_download_status(self, download_ids):
            calls.append("status")
            payload = {"data": [{"id": download_ids[0], "status": "SUCCESS"}]}
            return HttpResult(200, json.dumps(payload))

        def nm_report_download_file(self, download_id):
            calls.append("download")
            return 200, _zip_with_csv(_csv_text()), None

    worker = FunnelWorker(analytics=FakeAnalytics(), poll_interval_sec=0)
    rows, errors, pending = worker.fetch_nm_funnel(
        624468743,
        date(2026, 7, 16),
        date(2026, 7, 22),
        pending_download_id="resume-me",
    )

    assert rows
    assert errors == []
    assert pending is None
    assert "create" not in calls


def test_extract_csv_from_zip_parses_sample() -> None:
    csv_text = _csv_text()
    parsed = parse_funnel_csv(extract_csv_from_zip(_zip_with_csv(csv_text)) or "")

    assert len(parsed) == 1
    assert parsed[0]["orders_count"] == 181


def _sku(nm_id: str) -> PilotSkuRow:
    return PilotSkuRow(nm_id=nm_id, wb_campaign_search=1)


def test_pick_rotate_nm_ids_prefers_never_attempted(tmp_path: Path) -> None:
    report = tmp_path / "last_funnel_sync.json"
    report.write_text(
        json.dumps(
            {
                "synced_at": "2026-07-21T16:00:00+00:00",
                "products": [
                    {"nm_id": 111, "rows": 10, "last_attempt_at": "2026-07-06T11:00:00+00:00"},
                    {"nm_id": 333, "rows": 10, "last_attempt_at": "2026-07-21T16:00:00+00:00"},
                ],
            },
        ),
        encoding="utf-8",
    )
    ready = [_sku("111"), _sku("222"), _sku("333")]

    picked = pick_rotate_nm_ids(ready, report, limit=1)

    assert [int(s.nm_id) for s in picked] == [222]


def test_merge_funnel_row_failed_attempt_preserves_synced_at() -> None:
    merged = merge_funnel_row(
        {"nm_id": 624468743, "rows": 365, "synced_at": "2026-07-20T10:00:00+00:00"},
        {
            "nm_id": 624468743,
            "rows": 0,
            "errors": ["nm-report poll: timeout"],
            "pending_download_id": "still-pending",
        },
        now="2026-07-23T12:00:00+00:00",
    )

    assert merged["rows"] == 0
    assert merged["pending_download_id"] == "still-pending"
    assert merged["synced_at"] == "2026-07-20T10:00:00+00:00"
    assert merged["last_attempt_at"] == "2026-07-23T12:00:00+00:00"
