#!/usr/bin/env python
"""Compare parser results across WB regions (Moscow / Rostov / Krasnodar)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.constants import PENDING_NM_PREFIX  # noqa: E402
from wb_advert.import_data.csv_loader import load_pilot_skus  # noqa: E402
from wb_advert.parser.regions import REGION_DEST  # noqa: E402
from wb_advert.parser.search import WbSearchParser  # noqa: E402
from wb_advert.storage.pilot_store import pilot_data_dir  # noqa: E402

DEFAULT_REGIONS = ("moscow", "rostov", "krasnodar")


def main() -> int:
    parser = argparse.ArgumentParser(description="Test WB search parser across regions")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None, help="Max SKUs to test")
    parser.add_argument(
        "--regions",
        type=str,
        default=",".join(DEFAULT_REGIONS),
        help="Comma-separated region keys from parser/regions.py",
    )
    parser.add_argument("--pause", type=float, default=5.0)
    parser.add_argument("--pause-between-regions", type=float, default=20.0)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--advert-id", type=int, action="append")
    args = parser.parse_args()

    data_dir = args.data_dir or pilot_data_dir()
    regions = [r.strip().lower() for r in args.regions.split(",") if r.strip()]
    unknown = [r for r in regions if r not in REGION_DEST]
    if unknown:
        print(f"Unknown regions: {unknown}. Known: {sorted(REGION_DEST)}", flush=True)
        return 1

    skus = [
        s
        for s in load_pilot_skus(data_dir / "pilot_skus.csv")
        if s.primary_keyword and not (s.nm_id or "").startswith(PENDING_NM_PREFIX)
    ]
    if args.advert_id:
        allowed = set(args.advert_id)
        skus = [s for s in skus if s.wb_campaign_search in allowed]
    if args.limit:
        skus = skus[: args.limit]

    if not skus:
        print("No SKUs to test", flush=True)
        return 1

    print(f"Testing {len(skus)} SKU x {len(regions)} regions (pause={args.pause}s)", flush=True)

    rows: list[dict] = []
    for i, region in enumerate(regions):
        if i > 0 and args.pause_between_regions > 0:
            print(f"\n(pause {args.pause_between_regions:.0f}s before next region — avoid 429)", flush=True)
            time.sleep(args.pause_between_regions)
        dest = REGION_DEST[region]
        print(f"\n=== {region} dest={dest} ===", flush=True)
        with WbSearchParser(
            region=region,
            pause_sec=args.pause,
            max_pages=args.max_pages,
        ) as wb:
            for sku in skus:
                nm_id = int(sku.nm_id)
                kw = sku.primary_keyword.strip()
                result = wb.find_position(kw, nm_id)
                row = {
                    "region": region,
                    "dest": dest,
                    "advert_id": sku.wb_campaign_search,
                    "nm_id": nm_id,
                    "keyword": kw,
                    "target_grade": sku.target_grade,
                    "found": result.get("found"),
                    "position": result.get("position"),
                    "error": result.get("error"),
                    "scanned": result.get("scanned"),
                }
                rows.append(row)
                if row["found"]:
                    print(f"  {nm_id} pos {row['position']:>3}  {kw[:40]}", flush=True)
                else:
                    print(f"  {nm_id}  ---  {row['error']}  {kw[:30]}", flush=True)

    found = sum(1 for r in rows if r.get("found"))
    by_region = {r: sum(1 for row in rows if row["region"] == r and row.get("found")) for r in regions}

    report = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "sku_count": len(skus),
        "regions": regions,
        "found_total": found,
        "found_by_region": by_region,
        "rows": rows,
    }

    out_dir = data_dir / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "parser_region_test.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nSummary: {found}/{len(rows)} hits", flush=True)
    for region, count in by_region.items():
        print(f"  {region}: {count}/{len(skus)}", flush=True)
    print(f"Report: {out_path}", flush=True)
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
