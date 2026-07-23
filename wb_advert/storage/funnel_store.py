from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from wb_advert.config import settings


def _pkg_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sync_dir(data_dir: Path | None = None) -> Path:
    root = data_dir or (_pkg_root() / settings.pilot_data_path).resolve()
    d = root / "sync"
    d.mkdir(parents=True, exist_ok=True)
    return d


def funnel_path(nm_id: int, data_dir: Path | None = None) -> Path:
    return sync_dir(data_dir) / f"funnel_{nm_id}.json"


def load_funnel(nm_id: int, data_dir: Path | None = None) -> dict | None:
    path = funnel_path(nm_id, data_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def funnel_synced_at(nm_id: int, data_dir: Path | None = None) -> str | None:
    data = load_funnel(nm_id, data_dir)
    if not data:
        return None
    ts = data.get("synced_at")
    return str(ts) if ts else None


def last_funnel_date(nm_id: int, data_dir: Path | None = None) -> date | None:
    data = load_funnel(nm_id, data_dir)
    if not data:
        return None
    rows = data.get("rows") or []
    dates = [str(r.get("dt")) for r in rows if r.get("dt")]
    if not dates:
        return None
    return date.fromisoformat(max(dates))


def merge_funnel_rows(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    by_dt = {str(r["dt"]): r for r in existing if r.get("dt")}
    for row in new_rows:
        dt = row.get("dt")
        if dt:
            by_dt[str(dt)] = row
    return sorted(by_dt.values(), key=lambda r: str(r["dt"]))


def save_funnel(
    nm_id: int,
    *,
    period: dict[str, str],
    rows: list[dict],
    data_dir: Path | None = None,
) -> Path | None:
    if not rows:
        return None
    path = funnel_path(nm_id, data_dir)
    existing = load_funnel(nm_id, data_dir) or {}
    merged_rows = merge_funnel_rows(existing.get("rows") or [], rows)
    payload = {
        "nm_id": nm_id,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "rows": merged_rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
