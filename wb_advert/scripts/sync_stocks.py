#!/usr/bin/env python
"""Sync WB warehouse stocks for pilot nm_ids (Analytics API)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.client.analytics import AnalyticsClient  # noqa: E402
from wb_advert.client.base import WbHttpClient  # noqa: E402
from wb_advert.config import env_file_used, require_token, settings  # noqa: E402
from wb_advert.constants import PENDING_NM_PREFIX  # noqa: E402
from wb_advert.import_data.csv_loader import load_pilot_skus  # noqa: E402
from wb_advert.storage.pilot_store import pilot_data_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch stocks-report for pilot SKUs")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--min-hours", type=int, default=24, help="Skip if report newer than N hours")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    require_token()
    env = env_file_used()
    if env:
        print(f"Token from {env}", flush=True)

    data_dir = args.data_dir or pilot_data_dir()
    out_path = data_dir / "sync" / "stocks_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.is_file() and not args.force:
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            synced = prev.get("synced_at")
            if synced:
                then = datetime.fromisoformat(str(synced).replace("Z", "+00:00"))
                age_h = (datetime.now(timezone.utc) - then).total_seconds() / 3600
                if age_h < args.min_hours:
                    print(f"Skip stocks (updated {age_h:.1f}h ago, use --force)", flush=True)
                    return 0
        except (json.JSONDecodeError, ValueError, OSError):
            pass

    nm_ids = {
        int(s.nm_id)
        for s in load_pilot_skus(data_dir / "pilot_skus.csv")
        if (s.nm_id or "").isdigit() and not s.nm_id.startswith(PENDING_NM_PREFIX)
    }
    if not nm_ids:
        print("No pilot nm_ids", flush=True)
        return 1

    end = date.today()
    begin = end - timedelta(days=max(args.days, 1))
    print(f"Fetching stocks {begin}..{end} for {len(nm_ids)} SKU...", flush=True)

    client = AnalyticsClient(http=WbHttpClient(pause_sec=2.0))
    result = client.stocks_report_wb_warehouses(begin, end, limit=1000)
    if not result.ok:
        err = (result.error or result.body[:200] if result.body else "")[:200]
        print(f"API failed HTTP {result.status}: {err}", flush=True)
        return 1

    data = result.json()
    items = (data.get("data") or {}).get("items") or []
    filtered = [it for it in items if int(it.get("nmId") or it.get("nm_id") or 0) in nm_ids]

    report = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "period": {"start": begin.isoformat(), "end": end.isoformat()},
        "pilot_nm_ids": sorted(nm_ids),
        "items_total": len(items),
        "items_pilot": len(filtered),
        "items": filtered,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {out_path} ({len(filtered)} pilot rows)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
