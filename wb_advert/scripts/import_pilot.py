#!/usr/bin/env python
"""Import pilot CSV + optionally resolve PENDING nm_ids via WB API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from wb_advert.config import settings  # noqa: E402
from wb_advert.import_data.csv_loader import load_pilot_config, load_pilot_skus  # noqa: E402
from wb_advert.sync.worker import SyncWorker  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Load pilot data and optional nm_id resolve")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--resolve-nm", action="store_true")
    args = parser.parse_args()

    data_dir = args.data_dir or (ROOT / settings.pilot_data_path).resolve()
    config = load_pilot_config(data_dir / "config.yaml")
    skus = load_pilot_skus(data_dir / "pilot_skus.csv")

    report: dict = {"config": config, "skus": [s.model_dump() for s in skus], "resolved": {}}

    if args.resolve_nm:
        worker = SyncWorker()
        for sku in skus:
            nm = worker.resolve_nm_id(sku.wb_campaign_search)
            report["resolved"][sku.wb_campaign_search] = nm
            if nm:
                sku.nm_id = str(nm)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nLoaded {len(skus)} pilot SKUs from {data_dir}")
    if args.resolve_nm:
        ok = sum(1 for v in report["resolved"].values() if v)
        print(f"Resolved nm_id: {ok}/{len(skus)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
