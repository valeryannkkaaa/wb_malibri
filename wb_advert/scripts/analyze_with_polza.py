#!/usr/bin/env python
"""Analyze pilot dataset + manager call via Polza AI → optimizer rules JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.client.polza import PolzaError, chat_completion, get_balance  # noqa: E402
from wb_advert.config import require_polza_token, settings  # noqa: E402
from wb_advert.storage.pilot_store import pilot_data_dir  # noqa: E402

TRANSCRIPT_MARKERS = (
    "марж",
    "11%",
    "12%",
    "1500",
    "два часа",
    "2-3 час",
    "салфетк",
    "30х30",
    "top-5",
    "топ-5",
    "10-20",
    "15-20",
    "7.6",
    "юнит",
    "исключ",
    "cpc",
    "ctr",
    "перчатки для уборки",
    "pos_10",
)

OUTPUT_SCHEMA_HINT = {
    "generated_at": "ISO8601",
    "confidence": "high|medium|low",
    "sku_profiles": [
        {
            "nm_id": "string",
            "advert_id": "int|null",
            "primary_keyword": "string",
            "margin_pct": "number|null",
            "max_drr_pct": "number|null",
            "target_grade": "top_1_3|pos_4_10|pos_10_20",
            "notes": "string",
            "evidence": "string",
        }
    ],
    "benchmarks": {
        "primary_ctr_pct_min": "number",
        "primary_cpc_rub_max": "number",
        "cpm_cap_rub_per_1000": "number",
        "bid_test_hours_min": "number",
        "min_shows_for_decision": "number",
    },
    "optimizer_rules": [
        {
            "code": "string",
            "description": "string",
            "priority": "int",
        }
    ],
    "keyword_policies": {
        "exclude_when": ["string"],
        "keep_primary_when": ["string"],
        "retest_excluded_after_days": "int",
    },
    "sources_cited": ["string"],
}


def _load_dataset(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_transcript_excerpt(transcript_path: Path, *, max_chars: int = 14000) -> str:
    if not transcript_path.is_file():
        return ""
    text = transcript_path.read_text(encoding="utf-8")
    chunks: list[str] = []
    seen: set[str] = set()
    lower = text.lower()
    for marker in TRANSCRIPT_MARKERS:
        start = 0
        while True:
            idx = lower.find(marker.lower(), start)
            if idx < 0:
                break
            snippet = text[max(0, idx - 280) : idx + 420].strip()
            key = snippet[:80]
            if key not in seen:
                seen.add(key)
                chunks.append(snippet)
            start = idx + len(marker)
    if not chunks:
        return text[:max_chars]
    joined = "\n---\n".join(chunks)
    return joined[:max_chars]


def _compact_keywords(keywords: list[dict], *, per_sku: int = 8) -> list[dict]:
    by_nm: dict[str, list[dict]] = {}
    for row in keywords:
        by_nm.setdefault(str(row.get("nm_id") or ""), []).append(row)
    out: list[dict] = []
    for nm_id, rows in by_nm.items():
        rows_sorted = sorted(rows, key=lambda r: (-(r.get("shows") or 0), r.get("keyword") or ""))
        top = rows_sorted[:per_sku]
        weak = sorted(
            [r for r in rows if (r.get("orders") or 0) == 0 and (r.get("shows") or 0) >= 80],
            key=lambda r: (-(r.get("cpc_rub") or 0), -(r.get("shows") or 0)),
        )[:3]
        picked = {r.get("keyword"): r for r in top + weak}
        for row in picked.values():
            out.append(
                {
                    "nm_id": nm_id,
                    "keyword": row.get("keyword"),
                    "is_primary": row.get("is_primary"),
                    "shows": row.get("shows"),
                    "clicks": row.get("clicks"),
                    "orders": row.get("orders"),
                    "ctr_pct": row.get("ctr_pct"),
                    "cpc_rub": row.get("cpc_rub"),
                }
            )
    return out


def _build_user_payload(dataset: dict, data_dir: Path) -> dict:
    transcript_path = data_dir / "call_transcript_12_06_2026.txt"
    return {
        "summary": dataset.get("summary"),
        "config_snapshot": dataset.get("config_snapshot"),
        "products": dataset.get("products"),
        "optimizer_decisions_actionable": dataset.get("optimizer_decisions_actionable"),
        "manager_rules_from_call": dataset.get("manager_rules_from_call"),
        "keywords_sample": _compact_keywords(dataset.get("keywords") or []),
        "transcript_excerpt": _extract_transcript_excerpt(transcript_path),
    }


def _parse_json_content(content: str) -> dict:
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def _apply_rules(data_dir: Path, rules: dict) -> list[str]:
    import csv

    updated: list[str] = []

    econ_path = data_dir / "unit_economics.csv"
    sku_path = data_dir / "pilot_skus.csv"
    cfg_path = data_dir / "config.yaml"

    profiles_by_nm = {str(p.get("nm_id")): p for p in rules.get("sku_profiles") or [] if p.get("nm_id")}

    if econ_path.is_file() and profiles_by_nm:
        with econ_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        changed = 0
        for row in rows:
            prof = profiles_by_nm.get((row.get("nm_id") or "").strip())
            if not prof:
                continue
            if prof.get("margin_pct") is not None:
                row["margin_pct"] = str(prof["margin_pct"])
                changed += 1
            if prof.get("max_drr_pct") is not None:
                row["max_drr_pct"] = str(prof["max_drr_pct"])
        if changed:
            with econ_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            updated.append(f"unit_economics.csv ({changed} margin/max_drr updates)")

    if sku_path.is_file() and profiles_by_nm:
        with sku_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        changed = 0
        for row in rows:
            prof = profiles_by_nm.get((row.get("nm_id") or "").strip())
            if not prof or not prof.get("target_grade"):
                continue
            if row.get("target_grade") != prof["target_grade"]:
                row["target_grade"] = prof["target_grade"]
                changed += 1
        if changed:
            with sku_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            updated.append(f"pilot_skus.csv ({changed} target_grade updates)")

    benchmarks = rules.get("benchmarks") or {}
    if cfg_path.is_file() and benchmarks:
        import yaml

        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        cfg["optimizer_benchmarks"] = benchmarks
        if rules.get("keyword_policies"):
            cfg["keyword_policies"] = rules["keyword_policies"]
        if rules.get("optimizer_rules"):
            cfg["optimizer_rules_ai"] = rules["optimizer_rules"]
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        updated.append("config.yaml (optimizer_benchmarks)")

    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Polza AI analysis for WB advert pilot rules")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--apply", action="store_true", help="Write margin/target_grade/benchmarks to pilot files")
    parser.add_argument("--dry-run", action="store_true", help="Build payload only, no API call")
    parser.add_argument("--check-balance", action="store_true")
    args = parser.parse_args()

    require_polza_token()
    data_dir = args.data_dir or pilot_data_dir()
    dataset_path = args.dataset or (data_dir / "exports" / "manager_activity_dataset.json")
    if not dataset_path.is_file():
        print(f"Missing dataset: {dataset_path}", flush=True)
        print("Run: python -m scripts.export_manager_dataset", flush=True)
        return 1

    if args.check_balance:
        try:
            balance = get_balance()
            print(json.dumps(balance, ensure_ascii=False, indent=2), flush=True)
        except PolzaError as exc:
            print(f"Balance check failed: {exc}", flush=True)
            return 1
        if args.dry_run:
            return 0

    dataset = _load_dataset(dataset_path)
    payload = _build_user_payload(dataset, data_dir)
    out_dir = data_dir / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload_path = out_dir / "polza_request_payload.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Payload: {payload_path} ({payload_path.stat().st_size // 1024} KB)", flush=True)

    if args.dry_run:
        return 0

    system_prompt = (
        "Ты аналитик рекламы Wildberries. На входе: статистика пилота (10 SKU), решения optimizer, "
        "правила из звонка менеджера и выдержки из транскрипта.\n"
        "Задача: сформировать JSON для автоматического optimizer.\n"
        "Важно:\n"
        "- margin_pct оценивай из транскрипта и категории товара (если нет точной цифры — консервативная оценка + evidence).\n"
        "- target_grade: top_1_3 для основных перчаток/тряпок; pos_10_20 для нишевых салфеток 30x30 и подобных.\n"
        "- benchmarks: CTR/CPC primary, cap CPM 1500, min test 2-3h.\n"
        "- Не выдумывай nm_id — только из products.\n"
        "Ответ: ТОЛЬКО валидный JSON без markdown, по схеме:\n"
        + json.dumps(OUTPUT_SCHEMA_HINT, ensure_ascii=False, indent=2)
    )

    user_prompt = json.dumps(payload, ensure_ascii=False)
    model = args.model or settings.polza_ai_model
    print(f"Calling Polza model={model} ...", flush=True)

    try:
        content = chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            response_format={"type": "json_object"},
        )
        rules = _parse_json_content(content)
    except (PolzaError, json.JSONDecodeError) as exc:
        print(f"Polza analysis failed: {exc}", flush=True)
        raw_path = out_dir / "polza_raw_error.txt"
        raw_path.write_text(str(exc), encoding="utf-8")
        return 1

    rules.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    rules.setdefault("model", model)
    rules.setdefault("source_dataset", str(dataset_path))

    out_path = out_dir / "polza_optimizer_rules.json"
    out_path.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out_path}", flush=True)

    profiles = rules.get("sku_profiles") or []
    with_margin = sum(1 for p in profiles if p.get("margin_pct") is not None)
    print(f"SKU profiles: {len(profiles)}, with margin_pct: {with_margin}", flush=True)

    if args.apply:
        applied = _apply_rules(data_dir, rules)
        if applied:
            print("Applied:", flush=True)
            for line in applied:
                print(f"  - {line}", flush=True)
        else:
            print("Nothing applied (empty profiles/benchmarks)", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
