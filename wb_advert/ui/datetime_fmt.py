"""Display timestamps in Moscow time for the dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def _parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_dt_msk(value: str | datetime | None) -> str:
    dt = _parse_dt(value)
    if dt is None:
        return "—"
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M MSK")
