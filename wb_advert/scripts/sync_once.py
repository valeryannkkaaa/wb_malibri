#!/usr/bin/env python
"""Sync one WB campaign — phase 0 smoke test."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.config import require_token  # noqa: E402
from wb_advert.sync.worker import SyncWorker  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync single WB advert campaign")
    parser.add_argument("--advert-id", type=int, required=True)
    parser.add_argument("--nm-id", type=int, default=None)
    parser.add_argument(
        "--no-resolve-nm",
        action="store_true",
        help="Do not fetch nm_id from campaign detail",
    )
    parser.add_argument(
        "--with-fullstats",
        action="store_true",
        help="Call /adv/v3/fullstats (base token: 1 request per hour)",
    )
    args = parser.parse_args()

    require_token()
    print(f"Sync campaign {args.advert_id}...", flush=True)

    worker = SyncWorker()
    result = worker.sync_profile(
        nm_id_label=f"PENDING_{args.advert_id}",
        wb_campaign_id=args.advert_id,
        resolved_nm_id=args.nm_id,
        try_resolve_nm=not args.no_resolve_nm,
        with_fullstats=args.with_fullstats,
    )
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    ok = bool(result.keywords) or bool(result.campaigns and result.campaigns[0].fullstats_ok)
    if ok:
        nm = result.resolved_nm_id or "?"
        print(f"\nDone: {len(result.keywords)} keywords, nm_id={nm}")
    else:
        print("\nNo data yet.")
        if result.resolved_nm_id:
            print("Tip: wait 2-3 min (WB rate limit / server glitch), then retry:")
            print(f"     python -m scripts.sync_once --advert-id {args.advert_id} --no-resolve-nm")
        elif not args.nm_id:
            print(
                f"Tip: python -m scripts.resolve_nm --advert-id {args.advert_id}\n"
                f"     or: python -m scripts.sync_once --advert-id {args.advert_id}  (resolve via API)"
            )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
