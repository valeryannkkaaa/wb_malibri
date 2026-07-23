from __future__ import annotations

import csv
import io
import zipfile
from typing import Any

_CSV_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("nm_id", "nmID"),
    ("dt", "dt"),
    ("open_card_count", "openCardCount"),
    ("add_to_cart_count", "addToCartCount"),
    ("orders_count", "ordersCount"),
    ("orders_sum_rub", "ordersSumRub"),
    ("buyouts_count", "buyoutsCount"),
    ("buyouts_sum_rub", "buyoutsSumRub"),
    ("cancel_count", "cancelCount"),
    ("cancel_sum_rub", "cancelSumRub"),
    ("add_to_cart_conversion", "addToCartConversion"),
    ("cart_to_order_conversion", "cartToOrderConversion"),
    ("buyout_percent", "buyoutPercent"),
    ("add_to_wishlist", "addToWishlist"),
    ("currency", "currency"),
)

_INT_FIELDS = {
    "nm_id",
    "open_card_count",
    "add_to_cart_count",
    "orders_count",
    "buyouts_count",
    "cancel_count",
    "add_to_wishlist",
}


def map_funnel_csv_row(row: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for flat_key, csv_key in _CSV_FIELD_MAP:
        raw = row.get(csv_key)
        if raw is None or raw == "":
            continue
        if flat_key in _INT_FIELDS:
            out[flat_key] = int(raw)
        elif flat_key == "dt":
            out[flat_key] = str(raw)
        elif flat_key == "currency":
            out[flat_key] = str(raw)
        else:
            out[flat_key] = float(raw) if "." in raw else int(raw)
    return out


def parse_funnel_csv(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    return [map_funnel_csv_row(row) for row in reader if row.get("dt")]


def extract_csv_from_zip(zip_bytes: bytes) -> str | None:
    if not zip_bytes:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            csv_names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
            if not csv_names:
                return None
            return zf.read(csv_names[0]).decode("utf-8-sig")
    except (zipfile.BadZipFile, OSError, UnicodeDecodeError):
        return None


def extract_download_status(payload: dict[str, Any] | None, download_id: str) -> str | None:
    if not payload:
        return None
    data = payload.get("data")
    rows: list[dict[str, Any]] = []
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        inner = data.get("downloads") or data.get("items") or []
        if isinstance(inner, list):
            rows = [r for r in inner if isinstance(r, dict)]
    for row in rows:
        row_id = row.get("id") or row.get("downloadId") or row.get("download_id")
        if str(row_id) == str(download_id):
            status = row.get("status")
            return str(status) if status is not None else None
    if rows and len(rows) == 1:
        status = rows[0].get("status")
        return str(status) if status is not None else None
    return None
