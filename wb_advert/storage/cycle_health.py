from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from wb_advert.storage.pilot_store import _pkg_root


def _log_dir_candidates() -> list[Path]:
    root = _pkg_root()
    repo = root.parent
    return [
        repo / "data" / "pilot" / "logs",
        root / "logs",
        Path(os.environ.get("LOCALAPPDATA", "")) / "WBAdvert" / "logs",
        Path(os.environ.get("TEMP", "")) / "wb-advert" / "logs",
    ]


def _find_latest_log() -> Path | None:
    candidates: list[Path] = []
    for d in _log_dir_candidates():
        if d.is_dir():
            candidates.extend(d.glob("cycle_*.log"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _parse_log_timestamp(line: str) -> datetime | None:
    m = re.match(r"^========== (.+?) ==========$", line.strip())
    if not m:
        return None
    raw = m.group(1)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def load_cycle_health() -> dict:
    log_path = _find_latest_log()
    if not log_path or not log_path.is_file():
        return {
            "status": "unknown",
            "log_path": None,
            "last_started_at": None,
            "last_finished_at": None,
            "age_minutes": None,
            "exit_code": None,
            "tail": [],
        }

    try:
        text = log_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return {"status": "error", "log_path": str(log_path), "tail": []}

    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    starts: list[datetime] = []
    finished_at: datetime | None = None
    exit_code: int | None = None

    for line in lines:
        ts = _parse_log_timestamp(line)
        if ts:
            if "cycle finished" in line:
                finished_at = ts
            else:
                starts.append(ts)
        m = re.search(r"exit code:\s*(\d+)", line, re.I)
        if m:
            exit_code = int(m.group(1))

    last_started = starts[-1] if starts else None
    has_finished = any("cycle finished" in line for line in lines)
    if has_finished and log_path:
        finished_at = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
    else:
        finished_at = None

    age_minutes: float | None = None
    ref = finished_at or last_started
    if ref:
        age_minutes = round((datetime.now(timezone.utc) - ref).total_seconds() / 60, 1)

    status = "ok"
    if exit_code and exit_code != 0:
        status = "error"
    elif age_minutes is not None and age_minutes > 30:
        status = "stale"
    elif last_started and not has_finished:
        status = "running"

    return {
        "status": status,
        "log_path": str(log_path),
        "last_started_at": last_started.isoformat() if last_started else None,
        "last_finished_at": finished_at.isoformat() if finished_at else None,
        "age_minutes": age_minutes,
        "exit_code": exit_code,
        "tail": lines[-12:],
    }
