from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from wb_advert.config import settings
from wb_advert.schemas.sync import KeywordMetrics


def _pkg_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sync_dir(data_dir: Path | None = None) -> Path:
    root = data_dir or (_pkg_root() / settings.pilot_data_path).resolve()
    d = root / "sync"
    d.mkdir(parents=True, exist_ok=True)
    return d


def keywords_path(advert_id: int, data_dir: Path | None = None) -> Path:
    return sync_dir(data_dir) / f"keywords_{advert_id}.json"


def save_keywords(
    advert_id: int,
    nm_id: int,
    keywords: list[KeywordMetrics],
    *,
    data_dir: Path | None = None,
) -> Path:
    path = keywords_path(advert_id, data_dir)
    payload = {
        "wb_campaign_id": advert_id,
        "nm_id": nm_id,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "keywords": [k.model_dump() for k in keywords],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_keywords(advert_id: int, data_dir: Path | None = None) -> dict | None:
    path = keywords_path(advert_id, data_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def campaign_keywords_synced_at(advert_id: int, data_dir: Path | None = None) -> str | None:
    """When keywords were last saved successfully (one file, one campaign)."""
    data = load_keywords(advert_id, data_dir)
    if not data:
        return None
    ts = data.get("synced_at")
    return str(ts) if ts else None


def list_saved_campaign_ids(data_dir: Path | None = None) -> list[int]:
    d = sync_dir(data_dir)
    ids: list[int] = []
    for p in d.glob("keywords_*.json"):
        try:
            ids.append(int(p.stem.removeprefix("keywords_")))
        except ValueError:
            continue
    return sorted(ids)
