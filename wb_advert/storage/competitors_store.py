from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from wb_advert.config import settings


def _data_dir(data_dir: Path | None) -> Path:
    if data_dir is not None:
        return data_dir
    return (Path(__file__).resolve().parents[1] / settings.pilot_data_path).resolve()


def competitors_dir(data_dir: Path | None = None) -> Path:
    d = _data_dir(data_dir) / "sync" / "competitors"
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_competitors_snapshot(entry: dict, data_dir: Path | None = None) -> Path:
    """Append one competitors slice to daily JSONL log."""
    d = competitors_dir(data_dir)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = d / f"competitors_{day}.jsonl"
    row = {
        "nm_id": entry.get("nm_id"),
        "keyword": entry.get("keyword"),
        "dest": entry.get("dest"),
        "region_key": entry.get("region_key"),
        "found": entry.get("found"),
        "position": entry.get("position"),
        "our_in_slice": entry.get("our_in_slice", False),
        "competitors_slice": entry.get("competitors_slice") or [],
        "advert_id": entry.get("advert_id"),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
