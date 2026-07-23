from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from wb_advert.config import settings


def _data_dir(data_dir: Path | None) -> Path:
    if data_dir is not None:
        return data_dir
    return (Path(__file__).resolve().parents[1] / settings.pilot_data_path).resolve()


def competitors_dir(data_dir: Path | None = None) -> Path:
    d = _data_dir(data_dir) / "sync" / "competitors"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _competitors_files(data_dir: Path | None = None) -> list[Path]:
    return sorted(competitors_dir(data_dir).glob("competitors_*.jsonl"), reverse=True)


def load_latest_competitors_snapshot(nm_id: int | str, data_dir: Path | None = None) -> dict | None:
    """Latest competitors slice for nm_id: newest daily file, last matching row."""
    files = _competitors_files(data_dir)
    if not files:
        return None

    target_nm = int(nm_id)
    last_match: dict | None = None
    try:
        text = files[0].read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if int(row.get("nm_id") or 0) == target_nm:
            last_match = row
    return last_match


def _median_neighbor_price(competitors_slice: list[dict]) -> float | None:
    prices = [
        float(item["price_rub"])
        for item in competitors_slice
        if not item.get("is_ours") and item.get("price_rub") is not None
    ]
    if not prices:
        return None
    return float(statistics.median(prices))


def build_competitors_display(snapshot: dict | None) -> dict:
    """Prepare competitors block for product page."""
    if not snapshot:
        return {"available": False}

    competitors_slice = snapshot.get("competitors_slice") or []
    our_row = next((item for item in competitors_slice if item.get("is_ours")), None)
    our_in_slice = bool(snapshot.get("our_in_slice")) and our_row is not None
    median_price = _median_neighbor_price(competitors_slice)

    price_summary: str | None = None
    if not our_in_slice:
        price_summary = "Нас нет в текущем срезе выдачи"
    elif our_row and our_row.get("price_rub") is not None and median_price is not None:
        our_price = float(our_row["price_rub"])
        diff = round(our_price - median_price, 2)
        median_label = round(median_price, 2)
        if diff > 0:
            price_summary = (
                f"Наша цена {our_price:g} ₽ — дороже медианы соседей ({median_label:g} ₽) на {diff:g} ₽"
            )
        elif diff < 0:
            price_summary = (
                f"Наша цена {our_price:g} ₽ — дешевле медианы соседей ({median_label:g} ₽) "
                f"на {abs(diff):g} ₽"
            )
        else:
            price_summary = f"Наша цена {our_price:g} ₽ — на уровне медианы соседей ({median_label:g} ₽)"
    elif our_row and our_row.get("price_rub") is not None:
        price_summary = f"Наша цена {float(our_row['price_rub']):g} ₽"

    rows = sorted(
        competitors_slice,
        key=lambda item: (item.get("position") is None, item.get("position") or 10**9),
    )

    return {
        "available": True,
        "keyword": snapshot.get("keyword"),
        "parsed_at": snapshot.get("parsed_at"),
        "our_in_slice": our_in_slice,
        "price_summary": price_summary,
        "rows": rows,
    }


def append_competitors_snapshot(entry: dict, data_dir: Path | None = None) -> Path:
    """Append one competitors slice to daily JSONL log."""
    d = competitors_dir(data_dir)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = d / f"competitors_{day}.jsonl"
    row = {
        "nm_id": entry.get("nm_id"),
        "keyword": entry.get("keyword"),
        "dest": entry.get("dest"),
        "region_key": entry.get("region_key"),
        "found": entry.get("found"),
        "position": entry.get("position"),
        "our_in_slice": entry.get("our_in_slice", False),
        "competitors_slice": entry.get("competitors_slice") or [],
        "advert_id": entry.get("advert_id"),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
