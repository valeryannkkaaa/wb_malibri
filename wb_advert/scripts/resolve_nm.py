#!/usr/bin/env python
"""Resolve PENDING nm_ids via get_advert and update pilot CSVs."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.client.promotion import PromotionClient  # noqa: E402
from wb_advert.config import require_token, settings  # noqa: E402
from wb_advert.constants import PENDING_NM_PREFIX  # noqa: E402
from wb_advert.import_data.csv_loader import apply_nm_id_mapping, load_pilot_skus  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve PENDING nm_ids from WB campaign detail")
    parser.add_argument("--advert-id", type=int, action="append", help="Campaign id (repeatable; default: all pending)")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--pause", type=float, default=3.0, help="Seconds between API calls")
    parser.add_argument("--dry-run", action="store_true", help="Fetch only, do not write CSVs")
    args = parser.parse_args()

    require_token()
    data_dir = args.data_dir or (ROOT / settings.pilot_data_path).resolve()
    skus_path = data_dir / "pilot_skus.csv"

    pending = [
        s.wb_campaign_search
        for s in load_pilot_skus(skus_path)
        if (s.nm_id or "").startswith(PENDING_NM_PREFIX)
    ]
    if args.advert_id:
        targets = list(dict.fromkeys(args.advert_id))
    else:
        targets = pending

    if not targets:
        print("No PENDING campaigns in pilot_skus.csv")
        return 0

    print(f"Resolving nm_id for {len(targets)} campaign(s)...", flush=True)
    client = PromotionClient()
    mapping: dict[int, int] = {}

    for i, advert_id in enumerate(targets):
        if i:
            time.sleep(args.pause)
        print(f"  [{i + 1}/{len(targets)}] advert {advert_id}...", flush=True)
        detail = client.get_advert(advert_id)
        if not detail.ok:
            print(f"     failed HTTP {detail.status} - stopping (rate limit? wait 5 min)", flush=True)
            break
        ids = client.extract_nm_ids_from_detail(detail.json())
        if not ids:
            print("     no nm_id in response", flush=True)
            continue
        mapping[advert_id] = ids[0]
        print(f"     nm_id={ids[0]}", flush=True)

    if not mapping:
        print("\nNothing resolved. Wait ~5 min if rate-limited, then retry.")
        return 1

    print("\nResolved:")
    for aid, nid in mapping.items():
        print(f"  {aid} -> {nid}")

    if args.dry_run:
        print("\n(dry-run: CSVs not updated)")
        return 0

    updated = apply_nm_id_mapping(data_dir, mapping)
    print(f"\nUpdated: {', '.join(updated) or 'none'}")
    print("Next: python -m scripts.sync_once --advert-id", targets[0], "--no-resolve-nm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
