#!/usr/bin/env python
"""Apply latest optimizer suggestions to WB (when auto mode enabled)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.executor.apply import apply_optimizer_results  # noqa: E402
from wb_advert.executor.guards import get_apply_settings  # noqa: E402
from wb_advert.optimizer.engine import optimize_all, optimize_product  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply optimizer actions to WB API")
    parser.add_argument("--advert-id", type=int, action="append")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without WB writes")
    args = parser.parse_args()

    settings = get_apply_settings()
    print(f"Mode: {settings['optimizer_mode']} | can_apply={settings['can_apply']}")
    if settings["blocked_reasons"]:
        for r in settings["blocked_reasons"]:
            print(f"  blocked: {r}")

    if args.advert_id:
        results = [optimize_product(aid) for aid in args.advert_id]
    else:
        results = optimize_all()

    batch = apply_optimizer_results(results, dry_run=args.dry_run)
    if not batch.items:
        print("No applicable actions (raise/lower/exclude)")
        return 0

    for item in batch.items:
        tag = "DRY" if item.dry_run else ("OK" if item.ok else "FAIL")
        print(f"  [{tag}] {item.advert_id} {item.action} {item.keyword[:35]:35} {item.detail[:80]}")

    print(
        f"\nTotal: {len(batch.items)} actions, "
        f"applied={batch.applied_count}, failed={batch.failed_count}, dry_run={batch.dry_run}"
    )
    return 0 if batch.failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
