from __future__ import annotations

import json
from pathlib import Path

import yaml

from wb_advert.config import settings
from wb_advert.constants import PENDING_NM_PREFIX
from wb_advert.import_data.csv_loader import load_pilot_skus
from wb_advert.storage.keywords_store import load_keywords


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


def load_config(data_dir: Path | None = None) -> dict:
    path = (data_dir or pilot_data_dir()) / "config.yaml"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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


def build_product_rows(data_dir: Path | None = None) -> list[dict]:
    data_dir = data_dir or pilot_data_dir()
    report = load_sync_report(data_dir)
    by_advert = {int(c["wb_campaign_id"]): c for c in report.get("campaigns") or [] if c.get("wb_campaign_id")}
    economics = load_unit_economics(data_dir)
    rows: list[dict] = []

    for sku in load_pilot_skus(data_dir / "pilot_skus.csv"):
        if (sku.nm_id or "").startswith(PENDING_NM_PREFIX):
            continue
        advert_id = sku.wb_campaign_search
        sync_row = by_advert.get(advert_id, {})
        kw_file = load_keywords(advert_id, data_dir)
        keyword_count = len(kw_file.get("keywords") or []) if kw_file else sync_row.get("keywords", 0)
        econ = economics.get(sku.nm_id, {})
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
                "top_stats": sync_row.get("top_stats"),
                "sync_errors": sync_row.get("errors") or [],
                "has_economics": bool(econ.get("cost_price_rub") and econ.get("retail_price_rub")),
                "max_drr_pct": econ.get("max_drr_pct") or "15",
            }
        )
    return sorted(rows, key=lambda r: r["advert_id"])


def build_dashboard(data_dir: Path | None = None) -> dict:
    data_dir = data_dir or pilot_data_dir()
    config = load_config(data_dir)
    products = build_product_rows(data_dir)
    report = load_sync_report(data_dir)
    total_keywords = sum(p["keyword_count"] for p in products)
    total_orders = sum(
        (p.get("top_stats") or {}).get("orders") or 0 for p in products
    )
    with_economics = sum(1 for p in products if p["has_economics"])
    keywords_saved = sum(1 for p in products if p["keywords_saved"])

    return {
        "optimizer_mode": config.get("optimizer_mode", "suggest-only"),
        "synced_at": report.get("synced_at"),
        "product_count": len(products),
        "total_keywords": total_keywords,
        "total_orders_7d": total_orders,
        "with_economics": with_economics,
        "keywords_saved": keywords_saved,
        "products": products,
    }


def get_product_detail(advert_id: int, data_dir: Path | None = None) -> dict | None:
    data_dir = data_dir or pilot_data_dir()
    for row in build_product_rows(data_dir):
        if row["advert_id"] == advert_id:
            kw_data = load_keywords(advert_id, data_dir)
            return {
                **row,
                "keywords": kw_data.get("keywords") if kw_data else [],
                "keywords_synced_at": kw_data.get("synced_at") if kw_data else None,
            }
    return None
