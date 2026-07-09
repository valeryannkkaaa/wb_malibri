#!/usr/bin/env python
"""Fill retail_price_rub in unit_economics.csv from WB Analytics sales-funnel API."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.client.analytics import AnalyticsClient  # noqa: E402
from wb_advert.client.base import WbHttpClient  # noqa: E402
from wb_advert.client.funnel_parse import extract_avg_prices  # noqa: E402
from wb_advert.config import env_file_used, require_token, settings  # noqa: E402
from wb_advert.constants import PENDING_NM_PREFIX  # noqa: E402
from wb_advert.import_data.csv_loader import update_unit_economics_retail  # noqa: E402


def load_nm_ids(econ_path: Path) -> list[int]:
    ids: list[int] = []
    with econ_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw = (row.get("nm_id") or "").strip()
            if not raw or raw.startswith(PENDING_NM_PREFIX) or not raw.isdigit():
                continue
            ids.append(int(raw))
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fill retail_price_rub from WB sales-funnel avgPrice (last N days)",
    )
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--days", type=int, default=7, help="Lookback window for avgPrice")
    parser.add_argument("--dry-run", action="store_true", help="Fetch only, do not write CSV")
    parser.add_argument("--force", action="store_true", help="Overwrite existing retail_price_rub")
    parser.add_argument("--pause", type=float, default=2.0, help="Pause before API call")
    args = parser.parse_args()

    require_token()
    env = env_file_used()
    if env:
        print(f"Token from {env}", flush=True)

    data_dir = args.data_dir or (ROOT / settings.pilot_data_path).resolve()
    econ_path = data_dir / "unit_economics.csv"
    if not econ_path.is_file():
        print(f"Missing {econ_path}", flush=True)
        return 1

    nm_ids = load_nm_ids(econ_path)
    if not nm_ids:
        print("No resolved nm_id in unit_economics.csv", flush=True)
        return 1

    end = date.today()
    begin = end - timedelta(days=max(args.days, 1))
    print(f"Fetching avgPrice for {len(nm_ids)} SKU ({begin} .. {end})...", flush=True)

    http = WbHttpClient(pause_sec=args.pause)
    client = AnalyticsClient(http=http)
    result = client.sales_funnel_products(begin, end, nm_ids=nm_ids, limit=max(len(nm_ids), 10))
    if not result.ok:
        err = (result.error or result.body[:200] if result.body else "")[:200]
        print(f"API failed HTTP {result.status}: {err}", flush=True)
        return 1

    prices = extract_avg_prices(result.json())
    missing = [n for n in nm_ids if n not in prices]

    print(f"\n{'nm_id':>12}  {'avgPrice':>10}  source")
    print("-" * 40)
    for nm_id in nm_ids:
        if nm_id in prices:
            print(f"{nm_id:>12}  {prices[nm_id]:>10.0f}  sales-funnel selected.avgPrice")
        else:
            print(f"{nm_id:>12}  {'—':>10}  not in response")

    if missing:
        print(f"\nWarning: no price for {len(missing)} nm_id(s): {missing}", flush=True)

    if args.dry_run:
        print("\nDry run — CSV not updated.", flush=True)
        return 0 if prices else 1

    nm_to_price = {str(k): v for k, v in prices.items()}
    updated, skipped = update_unit_economics_retail(
        econ_path,
        nm_to_price,
        overwrite=args.force,
    )
    print(f"\nUpdated {econ_path.name}: {updated} row(s), skipped {skipped} (already filled)", flush=True)
    if updated:
        print("Note: cost_price_rub still empty — CPC limits need both price and cost.", flush=True)
    return 0 if updated or skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
