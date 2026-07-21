"""Tests for sync_pilot campaign rotation (issue #9)."""

from __future__ import annotations

import json
from pathlib import Path

from wb_advert.schemas.wb_api import PilotSkuRow
from wb_advert.scripts.sync_pilot import pick_rotate_skus


def _sku(advert_id: int, nm_id: str = "100") -> PilotSkuRow:
    return PilotSkuRow(
        nm_id=nm_id,
        wb_campaign_search=advert_id,
    )


def _write_report(path: Path, campaigns: list[dict]) -> None:
    path.write_text(
        json.dumps({"synced_at": "2026-07-21T16:00:00+00:00", "campaigns": campaigns}),
        encoding="utf-8",
    )


def test_pick_rotate_skus_prefers_missing_synced_at_over_csv_order(tmp_path: Path) -> None:
    """Campaign without synced_at must win over first CSV row and over recently synced."""
    report = tmp_path / "last_sync_report.json"
    _write_report(
        report,
        [
            {"wb_campaign_id": 111, "keywords": 10, "synced_at": "2026-07-06T11:00:00+00:00"},
            {"wb_campaign_id": 222, "keywords": 10},  # never synced in report
            {"wb_campaign_id": 333, "keywords": 10, "synced_at": "2026-07-21T16:00:00+00:00"},
        ],
    )
    ready = [_sku(111), _sku(222), _sku(333)]

    picked = pick_rotate_skus(ready, report, limit=1)

    assert [s.wb_campaign_search for s in picked] == [222]


def test_pick_rotate_skus_picks_oldest_when_all_synced(tmp_path: Path) -> None:
    report = tmp_path / "last_sync_report.json"
    _write_report(
        report,
        [
            {"wb_campaign_id": 111, "keywords": 10, "synced_at": "2026-07-10T12:00:00+00:00"},
            {"wb_campaign_id": 222, "keywords": 10, "synced_at": "2026-07-06T11:00:00+00:00"},
            {"wb_campaign_id": 333, "keywords": 10, "synced_at": "2026-07-08T09:00:00+00:00"},
        ],
    )
    ready = [_sku(111), _sku(222), _sku(333)]

    picked = pick_rotate_skus(ready, report, limit=2)

    assert [s.wb_campaign_search for s in picked] == [222, 333]
