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


def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest-only optimizer (no WB writes)")
    parser.add_argument("--advert-id", type=int, action="append")
    parser.add_argument("--no-save", action="store_true")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
