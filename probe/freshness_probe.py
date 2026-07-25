#!/usr/bin/env python3
"""Standalone WB API freshness probe — issue #20, spec docs/PROBE_FRESHNESS.md."""

from __future__ import annotations

import csv
import fcntl
import gzip
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

MSK = ZoneInfo("Europe/Moscow")
API_BASE = "https://advert-api.wildberries.ru"
FULLSTATS_PAUSE_SEC = 7.0
PROMOTION_PAUSE_SEC = 1.2
RETENTION_DAYS = 14

CAMPAIGNS: list[tuple[int, int]] = [
    (31275686, 624468743),  # перчатки
    (31314341, 629004626),  # тряпка для стёкол
]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "probe"
DEFAULT_ENV_PATH = Path("/opt/wb-advert/.env")
DEFAULT_PROD_LOCK = Path("/tmp/wb-advert-cycle.lock")

CSV_COLUMNS = [
    "probed_at_utc",
    "advert_id",
    "nm_id",
    "bucket_date",
    "bucket_hour",
    "fs_views",
    "fs_clicks",
    "fs_sum",
    "fs_orders",
    "nq_views",
    "nq_clicks",
    "nq_orders",
    "nq_cpc",
    "nq_cpc_x_clicks",
    "http_status",
    "duration_ms",
    "is_429",
    "skipped_tact",
]

log = logging.getLogger("freshness_probe")


def read_env_token(env_path: Path) -> str:
    if not env_path.is_file():
        raise FileNotFoundError(f"env file not found: {env_path}")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("WB_API_TOKEN="):
            continue
        value = line.split("=", 1)[1].strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        if value:
            return value
    raise RuntimeError("WB_API_TOKEN not found in env file")


def msk_date_window(now: datetime | None = None) -> tuple[date, date]:
    if now is None:
        now = datetime.now(MSK)
    else:
        now = now.astimezone(MSK)
    today = now.date()
    return today - timedelta(days=1), today


def _fullstats_campaigns(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        if "days" in data or "advertId" in data or "advert_id" in data:
            return [data]
        nested = data.get("adverts") or data.get("data") or []
        if isinstance(nested, list):
            return [x for x in nested if isinstance(x, dict)]
    return []


def parse_fullstats_hours(data: Any) -> list[dict[str, Any]]:
    """Return one dict per hourly bucket from days[].hours[]."""
    rows: list[dict[str, Any]] = []
    for campaign in _fullstats_campaigns(data):
        days = campaign.get("days")
        if not days:
            continue
        for day in days:
            if not isinstance(day, dict):
                continue
            bucket_date = str(day.get("date") or "")[:10]
            hours = day.get("hours")
            if not hours:
                continue
            for hour_row in hours:
                if not isinstance(hour_row, dict):
                    continue
                bucket_hour = hour_row.get("hour")
                if bucket_hour is None:
                    bucket_hour = hour_row.get("time") or hour_row.get("dt")
                rows.append(
                    {
                        "bucket_date": bucket_date,
                        "bucket_hour": bucket_hour,
                        "views": hour_row.get("views"),
                        "clicks": hour_row.get("clicks"),
                        "sum": hour_row.get("sum"),
                        "orders": hour_row.get("orders"),
                    }
                )
    return rows


def parse_normquery_totals(data: Any, nm_id: int) -> dict[str, Any]:
    """Aggregate normquery/stats for one nm_id (sum keywords, weighted cpc)."""
    totals = {
        "views": 0,
        "clicks": 0,
        "orders": 0,
        "cpc": None,
        "cpc_x_clicks": 0.0,
    }
    if not isinstance(data, dict):
        return totals

    blocks = data.get("stats") or []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        block_nm = block.get("nm_id") or block.get("nmId")
        if block_nm is not None and int(block_nm) != nm_id:
            continue
        inner = block.get("stats") or block.get("stat") or []
        if isinstance(inner, dict):
            inner = [inner]
        for item in inner or []:
            if not isinstance(item, dict):
                continue
            views = int(item.get("views") or 0)
            clicks = int(item.get("clicks") or 0)
            orders = int(item.get("orders") or 0)
            cpc = float(item.get("cpc") or 0)
            totals["views"] += views
            totals["clicks"] += clicks
            totals["orders"] += orders
            if clicks and cpc:
                totals["cpc_x_clicks"] += cpc * clicks

    if totals["clicks"] > 0 and totals["cpc_x_clicks"]:
        totals["cpc"] = totals["cpc_x_clicks"] / totals["clicks"]
    return totals


def apply_retention(data_dir: Path, *, days: int = RETENTION_DAYS, now: datetime | None = None) -> None:
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).date()

    for sub in ("raw", "flat"):
        root = data_dir / sub
        if not root.is_dir():
            continue
        for child in root.iterdir():
            name = child.name
            if sub == "raw":
                try:
                    folder_date = date.fromisoformat(name)
                except ValueError:
                    continue
                if folder_date < cutoff:
                    _rm_tree(child)
            elif sub == "flat" and name.startswith("probe_") and name.endswith(".csv"):
                stem = name[len("probe_") : -len(".csv")]
                try:
                    file_date = date.fromisoformat(stem)
                except ValueError:
                    continue
                if file_date < cutoff:
                    child.unlink(missing_ok=True)


def _rm_tree(path: Path) -> None:
    if path.is_dir():
        for child in path.iterdir():
            _rm_tree(child)
        path.rmdir()
    else:
        path.unlink(missing_ok=True)


def try_acquire_prod_lock(lock_path: Path) -> int | None:
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        os.close(fd)
        return None


def release_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def save_raw_gzip(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(payload)


def csv_path_for_day(data_dir: Path, day: date) -> Path:
    flat_dir = data_dir / "flat"
    flat_dir.mkdir(parents=True, exist_ok=True)
    return flat_dir / f"probe_{day.isoformat()}.csv"


def append_csv_rows(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _blank_row(
    probed_at: str,
    advert_id: int,
    nm_id: int,
    *,
    http_status: int | None = None,
    duration_ms: int | None = None,
    is_429: bool = False,
    skipped_tact: bool = False,
) -> dict[str, Any]:
    return {
        "probed_at_utc": probed_at,
        "advert_id": advert_id,
        "nm_id": nm_id,
        "bucket_date": "",
        "bucket_hour": "",
        "fs_views": "",
        "fs_clicks": "",
        "fs_sum": "",
        "fs_orders": "",
        "nq_views": "",
        "nq_clicks": "",
        "nq_orders": "",
        "nq_cpc": "",
        "nq_cpc_x_clicks": "",
        "http_status": http_status if http_status is not None else "",
        "duration_ms": duration_ms if duration_ms is not None else "",
        "is_429": int(is_429),
        "skipped_tact": int(skipped_tact),
    }


def build_hour_rows(
    probed_at: str,
    advert_id: int,
    nm_id: int,
    hour_buckets: list[dict[str, Any]],
    normquery: dict[str, Any],
    *,
    http_status: int,
    duration_ms: int,
    is_429: bool = False,
) -> list[dict[str, Any]]:
    base_nq = {
        "nq_views": normquery.get("views", 0),
        "nq_clicks": normquery.get("clicks", 0),
        "nq_orders": normquery.get("orders", 0),
        "nq_cpc": normquery.get("cpc") if normquery.get("cpc") is not None else "",
        "nq_cpc_x_clicks": normquery.get("cpc_x_clicks", 0),
        "http_status": http_status,
        "duration_ms": duration_ms,
        "is_429": int(is_429),
        "skipped_tact": 0,
    }
    if not hour_buckets:
        row = _blank_row(probed_at, advert_id, nm_id, http_status=http_status, duration_ms=duration_ms, is_429=is_429)
        row.update(base_nq)
        return [row]

    rows: list[dict[str, Any]] = []
    for bucket in hour_buckets:
        row = {
            "probed_at_utc": probed_at,
            "advert_id": advert_id,
            "nm_id": nm_id,
            "bucket_date": bucket.get("bucket_date", ""),
            "bucket_hour": bucket.get("bucket_hour", ""),
            "fs_views": bucket.get("views", ""),
            "fs_clicks": bucket.get("clicks", ""),
            "fs_sum": bucket.get("sum", ""),
            "fs_orders": bucket.get("orders", ""),
            **base_nq,
        }
        rows.append(row)
    return rows


def api_get_fullstats(
    session: requests.Session,
    token: str,
    advert_id: int,
    begin: date,
    end: date,
) -> tuple[int, bytes, float]:
    started = time.monotonic()
    resp = session.get(
        f"{API_BASE}/adv/v3/fullstats",
        headers={"Authorization": token},
        params={
            "ids": str(advert_id),
            "beginDate": begin.isoformat(),
            "endDate": end.isoformat(),
        },
        timeout=60,
    )
    elapsed = time.monotonic() - started
    return resp.status_code, resp.content, elapsed


def api_post_normquery_stats(
    session: requests.Session,
    token: str,
    advert_id: int,
    nm_id: int,
    begin: date,
    end: date,
) -> tuple[int, bytes, float]:
    started = time.monotonic()
    resp = session.post(
        f"{API_BASE}/adv/v0/normquery/stats",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={
            "from": begin.isoformat(),
            "to": end.isoformat(),
            "items": [{"advert_id": advert_id, "nm_id": nm_id}],
        },
        timeout=60,
    )
    elapsed = time.monotonic() - started
    return resp.status_code, resp.content, elapsed


def run_probe_cycle(
    *,
    data_dir: Path,
    env_path: Path,
    prod_lock_path: Path,
    now: datetime | None = None,
    session: requests.Session | None = None,
) -> int:
    if now is None:
        now = datetime.now(timezone.utc)
    probed_at = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    utc_day = now.astimezone(timezone.utc).date()
    tick = now.astimezone(timezone.utc).strftime("%H%M")
    csv_path = csv_path_for_day(data_dir, utc_day)

    apply_retention(data_dir, now=now)

    lock_fd = try_acquire_prod_lock(prod_lock_path)
    if lock_fd is None:
        log.info("skipped: prod cycle running")
        rows = [
            _blank_row(probed_at, advert_id, nm_id, skipped_tact=True)
            for advert_id, nm_id in CAMPAIGNS
        ]
        append_csv_rows(csv_path, rows)
        return 0

    own_session = session is None
    if own_session:
        session = requests.Session()

    try:
        token = read_env_token(env_path)
        begin, end = msk_date_window(now.astimezone(MSK))
        raw_root = data_dir / "raw" / utc_day.isoformat()
        all_rows: list[dict[str, Any]] = []
        got_429 = False

        for idx, (advert_id, nm_id) in enumerate(CAMPAIGNS):
            if idx > 0:
                time.sleep(FULLSTATS_PAUSE_SEC)

            status, body, elapsed = api_get_fullstats(session, token, advert_id, begin, end)
            save_raw_gzip(
                raw_root / f"{tick}_{advert_id}_fullstats.json.gz",
                body,
            )
            if status == 429:
                log.warning("fullstats advert_id=%s: HTTP 429, stopping cycle", advert_id)
                all_rows.append(
                    _blank_row(
                        probed_at,
                        advert_id,
                        nm_id,
                        http_status=status,
                        duration_ms=int(elapsed * 1000),
                        is_429=True,
                    )
                )
                got_429 = True
                break

            parsed_hours: list[dict[str, Any]] = []
            if status == 200:
                try:
                    parsed_hours = parse_fullstats_hours(json.loads(body.decode("utf-8")))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    log.exception("fullstats JSON decode failed advert_id=%s", advert_id)

            time.sleep(PROMOTION_PAUSE_SEC)
            nq_status, nq_body, nq_elapsed = api_post_normquery_stats(
                session, token, advert_id, nm_id, begin, end
            )
            save_raw_gzip(
                raw_root / f"{tick}_{advert_id}_normquery_stats.json.gz",
                nq_body,
            )
            if nq_status == 429:
                log.warning("normquery advert_id=%s: HTTP 429, stopping cycle", advert_id)
                all_rows.append(
                    _blank_row(
                        probed_at,
                        advert_id,
                        nm_id,
                        http_status=nq_status,
                        duration_ms=int(nq_elapsed * 1000),
                        is_429=True,
                    )
                )
                got_429 = True
                break

            normquery = {"views": 0, "clicks": 0, "orders": 0, "cpc": None, "cpc_x_clicks": 0.0}
            if nq_status == 200:
                try:
                    normquery = parse_normquery_totals(json.loads(nq_body.decode("utf-8")), nm_id)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    log.exception("normquery JSON decode failed advert_id=%s", advert_id)

            all_rows.extend(
                build_hour_rows(
                    probed_at,
                    advert_id,
                    nm_id,
                    parsed_hours,
                    normquery,
                    http_status=status,
                    duration_ms=int(elapsed * 1000),
                )
            )

            if idx < len(CAMPAIGNS) - 1:
                time.sleep(PROMOTION_PAUSE_SEC)

        append_csv_rows(csv_path, all_rows)
        if got_429:
            return 0
        log.info("probe cycle done: %s rows, raw in %s", len(all_rows), raw_root)
        return 0
    finally:
        release_lock(lock_fd)
        if own_session and session is not None:
            session.close()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    data_dir = Path(os.environ.get("PROBE_DATA_DIR", DEFAULT_DATA_DIR))
    env_path = Path(os.environ.get("WB_ENV_PATH", DEFAULT_ENV_PATH))
    prod_lock = Path(os.environ.get("WB_PROD_LOCK", DEFAULT_PROD_LOCK))
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    try:
        return run_probe_cycle(data_dir=data_dir, env_path=env_path, prod_lock_path=prod_lock)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1
    except Exception:
        log.exception("probe failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
