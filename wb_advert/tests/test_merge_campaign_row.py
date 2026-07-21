"""Tests for atomic campaign row merge in sync report (issue #9)."""

from __future__ import annotations

from wb_advert.scripts.sync_pilot import merge_campaign_row

_NOW = "2026-07-21T17:19:00+00:00"

_PREV = {
    "wb_campaign_id": 35704170,
    "nm_id": 929900180,
    "keywords": 6,
    "top_keyword": "спонж для умывания",
    "top_stats": {"shows": 1282, "ctr": 5.46, "orders": 10},
    "fullstats_ok": True,
    "fullstats_at": "2026-07-06T11:40:00+00:00",
}


def test_failed_attempt_preserves_success_snapshot() -> None:
    attempt = {
        "wb_campaign_id": 35704170,
        "nm_id": 929900180,
        "keywords": 0,
        "errors": ["normquery_stats: HTTP 200 but 0 keywords in period"],
        "top_keyword": None,
        "fullstats_ok": False,
    }

    merged = merge_campaign_row(_PREV, attempt, now=_NOW)

    assert merged["keywords"] == 0
    assert merged["errors"] == attempt["errors"]
    assert merged["last_attempt_at"] == _NOW
    assert merged["top_keyword"] == "спонж для умывания"
    assert merged["top_stats"] == _PREV["top_stats"]
    assert merged["fullstats_ok"] is True
    assert merged["fullstats_at"] == _PREV["fullstats_at"]
    assert "synced_at" not in merged


def test_success_overwrites_previous_snapshot() -> None:
    attempt = {
        "wb_campaign_id": 35704170,
        "nm_id": 929900180,
        "keywords": 8,
        "errors": [],
        "top_keyword": "новый ключ",
        "top_stats": {"shows": 10, "ctr": 1.0, "orders": 1},
        "fullstats_ok": False,
    }

    merged = merge_campaign_row(_PREV, attempt, now=_NOW)

    assert merged["keywords"] == 8
    assert merged["top_keyword"] == "новый ключ"
    assert merged["top_stats"] == attempt["top_stats"]
    assert merged["fullstats_ok"] is False
    assert merged["synced_at"] == _NOW
    assert merged["last_attempt_at"] == _NOW
