#!/usr/bin/env python
"""Sync WB nm-report detail history (daily sales funnel) for pilot nm_ids."""

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
from wb_advert.storage.funnel_store import (  # noqa: E402
    last_funnel_date,
    load_funnel,
    save_funnel,
    funnel_synced_at,
)
from wb_advert.sync.funnel_worker import FunnelWorker, INITIAL_LOOKBACK_DAYS  # noqa: E402
from wb_advert.sync.rotate import pick_rotate_batch  # noqa: E402

# Report generation may wait on 429 retry plus async polling.
MIN_CARD_PAUSE_SEC = RETRY_429_BASE_SEC + 5
DEFAULT_PAUSE_SEC = MIN_CARD_PAUSE_SEC
_ATTEMPT_FIELDS = ("nm_id", "rows", "errors", "pending_download_id")


def compute_funnel_period(nm_id: int, data_dir: Path, *, end: date | None = None) -> tuple[date, date]:
    end_date = end or date.today()
    last_dt = last_funnel_date(nm_id, data_dir)
    if last_dt is None:
        start_date = end_date - timedelta(days=INITIAL_LOOKBACK_DAYS)
    else:
        start_date = last_dt
    return start_date, end_date


def merge_funnel_row(prev_row: dict, attempt_row: dict, *, now: str) -> dict:
    if attempt_row.get("rows", 0) > 0:
        merged = {**prev_row, **attempt_row, "last_attempt_at": now, "synced_at": now}
        merged.pop("pending_download_id", None)
        return merged
    merged = dict(prev_row)
    for key in _ATTEMPT_FIELDS:
        if key in attempt_row:
            merged[key] = attempt_row[key]
    merged["last_attempt_at"] = now
    if "pending_download_id" in attempt_row:
        pending = attempt_row["pending_download_id"]
        if pending:
            merged["pending_download_id"] = pending
        else:
            merged.pop("pending_download_id", None)
    return merged


def load_funnel_sync_report(report_path: Path) -> dict:
    if not report_path.is_file():
        return {}
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def merge_funnel_sync_report(report_path: Path, new_rows: list[dict]) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    prev = load_funnel_sync_report(report_path)
    by_id = {int(r["nm_id"]): r for r in prev.get("products") or [] if r.get("nm_id")}
    for row in new_rows:
        nm_id = int(row["nm_id"])
        prev_row = by_id.get(nm_id, {})
        by_id[nm_id] = merge_funnel_row(prev_row, row, now=now)
    return {
        "synced_at": now,
        "products": sorted(by_id.values(), key=lambda r: r["nm_id"]),
    }


def pick_rotate_nm_ids(ready: list, report_path: Path, limit: int = 1) -> list:
    data_dir = report_path.parent
    report = load_funnel_sync_report(report_path)
    by_nm = {int(r["nm_id"]): r for r in report.get("products") or [] if r.get("nm_id")}
    return pick_rotate_batch(
        ready,
        entity_id=lambda sku: int(sku.nm_id),
        report_by_id=by_nm,
        canonical_synced_at=lambda nm_id: funnel_synced_at(nm_id, data_dir),
        limit=limit,
    )


def effective_pause_sec(requested: float, data_dir: Path) -> float:
    sync_cfg = load_config(data_dir).get("sync") or {}
    min_pause = float(sync_cfg.get("rate_limit_pause_sec") or 0)
    return max(requested, min_pause, MIN_CARD_PAUSE_SEC)


def _has_429(errors: list[str]) -> bool:
    return any("429" in e for e in errors)


def _is_poll_timeout(errors: list[str]) -> bool:
    return any("nm-report poll: timeout" in e for e in errors)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync WB nm-report daily funnel for pilot SKUs")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None, help="Max nm_ids per run (rotate default: 1)")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SEC, help="Pause between API calls")
    parser.add_argument("--max-retries", type=int, default=2, help="HTTP retries per call")
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Sync least recently attempted nm_id(s) — for scheduled daily runs",
    )
    parser.add_argument("--report", type=Path, default=None, help="JSON rotation report path")
    parser.add_argument(
        "--poll-attempts",
        type=int,
        default=30,
        help="Max status polls per report (issue #17 guard)",
    )
    parser.add_argument("--poll-interval", type=float, default=10.0, help="Seconds between status polls")
    args = parser.parse_args()

    require_token()
    env = env_file_used()
    if env:
        print(f"Token from {env}", flush=True)

    data_dir = args.data_dir or (ROOT / settings.pilot_data_path).resolve()
    report_path = args.report or (data_dir / "last_funnel_sync.json")
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

    http = WbHttpClient(pause_sec=pause, max_retries=args.max_retries)
    worker = FunnelWorker(
        analytics=AnalyticsClient(http=http),
        max_poll_attempts=max(args.poll_attempts, 1),
        poll_interval_sec=max(args.poll_interval, 1.0),
    )

    sync_report = load_funnel_sync_report(report_path)
    report_by_nm = {
        int(r["nm_id"]): r for r in sync_report.get("products") or [] if r.get("nm_id")
    }

    batch_rows: list[dict] = []
    failures = 0
    timeouts = 0
    stopped_429 = False

    print(
        f"Funnel queue: {len(to_sync)} nm_id(s)"
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
        prev_report = report_by_nm.get(nm_id, {})
        pending_id = prev_report.get("pending_download_id")
        start, end = compute_funnel_period(nm_id, data_dir)
        period = {"start": start.isoformat(), "end": end.isoformat()}

        print(
            f"\n[{i + 1}/{len(to_sync)}] Funnel nm_id={nm_id} "
            f"{start}..{end}"
            + (f" (pending {pending_id})" if pending_id else "")
            + "...",
            flush=True,
        )
        rows, errors, still_pending = worker.fetch_nm_funnel(
            nm_id,
            start,
            end,
            pending_download_id=str(pending_id) if pending_id else None,
        )
        row = {
            "nm_id": nm_id,
            "rows": len(rows),
            "errors": errors,
        }
        if still_pending:
            row["pending_download_id"] = still_pending
            timeouts += 1
            print("  -> TIMEOUT (previous snapshot kept, will resume next run)", flush=True)
        elif rows:
            save_funnel(nm_id, period=period, rows=rows, data_dir=data_dir)
            saved = load_funnel(nm_id, data_dir)
            total_rows = len((saved or {}).get("rows") or [])
            print(f"  -> {len(rows)} new day row(s), {total_rows} total (saved JSON)", flush=True)
        else:
            failures += 1
            if pending_id:
                row["pending_download_id"] = None
            print("  -> FAILED (previous snapshot kept)", flush=True)
            if _has_429(errors):
                stopped_429 = True
                print("  -> 429: stopping batch (wait ~10 min, then re-run)", flush=True)
        batch_rows.append(row)

    report = merge_funnel_sync_report(report_path, batch_rows)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {report_path}", flush=True)

    ok_count = sum(1 for r in batch_rows if r.get("rows", 0) > 0)
    print(
        f"\nDone: {ok_count}/{len(to_sync)} nm_ids synced this run"
        + (f", timed out {timeouts}" if timeouts else "")
        + (f", failed {failures}" if failures else ""),
        flush=True,
    )
    if stopped_429:
        return 1
    hard_failures = [
        r for r in batch_rows
        if r.get("rows", 0) == 0 and not _is_poll_timeout(r.get("errors") or [])
    ]
    return 1 if hard_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
