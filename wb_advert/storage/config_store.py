from __future__ import annotations

from pathlib import Path

import yaml

from wb_advert.config import settings
from wb_advert.parser.regions import (
    PARSER_REGION_OPTIONS,
    normalize_region_key,
    region_config_label,
    resolve_dest,
)


def _data_dir(data_dir: Path | None = None) -> Path:
    if data_dir is not None:
        return data_dir
    root = Path(__file__).resolve().parents[1]
    return (root / settings.pilot_data_path).resolve()


def load_config(data_dir: Path | None = None) -> dict:
    path = _data_dir(data_dir) / "config.yaml"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict, data_dir: Path | None = None) -> Path:
    path = _data_dir(data_dir) / "config.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return path


def get_parser_settings(data_dir: Path | None = None) -> dict:
    config = load_config(data_dir)
    parser = config.get("parser") or {}
    region_raw = parser.get("region")
    key = normalize_region_key(str(region_raw) if region_raw else None)
    return {
        "region_key": key,
        "region": region_config_label(key),
        "dest": parser.get("dest") or resolve_dest(key),
        "options": PARSER_REGION_OPTIONS,
    }


def set_parser_region(region_key: str, data_dir: Path | None = None) -> dict:
    key = normalize_region_key(region_key)
    if key not in {o["key"] for o in PARSER_REGION_OPTIONS}:
        raise ValueError(f"Unknown region: {region_key}")

    config = load_config(data_dir)
    parser = config.setdefault("parser", {})
    parser["region"] = region_config_label(key)
    parser["dest"] = resolve_dest(key)
    save_config(config, data_dir)
    return get_parser_settings(data_dir)
