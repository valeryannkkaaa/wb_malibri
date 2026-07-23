"""Tests for competitors slice storage."""

from __future__ import annotations

import json
from pathlib import Path

from wb_advert.storage.competitors_store import append_competitors_snapshot, competitors_dir


def _sample_entry(**overrides) -> dict:
    base = {
        "nm_id": 624468743,
        "keyword": "перчатки для уборки",
        "dest": "-1059500",
        "region_key": "krasnodar",
        "found": True,
        "position": 3,
        "our_in_slice": True,
        "competitors_slice": [
            {
                "nm_id": 907517204,
                "position": 1,
                "brand": None,
                "price_rub": 115.0,
                "rating": 4.9,
                "feedbacks": 55,
                "is_ours": False,
            },
            {
                "nm_id": 624468743,
                "position": 3,
                "brand": "Dora",
                "price_rub": 136.0,
                "rating": 4.9,
                "feedbacks": 2236,
                "is_ours": True,
            },
        ],
        "advert_id": 33206346,
    }
    base.update(overrides)
    return base


def test_append_competitors_snapshot_writes_dated_file(tmp_path: Path) -> None:
    path = append_competitors_snapshot(_sample_entry(), tmp_path)

    assert path.parent == competitors_dir(tmp_path)
    assert path.name.startswith("competitors_")
    assert path.name.endswith(".jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["nm_id"] == 624468743
    assert row["our_in_slice"] is True
    assert len(row["competitors_slice"]) == 2
    assert row["competitors_slice"][1]["is_ours"] is True
    assert "parsed_at" in row


def test_append_competitors_snapshot_appends_without_overwrite(tmp_path: Path) -> None:
    first = append_competitors_snapshot(_sample_entry(nm_id=1), tmp_path)
    second = append_competitors_snapshot(_sample_entry(nm_id=2, our_in_slice=False), tmp_path)

    assert first == second
    lines = first.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["nm_id"] == 1
    assert json.loads(lines[1])["nm_id"] == 2


def test_append_competitors_snapshot_saves_not_in_slice(tmp_path: Path) -> None:
    entry = _sample_entry(
        found=False,
        position=None,
        our_in_slice=False,
        competitors_slice=[
            {
                "nm_id": 111,
                "position": 1,
                "brand": "Other",
                "price_rub": 99.0,
                "rating": 4.5,
                "feedbacks": 10,
                "is_ours": False,
            }
        ],
    )
    path = append_competitors_snapshot(entry, tmp_path)
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["our_in_slice"] is False
    assert row["found"] is False
    assert all(not item["is_ours"] for item in row["competitors_slice"])
