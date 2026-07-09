#!/usr/bin/env python
"""Export pilot stats into one JSON + CSV bundle for manager workflow analysis (Polza AI / Anton)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.config import settings  # noqa: E402
from wb_advert.constants import PENDING_NM_PREFIX  # noqa: E402
from wb_advert.import_data.csv_loader import load_pilot_skus  # noqa: E402
from wb_advert.storage.decisions_store import load_recent_decisions  # noqa: E402
from wb_advert.storage.keywords_store import list_saved_campaign_ids, load_keywords  # noqa: E402
from wb_advert.storage.pilot_store import (  # noqa: E402
    load_config,
    load_sync_report,
    load_unit_economics,
    pilot_data_dir,
)
from wb_advert.storage.positions_store import load_latest_positions  # noqa: E402

EXPORT_VERSION = "1.0"

# Краткие правила из звонка 12.06.2026 — для промпта Polza AI (не полный транскрипт).
MANAGER_RULES_FROM_CALL = [
    {
        "topic": "target_position",
        "rule": "Основные ключи — top-5 (top_1_3); часть ключей окупается на 10–20 позиции",
        "example": "Салфетки 30×30 — pos_10_20, не top-5",
    },
    {
        "topic": "metrics_trust",
        "rule": "Ориентир только CTR и CPC из WB API; Evirma/WB-кабинет завышает",
    },
    {
        "topic": "bid_test_window",
        "rule": "После смены ставки ждать минимум 2–3 часа перед выводами",
    },
    {
        "topic": "cpm_cap",
        "rule": "Жёсткий потолок ~1500 ₽ за 1000 показов",
    },
    {
        "topic": "unit_economics",
        "rule": "Лимит CPC из retail + margin_pct + max DRR, не обязательно cost_price из 1С",
        "example": "Салфетки без рекламы — 11% маржи",
    },
    {
        "topic": "keyword_cleanup",
        "rule": "Отключать secondary/longtail без конверсии; периодически возвращать из исключений на тест",
    },
    {
        "topic": "competitive_price",
        "rule": "Цена должна быть конкурентоспособной относимо соседей в выдаче",
    },
    {
        "topic": "primary_benchmark",
        "rule": "Эталон primary «перчатки для уборки»: CTR ~13%, CPC ~7.6 ₽",
    },
]


def _kopecks_to_rub(value: int | float | None) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value) / 100, 2)
    except (TypeError, ValueError):
        return None


def _safe_float(value: str | float | int | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_all_decisions(data_dir: Path) -> list[dict]:
    path = data_dir / "sync" / "decisions_log.jsonl"
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
    return rows


def _latest_decisions_per_advert(rows: list[dict]) -> dict[int, dict]:
    latest: dict[int, dict] = {}
    for row in rows:
        advert_id = row.get("advert_id")
        if advert_id is not None:
            latest[int(advert_id)] = row
    return latest


def _collect_actionable(decisions: list[dict]) -> list[dict]:
    seen: set[tuple[int, str, str]] = set()
    out: list[dict] = []
    for row in reversed(decisions):
        for s in row.get("suggestions") or []:
            action = s.get("action") or ""
            if action in ("keep", "skip"):
                continue
            key = (int(row.get("advert_id") or 0), s.get("keyword") or "", action)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "advert_id": row.get("advert_id"),
                    "nm_id": row.get("nm_id"),
                    "keyword": s.get("keyword"),
                    "action": action,
                    "reason_code": s.get("reason_code"),
                    "reason_text": s.get("reason_text"),
                    "before_state": s.get("before_state"),
                    "after_state": s.get("after_state"),
                    "decided_at": row.get("decided_at"),
                }
            )
    return out


def _build_keywords_flat(data_dir: Path, skus_by_advert: dict[int, object]) -> list[dict]:
    flat: list[dict] = []
    economics = load_unit_economics(data_dir)
    positions = load_latest_positions(data_dir)

    for advert_id in list_saved_campaign_ids(data_dir):
        kw_data = load_keywords(advert_id, data_dir)
        if not kw_data:
            continue
        sku = skus_by_advert.get(advert_id)
        nm_id = str(kw_data.get("nm_id") or (sku.nm_id if sku else ""))
        primary = (sku.primary_keyword if sku else "") or ""
        target_grade = (sku.target_grade if sku else "") or ""
        econ = economics.get(nm_id, {})
        pos = positions.get(nm_id, {})

        for kw in kw_data.get("keywords") or []:
            keyword = kw.get("keyword") or ""
            flat.append(
                {
                    "advert_id": advert_id,
                    "nm_id": nm_id,
                    "primary_keyword": primary,
                    "target_grade": target_grade,
                    "keyword": keyword,
                    "is_primary": keyword.strip().lower() == primary.strip().lower(),
                    "shows": kw.get("shows") or 0,
                    "clicks": kw.get("clicks") or 0,
                    "orders": kw.get("orders") or 0,
                    "ctr_pct": kw.get("ctr_calculated"),
                    "cpc_rub": _kopecks_to_rub(kw.get("cpc_calculated_kopecks")),
                    "spend_rub": _kopecks_to_rub(kw.get("spend_kopecks")),
                    "bid_rub": _kopecks_to_rub(kw.get("current_bid_kopecks")),
                    "status": kw.get("status"),
                    "retail_price_rub": _safe_float(econ.get("retail_price_rub")),
                    "cost_price_rub": _safe_float(econ.get("cost_price_rub")),
                    "margin_pct": _safe_float(econ.get("margin_pct")),
                    "max_drr_pct": _safe_float(econ.get("max_drr_pct")),
                    "parsed_position": pos.get("position") if pos.get("found") else None,
                    "keywords_synced_at": kw_data.get("synced_at"),
                }
            )
    return sorted(flat, key=lambda r: (-(r.get("shows") or 0), r.get("advert_id") or 0))


def _build_product_summaries(
    data_dir: Path,
    skus_by_advert: dict[int, object],
    keywords_flat: list[dict],
) -> list[dict]:
    report = load_sync_report(data_dir)
    by_advert = {int(c["wb_campaign_id"]): c for c in report.get("campaigns") or [] if c.get("wb_campaign_id")}
    economics = load_unit_economics(data_dir)
    positions = load_latest_positions(data_dir)
    kw_by_advert: dict[int, list[dict]] = {}
    for row in keywords_flat:
        kw_by_advert.setdefault(int(row["advert_id"]), []).append(row)

    products: list[dict] = []
    for sku in load_pilot_skus(data_dir / "pilot_skus.csv"):
        if (sku.nm_id or "").startswith(PENDING_NM_PREFIX):
            continue
        advert_id = sku.wb_campaign_search
        sync_row = by_advert.get(advert_id, {})
        econ = economics.get(sku.nm_id, {})
        pos = positions.get(sku.nm_id, {})
        kws = kw_by_advert.get(advert_id, [])
        primary_rows = [k for k in kws if k.get("is_primary")]
        primary = primary_rows[0] if primary_rows else None

        products.append(
            {
                "advert_id": advert_id,
                "nm_id": sku.nm_id,
                "primary_keyword": sku.primary_keyword,
                "target_grade": sku.target_grade,
                "schedule": sku.schedule,
                "notes": sku.notes,
                "keyword_count": len(kws),
                "total_shows": sum(k.get("shows") or 0 for k in kws),
                "total_clicks": sum(k.get("clicks") or 0 for k in kws),
                "total_orders": sum(k.get("orders") or 0 for k in kws),
                "primary_shows": (primary or {}).get("shows"),
                "primary_ctr_pct": (primary or {}).get("ctr_pct"),
                "primary_cpc_rub": (primary or {}).get("cpc_rub"),
                "primary_orders": (primary or {}).get("orders"),
                "retail_price_rub": _safe_float(econ.get("retail_price_rub")),
                "cost_price_rub": _safe_float(econ.get("cost_price_rub")),
                "margin_pct": _safe_float(econ.get("margin_pct")),
                "max_drr_pct": _safe_float(econ.get("max_drr_pct")),
                "has_full_economics": bool(econ.get("cost_price_rub") and econ.get("retail_price_rub")),
                "has_retail_only": bool(econ.get("retail_price_rub") and not econ.get("cost_price_rub")),
                "sync_top_stats": sync_row.get("top_stats"),
                "sync_errors": sync_row.get("errors") or [],
                "parsed_position": pos.get("position") if pos.get("found") else None,
                "position_error": None if pos.get("found") else pos.get("error"),
            }
        )
    return sorted(products, key=lambda p: p["advert_id"])


def _aggregate_summary(keywords_flat: list[dict], products: list[dict], decisions: list[dict]) -> dict:
    actionable = _collect_actionable(decisions)
    return {
        "product_count": len(products),
        "keyword_count": len(keywords_flat),
        "total_shows": sum(k.get("shows") or 0 for k in keywords_flat),
        "total_clicks": sum(k.get("clicks") or 0 for k in keywords_flat),
        "total_orders": sum(k.get("orders") or 0 for k in keywords_flat),
        "primary_keyword_count": sum(1 for k in keywords_flat if k.get("is_primary")),
        "with_retail_price": sum(1 for p in products if p.get("retail_price_rub")),
        "with_margin_pct": sum(1 for p in products if p.get("margin_pct")),
        "with_full_economics": sum(1 for p in products if p.get("has_full_economics")),
        "optimizer_runs_logged": len(decisions),
        "actionable_suggestions_unique": len(actionable),
        "exclude_keyword_count": sum(1 for a in actionable if a.get("action") == "exclude_keyword"),
    }


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_dataset(data_dir: Path) -> dict:
    skus = load_pilot_skus(data_dir / "pilot_skus.csv")
    skus_by_advert = {s.wb_campaign_search: s for s in skus}
    config = load_config(data_dir)
    sync_report = load_sync_report(data_dir)
    all_decisions = _load_all_decisions(data_dir)
    keywords_flat = _build_keywords_flat(data_dir, skus_by_advert)
    products = _build_product_summaries(data_dir, skus_by_advert, keywords_flat)
    latest_decisions = _latest_decisions_per_advert(all_decisions)
    actionable = _collect_actionable(all_decisions)
    positions = load_latest_positions(data_dir)

    transcript_txt = data_dir / "call_transcript_12_06_2026.txt"
    transcript_json = data_dir / "call_transcript_12_06_2026.json"

    return {
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Датасет пилота для анализа логики менеджера (Anton / Polza AI)",
        "sources": {
            "pilot_skus": str(data_dir / "pilot_skus.csv"),
            "unit_economics": str(data_dir / "unit_economics.csv"),
            "sync_report": str(data_dir / "last_sync_report.json"),
            "decisions_log": str(data_dir / "sync" / "decisions_log.jsonl"),
            "keywords_glob": str(data_dir / "sync" / "keywords_*.json"),
            "transcript_txt": str(transcript_txt) if transcript_txt.is_file() else None,
            "transcript_json": str(transcript_json) if transcript_json.is_file() else None,
            "manager_checklist": str(data_dir / "MANAGER_CHECKLIST.md"),
        },
        "config_snapshot": {
            "optimizer_mode": config.get("optimizer_mode"),
            "parser_region": (config.get("parser") or {}).get("region"),
            "fullstats_enabled": (config.get("sync") or {}).get("fullstats_enabled"),
        },
        "summary": _aggregate_summary(keywords_flat, products, all_decisions),
        "products": products,
        "keywords": keywords_flat,
        "optimizer_decisions_latest": latest_decisions,
        "optimizer_decisions_actionable": actionable,
        "positions_latest": positions,
        "sync_report": sync_report,
        "manager_rules_from_call": MANAGER_RULES_FROM_CALL,
        "polza_ai_prompt_hint": (
            "Проанализируй keywords + products + manager_rules_from_call. "
            "Извлеки: margin_pct по SKU, target_grade overrides, benchmarks CTR/CPC, "
            "правила исключения ключей. Выход — JSON для optimizer config."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export pilot manager activity dataset")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Default: data/pilot/exports/",
    )
    args = parser.parse_args()

    data_dir = args.data_dir or pilot_data_dir()
    output_dir = args.output_dir or (data_dir / "exports")
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = build_dataset(data_dir)

    json_path = output_dir / "manager_activity_dataset.json"
    json_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

    kw_fields = [
        "advert_id",
        "nm_id",
        "primary_keyword",
        "target_grade",
        "keyword",
        "is_primary",
        "shows",
        "clicks",
        "orders",
        "ctr_pct",
        "cpc_rub",
        "spend_rub",
        "bid_rub",
        "status",
        "retail_price_rub",
        "cost_price_rub",
        "margin_pct",
        "max_drr_pct",
        "parsed_position",
        "keywords_synced_at",
    ]
    _write_csv(output_dir / "keywords_flat.csv", dataset["keywords"], kw_fields)

    prod_fields = [
        "advert_id",
        "nm_id",
        "primary_keyword",
        "target_grade",
        "keyword_count",
        "total_shows",
        "total_clicks",
        "total_orders",
        "primary_ctr_pct",
        "primary_cpc_rub",
        "primary_orders",
        "retail_price_rub",
        "margin_pct",
        "has_retail_only",
        "parsed_position",
        "position_error",
    ]
    _write_csv(output_dir / "products_summary.csv", dataset["products"], prod_fields)

    act_fields = [
        "advert_id",
        "nm_id",
        "keyword",
        "action",
        "reason_code",
        "reason_text",
        "decided_at",
    ]
    _write_csv(
        output_dir / "optimizer_actionable.csv",
        dataset["optimizer_decisions_actionable"],
        act_fields,
    )

    s = dataset["summary"]
    print(f"Exported to {output_dir}", flush=True)
    print(
        f"  {s['product_count']} SKU, {s['keyword_count']} keywords, "
        f"{s['total_orders']} orders, {s['exclude_keyword_count']} exclude suggestions",
        flush=True,
    )
    print(f"  JSON: {json_path.name}", flush=True)
    print(f"  CSV: keywords_flat.csv, products_summary.csv, optimizer_actionable.csv", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
