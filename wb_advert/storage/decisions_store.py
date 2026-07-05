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
