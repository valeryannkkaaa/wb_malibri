from __future__ import annotations

import csv
from pathlib import Path

import yaml

from wb_advert.constants import PENDING_NM_PREFIX
from wb_advert.schemas.wb_api import PilotSkuRow


def load_pilot_skus(path: Path) -> list[PilotSkuRow]:
    rows: list[PilotSkuRow] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            if not raw.get("wb_campaign_search"):
                continue
            rows.append(
                PilotSkuRow(
                    nm_id=raw.get("nm_id") or f"{PENDING_NM_PREFIX}{raw['wb_campaign_search']}",
                    product_name=raw.get("product_name") or "",
                    project_id=int(raw.get("project_id") or 1),
                    wb_campaign_search=int(raw["wb_campaign_search"]),
                    wb_campaign_unified=int(raw["wb_campaign_unified"]) if raw.get("wb_campaign_unified") else None,
                    schedule=raw.get("schedule") or "always_on",
                    primary_keyword=raw.get("primary_keyword") or "",
                    target_grade=raw.get("target_grade") or "top_1_3",
                    notes=raw.get("notes") or "",
                )
            )
    return rows


def load_pilot_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def lookup_nm_id_for_campaign(advert_id: int, pilot_csv: Path) -> int | None:
    """Read nm_id from pilot_skus.csv — avoids API call when rate-limited."""
    if not pilot_csv.is_file():
        return None
    for row in load_pilot_skus(pilot_csv):
        if row.wb_campaign_search != advert_id:
            continue
        raw = (row.nm_id or "").strip()
        if not raw or raw.startswith(PENDING_NM_PREFIX):
            return None
        if raw.isdigit():
            return int(raw)
    return None


def update_pilot_nm_ids(csv_path: Path, mapping: dict[int, int]) -> None:
    """Replace PENDING_{advert_id} with real nm_id in a pilot CSV."""
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    for row in rows:
        advert_id = int(row.get("wb_campaign_search") or row.get("nm_id", "").replace(PENDING_NM_PREFIX, "") or 0)
        if advert_id in mapping:
            row["nm_id"] = str(mapping[advert_id])
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def apply_nm_id_mapping(data_dir: Path, mapping: dict[int, int]) -> list[str]:
    """Update pilot_skus, keywords, unit_economics with resolved nm_ids."""
    updated: list[str] = []
    for name in ("pilot_skus.csv", "keywords.csv", "unit_economics.csv"):
        path = data_dir / name
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        changed = False
        for row in rows:
            raw = (row.get("nm_id") or "").strip()
            advert_id = 0
            if raw.startswith(PENDING_NM_PREFIX):
                advert_id = int(raw.removeprefix(PENDING_NM_PREFIX))
            elif row.get("wb_campaign_search"):
                advert_id = int(row["wb_campaign_search"])
            if advert_id and advert_id in mapping:
                row["nm_id"] = str(mapping[advert_id])
                changed = True
        if changed:
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            updated.append(name)
    return updated


def update_primary_keywords(data_dir: Path, nm_to_keyword: dict[str, str]) -> list[str]:
    """Set primary keyword in pilot_skus.csv and keywords.csv."""
    updated: list[str] = []
    skus_path = data_dir / "pilot_skus.csv"
    if skus_path.is_file():
        with skus_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        changed = False
        for row in rows:
            nm = (row.get("nm_id") or "").strip()
            if nm in nm_to_keyword:
                row["primary_keyword"] = nm_to_keyword[nm]
                changed = True
        if changed:
            with skus_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            updated.append("pilot_skus.csv")

    kw_path = data_dir / "keywords.csv"
    if kw_path.is_file():
        with kw_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        changed = False
        for row in rows:
            nm = (row.get("nm_id") or "").strip()
            if nm in nm_to_keyword and (row.get("keyword_class") or "primary") == "primary":
                row["keyword"] = nm_to_keyword[nm]
                changed = True
        if changed:
            with kw_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            updated.append("keywords.csv")
    return updated


def update_unit_economics_retail(
    csv_path: Path,
    nm_to_price: dict[str, float],
    *,
    overwrite: bool = False,
) -> tuple[int, int]:
    """Set retail_price_rub in unit_economics.csv from nm_id -> price mapping."""
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    updated = 0
    skipped = 0
    for row in rows:
        nm = (row.get("nm_id") or "").strip()
        if nm not in nm_to_price:
            continue
        if row.get("retail_price_rub") and not overwrite:
            skipped += 1
            continue
        price = nm_to_price[nm]
        row["retail_price_rub"] = str(int(price) if price == int(price) else round(price, 2))
        updated += 1

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return updated, skipped
