"""Unit tests for probe/freshness_probe.py — no network."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

PROBE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROBE_DIR.parent))

from probe.freshness_probe import (  # noqa: E402
    CAMPAIGNS,
    apply_retention,
    build_hour_rows,
    msk_date_window,
    parse_fullstats_hours,
    parse_normquery_totals,
    run_probe_cycle,
    try_acquire_prod_lock,
)

FIXTURES = Path(__file__).parent / "fixtures"
MSK = ZoneInfo("Europe/Moscow")


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_fullstats_hours_normal() -> None:
    rows = parse_fullstats_hours(_load("fullstats_normal.json"))
    assert len(rows) == 3
    assert rows[0] == {
        "bucket_date": "2026-07-24",
        "bucket_hour": 9,
        "views": 120,
        "clicks": 12,
        "sum": 45.5,
        "orders": 2,
    }
    assert rows[2]["bucket_hour"] == 8


def test_parse_fullstats_hours_empty_hours() -> None:
    assert parse_fullstats_hours(_load("fullstats_empty_hours.json")) == []


def test_parse_fullstats_hours_missing_sum() -> None:
    rows = parse_fullstats_hours(_load("fullstats_missing_sum.json"))
    assert len(rows) == 1
    assert rows[0]["sum"] is None
    assert rows[0]["views"] == 10


def test_parse_fullstats_hours_no_days() -> None:
    assert parse_fullstats_hours(_load("fullstats_no_days.json")) == []


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


def test_parse_normquery_totals() -> None:
    totals = parse_normquery_totals(_load("normquery_sample.json"), 624468743)
    assert totals["views"] == 150
    assert totals["clicks"] == 15
    assert totals["orders"] == 3
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


def test_429_writes_flag_no_retry(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("WB_API_TOKEN=test-token\n", encoding="utf-8")
    lock_file = tmp_path / "cycle.lock"
    data_dir = tmp_path / "data"

    session = MagicMock()
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.content = b'{"error":"too many requests"}'
    session.get.return_value = resp_429

    fixed_now = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    rc = run_probe_cycle(
        data_dir=data_dir,
        env_path=env_file,
        prod_lock_path=lock_file,
        now=fixed_now,
        session=session,
    )
    assert rc == 0
    session.get.assert_called_once()
    session.post.assert_not_called()

    csv_path = data_dir / "flat" / "probe_2026-07-25.csv"
    text = csv_path.read_text(encoding="utf-8")
    assert "is_429" in text
    assert ",1," in text or ",1\n" in text


def test_flock_busy_skips_exit_zero(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("WB_API_TOKEN=test-token\n", encoding="utf-8")
    lock_file = tmp_path / "cycle.lock"
    data_dir = tmp_path / "data"

    holder = try_acquire_prod_lock(lock_file)
    assert holder is not None

    try:
        fixed_now = datetime(2026, 7, 25, 11, 0, tzinfo=timezone.utc)
        session = MagicMock()
        rc = run_probe_cycle(
            data_dir=data_dir,
            env_path=env_file,
            prod_lock_path=lock_file,
            now=fixed_now,
            session=session,
        )
        assert rc == 0
        session.get.assert_not_called()
        session.post.assert_not_called()

        csv_path = data_dir / "flat" / "probe_2026-07-25.csv"
        lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1 + len(CAMPAIGNS)
        assert lines[-1].endswith(",0,1")
    finally:
        os.close(holder)
