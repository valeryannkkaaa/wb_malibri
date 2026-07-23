#!/usr/bin/env python
"""Sync WB search-report search-texts for pilot nm_ids (Analytics API)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.client.analytics import AnalyticsClient  # noqa: E402
from wb_advert.client.base import RETRY_429_BASE_SEC, WbHttpClient  # noqa: E402
from wb_advert.config import env_file_used, require_token, settings  # noqa: E402
from wb_advert.constants import PENDING_NM_PREFIX  # noqa: E402
from wb_advert.import_data.csv_loader import load_pilot_skus  # noqa: E402
from wb_advert.storage.config_store import load_config  # noqa: E402
from wb_advert.storage.search_report_store import (  # noqa: E402
    save_search_report,
    search_report_synced_at,
)
from wb_advert.sync.rotate import pick_rotate_batch  # noqa: E402
from wb_advert.sync.search_report_worker import SearchReportWorker, is_blocking_error  # noqa: E402

# One search-texts call may wait ~20s on 429 retry before succeeding.
MIN_CARD_PAUSE_SEC = RETRY_429_BASE_SEC + 5
DEFAULT_PAUSE_SEC = MIN_CARD_PAUSE_SEC
_ATTEMPT_FIELDS = ("nm_id", "items", "errors")


def merge_search_report_row(prev_row: dict, attempt_row: dict, *, now: str) -> dict:
    """Success replaces snapshot; failure updates only attempt facts."""
    if attempt_row.get("items", 0) > 0:
        return {**prev_row, **attempt_row, "last_attempt_at": now, "synced_at": now}
    merged = dict(prev_row)
    for key in _ATTEMPT_FIELDS:
        if key in attempt_row:
            merged[key] = attempt_row[key]
    merged["last_attempt_at"] = now
    return merged


def load_search_report_sync_report(report_path: Path) -> dict:
    if not report_path.is_file():
        return {}
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def merge_search_report_sync_report(report_path: Path, new_rows: list[dict]) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    prev = load_search_report_sync_report(report_path)
    by_id = {int(r["nm_id"]): r for r in prev.get("products") or [] if r.get("nm_id")}
    for row in new_rows:
        nm_id = int(row["nm_id"])
        prev_row = by_id.get(nm_id, {})
        by_id[nm_id] = merge_search_report_row(prev_row, row, now=now)
    return {
        "synced_at": now,
        "products": sorted(by_id.values(), key=lambda r: r["nm_id"]),
    }


def pick_rotate_nm_ids(ready: list, report_path: Path, limit: int = 1) -> list:
    data_dir = report_path.parent
    report = load_search_report_sync_report(report_path)
    by_nm = {int(r["nm_id"]): r for r in report.get("products") or [] if r.get("nm_id")}
    return pick_rotate_batch(
        ready,
        entity_id=lambda sku: int(sku.nm_id),
        report_by_id=by_nm,
        canonical_synced_at=lambda nm_id: search_report_synced_at(nm_id, data_dir),
        limit=limit,
    )


def effective_pause_sec(requested: float, data_dir: Path) -> float:
    sync_cfg = load_config(data_dir).get("sync") or {}
    min_pause = float(sync_cfg.get("rate_limit_pause_sec") or 0)
    return max(requested, min_pause, MIN_CARD_PAUSE_SEC)


def _has_429(errors: list[str]) -> bool:
    return any("429" in e for e in errors)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync WB search-report search-texts for pilot SKUs")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--days", type=int, default=7, help="Lookback window (end = today)")
    parser.add_argument("--limit", type=int, default=None, help="Max nm_ids per run (rotate default: 1)")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SEC, help="Pause between API calls")
    parser.add_argument("--max-retries", type=int, default=2, help="HTTP retries per call")
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Sync least recently attempted nm_id(s) — for scheduled incremental runs",
    )
    parser.add_argument("--report", type=Path, default=None, help="JSON rotation report path")
    args = parser.parse_args()

    require_token()
    env = env_file_used()
    if env:
        print(f"Token from {env}", flush=True)

    data_dir = args.data_dir or (ROOT / settings.pilot_data_path).resolve()
    report_path = args.report or (data_dir / "last_search_report_sync.json")
    pause = effective_pause_sec(args.pause, data_dir)

    ready = [
        s
        for s in load_pilot_skus(data_dir / "pilot_skus.csv")
        if (s.nm_id or "").isdigit() and not s.nm_id.startswith(PENDING_NM_PREFIX)
    ]
    if not ready:
        print("No pilot nm_ids", flush=True)
        return 1

    if args.rotate:
        lim = args.limit if args.limit is not None else 1
        to_sync = pick_rotate_nm_ids(ready, report_path, lim)
    else:
        to_sync = ready
        if args.limit is not None:
            to_sync = to_sync[: args.limit]

    end = date.today()
    begin = end - timedelta(days=max(args.days, 1))
    period = {"start": begin.isoformat(), "end": end.isoformat()}

    http = WbHttpClient(pause_sec=pause, max_retries=args.max_retries)
    worker = SearchReportWorker(analytics=AnalyticsClient(http=http))

    batch_rows: list[dict] = []
    failures = 0
    stopped_429 = False

    print(
        f"Search report queue: {len(to_sync)} nm_id(s)"
        + (" (rotate)" if args.rotate else "")
        + f", pause {pause}s",
        flush=True,
    )
    for i, sku in enumerate(to_sync):
        if stopped_429:
            break
        if i:
            time.sleep(pause)
        nm_id = int(sku.nm_id)
        print(f"\n[{i + 1}/{len(to_sync)}] Search report nm_id={nm_id}...", flush=True)
        items, errors = worker.fetch_nm_search_texts(nm_id, begin, end)
        row = {
            "nm_id": nm_id,
            "items": len(items),
            "errors": errors,
        }
        hard_errors = [e for e in errors if is_blocking_error(e)]
        if items and not hard_errors:
            save_search_report(nm_id, period=period, items=items, data_dir=data_dir)
            if errors:
                print(f"  -> {len(items)} keywords (saved JSON, with warnings)", flush=True)
            else:
                print(f"  -> {len(items)} keywords (saved JSON)", flush=True)
        else:
            failures += 1
            print("  -> FAILED (previous snapshot kept)", flush=True)
            if _has_429(errors):
                stopped_429 = True
                print("  -> 429: stopping batch (wait ~10 min, then re-run)", flush=True)
        batch_rows.append(row)

    report = merge_search_report_sync_report(report_path, batch_rows)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {report_path}", flush=True)

    ok_count = sum(1 for r in batch_rows if r.get("items", 0) > 0)
    print(
        f"\nDone: {ok_count}/{len(to_sync)} nm_ids synced this run"
        + (f", failed {failures}" if failures else ""),
        flush=True,
    )
    return 1 if failures or stopped_429 else 0


if __name__ == "__main__":
    raise SystemExit(main())
