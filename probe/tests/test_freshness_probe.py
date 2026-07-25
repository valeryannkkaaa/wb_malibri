"""Unit tests for probe/freshness_probe.py — no network."""

from __future__ import annotations

import csv
import fcntl
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

PROBE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROBE_DIR.parent))

from probe.freshness_probe import (  # noqa: E402
    CAMPAIGNS,
    CSV_COLUMNS,
    apply_retention,
    append_csv_rows,
    csv_header_line,
    msk_date_window,
    parse_fullstats_days,
    parse_normquery_totals,
    prod_cycle_running,
    run_probe_cycle,
)

FIXTURES = Path(__file__).parent / "fixtures"
MSK = ZoneInfo("Europe/Moscow")


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _hold_lock(lock_path: Path) -> int:
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def _release_lock_fd(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _run_cycle(tmp_path: Path, session: MagicMock, when: datetime) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text("WB_API_TOKEN=test-token\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    run_probe_cycle(
        data_dir=data_dir,
        env_path=env_file,
        prod_lock_path=tmp_path / "cycle.lock",
        now=when,
        session=session,
    )
    return data_dir / "flat" / f"probe_{when.date().isoformat()}.csv"


def _read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_parse_fullstats_days_normal() -> None:
    data = _load("fullstats_normal.json")
    rows = parse_fullstats_days(data, 31275686)
    assert len(rows) == 2
    assert rows[0] == {
        "bucket_date": "2026-07-24",
        "views": 1200,
        "clicks": 120,
        "sum": 455.5,
        "orders": 20,
    }
    assert rows[1]["bucket_date"] == "2026-07-25"
    assert len(parse_fullstats_days(data, 31314341)) == 2


def test_parse_fullstats_days_empty_days() -> None:
    assert parse_fullstats_days(_load("fullstats_empty_days.json"), 31275686) == []


def test_parse_fullstats_days_missing_sum() -> None:
    rows = parse_fullstats_days(_load("fullstats_missing_sum.json"), 31275686)
    assert len(rows) == 1
    assert rows[0]["sum"] is None
    assert rows[0]["views"] == 10


def test_parse_fullstats_days_no_days_key() -> None:
    assert parse_fullstats_days(_load("fullstats_no_days.json"), 31275686) == []


def test_msk_date_window_same_month() -> None:
    now = datetime(2026, 7, 25, 15, 30, tzinfo=MSK)
    begin, end = msk_date_window(now)
    assert begin == date(2026, 7, 24)
    assert end == date(2026, 7, 25)


def test_msk_date_window_month_boundary() -> None:
    now = datetime(2026, 7, 1, 0, 5, tzinfo=MSK)
    begin, end = msk_date_window(now)
    assert begin == date(2026, 6, 30)
    assert end == date(2026, 7, 1)


def test_parse_normquery_totals_includes_spend() -> None:
    totals = parse_normquery_totals(_load("normquery_sample.json"), 624468743)
    assert totals["views"] == 170
    assert totals["clicks"] == 15
    assert totals["orders"] == 3
    assert totals["spend"] == pytest.approx(75.5)
    assert totals["cpc_x_clicks"] == pytest.approx(75.0)
    assert totals["cpc"] == pytest.approx(5.0)


def test_retention_deletes_old_keeps_fresh(tmp_path: Path) -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    raw_old = tmp_path / "raw" / "2026-07-01"
    raw_fresh = tmp_path / "raw" / "2026-07-20"
    flat_old = tmp_path / "flat" / "probe_2026-07-01.csv"
    flat_fresh = tmp_path / "flat" / "probe_2026-07-20.csv"
    raw_old.mkdir(parents=True)
    raw_fresh.mkdir(parents=True)
    (tmp_path / "flat").mkdir(parents=True)
    (raw_old / "stale.json.gz").write_bytes(b"x")
    (raw_fresh / "fresh.json.gz").write_bytes(b"x")
    flat_old.write_text("old\n", encoding="utf-8")
    flat_fresh.write_text("fresh\n", encoding="utf-8")

    apply_retention(tmp_path, now=now)

    assert not raw_old.exists()
    assert raw_fresh.exists()
    assert not flat_old.exists()
    assert flat_fresh.exists()


def test_append_csv_rows_wires_header_rotation(tmp_path: Path) -> None:
    csv_path = tmp_path / "probe_2026-07-25.csv"
    csv_path.write_text(
        "probed_at_utc,advert_id,nm_id,bucket_date,bucket_hour,fs_views\nstale-row\n",
        encoding="utf-8",
    )
    fixed_now = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    row = {
        "probed_at_utc": "2026-07-25T10:00:00+00:00",
        "advert_id": 31275686,
        "nm_id": 624468743,
        "bucket_date": "2026-07-25",
        "fs_views": 2,
        "fs_clicks": 0,
        "fs_sum": 0.85,
        "fs_orders": 0,
        "nq_spend": 0.5,
        "skipped_tact": 0,
    }

    append_csv_rows(csv_path, [row], now=fixed_now)

    legacy_files = list(tmp_path.glob("probe_2026-07-25.legacy-*.csv"))
    assert len(legacy_files) == 1
    legacy_text = legacy_files[0].read_text(encoding="utf-8")
    assert "bucket_hour" in legacy_text
    assert "stale-row" in legacy_text

    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == csv_header_line()
    written = _read_csv_rows(csv_path)
    assert len(written) == 1
    assert written[0]["fs_views"] == "2"
    assert written[0]["fs_sum"] == "0.85"
    assert written[0]["nq_spend"] == "0.5"


def test_retention_deletes_old_legacy_keeps_fresh(tmp_path: Path) -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    flat = tmp_path / "flat"
    flat.mkdir(parents=True)
    old_legacy = flat / "probe_2026-07-01.legacy-20260701T120000Z.csv"
    fresh_legacy = flat / "probe_2026-07-20.legacy-20260720T120000Z.csv"
    old_legacy.write_text("old\n", encoding="utf-8")
    fresh_legacy.write_text("fresh\n", encoding="utf-8")

    apply_retention(tmp_path, now=now)

    assert not old_legacy.exists()
    assert fresh_legacy.exists()


def test_batch_fullstats_one_request_both_campaigns(tmp_path: Path) -> None:
    fs_body = json.dumps(_load("fullstats_normal.json")).encode()
    nq_body = json.dumps(_load("normquery_sample.json")).encode()
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=200, content=fs_body)
    session.post.return_value = MagicMock(status_code=200, content=nq_body)

    fixed_now = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    csv_path = _run_cycle(tmp_path, session, fixed_now)

    session.get.assert_called_once()
    ids_param = session.get.call_args.kwargs["params"]["ids"]
    assert ids_param == "31275686,31314341"

    rows = _read_csv_rows(csv_path)
    by_advert = {int(r["advert_id"]): r for r in rows if r["bucket_date"] == "2026-07-24"}
    assert by_advert[31275686]["fs_views"] == "1200"
    assert by_advert[31314341]["fs_views"] == "500"
    assert session.post.call_count == 2


def test_csv_row_contains_nq_spend_from_raw(tmp_path: Path) -> None:
    fs_body = json.dumps(_load("fullstats_normal.json")).encode()
    nq_body = json.dumps(_load("normquery_sample.json")).encode()
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=200, content=fs_body)
    session.post.return_value = MagicMock(status_code=200, content=nq_body)

    fixed_now = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    csv_path = _run_cycle(tmp_path, session, fixed_now)

    rows = _read_csv_rows(csv_path)
    camp1 = [r for r in rows if r["advert_id"] == "31275686"]
    assert camp1
    assert camp1[0]["nq_spend"] == "75.5"
    assert "nq_spend" in CSV_COLUMNS


def test_429_on_one_campaign_does_not_stop_others(tmp_path: Path) -> None:
    fs_body = json.dumps(_load("fullstats_normal.json")).encode()
    nq_ok = json.dumps(
        {
            "stats": [
                {
                    "nm_id": 629004626,
                    "stats": [
                        {"views": 10, "clicks": 2, "orders": 0, "cpc": 3.0, "spend": 6.0},
                    ],
                }
            ]
        }
    ).encode()

    session = MagicMock()
    session.get.return_value = MagicMock(status_code=200, content=fs_body)
    session.post.side_effect = [
        MagicMock(status_code=429, content=b'{"error":"too many requests"}'),
        MagicMock(status_code=200, content=nq_ok),
    ]

    fixed_now = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    csv_path = _run_cycle(tmp_path, session, fixed_now)

    assert session.get.call_count == 1
    assert session.post.call_count == 2
    rows = _read_csv_rows(csv_path)
    camp2 = [r for r in rows if r["advert_id"] == "31314341" and r["bucket_date"] == "2026-07-24"]
    assert camp2[0]["nq_spend"] == "6.0"
    camp1 = [r for r in rows if r["advert_id"] == "31275686"]
    assert camp1[0]["is_429"] == "1"


def test_fullstats_error_status_preserved_separate_from_normquery(tmp_path: Path) -> None:
    fs_body = b"internal error"
    nq_body = json.dumps(_load("normquery_sample.json")).encode()
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=500, content=fs_body)
    session.post.return_value = MagicMock(status_code=200, content=nq_body)

    fixed_now = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    csv_path = _run_cycle(tmp_path, session, fixed_now)

    row = _read_csv_rows(csv_path)[0]
    assert row["fs_status"] == "500"
    assert row["nq_status"] == "200"
    assert row["fs_views"] == ""
    assert row["nq_spend"] == "75.5"
    assert row["fs_duration_ms"] != ""
    assert row["nq_duration_ms"] != ""


def test_flock_busy_skips_exit_zero(tmp_path: Path) -> None:
    lock_file = tmp_path / "cycle.lock"
    holder = _hold_lock(lock_file)

    try:
        assert prod_cycle_running(lock_file) is True
        session = MagicMock()
        fixed_now = datetime(2026, 7, 25, 11, 0, tzinfo=timezone.utc)
        csv_path = _run_cycle(tmp_path, session, fixed_now)

        session.get.assert_not_called()
        session.post.assert_not_called()
        rows = _read_csv_rows(csv_path)
        assert len(rows) == len(CAMPAIGNS)
        assert all(r["skipped_tact"] == "1" for r in rows)
    finally:
        _release_lock_fd(holder)


def test_probe_does_not_hold_prod_lock_during_cycle(tmp_path: Path) -> None:
    lock_file = tmp_path / "cycle.lock"
    fs_body = json.dumps(_load("fullstats_normal.json")).encode()
    nq_body = json.dumps(_load("normquery_sample.json")).encode()
    lock_free_during: list[bool] = []

    session = MagicMock()

    def on_post(*_args, **_kwargs):
        lock_free_during.append(not prod_cycle_running(lock_file))
        return MagicMock(status_code=200, content=nq_body)

    session.get.return_value = MagicMock(status_code=200, content=fs_body)
    session.post.side_effect = on_post

    fixed_now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    _run_cycle(tmp_path, session, fixed_now)
    assert lock_free_during == [True, True]
