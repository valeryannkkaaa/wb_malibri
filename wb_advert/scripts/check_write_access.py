#!/usr/bin/env python
"""Probe whether current WB token can change bids / exclude keywords."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.client.promotion import PromotionClient  # noqa: E402
from wb_advert.config import require_token  # noqa: E402
from wb_advert.executor.guards import get_apply_settings  # noqa: E402
from wb_advert.import_data.csv_loader import load_pilot_skus  # noqa: E402
from wb_advert.storage.pilot_store import pilot_data_dir  # noqa: E402
from wb_advert.storage.write_access import save_write_access  # noqa: E402


def _classify(status: int | None) -> str:
    if status is None:
        return "network_error"
    if status in (401, 403):
        return "forbidden"
    if status == 429:
        return "rate_limit"
    if 200 <= status < 300:
        return "ok"
    if 400 <= status < 500:
        return "bad_request"
    return "server_error"


def main() -> int:
    require_token()
    data_dir = pilot_data_dir()
    skus = [s for s in load_pilot_skus(data_dir / "pilot_skus.csv") if s.wb_campaign_search and s.nm_id]
    if not skus:
        print("No pilot SKUs for probe")
        return 1

    sku = skus[0]
    advert_id = int(sku.wb_campaign_search)
    nm_id = int(sku.nm_id)
    client = PromotionClient()

    probes: list[dict] = []

    min_resp = client.bids_min(advert_id, nm_id)
    probes.append(
        {
            "endpoint": "bids/min",
            "status": min_resp.status,
            "class": _classify(min_resp.status),
            "sample": (min_resp.body or "")[:160],
        }
    )

    bid_resp = client.normquery_set_bids(advert_id, nm_id, "__probe_keyword__", 35000)
    probes.append(
        {
            "endpoint": "normquery/bids",
            "status": bid_resp.status,
            "class": _classify(bid_resp.status),
            "sample": (bid_resp.body or "")[:160],
        }
    )

    minus_resp = client.normquery_set_minus(advert_id, nm_id, ["__probe_keyword__"])
    probes.append(
        {
            "endpoint": "normquery/set-minus",
            "status": minus_resp.status,
            "class": _classify(minus_resp.status),
            "sample": (minus_resp.body or "")[:160],
        }
    )

    write_classes = {p["class"] for p in probes if p["endpoint"] != "bids/min"}
    can_write = "ok" in write_classes or (
        "bad_request" in write_classes and "forbidden" not in write_classes
    )

    if "forbidden" in write_classes:
        summary = "Токен без прав на запись (403/401)"
        can_write = False
    elif can_write:
        summary = "Write-доступ вероятно есть (ответ не 403)"
    else:
        summary = "Write-доступ не подтверждён"

    report = {
        "advert_id": advert_id,
        "nm_id": nm_id,
        "can_write": can_write,
        "summary": summary,
        "probes": probes,
        "apply_settings": get_apply_settings(data_dir),
    }
    path = save_write_access(report, data_dir)

    print(f"Write probe: {summary}")
    for p in probes:
        print(f"  {p['endpoint']}: HTTP {p['status']} ({p['class']})")
    print(f"Saved: {path}")

    settings = report["apply_settings"]
    if settings["blocked_reasons"]:
        print("Apply blocked:")
        for r in settings["blocked_reasons"]:
            print(f"  - {r}")
    else:
        print("Apply ready: optimizer_mode=auto + allow_wb_writes=true")

    return 0 if can_write else 2


if __name__ == "__main__":
    raise SystemExit(main())
