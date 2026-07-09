"""Append-only log of applied optimizer actions."""

from __future__ import annotations

import json
from pathlib import Path

from wb_advert.storage.pilot_store import pilot_data_dir


def apply_log_path(data_dir: Path | None = None) -> Path:
    d = (data_dir or pilot_data_dir()) / "sync"
    d.mkdir(parents=True, exist_ok=True)
    return d / "apply_log.jsonl"


def append_apply_record(record: dict, data_dir: Path | None = None) -> None:
    path = apply_log_path(data_dir)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_recent_apply(limit: int = 50, data_dir: Path | None = None) -> list[dict]:
    path = apply_log_path(data_dir)
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]
