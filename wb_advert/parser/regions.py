"""WB search `dest` codes — geo affects organic positions."""

from __future__ import annotations

from typing import Any

import httpx

GEO_URL = "https://user-geo-data.wildberries.ru/get-geo-info"
DEFAULT_REGION_KEY = "moscow"

# Legacy dest fallbacks (v9 era); used only when geo API is unavailable.
REGION_DEST: dict[str, str] = {
    "moscow": "-1257786",
    "москва": "-1257786",
    "rostov": "-2228363",
    "ростов": "-2228363",
    "krasnodar": "-1059500",
    "краснодар": "-1059500",
}

REGION_GEO: dict[str, dict[str, Any]] = {
    "moscow": {"latitude": 55.7558, "longitude": 37.6173, "address": "Москва"},
    "rostov": {"latitude": 47.2357, "longitude": 39.7015, "address": "Ростов-на-Дону"},
    "krasnodar": {"latitude": 45.0355, "longitude": 38.9753, "address": "Краснодар"},
}

# Canonical keys for dashboard / config UI (dest refreshed via resolve_dest on save)
PARSER_REGION_OPTIONS: list[dict[str, str]] = [
    {"key": "krasnodar", "label": "Краснодар", "dest": REGION_DEST["krasnodar"]},
    {"key": "moscow", "label": "Москва", "dest": REGION_DEST["moscow"]},
    {"key": "rostov", "label": "Ростов", "dest": REGION_DEST["rostov"]},
]

_CONFIG_REGION_LABELS = {
    "krasnodar": "Krasnodar",
    "moscow": "Moscow",
    "rostov": "Rostov",
}

_dest_cache: dict[str, str] = {}


def clear_dest_cache() -> None:
    _dest_cache.clear()


def normalize_region_key(region: str | None) -> str:
    if not region:
        return DEFAULT_REGION_KEY
    key = region.strip().lower()
    if key in _CONFIG_REGION_LABELS:
        return key
    for k in REGION_DEST:
        if k == key and k in _CONFIG_REGION_LABELS:
            return k
    for opt in PARSER_REGION_OPTIONS:
        if opt["label"].lower() == key or opt["key"] == key:
            return opt["key"]
    return DEFAULT_REGION_KEY


def region_config_label(key: str) -> str:
    return _CONFIG_REGION_LABELS.get(normalize_region_key(key), "Moscow")


def _parse_dest_from_geo(data: dict[str, Any]) -> str | None:
    xinfo = data.get("xinfo", "")
    if isinstance(xinfo, str):
        for part in xinfo.split("&"):
            if part.startswith("dest="):
                return part.split("=", 1)[1]
    destinations = data.get("destinations") or []
    if destinations:
        return str(destinations[-1])
    return None


def resolve_dest_via_geo(region_key: str, *, client: httpx.Client | None = None) -> str | None:
    """Resolve current WB dest for a region via public geo API (same approach as wb_pars)."""
    geo = REGION_GEO.get(normalize_region_key(region_key))
    if not geo:
        return None
    params = {"currency": "RUB", "locale": "ru", **geo}
    own_client = client is None
    http = client or httpx.Client(timeout=15.0)
    try:
        resp = http.get(GEO_URL, params=params)
        resp.raise_for_status()
        return _parse_dest_from_geo(resp.json())
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    finally:
        if own_client:
            http.close()


def resolve_dest(region: str | None, explicit_dest: str | int | None = None) -> str:
    if explicit_dest is not None and str(explicit_dest).strip():
        return str(explicit_dest).strip()
    key = normalize_region_key(region)
    if key in _dest_cache:
        return _dest_cache[key]
    dest = resolve_dest_via_geo(key) or REGION_DEST.get(key) or REGION_DEST[DEFAULT_REGION_KEY]
    _dest_cache[key] = dest
    return dest
