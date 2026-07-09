"""Per-campaign recommendation summaries for the dashboard."""

from __future__ import annotations

ACTION_PRIORITY: dict[str, int] = {
    "exclude_keyword": 0,
    "lower_bid": 1,
    "raise_bid": 2,
    "promote_managed": 3,
    "keep": 4,
    "skip": 5,
}


def _rank(suggestion: dict, *, primary_keyword: str) -> tuple[int, int]:
    action = suggestion.get("action") or "skip"
    kw = (suggestion.get("keyword") or "").strip().lower()
    primary = primary_keyword.strip().lower()
    is_primary = bool(primary and kw == primary)
    return (ACTION_PRIORITY.get(action, 99), 0 if is_primary else 1)


def pick_display_suggestion(
    suggestions: list[dict],
    *,
    primary_keyword: str,
) -> dict | None:
    if not suggestions:
        return None
    ranked = sorted(suggestions, key=lambda s: _rank(s, primary_keyword=primary_keyword))
    for s in ranked:
        if s.get("action") not in ("skip",):
            return s
    return ranked[0]


def summarize_campaign(
    *,
    advert_id: int,
    nm_id: str,
    primary_keyword: str | None,
    suggestions: list[dict],
    alerts: list[str] | None = None,
    decided_at: str | None = None,
) -> dict:
    primary = (primary_keyword or "").strip()
    actionable = [s for s in suggestions if s.get("action") not in ("skip", "keep")]
    display = pick_display_suggestion(suggestions, primary_keyword=primary)

    if display is None and alerts:
        return {
            "advert_id": advert_id,
            "nm_id": nm_id,
            "keyword": primary or "—",
            "action": "skip",
            "reason_text": alerts[0],
            "summary": alerts[0],
            "actionable_count": 0,
            "decided_at": decided_at,
        }

    if display is None:
        return {
            "advert_id": advert_id,
            "nm_id": nm_id,
            "keyword": primary or "—",
            "action": "skip",
            "reason_text": "Нет данных optimizer",
            "summary": "Нет данных",
            "actionable_count": 0,
            "decided_at": decided_at,
        }

    action = display.get("action") or "skip"
    keyword = display.get("keyword") or primary or "—"
    reason = display.get("reason_text") or ""

    if len(actionable) > 1:
        summary = f"{len(actionable)} действия"
    elif action == "keep":
        summary = "В норме"
    elif action == "skip":
        summary = reason or "Недостаточно данных"
    else:
        summary = reason

    return {
        "advert_id": advert_id,
        "nm_id": nm_id,
        "keyword": keyword,
        "action": action,
        "reason_text": reason,
        "summary": summary,
        "actionable_count": len(actionable),
        "decided_at": decided_at,
    }


def build_campaign_recommendations(products: list[dict]) -> list[dict]:
    out = [p["recommendation"] for p in products if p.get("recommendation")]
    out.sort(
        key=lambda r: (
            -r["actionable_count"],
            ACTION_PRIORITY.get(r["action"], 99),
            r["advert_id"],
        )
    )
    return out
