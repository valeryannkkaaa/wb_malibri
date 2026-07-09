"""Dashboard alerts: CPC over limit, zero stock, parser 429."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wb_advert.parser.regions import PARSER_REGION_OPTIONS, normalize_region_key
from wb_advert.storage.config_store import get_parser_settings
from wb_advert.storage.positions_store import positions_dir

ALERT_SEVERITY: dict[str, str] = {
    "stock_zero": "error",
    "parser_429": "error",
    "cpc_over_limit": "warning",
}

ALERT_PRIORITY: dict[str, int] = {
    "stock_zero": 0,
    "parser_429": 1,
    "cpc_over_limit": 2,
}


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def load_recent_rate_limit_events(
    data_dir: Path | None = None,
    *,
    hours: float = 6.0,
) -> list[dict]:
    """Recent parser 429 events from position JSONL, newest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    events: list[dict] = []
    d = positions_dir(data_dir)
    for path in sorted(d.glob("positions_*.jsonl"), reverse=True):
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            err = str(row.get("error") or "")
            if "429" not in err:
                continue
            parsed = _parse_ts(row.get("parsed_at"))
            if parsed is None:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed < cutoff:
                continue
            events.append(
                {
                    "nm_id": str(row.get("nm_id") or ""),
                    "advert_id": row.get("advert_id"),
                    "region_key": normalize_region_key(str(row.get("region_key") or "")),
                    "parsed_at": row.get("parsed_at"),
                    "error": err,
                }
            )
    return events


def build_dashboard_alerts(
    products: list[dict],
    data_dir: Path | None = None,
    *,
    rate_limit_hours: float = 6.0,
) -> list[dict]:
    """Build alert rows for dashboard (CPC>max, stock=0, parser 429)."""
    parser_region = get_parser_settings(data_dir)["region_key"]
    region_label = next(
        (opt["label"] for opt in PARSER_REGION_OPTIONS if opt["key"] == parser_region),
        parser_region,
    )
    alerts: list[dict] = []
    seen: set[tuple] = set()

    for product in products:
        advert_id = int(product["advert_id"])
        nm_id = str(product["nm_id"])
        primary = product.get("primary_keyword") or "—"

        if int(product.get("stock_quantity") or 0) == 0:
            key = (advert_id, "stock_zero")
            if key not in seen:
                seen.add(key)
                alerts.append(
                    {
                        "code": "stock_zero",
                        "severity": ALERT_SEVERITY["stock_zero"],
                        "advert_id": advert_id,
                        "nm_id": nm_id,
                        "keyword": primary,
                        "region_key": None,
                        "message": "Остаток 0 — рекламу лучше приостановить",
                        "detail": None,
                        "detected_at": None,
                    }
                )

        if product.get("cpc_over_limit"):
            cpc = product.get("primary_cpc_rub")
            max_cpc = product.get("max_cpc_rub")
            key = (advert_id, "cpc_over_limit")
            if key not in seen:
                seen.add(key)
                alerts.append(
                    {
                        "code": "cpc_over_limit",
                        "severity": ALERT_SEVERITY["cpc_over_limit"],
                        "advert_id": advert_id,
                        "nm_id": nm_id,
                        "keyword": primary,
                        "region_key": None,
                        "message": f"CPC {cpc}₽ выше лимита {max_cpc}₽",
                        "detail": "Primary ключ переплачивает по юнит-экономике",
                        "detected_at": None,
                    }
                )

        pos_err = str(product.get("position_error") or "")
        if "429" in pos_err:
            key = (advert_id, "parser_429", parser_region)
            if key not in seen:
                seen.add(key)
                alerts.append(
                    {
                        "code": "parser_429",
                        "severity": ALERT_SEVERITY["parser_429"],
                        "advert_id": advert_id,
                        "nm_id": nm_id,
                        "keyword": primary,
                        "region_key": parser_region,
                        "message": f"Парсер: HTTP 429 ({region_label})",
                        "detail": "WB ограничивает поиск — позиция не обновлена",
                        "detected_at": product.get("position_parsed_at"),
                    }
                )

    rate_events = load_recent_rate_limit_events(data_dir, hours=rate_limit_hours)
    if len(rate_events) >= 3:
        latest = rate_events[0].get("parsed_at")
        alerts.append(
            {
                "code": "parser_429",
                "severity": ALERT_SEVERITY["parser_429"],
                "advert_id": None,
                "nm_id": None,
                "keyword": None,
                "region_key": None,
                "message": f"Парсер: {len(rate_events)}× HTTP 429 за {rate_limit_hours:g} ч",
                "detail": "Подождите 10–30 мин или уменьшите частоту парсинга",
                "detected_at": latest,
            }
        )

    alerts.sort(
        key=lambda a: (
            0 if a["severity"] == "error" else 1,
            ALERT_PRIORITY.get(a["code"], 99),
            a.get("advert_id") or 0,
        )
    )
    return alerts


def summarize_alerts(alerts: list[dict]) -> dict:
    counts = {code: 0 for code in ALERT_SEVERITY}
    for alert in alerts:
        code = alert.get("code")
        if code in counts:
            counts[code] += 1
    return {
        "total": len(alerts),
        "error_count": sum(1 for a in alerts if a.get("severity") == "error"),
        "warning_count": sum(1 for a in alerts if a.get("severity") == "warning"),
        **{f"{code}_count": counts[code] for code in ALERT_SEVERITY},
    }


def attach_alert_flags(products: list[dict], alerts: list[dict]) -> list[dict]:
    by_advert: dict[int, list[str]] = {}
    for alert in alerts:
        advert_id = alert.get("advert_id")
        if advert_id is None:
            continue
        by_advert.setdefault(int(advert_id), []).append(alert["code"])

    for product in products:
        codes = by_advert.get(int(product["advert_id"]), [])
        product["alert_codes"] = codes
        product["has_alerts"] = bool(codes)
        if any(ALERT_SEVERITY.get(c) == "error" for c in codes):
            product["alert_severity"] = "error"
        elif codes:
            product["alert_severity"] = "warning"
        else:
            product["alert_severity"] = None
    return products
