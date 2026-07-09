"""Cycle snapshots — memory for before/after bid and position comparison."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from wb_advert.parser.regions import PARSER_REGION_OPTIONS, normalize_region_key
from wb_advert.optimizer.summary import summarize_campaign
from wb_advert.storage.config_store import get_parser_settings, load_config
from wb_advert.storage.decisions_store import load_latest_optimize_by_advert
from wb_advert.storage.keywords_store import load_keywords
from wb_advert.storage.pilot_store import (
    build_product_rows,
    load_stocks_by_nm,
    load_sync_report,
    load_unit_economics,
    pilot_data_dir,
)
from wb_advert.storage.positions_store import load_latest_all_regions


def snapshots_dir(data_dir: Path | None = None) -> Path:
    d = (data_dir or pilot_data_dir()) / "sync" / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _today_path(data_dir: Path | None = None) -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return snapshots_dir(data_dir) / f"snapshots_{day}.jsonl"


def append_snapshot_rows(rows: list[dict], data_dir: Path | None = None) -> Path:
    path = _today_path(data_dir)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _primary_kw_metrics(kw_file: dict | None, primary: str) -> dict | None:
    if not kw_file or not primary:
        return None
    pl = primary.strip().lower()
    for k in kw_file.get("keywords") or []:
        if (k.get("keyword") or "").strip().lower() == pl:
            return k
    return None


def _optimizer_hint_for_keyword(opt_row: dict | None, keyword: str) -> dict | None:
    if not opt_row:
        return None
    kl = keyword.strip().lower()
    for s in opt_row.get("suggestions") or []:
        if (s.get("keyword") or "").strip().lower() == kl:
            return {
                "action": s.get("action"),
                "reason_code": s.get("reason_code"),
                "reason_text": s.get("reason_text"),
            }
    return None


def build_cycle_snapshot_rows(
    data_dir: Path | None = None,
    *,
    cycle_id: str | None = None,
) -> list[dict]:
    """Build keyword + campaign snapshots for all pilot SKUs (all parser regions)."""
    data_dir = data_dir or pilot_data_dir()
    recorded_at = datetime.now(timezone.utc)
    cycle_id = cycle_id or recorded_at.isoformat()
    config = load_config(data_dir)
    optimizer_mode = config.get("optimizer_mode", "suggest-only")
    parser_region_key = get_parser_settings(data_dir)["region_key"]

    products = build_product_rows(data_dir, region_key=parser_region_key)
    latest_opt = load_latest_optimize_by_advert(data_dir)
    positions_by_region = load_latest_all_regions(data_dir)
    economics = load_unit_economics(data_dir)
    stocks = load_stocks_by_nm(data_dir)
    report = load_sync_report(data_dir)
    by_advert = {
        int(c["wb_campaign_id"]): c
        for c in report.get("campaigns") or []
        if c.get("wb_campaign_id")
    }

    rows: list[dict] = []
    ts = recorded_at.isoformat()

    for product in products:
        advert_id = int(product["advert_id"])
        nm_id = str(product["nm_id"])
        primary = (product.get("primary_keyword") or "").strip()
        kw_file = load_keywords(advert_id, data_dir)
        opt_row = latest_opt.get(advert_id)
        sync_row = by_advert.get(advert_id, {})
        econ = economics.get(nm_id, {})
        stock = stocks.get(nm_id, {})
        kw_metrics = _primary_kw_metrics(kw_file, primary)
        opt_hint = _optimizer_hint_for_keyword(opt_row, primary) if primary else None

        recommendation = summarize_campaign(
            advert_id=advert_id,
            nm_id=nm_id,
            primary_keyword=primary or None,
            suggestions=(opt_row or {}).get("suggestions") or [],
            alerts=(opt_row or {}).get("alerts"),
            decided_at=(opt_row or {}).get("decided_at"),
        )

        rows.append(
            {
                "snapshot_type": "campaign",
                "cycle_id": cycle_id,
                "recorded_at": ts,
                "advert_id": advert_id,
                "nm_id": nm_id,
                "region_key": parser_region_key,
                "optimizer_mode": optimizer_mode,
                "primary_keyword": primary or None,
                "target_grade": product.get("target_grade"),
                "top_stats": sync_row.get("top_stats") or product.get("top_stats"),
                "stock_quantity": stock.get("quantity", product.get("stock_quantity", 0)),
                "stock_in_way": stock.get("in_way", product.get("stock_in_way", 0)),
                "retail_price_rub": econ.get("retail_price_rub") or product.get("retail_price_rub"),
                "max_cpc_rub": product.get("max_cpc_rub"),
                "recommendation_summary": recommendation.get("summary"),
                "recommendation_action": recommendation.get("action"),
                "recommendation_reason": recommendation.get("reason_text"),
                "actionable_count": recommendation.get("actionable_count", 0),
                "optimizer_decided_at": (opt_row or {}).get("decided_at"),
                "alerts": (opt_row or {}).get("alerts") or [],
            }
        )

        if not primary:
            continue

        for opt in PARSER_REGION_OPTIONS:
            region_key = opt["key"]
            pos = (positions_by_region.get(region_key) or {}).get(nm_id, {})
            rows.append(
                {
                    "snapshot_type": "keyword",
                    "cycle_id": cycle_id,
                    "recorded_at": ts,
                    "advert_id": advert_id,
                    "nm_id": nm_id,
                    "keyword": primary,
                    "region_key": region_key,
                    "optimizer_mode": optimizer_mode,
                    "target_grade": product.get("target_grade"),
                    "parsed_position": pos.get("position") if pos.get("found") else None,
                    "position_found": bool(pos.get("found")),
                    "position_parsed_at": pos.get("parsed_at"),
                    "position_error": None if pos.get("found") else pos.get("error"),
                    "shows": int((kw_metrics or {}).get("shows") or 0),
                    "clicks": int((kw_metrics or {}).get("clicks") or 0),
                    "spend_kopecks": int((kw_metrics or {}).get("spend_kopecks") or 0),
                    "orders": int((kw_metrics or {}).get("orders") or 0),
                    "ctr": (kw_metrics or {}).get("ctr_calculated"),
                    "cpc_kopecks": (kw_metrics or {}).get("cpc_calculated_kopecks"),
                    "bid_kopecks": (kw_metrics or {}).get("current_bid_kopecks"),
                    "stock_quantity": stock.get("quantity", product.get("stock_quantity", 0)),
                    "retail_price_rub": econ.get("retail_price_rub") or product.get("retail_price_rub"),
                    "max_cpc_rub": product.get("max_cpc_rub"),
                    "optimizer_action": (opt_hint or {}).get("action"),
                    "optimizer_reason_code": (opt_hint or {}).get("reason_code"),
                    "optimizer_reason_text": (opt_hint or {}).get("reason_text"),
                    "optimizer_decided_at": (opt_row or {}).get("decided_at"),
                }
            )

    return rows


def capture_cycle_snapshots(
    data_dir: Path | None = None,
    *,
    cycle_id: str | None = None,
) -> dict:
    rows = build_cycle_snapshot_rows(data_dir, cycle_id=cycle_id)
    path = append_snapshot_rows(rows, data_dir)
    keyword_rows = sum(1 for r in rows if r.get("snapshot_type") == "keyword")
    campaign_rows = sum(1 for r in rows if r.get("snapshot_type") == "campaign")
    return {
        "cycle_id": rows[0]["cycle_id"] if rows else cycle_id,
        "recorded_at": rows[0]["recorded_at"] if rows else None,
        "path": str(path),
        "keyword_rows": keyword_rows,
        "campaign_rows": campaign_rows,
        "total_rows": len(rows),
    }


def _iter_snapshot_lines(data_dir: Path | None = None):
    d = snapshots_dir(data_dir)
    for path in sorted(d.glob("snapshots_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_recent_snapshots(
    *,
    advert_id: int | None = None,
    keyword: str | None = None,
    region_key: str | None = None,
    snapshot_type: str | None = "keyword",
    limit: int = 200,
    data_dir: Path | None = None,
) -> list[dict]:
    """Newest first."""
    want_kw = keyword.strip().lower() if keyword else None
    want_region = normalize_region_key(region_key) if region_key else None
    rows: list[dict] = []
    for row in reversed(list(_iter_snapshot_lines(data_dir))):
        if snapshot_type and row.get("snapshot_type") != snapshot_type:
            continue
        if advert_id is not None and row.get("advert_id") != advert_id:
            continue
        if want_kw and (row.get("keyword") or "").strip().lower() != want_kw:
            continue
        if want_region and normalize_region_key(str(row.get("region_key") or "")) != want_region:
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def load_snapshot_history(
    advert_id: int,
    keyword: str,
    *,
    region_key: str | None = None,
    snapshot_type: str = "keyword",
    limit: int = 40,
    data_dir: Path | None = None,
) -> list[dict]:
    """Chronological oldest→newest for charts."""
    rows = load_recent_snapshots(
        advert_id=advert_id,
        keyword=keyword,
        region_key=region_key,
        snapshot_type=snapshot_type,
        limit=limit,
        data_dir=data_dir,
    )
    return list(reversed(rows))


def get_snapshots_meta(data_dir: Path | None = None) -> dict:
    """Summary for dashboard badge."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = snapshots_dir(data_dir) / f"snapshots_{today}.jsonl"
    cycles_today: set[str] = set()
    keyword_rows_today = 0
    last_recorded_at: str | None = None

    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("snapshot_type") == "keyword":
                keyword_rows_today += 1
            cid = row.get("cycle_id")
            if cid:
                cycles_today.add(str(cid))
            ts = str(row.get("recorded_at") or "")
            if not last_recorded_at or ts > last_recorded_at:
                last_recorded_at = ts

    all_files = list(snapshots_dir(data_dir).glob("snapshots_*.jsonl"))
    return {
        "last_recorded_at": last_recorded_at,
        "cycles_today": len(cycles_today),
        "keyword_rows_today": keyword_rows_today,
        "snapshot_files": len(all_files),
    }
