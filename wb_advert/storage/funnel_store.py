from __future__ import annotations

import json
from pathlib import Path

from wb_advert.storage.search_report_store import sync_dir


def funnel_path(nm_id: int | str, data_dir: Path | None = None) -> Path:
    return sync_dir(data_dir) / f"funnel_{nm_id}.json"


def load_funnel(nm_id: int | str, data_dir: Path | None = None) -> dict | None:
    path = funnel_path(nm_id, data_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
