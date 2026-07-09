#!/usr/bin/env python
"""Save full keyword lists to data/pilot/sync/ (one campaign per run)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.client.base import WbHttpClient  # noqa: E402
from wb_advert.client.promotion import PromotionClient  # noqa: E402
from wb_advert.config import require_token, settings  # noqa: E402
from wb_advert.storage.keywords_store import keywords_path, save_keywords  # noqa: E402
from wb_advert.storage.pilot_store import build_product_rows, pilot_data_dir  # noqa: E402
from wb_advert.sync.worker import SyncWorker  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill keywords JSON from WB API")
    parser.add_argument("--advert-id", type=int, action="append")
    parser.add_argument("--skip-existing", action="store_true", help="Skip if JSON already exists")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if JSON exists")
    parser.add_argument("--max-retries", type=int, default=2, help="HTTP retries (keep low for 429)")
    args = parser.parse_args()

    require_token()
    data_dir = pilot_data_dir()
    http = WbHttpClient(pause_sec=3.0, max_retries=args.max_retries)
    worker = SyncWorker(
        promotion=PromotionClient(http=http),
        pilot_csv=data_dir / "pilot_skus.csv",
    )
    rows = build_product_rows(data_dir)
    if args.advert_id:
        targets = [r for r in rows if r["advert_id"] in args.advert_id]
    else:
        targets = rows

    if not targets:
        print("No campaigns to backfill")
        return 1

    ok = 0
    for row in targets:
        advert_id = row["advert_id"]
        if args.skip_existing and not args.force and keywords_path(advert_id, data_dir).is_file():
            print(f"Skip {advert_id} (JSON exists, use --force)")
            continue
        nm_id = int(row["nm_id"])
        print(f"Sync {advert_id} nm_id={nm_id}...", flush=True)
        result = worker.sync_profile(
            nm_id_label=row["nm_id"],
            wb_campaign_id=advert_id,
            resolved_nm_id=nm_id,
            try_resolve_nm=False,
            with_fullstats=False,
        )
        if not result.keywords:
            err = (result.errors[0] if result.errors else "unknown")[:200]
            print(f"  FAILED: {err}")
            if "401" in err or "withdrawn" in err.lower() or "unauthorized" in err.lower():
                print("  -> WB token revoked. Create new token in seller cabinet, update wb_advert_probe\\.env")
                return 3
            if "429" in err:
                print("  -> rate limit: wait 10-15 min, re-run with --skip-existing")
                return 2
            return 1
        path = save_keywords(advert_id, nm_id, result.keywords, data_dir=data_dir)
        print(f"  -> {len(result.keywords)} keywords -> {path}")
        ok += 1
        if len(targets) > 1:
            print("  (run again for next campaign to avoid 429)")

    print(f"\nDone: {ok} campaign(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
