from __future__ import annotations

import json
from pathlib import Path

from wb_advert.config import settings
from wb_advert.constants import PENDING_NM_PREFIX
from wb_advert.import_data.csv_loader import load_pilot_skus
from wb_advert.optimizer.rules import calc_max_cpc_kopecks, resolve_cr_fact
from wb_advert.optimizer.summary import summarize_campaign
from wb_advert.storage.config_store import get_parser_settings, load_config
from wb_advert.storage.keywords_store import load_keywords
from wb_advert.storage.positions_store import count_positions_for_region, load_latest_positions


def pilot_data_dir() -> Path:
    return (_pkg_root() / settings.pilot_data_path).resolve()


def _pkg_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_sync_report(data_dir: Path | None = None) -> dict:
    path = (data_dir or pilot_data_dir()) / "last_sync_report.json"
    if not path.is_file():
        return {"campaigns": [], "primary_keywords": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"campaigns": [], "primary_keywords": {}}


def _economics_complete(econ: dict) -> bool:
    if not econ.get("retail_price_rub"):
        return False
    return bool(econ.get("cost_price_rub") or econ.get("margin_pct"))


def _max_cpc_kopecks(
    econ: dict,
    *,
    kw_clicks: int = 0,
    kw_orders: int = 0,
    campaign_clicks: int = 0,
    campaign_orders: int = 0,
) -> int | None:
    retail = econ.get("retail_price_rub")
    if not retail:
        return None
    cr_fact = resolve_cr_fact(kw_clicks, kw_orders, campaign_clicks, campaign_orders)
    if cr_fact is None:
        return None
    max_drr = float(econ.get("max_drr_pct") or 15)
    return calc_max_cpc_kopecks(float(retail), max_drr, cr_fact)


def load_stocks_by_nm(data_dir: Path | None = None) -> dict[str, dict]:
    path = (data_dir or pilot_data_dir()) / "sync" / "stocks_report.json"
    if not path.is_file():
        return {}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    totals: dict[str, dict] = {}
    for item in report.get("items") or []:
        nm = str(item.get("nmId") or "")
        if not nm:
            continue
        bucket = totals.setdefault(nm, {"quantity": 0, "in_way": 0})
        bucket["quantity"] += int(item.get("quantity") or 0)
        bucket["in_way"] += int(item.get("inWayToClient") or 0) + int(item.get("inWayFromClient") or 0)
    return totals


def load_stocks_meta(data_dir: Path | None = None) -> dict:
    path = (data_dir or pilot_data_dir()) / "sync" / "stocks_report.json"
    if not path.is_file():
        return {}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {"synced_at": report.get("synced_at"), "items_pilot": report.get("items_pilot")}


def load_unit_economics(data_dir: Path | None = None) -> dict[str, dict]:
    path = (data_dir or pilot_data_dir()) / "unit_economics.csv"
    if not path.is_file():
        return {}
    import csv

    out: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            nm = (row.get("nm_id") or "").strip()
            if nm and not nm.startswith(PENDING_NM_PREFIX):
                out[nm] = row
    return out


def build_product_rows(data_dir: Path | None = None, *, region_key: str | None = None) -> list[dict]:
    data_dir = data_dir or pilot_data_dir()
    if region_key is None:
        region_key = get_parser_settings(data_dir)["region_key"]
    report = load_sync_report(data_dir)
    by_advert = {int(c["wb_campaign_id"]): c for c in report.get("campaigns") or [] if c.get("wb_campaign_id")}
    economics = load_unit_economics(data_dir)
    positions = load_latest_positions(data_dir, region_key=region_key)
    stocks = load_stocks_by_nm(data_dir)
    rows: list[dict] = []

    for sku in load_pilot_skus(data_dir / "pilot_skus.csv"):
        if (sku.nm_id or "").startswith(PENDING_NM_PREFIX):
            continue
        advert_id = sku.wb_campaign_search
        sync_row = by_advert.get(advert_id, {})
        kw_file = load_keywords(advert_id, data_dir)
        keywords = kw_file.get("keywords") or [] if kw_file else []
        keyword_count = len(keywords) if kw_file else sync_row.get("keywords", 0)
        econ = economics.get(sku.nm_id, {})
        pos = positions.get(sku.nm_id, {})
        campaign_clicks = sum(int(k.get("clicks") or 0) for k in keywords)
        campaign_orders = sum(int(k.get("orders") or 0) for k in keywords)
        top = sync_row.get("top_stats") or {}
        stock = stocks.get(sku.nm_id, {})
        primary_cpc: int | None = None
        primary_kw_clicks = 0
        primary_kw_orders = 0
        if kw_file:
            primary_kw = (sku.primary_keyword or sync_row.get("top_keyword") or "").strip().lower()
            for k in keywords:
                if (k.get("keyword") or "").strip().lower() == primary_kw:
                    primary_cpc = k.get("cpc_calculated_kopecks")
                    primary_kw_clicks = int(k.get("clicks") or 0)
                    primary_kw_orders = int(k.get("orders") or 0)
                    break
        max_cpc = _max_cpc_kopecks(
            econ,
            kw_clicks=primary_kw_clicks,
            kw_orders=primary_kw_orders,
            campaign_clicks=campaign_clicks,
            campaign_orders=campaign_orders,
        )
        rows.append(
            {
                "advert_id": advert_id,
                "nm_id": sku.nm_id,
                "primary_keyword": sku.primary_keyword or sync_row.get("top_keyword"),
                "target_grade": sku.target_grade,
                "schedule": sku.schedule,
                "notes": sku.notes,
                "keyword_count": keyword_count,
                "keywords_saved": kw_file is not None,
                "top_stats": top or None,
                "sync_errors": sync_row.get("errors") or [],
                "has_economics": _economics_complete(econ),
                "has_retail_price": bool(econ.get("retail_price_rub")),
                "retail_price_rub": econ.get("retail_price_rub"),
                "margin_pct": econ.get("margin_pct"),
                "max_cpc_rub": round(max_cpc / 100, 2) if max_cpc else None,
                "primary_cpc_rub": round(primary_cpc / 100, 2) if primary_cpc else None,
                "cpc_over_limit": bool(max_cpc and primary_cpc and primary_cpc > max_cpc),
                "max_drr_pct": econ.get("max_drr_pct") or "15",
                "stock_quantity": stock.get("quantity", 0),
                "stock_in_way": stock.get("in_way", 0),
                "parsed_position": pos.get("position") if pos.get("found") else None,
                "position_parsed_at": pos.get("parsed_at"),
                "position_error": None if pos.get("found") else pos.get("error"),
            }
        )
    return sorted(rows, key=lambda r: r["advert_id"])


def load_dashboard_recommendations(limit: int = 5, data_dir: Path | None = None) -> list[dict]:
    """Top N recommendations: actionable first, then keep to fill the block."""
    from wb_advert.storage.decisions_store import load_recent_decisions

    actionable_actions = {"exclude_keyword", "lower_bid", "raise_bid", "promote_managed"}
    rows = load_recent_decisions(limit=500, data_dir=data_dir)
    seen: set[tuple] = set()
    actionable: list[dict] = []
    keep_by_advert: dict[int, dict] = {}

    for row in reversed(rows):
        advert_id = row.get("advert_id")
        for s in row.get("suggestions") or []:
            action = s.get("action") or ""
            if action == "skip":
                continue
            key = (advert_id, s.get("keyword"), action)
            if key in seen:
                continue
            seen.add(key)
            entry = {
                "advert_id": advert_id,
                "nm_id": row.get("nm_id"),
                "keyword": s.get("keyword"),
                "action": action,
                "reason_text": s.get("reason_text"),
                "decided_at": row.get("decided_at"),
            }
            if action in actionable_actions:
                actionable.append(entry)
            elif action == "keep" and advert_id not in keep_by_advert:
                keep_by_advert[int(advert_id)] = entry

    out = actionable[:limit]
    if len(out) < limit:
        for entry in sorted(keep_by_advert.values(), key=lambda r: r["advert_id"] or 0):
            if len(out) >= limit:
                break
            if any(
                x["advert_id"] == entry["advert_id"] and x["keyword"] == entry["keyword"]
                for x in out
            ):
                continue
            out.append(entry)
    return out[:limit]


def load_actionable_decisions(limit: int = 20, data_dir: Path | None = None) -> list[dict]:
    """Latest unique actionable suggestions (newest per advert+keyword+action)."""
    from wb_advert.storage.decisions_store import load_recent_decisions

    rows = load_recent_decisions(limit=500, data_dir=data_dir)
    seen: set[tuple] = set()
    out: list[dict] = []
    for row in reversed(rows):
        for s in row.get("suggestions") or []:
            action = s.get("action") or ""
            if action in ("keep", "skip"):
                continue
            key = (row.get("advert_id"), s.get("keyword"), action)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "advert_id": row.get("advert_id"),
                    "nm_id": row.get("nm_id"),
                    "keyword": s.get("keyword"),
                    "action": action,
                    "reason_text": s.get("reason_text"),
                    "decided_at": row.get("decided_at"),
                }
            )
            if len(out) >= limit:
                return out
    return out


def _attach_recommendation_summaries(
    products: list[dict],
    latest_by_advert: dict[int, dict],
) -> list[dict]:
    for product in products:
        advert_id = int(product["advert_id"])
        row = latest_by_advert.get(advert_id)
        if row:
            summary = summarize_campaign(
                advert_id=advert_id,
                nm_id=product.get("nm_id") or "",
                primary_keyword=product.get("primary_keyword"),
                suggestions=row.get("suggestions") or [],
                alerts=row.get("alerts"),
                decided_at=row.get("decided_at"),
            )
        else:
            summary = summarize_campaign(
                advert_id=advert_id,
                nm_id=product.get("nm_id") or "",
                primary_keyword=product.get("primary_keyword"),
                suggestions=[],
                alerts=["Optimizer ещё не запускался"],
            )
        product["recommendation"] = summary
    return products


def build_dashboard(data_dir: Path | None = None) -> dict:
    data_dir = data_dir or pilot_data_dir()
    config = load_config(data_dir)
    from wb_advert.storage.decisions_store import load_latest_optimize_by_advert

    products = build_product_rows(data_dir)
    latest_by_advert = load_latest_optimize_by_advert(data_dir)
    missing = [int(p["advert_id"]) for p in products if int(p["advert_id"]) not in latest_by_advert]
    if missing:
        from wb_advert.optimizer.engine import optimize_product
        from wb_advert.storage.decisions_store import append_decisions

        for advert_id in missing:
            result = optimize_product(advert_id)
            if result.suggestions or result.alerts:
                append_decisions(result, data_dir)
            latest_by_advert[advert_id] = result.model_dump(mode="json")

    products = _attach_recommendation_summaries(products, latest_by_advert)
    recommendations = load_dashboard_recommendations(limit=5, data_dir=data_dir)
    from wb_advert.storage.dashboard_alerts import (
        attach_alert_flags,
        build_dashboard_alerts,
        summarize_alerts,
    )

    alerts = build_dashboard_alerts(products, data_dir)
    products = attach_alert_flags(products, alerts)
    alerts_summary = summarize_alerts(alerts)
    report = load_sync_report(data_dir)
    total_keywords = sum(p["keyword_count"] for p in products)
    total_orders = sum(
        (p.get("top_stats") or {}).get("orders") or 0 for p in products
    )
    with_economics = sum(1 for p in products if p["has_economics"])
    keywords_saved = sum(1 for p in products if p["keywords_saved"])
    parser_settings = get_parser_settings(data_dir)
    positions_ok = count_positions_for_region(parser_settings["region_key"], data_dir)
    positions_by_region = {
        opt["key"]: count_positions_for_region(opt["key"], data_dir)
        for opt in parser_settings["options"]
    }
    stocks_meta = load_stocks_meta(data_dir)
    from wb_advert.executor.guards import get_apply_settings

    apply_settings = get_apply_settings(data_dir)
    from wb_advert.storage.snapshots_store import get_snapshots_meta

    snapshots_meta = get_snapshots_meta(data_dir)

    return {
        "optimizer_mode": config.get("optimizer_mode", "suggest-only"),
        "synced_at": report.get("synced_at"),
        "product_count": len(products),
        "total_keywords": total_keywords,
        "total_orders_7d": total_orders,
        "with_economics": with_economics,
        "with_retail_price": sum(1 for p in products if p.get("has_retail_price")),
        "keywords_saved": keywords_saved,
        "positions_parsed": positions_ok,
        "positions_by_region": positions_by_region,
        "stocks_synced_at": stocks_meta.get("synced_at"),
        "products": products,
        "recommendations": recommendations,
        "alerts": alerts,
        "alerts_summary": alerts_summary,
        "actionable_decisions": load_actionable_decisions(data_dir=data_dir),
        "parser_region": parser_settings["region"],
        "parser_dest": parser_settings["dest"],
        "parser_region_key": parser_settings["region_key"],
        "parser_region_options": parser_settings["options"],
        "sync_interval_min": (config.get("sync") or {}).get("interval_minutes"),
        "apply_settings": apply_settings,
        "snapshots_meta": snapshots_meta,
    }


def get_product_detail(advert_id: int, data_dir: Path | None = None) -> dict | None:
    data_dir = data_dir or pilot_data_dir()
    region_key = get_parser_settings(data_dir)["region_key"]
    for row in build_product_rows(data_dir, region_key=region_key):
        if row["advert_id"] == advert_id:
            kw_data = load_keywords(advert_id, data_dir)
            return {
                **row,
                "keywords": kw_data.get("keywords") if kw_data else [],
                "keywords_synced_at": kw_data.get("synced_at") if kw_data else None,
            }
    return None
