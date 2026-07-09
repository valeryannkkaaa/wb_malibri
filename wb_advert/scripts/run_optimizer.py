#!/usr/bin/env python
"""Run suggest-only optimizer for pilot campaigns."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.optimizer.engine import optimize_all, optimize_product  # noqa: E402
from wb_advert.storage.decisions_store import append_decisions  # noqa: E402
from wb_advert.executor.guards import get_apply_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimizer for pilot campaigns")
    parser.add_argument("--advert-id", type=int, action="append")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Apply actionable suggestions to WB")
    parser.add_argument("--dry-run", action="store_true", help="Simulate apply without WB writes")
    args = parser.parse_args()

    if args.advert_id:
        results = [optimize_product(aid) for aid in args.advert_id]
    else:
        results = optimize_all()

    for r in results:
        print(f"\n=== {r.advert_id} nm_id={r.nm_id} ===")
        for a in r.alerts:
            print(f"  ! {a}")
        if not r.suggestions:
            print("  (no suggestions)")
            continue
        for s in r.suggestions:
            print(f"  {s.action:18} {s.keyword[:40]:40} {s.reason_code}")

    if not args.no_save:
        for r in results:
            if r.suggestions or r.alerts:
                append_decisions(r)

    total = sum(len(r.suggestions) for r in results)
    print(f"\nTotal suggestions: {total}")

    apply_settings = get_apply_settings()
    should_apply = args.apply or (
        apply_settings["optimizer_mode"] == "auto" and apply_settings["can_apply"]
    )
    if should_apply:
        from wb_advert.executor.apply import apply_optimizer_results

        batch = apply_optimizer_results(results, dry_run=args.dry_run)
        if batch.items:
            print(f"\nApply: {batch.applied_count} ok, {batch.failed_count} fail, dry_run={batch.dry_run}")
        elif batch.blocked_reasons and not args.dry_run:
            print("\nApply skipped:")
            for r in batch.blocked_reasons:
                print(f"  - {r}")
    elif apply_settings["optimizer_mode"] == "auto" and apply_settings["blocked_reasons"]:
        print("\nApply disabled:")
        for r in apply_settings["blocked_reasons"]:
            print(f"  - {r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
