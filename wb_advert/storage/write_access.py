"""Cached result of WB write-token probe."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from wb_advert.storage.pilot_store import pilot_data_dir


def write_access_path(data_dir: Path | None = None) -> Path:
    d = (data_dir or pilot_data_dir()) / "sync"
    d.mkdir(parents=True, exist_ok=True)
    return d / "write_access.json"


def load_write_access(data_dir: Path | None = None) -> dict:
    path = write_access_path(data_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_write_access(report: dict, data_dir: Path | None = None) -> Path:
    path = write_access_path(data_dir)
    report = {**report, "checked_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
