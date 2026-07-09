from __future__ import annotations

from wb_advert.storage.decisions_store import load_recent_decisions
from wb_advert.storage.positions_store import load_position_history


def build_position_chart(nm_id: str, *, region_key: str | None = None, limit: int = 30) -> dict:
    """Line chart data: successful parses only, oldest→newest."""
    rows = list(reversed(load_position_history(nm_id, limit=limit * 3, region_key=region_key)))
    labels: list[str] = []
    values: list[int] = []
    for row in rows:
        if not row.get("found") or row.get("position") is None:
            continue
        ts = str(row.get("parsed_at") or "")[:16].replace("T", " ")
        labels.append(ts)
        values.append(int(row["position"]))
        if len(labels) >= limit:
            break
    return {"labels": labels, "values": values}


def build_ctr_chart(
    advert_id: int,
    primary_keyword: str,
    *,
    region_key: str | None = None,
    limit: int = 40,
) -> dict:
    """CTR over time — prefer cycle snapshots, fallback to optimizer log."""
    from wb_advert.storage.snapshots_store import load_snapshot_history

    history = load_snapshot_history(
        advert_id,
        primary_keyword,
        region_key=region_key,
        snapshot_type="keyword",
        limit=limit * 2,
    )
    if history:
        labels: list[str] = []
        values: list[float] = []
        for row in history:
            ctr = row.get("ctr")
            if ctr is None:
                continue
            labels.append(str(row.get("recorded_at") or "")[:16].replace("T", " "))
            values.append(float(ctr))
            if len(labels) >= limit:
                break
        if labels:
            return {"labels": labels, "values": values}

    primary = primary_keyword.strip().lower()
    rows = load_recent_decisions(advert_id=advert_id, limit=500)
    labels: list[str] = []
    values: list[float] = []
    seen: set[str] = set()

    for row in rows:
        decided = str(row.get("decided_at") or "")
        if decided in seen:
            continue
        for s in row.get("suggestions") or []:
            kw = (s.get("keyword") or "").strip().lower()
            if kw != primary:
                continue
            ctr = (s.get("before_state") or {}).get("ctr")
            if ctr is None:
                continue
            seen.add(decided)
            labels.append(decided[:16].replace("T", " "))
            values.append(float(ctr))
            break

    if len(labels) > limit:
        labels = labels[-limit:]
        values = values[-limit:]

    return {"labels": labels, "values": values}
