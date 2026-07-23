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


def test_pick_rotate_skus_prefers_never_attempted_over_csv_order(tmp_path: Path) -> None:
    """Campaign with no attempt and no keywords file wins over CSV order."""
    report = tmp_path / "last_sync_report.json"
    _write_report(
        report,
        [
            {"wb_campaign_id": 111, "keywords": 10, "last_attempt_at": "2026-07-06T11:00:00+00:00"},
            {"wb_campaign_id": 222, "keywords": 10},
            {"wb_campaign_id": 333, "keywords": 10, "last_attempt_at": "2026-07-21T16:00:00+00:00"},
        ],
    )
    ready = [_sku(111), _sku(222), _sku(333)]

    picked = pick_rotate_skus(ready, report, limit=1)

    assert [s.wb_campaign_search for s in picked] == [222]


def test_pick_rotate_skus_picks_oldest_attempt_when_all_tried(tmp_path: Path) -> None:
    report = tmp_path / "last_sync_report.json"
    _write_report(
        report,
        [
            {"wb_campaign_id": 111, "keywords": 10, "last_attempt_at": "2026-07-10T12:00:00+00:00"},
            {"wb_campaign_id": 222, "keywords": 10, "last_attempt_at": "2026-07-06T11:00:00+00:00"},
            {"wb_campaign_id": 333, "keywords": 10, "last_attempt_at": "2026-07-08T09:00:00+00:00"},
        ],
    )
    ready = [_sku(111), _sku(222), _sku(333)]

    picked = pick_rotate_skus(ready, report, limit=2)

    assert [s.wb_campaign_search for s in picked] == [222, 333]


def test_failed_attempt_does_not_block_queue(tmp_path: Path) -> None:
    """Recent failed attempt must not keep campaign first in every batch."""
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    (sync_dir / "keywords_35704170.json").write_text(
        json.dumps({"synced_at": "2026-07-06T11:40:03+00:00"}),
        encoding="utf-8",
    )
    (sync_dir / "keywords_31275686.json").write_text(
        json.dumps({"synced_at": "2026-07-06T11:41:17+00:00"}),
        encoding="utf-8",
    )
    report = tmp_path / "last_sync_report.json"
    _write_report(
        report,
        [
            {
                "wb_campaign_id": 35704170,
                "keywords": 0,
                "last_attempt_at": "2026-07-21T17:00:00+00:00",
            },
            {"wb_campaign_id": 31275686, "keywords": 39},
            {"wb_campaign_id": 33206165, "keywords": 46},
        ],
    )
    ready = [_sku(35704170), _sku(31275686), _sku(33206165)]

    picked = pick_rotate_skus(ready, report, limit=3)

    assert [s.wb_campaign_search for s in picked][0] != 35704170
