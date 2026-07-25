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
    "fs_views",
    "fs_clicks",
    "fs_sum",
    "fs_orders",
    "nq_views",
    "nq_clicks",
    "nq_orders",
    "nq_cpc",
    "nq_spend",
    "nq_cpc_x_clicks",
    "fs_status",
    "fs_duration_ms",
    "nq_status",
    "nq_duration_ms",
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


def _campaign_advert_id(campaign: dict[str, Any]) -> int | None:
    raw = campaign.get("advertId") or campaign.get("advert_id")
    return int(raw) if raw is not None else None


def parse_fullstats_days(data: Any, advert_id: int) -> list[dict[str, Any]]:
    """Return one dict per daily bucket from days[] for a campaign."""
    rows: list[dict[str, Any]] = []
    for campaign in _fullstats_campaigns(data):
        cid = _campaign_advert_id(campaign)
        if cid is not None and cid != advert_id:
            continue
        days = campaign.get("days")
        if not days:
            continue
        for day in days:
            if not isinstance(day, dict):
                continue
            rows.append(
                {
                    "bucket_date": str(day.get("date") or "")[:10],
                    "views": day.get("views"),
                    "clicks": day.get("clicks"),
                    "sum": day.get("sum"),
                    "orders": day.get("orders"),
                }
            )
    return rows


def parse_normquery_totals(data: Any, nm_id: int) -> dict[str, Any]:
    """Aggregate normquery/stats for one nm_id (sum keywords, weighted cpc)."""
    totals = {
        "views": 0,
        "clicks": 0,
        "orders": 0,
        "spend": 0.0,
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
            spend = float(item.get("spend") or 0)
            totals["views"] += views
            totals["clicks"] += clicks
            totals["orders"] += orders
            totals["spend"] += spend
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
                if ".legacy-" in name:
                    continue
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


def prod_cycle_running(lock_path: Path) -> bool:
    """Non-blocking check: True if prod holds the lock. Never keeps the lock."""
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o666)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True
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


def csv_header_line() -> str:
    return ",".join(CSV_COLUMNS)


def csv_header_matches(csv_path: Path) -> bool:
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return True
    first_line = csv_path.read_text(encoding="utf-8").splitlines()[0]
    return first_line == csv_header_line()


def rotate_csv_if_header_mismatch(csv_path: Path, now: datetime | None = None) -> Path | None:
    if csv_header_matches(csv_path):
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    legacy = csv_path.with_name(f"{csv_path.stem}.legacy-{stamp}{csv_path.suffix}")
    csv_path.rename(legacy)
    log.warning("CSV schema changed, rotated %s -> %s", csv_path.name, legacy.name)
    return legacy


def append_csv_rows(
    csv_path: Path,
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> None:
    rotate_csv_if_header_mismatch(csv_path, now=now)
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
    fs_status: int | None = None,
    fs_duration_ms: int | None = None,
    nq_status: int | None = None,
    nq_duration_ms: int | None = None,
    is_429: bool = False,
    skipped_tact: bool = False,
) -> dict[str, Any]:
    return {
        "probed_at_utc": probed_at,
        "advert_id": advert_id,
        "nm_id": nm_id,
        "bucket_date": "",
        "fs_views": "",
        "fs_clicks": "",
        "fs_sum": "",
        "fs_orders": "",
        "nq_views": "",
        "nq_clicks": "",
        "nq_orders": "",
        "nq_cpc": "",
        "nq_spend": "",
        "nq_cpc_x_clicks": "",
        "fs_status": fs_status if fs_status is not None else "",
        "fs_duration_ms": fs_duration_ms if fs_duration_ms is not None else "",
        "nq_status": nq_status if nq_status is not None else "",
        "nq_duration_ms": nq_duration_ms if nq_duration_ms is not None else "",
        "is_429": int(is_429),
        "skipped_tact": int(skipped_tact),
    }


def build_day_rows(
    probed_at: str,
    advert_id: int,
    nm_id: int,
    day_buckets: list[dict[str, Any]],
    normquery: dict[str, Any],
    *,
    fs_status: int | None,
    fs_duration_ms: int | None,
    nq_status: int | None,
    nq_duration_ms: int | None,
    is_429: bool = False,
) -> list[dict[str, Any]]:
    base = {
        "nq_views": normquery.get("views", 0),
        "nq_clicks": normquery.get("clicks", 0),
        "nq_orders": normquery.get("orders", 0),
        "nq_cpc": normquery.get("cpc") if normquery.get("cpc") is not None else "",
        "nq_spend": normquery.get("spend", 0),
        "nq_cpc_x_clicks": normquery.get("cpc_x_clicks", 0),
        "fs_status": fs_status if fs_status is not None else "",
        "fs_duration_ms": fs_duration_ms if fs_duration_ms is not None else "",
        "nq_status": nq_status if nq_status is not None else "",
        "nq_duration_ms": nq_duration_ms if nq_duration_ms is not None else "",
        "is_429": int(is_429),
        "skipped_tact": 0,
    }
    if not day_buckets:
        row = _blank_row(
            probed_at,
            advert_id,
            nm_id,
            fs_status=fs_status,
            fs_duration_ms=fs_duration_ms,
            nq_status=nq_status,
            nq_duration_ms=nq_duration_ms,
            is_429=is_429,
        )
        row.update(base)
        return [row]

    rows: list[dict[str, Any]] = []
    for bucket in day_buckets:
        row = {
            "probed_at_utc": probed_at,
            "advert_id": advert_id,
            "nm_id": nm_id,
            "bucket_date": bucket.get("bucket_date", ""),
            "fs_views": bucket.get("views", ""),
            "fs_clicks": bucket.get("clicks", ""),
            "fs_sum": bucket.get("sum", ""),
            "fs_orders": bucket.get("orders", ""),
            **base,
        }
        rows.append(row)
    return rows


def api_get_fullstats(
    session: requests.Session,
    token: str,
    advert_ids: list[int],
    begin: date,
    end: date,
) -> tuple[int, bytes, float]:
    started = time.monotonic()
    resp = session.get(
        f"{API_BASE}/adv/v3/fullstats",
        headers={"Authorization": token},
        params={
            "ids": ",".join(str(i) for i in advert_ids),
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

    if prod_cycle_running(prod_lock_path):
        log.info("skipped: prod cycle running")
        rows = [
            _blank_row(probed_at, advert_id, nm_id, skipped_tact=True)
            for advert_id, nm_id in CAMPAIGNS
        ]
        append_csv_rows(csv_path, rows, now=now)
        return 0

    own_session = session is None
    if own_session:
        session = requests.Session()

    try:
        token = read_env_token(env_path)
        begin, end = msk_date_window(now.astimezone(MSK))
        raw_root = data_dir / "raw" / utc_day.isoformat()
        all_rows: list[dict[str, Any]] = []
        advert_ids = [a for a, _ in CAMPAIGNS]

        fs_status, fs_body, fs_elapsed = api_get_fullstats(session, token, advert_ids, begin, end)
        fs_duration_ms = int(fs_elapsed * 1000)
        save_raw_gzip(raw_root / f"{tick}_fullstats.json.gz", fs_body)

        fs_parsed: dict[int, list[dict[str, Any]]] = {}
        if fs_status == 200:
            try:
                fs_data = json.loads(fs_body.decode("utf-8"))
                for advert_id, _ in CAMPAIGNS:
                    fs_parsed[advert_id] = parse_fullstats_days(fs_data, advert_id)
            except (json.JSONDecodeError, UnicodeDecodeError):
                log.exception("fullstats JSON decode failed")
        elif fs_status == 429:
            log.warning("fullstats batch: HTTP 429")
        elif fs_status >= 400:
            log.warning("fullstats batch: HTTP %s", fs_status)

        for idx, (advert_id, nm_id) in enumerate(CAMPAIGNS):
            if idx > 0:
                time.sleep(PROMOTION_PAUSE_SEC)

            nq_status, nq_body, nq_elapsed = api_post_normquery_stats(
                session, token, advert_id, nm_id, begin, end
            )
            nq_duration_ms = int(nq_elapsed * 1000)
            save_raw_gzip(
                raw_root / f"{tick}_{advert_id}_normquery_stats.json.gz",
                nq_body,
            )

            is_429 = fs_status == 429 or nq_status == 429

            if nq_status == 429:
                log.warning("normquery advert_id=%s: HTTP 429", advert_id)

            normquery = {
                "views": 0,
                "clicks": 0,
                "orders": 0,
                "spend": 0.0,
                "cpc": None,
                "cpc_x_clicks": 0.0,
            }
            if nq_status == 200:
                try:
                    normquery = parse_normquery_totals(json.loads(nq_body.decode("utf-8")), nm_id)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    log.exception("normquery JSON decode failed advert_id=%s", advert_id)

            day_buckets = fs_parsed.get(advert_id, []) if fs_status == 200 else []
            all_rows.extend(
                build_day_rows(
                    probed_at,
                    advert_id,
                    nm_id,
                    day_buckets,
                    normquery,
                    fs_status=fs_status,
                    fs_duration_ms=fs_duration_ms,
                    nq_status=nq_status,
                    nq_duration_ms=nq_duration_ms,
                    is_429=is_429,
                )
            )

        append_csv_rows(csv_path, all_rows, now=now)
        log.info("probe cycle done: %s rows, raw in %s", len(all_rows), raw_root)
        return 0
    finally:
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
