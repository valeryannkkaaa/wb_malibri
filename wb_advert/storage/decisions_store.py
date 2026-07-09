from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from wb_advert.schemas.optimizer import OptimizeResult
from wb_advert.storage.pilot_store import pilot_data_dir


def decisions_path(data_dir: Path | None = None) -> Path:
    d = (data_dir or pilot_data_dir()) / "sync"
    d.mkdir(parents=True, exist_ok=True)
    return d / "decisions_log.jsonl"


def append_decisions(result: OptimizeResult, data_dir: Path | None = None) -> None:
    path = decisions_path(data_dir)
    line = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_latest_optimize_by_advert(data_dir: Path | None = None) -> dict[int, dict]:
    """Most recent optimizer run per campaign (chronological log)."""
    rows = load_recent_decisions(limit=10_000, data_dir=data_dir)
    latest: dict[int, dict] = {}
    for row in rows:
        advert_id = row.get("advert_id")
        if advert_id is not None:
            latest[int(advert_id)] = row
    return latest


def load_recent_decisions(advert_id: int | None = None, limit: int = 50, data_dir: Path | None = None) -> list[dict]:
    path = decisions_path(data_dir)
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if advert_id is None or row.get("advert_id") == advert_id:
            rows.append(row)
    return rows[-limit:]


def load_decisions_audit(*, limit: int = 300, data_dir: Path | None = None) -> list[dict]:
    """Flatten optimizer log into audit rows (newest first)."""
    rows = load_recent_decisions(limit=limit * 2, data_dir=data_dir)
    out: list[dict] = []
    for row in reversed(rows):
        decided_at = row.get("decided_at")
        advert_id = row.get("advert_id")
        nm_id = row.get("nm_id")
        for s in row.get("suggestions") or []:
            action = s.get("action") or ""
            if action in ("skip",):
                continue
            out.append(
                {
                    "decided_at": decided_at,
                    "advert_id": advert_id,
                    "nm_id": nm_id,
                    "keyword": s.get("keyword"),
                    "action": action,
                    "reason_code": s.get("reason_code"),
                    "reason_text": s.get("reason_text"),
                    "before_state": s.get("before_state"),
                    "after_state": s.get("after_state"),
                }
            )
            if len(out) >= limit:
                return out
    return out
