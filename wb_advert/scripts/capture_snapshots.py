#!/usr/bin/env python
"""Capture cycle snapshots after sync + optimizer + parse."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.storage.snapshots_store import capture_cycle_snapshots  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture advert cycle snapshots")
    parser.add_argument("--cycle-id", help="Optional batch id (default: recorded_at ISO)")
    parser.add_argument("--json", action="store_true", help="Print result as JSON")
    args = parser.parse_args()

    result = capture_cycle_snapshots(cycle_id=args.cycle_id)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"Snapshots: {result['total_rows']} rows "
            f"({result['keyword_rows']} keyword, {result['campaign_rows']} campaign)"
        )
        print(f"cycle_id: {result['cycle_id']}")
        print(f"path: {result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
