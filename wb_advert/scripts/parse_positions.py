#!/usr/bin/env python
"""Parse organic search positions for pilot primary keywords."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.constants import PENDING_NM_PREFIX  # noqa: E402
from wb_advert.import_data.csv_loader import load_pilot_skus  # noqa: E402
from wb_advert.parser.regions import PARSER_REGION_OPTIONS, region_config_label  # noqa: E402
from wb_advert.parser.search import WbSearchParser  # noqa: E402
from wb_advert.storage.pilot_store import load_config, pilot_data_dir  # noqa: E402
from wb_advert.storage.positions_store import (  # noqa: E402
    append_position_snapshot,
    is_position_fresh,
    write_positions_summary,
)


def _region_plans(
    *,
    all_regions: bool,
    region: str | None,
    dest: str | None,
    parser_cfg: dict,
    args_region: str | None,
    args_dest: str | None,
) -> list[tuple[str, str | None, str]]:
    if all_regions:
        return [(opt["key"], opt["dest"], opt["label"]) for opt in PARSER_REGION_OPTIONS]
    region_val = args_region if args_region is not None else parser_cfg.get("region")
    dest_val = args_dest
    from wb_advert.parser.regions import normalize_region_key

    rk = normalize_region_key(str(region_val) if region_val else None)
    return [(rk, str(dest_val) if dest_val else None, region_config_label(rk))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse WB search positions for pilot primary keys")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max SKUs this run (default: all pilot SKUs with primary keyword)",
    )
    parser.add_argument("--advert-id", type=int, action="append", help="Only these campaigns")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-pages", type=int, default=None, help="Search depth (pages × 100)")
    parser.add_argument("--dest", type=str, default=None, help="Override parser.dest (WB geo code)")
    parser.add_argument("--region", type=str, default=None, help="Override parser.region (if dest not set)")
    parser.add_argument(
        "--all-regions",
        action="store_true",
        help="Parse each SKU for all configured regions (Krasnodar, Moscow, Rostov)",
    )
    parser.add_argument("--pause-between-regions", type=float, default=None)
    parser.add_argument("--pause-between-queries", type=float, default=None)
    parser.add_argument(
        "--skip-fresh",
        action="store_true",
        help="Skip nm_id+region if parsed within parser.interval_min (config)",
    )
    parser.add_argument(
        "--min-age-min",
        type=float,
        default=None,
        help="Min minutes between re-parses when using --skip-fresh (default: parser.interval_min)",
    )
    parser.add_argument("--force", action="store_true", help="Parse even if position is still fresh")
    args = parser.parse_args()

    data_dir = args.data_dir or pilot_data_dir()
    config = load_config(data_dir)
    parser_cfg = config.get("parser") or {}

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
        print("No pilot SKUs with primary_keyword", flush=True)
        return 1

    pause = float(parser_cfg.get("pause_sec") or 0.4)
    max_pages = args.max_pages or int(parser_cfg.get("max_pages") or 5)
    pause_regions = args.pause_between_regions
    if pause_regions is None:
        pause_regions = float(parser_cfg.get("pause_between_regions_sec") or 8.0)
    pause_queries = args.pause_between_queries
    if pause_queries is None:
        pause_queries = float(parser_cfg.get("pause_between_queries_sec") or 0.5)

    min_age_min = 0.0
    if args.skip_fresh and not args.force:
        min_age_min = float(
            args.min_age_min
            if args.min_age_min is not None
            else parser_cfg.get("interval_min") or 5
        )

    region_plans = _region_plans(
        all_regions=args.all_regions,
        region=parser_cfg.get("region"),
        dest=parser_cfg.get("dest"),
        parser_cfg=parser_cfg,
        args_region=args.region,
        args_dest=args.dest,
    )

    mode = "region-batch"
    print(
        f"Parsing {len(skus)} SKU x {len(region_plans)} regions ({mode}), "
        f"pause={pause}s, between queries={pause_queries}s, between regions={pause_regions}s",
        flush=True,
    )
    if min_age_min > 0:
        print(f"Skip-fresh: re-parse only if older than {min_age_min:g} min", flush=True)

    entries: list[dict] = []
    skipped_fresh = 0
    failures = 0
    total_jobs = len(skus) * len(region_plans)
    job_n = 0

    for ri, (region_key, dest, label) in enumerate(region_plans):
        if ri > 0 and pause_regions > 0:
            print(f"\n(pause {pause_regions:g}s before {label})", flush=True)
            time.sleep(pause_regions)

        print(f"\n=== {label} ({region_key}) ===", flush=True)
        with WbSearchParser(
            dest=str(dest) if dest else None,
            region=region_key,
            pause_sec=pause,
            max_pages=max_pages,
        ) as wb:
            for si, sku in enumerate(skus):
                nm_id = int(sku.nm_id)
                nm_str = str(sku.nm_id)
                kw = sku.primary_keyword.strip()

                if min_age_min > 0 and is_position_fresh(
                    nm_str,
                    region_key=region_key,
                    min_age_min=min_age_min,
                    data_dir=data_dir,
                ):
                    skipped_fresh += 1
                    job_n += 1
                    print(f"  [{job_n}/{total_jobs}] skip fresh nm={nm_id} «{kw[:30]}»", flush=True)
                    continue

                if si > 0 and pause_queries > 0:
                    time.sleep(pause_queries)

                job_n += 1
                print(f"  [{job_n}/{total_jobs}] {sku.wb_campaign_search} nm={nm_id} «{kw}»", flush=True)
                result = wb.find_position(kw, nm_id)
                result["advert_id"] = sku.wb_campaign_search
                result["target_grade"] = sku.target_grade
                result["region_key"] = region_key
                result["region"] = label
                entries.append(result)

                if result.get("found"):
                    print(f"    -> position {result['position']}", flush=True)
                else:
                    failures += 1
                    err = str(result.get("error") or "")
                    print(f"    -> {err or 'miss'}", flush=True)
                    if "429" in err and pause_queries > 0:
                        backoff = max(30.0, pause_queries * 10)
                        print(f"    (429 backoff {backoff:.0f}s)", flush=True)
                        time.sleep(backoff)

                if not args.dry_run:
                    append_position_snapshot(result, data_dir)

    if not args.dry_run and entries:
        write_positions_summary(entries, data_dir)

    ok = sum(1 for e in entries if e.get("found"))
    parsed = len(entries)
    print(
        f"\nDone: {ok}/{parsed} found, {failures} missed/blocked, {skipped_fresh} skipped (fresh)",
        flush=True,
    )
    if failures and any("429" in str(e.get("error")) for e in entries):
        print("Tip: WB rate-limits search API — retry in 10–30 min or use --skip-fresh", flush=True)
    if parsed == 0 and skipped_fresh > 0:
        return 0
    return 0 if ok > 0 or parsed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
