"""WB search `dest` codes — geo affects organic positions."""

from __future__ import annotations

# Common dest values (see seller/parser config). Override in data/pilot/config.yaml → parser.dest
REGION_DEST: dict[str, str] = {
    "moscow": "-1257786",
    "москва": "-1257786",
    "rostov": "-2228363",
    "ростов": "-2228363",
    "krasnodar": "-1059500",
    "краснодар": "-1059500",
}

# Canonical keys for dashboard / config UI
PARSER_REGION_OPTIONS: list[dict[str, str]] = [
    {"key": "krasnodar", "label": "Краснодар", "dest": "-1059500"},
    {"key": "moscow", "label": "Москва", "dest": "-1257786"},
    {"key": "rostov", "label": "Ростов", "dest": "-2228363"},
]

_CONFIG_REGION_LABELS = {
    "krasnodar": "Krasnodar",
    "moscow": "Moscow",
    "rostov": "Rostov",
}


def normalize_region_key(region: str | None) -> str:
    if not region:
        return "krasnodar"
    key = region.strip().lower()
    if key in _CONFIG_REGION_LABELS:
        return key
    for k, dest in REGION_DEST.items():
        if k == key:
            return k if k in _CONFIG_REGION_LABELS else "moscow"
    for opt in PARSER_REGION_OPTIONS:
        if opt["label"].lower() == key or opt["key"] == key:
            return opt["key"]
    return "krasnodar"


def region_config_label(key: str) -> str:
    return _CONFIG_REGION_LABELS.get(normalize_region_key(key), "Krasnodar")


def resolve_dest(region: str | None, explicit_dest: str | int | None = None) -> str:
    if explicit_dest is not None and str(explicit_dest).strip():
        return str(explicit_dest).strip()
    key = (region or "moscow").strip().lower()
    return REGION_DEST.get(key, REGION_DEST["moscow"])
