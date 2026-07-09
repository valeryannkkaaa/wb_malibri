from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from wb_advert.config import settings


def _data_dir(data_dir: Path | None) -> Path:
    if data_dir is not None:
        return data_dir
    return (Path(__file__).resolve().parents[1] / settings.pilot_data_path).resolve()


def positions_dir(data_dir: Path | None = None) -> Path:
    d = _data_dir(data_dir) / "sync" / "positions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_position_snapshot(entry: dict, data_dir: Path | None = None) -> Path:
    """Append one parse result to daily JSONL log."""
    d = positions_dir(data_dir)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = d / f"positions_{day}.jsonl"
    row = {**entry, "parsed_at": datetime.now(timezone.utc).isoformat()}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


from wb_advert.parser.regions import PARSER_REGION_OPTIONS, normalize_region_key


def _entry_region_key(row: dict) -> str:
    if row.get("region_key"):
        return normalize_region_key(str(row["region_key"]))
    dest = str(row.get("dest") or "")
    for opt in PARSER_REGION_OPTIONS:
        if opt["dest"] == dest:
            return opt["key"]
    return "krasnodar"


def load_latest_positions(
    data_dir: Path | None = None,
    *,
    region_key: str | None = None,
) -> dict[str, dict]:
    """Latest position per nm_id for one region (by parsed_at)."""
    want = normalize_region_key(region_key) if region_key else None
    d = positions_dir(data_dir)
    latest: dict[str, dict] = {}
    for path in sorted(d.glob("positions_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            nm = str(row.get("nm_id") or "")
            if not nm:
                continue
            rk = _entry_region_key(row)
            if want and rk != want:
                continue
            prev = latest.get(nm)
            ts = str(row.get("parsed_at") or "")
            if prev is None or ts >= str(prev.get("parsed_at") or ""):
                latest[nm] = row
    return latest


def load_latest_all_regions(data_dir: Path | None = None) -> dict[str, dict[str, dict]]:
    """region_key -> nm_id -> latest row."""
    out: dict[str, dict[str, dict]] = {opt["key"]: {} for opt in PARSER_REGION_OPTIONS}
    d = positions_dir(data_dir)
    for path in sorted(d.glob("positions_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            nm = str(row.get("nm_id") or "")
            if not nm:
                continue
            rk = _entry_region_key(row)
            bucket = out.setdefault(rk, {})
            prev = bucket.get(nm)
            ts = str(row.get("parsed_at") or "")
            if prev is None or ts >= str(prev.get("parsed_at") or ""):
                bucket[nm] = row
    return out


def count_positions_for_region(region_key: str, data_dir: Path | None = None) -> int:
    return sum(1 for row in load_latest_positions(data_dir, region_key=region_key).values() if row.get("found"))


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def position_age_minutes(
    nm_id: str,
    *,
    region_key: str,
    data_dir: Path | None = None,
) -> float | None:
    """Minutes since last parse for nm_id in region; None if never parsed."""
    row = load_latest_positions(data_dir, region_key=region_key).get(str(nm_id))
    if not row:
        return None
    parsed = _parse_ts(row.get("parsed_at"))
    if not parsed:
        return None
    now = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed).total_seconds() / 60.0


def is_position_fresh(
    nm_id: str,
    *,
    region_key: str,
    min_age_min: float,
    data_dir: Path | None = None,
) -> bool:
    age = position_age_minutes(nm_id, region_key=region_key, data_dir=data_dir)
    if age is None:
        return False
    return age < min_age_min


def load_position_history(
    nm_id: str,
    *,
    limit: int = 14,
    region_key: str | None = None,
    data_dir: Path | None = None,
) -> list[dict]:
    """Recent parse snapshots for one nm_id (+ optional region), newest first."""
    want = normalize_region_key(region_key) if region_key else None
    d = positions_dir(data_dir)
    rows: list[dict] = []
    for path in sorted(d.glob("positions_*.jsonl"), reverse=True):
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("nm_id") or "") != nm_id:
                continue
            if want and _entry_region_key(row) != want:
                continue
            rows.append(row)
            if len(rows) >= limit:
                return rows
    return rows


def write_positions_summary(entries: list[dict], data_dir: Path | None = None) -> Path:
    path = _data_dir(data_dir) / "last_positions_report.json"
    report = {
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "count": len(entries),
        "entries": entries,
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
