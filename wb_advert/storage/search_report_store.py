from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from wb_advert.config import settings


def _pkg_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sync_dir(data_dir: Path | None = None) -> Path:
    root = data_dir or (_pkg_root() / settings.pilot_data_path).resolve()
    d = root / "sync"
    d.mkdir(parents=True, exist_ok=True)
    return d


def search_report_path(nm_id: int, data_dir: Path | None = None) -> Path:
    return sync_dir(data_dir) / f"search_report_{nm_id}.json"


def load_search_report(nm_id: int, data_dir: Path | None = None) -> dict | None:
    path = search_report_path(nm_id, data_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def search_report_synced_at(nm_id: int, data_dir: Path | None = None) -> str | None:
    """When search report was last saved successfully (one file, one nm_id)."""
    data = load_search_report(nm_id, data_dir)
    if not data:
        return None
    ts = data.get("synced_at")
    return str(ts) if ts else None


def save_search_report(
    nm_id: int,
    *,
    period: dict[str, str],
    items: list[dict],
    data_dir: Path | None = None,
) -> Path | None:
    if not items:
        return None
    path = search_report_path(nm_id, data_dir)
    payload = {
        "nm_id": nm_id,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "items": items,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
