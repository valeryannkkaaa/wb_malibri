"""Safety checks before applying optimizer actions to WB API."""

from __future__ import annotations

from wb_advert.constants import MAX_BID_KOPECKS_DEFAULT
from wb_advert.storage.config_store import load_config
from wb_advert.storage.write_access import load_write_access

APPLY_ACTIONS = frozenset({"raise_bid", "lower_bid", "exclude_keyword"})


def get_apply_settings(data_dir=None) -> dict:
    config = load_config(data_dir)
    mode = config.get("optimizer_mode", "suggest-only")
    allow_writes = bool(config.get("allow_wb_writes", False))
    gaps = list(config.get("token_gaps") or [])
    probe = load_write_access(data_dir)
    blocked_reasons: list[str] = []

    if mode != "auto":
        blocked_reasons.append("optimizer_mode=suggest-only (нужен auto)")
    if not allow_writes:
        blocked_reasons.append("allow_wb_writes=false в config.yaml")
    if "bid_write" in gaps:
        blocked_reasons.append("token_gaps: bid_write")
    if probe.get("checked_at") and not probe.get("can_write"):
        blocked_reasons.append(probe.get("summary") or "write probe failed")

    can_apply = not blocked_reasons
    return {
        "optimizer_mode": mode,
        "allow_wb_writes": allow_writes,
        "token_gaps": gaps,
        "write_probe": probe,
        "can_apply": can_apply,
        "blocked_reasons": blocked_reasons,
    }


def validate_bid_kopecks(bid_kopecks: int, *, max_kopecks: int = MAX_BID_KOPECKS_DEFAULT) -> str | None:
    if bid_kopecks <= 0:
        return "ставка должна быть > 0"
    if bid_kopecks > max_kopecks:
        return f"ставка {bid_kopecks/100:.2f}₽ выше лимита {max_kopecks/100:.2f}₽"
    return None
