"""Per-campaign recommendation summaries for the dashboard."""

from __future__ import annotations

from wb_advert.ui.labels import action_ru

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
    return (0 if is_primary else 1, ACTION_PRIORITY.get(action, 99))


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


def _extra_actions_phrase(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        word = "действие"
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        word = "действия"
    else:
        word = "действий"
    return f"ещё {count} {word}"


def _remaining_actionable_count(action: str, actionable_count: int) -> int:
    if action in ("keep", "skip"):
        return actionable_count
    return max(actionable_count - 1, 0)


def recommendation_needs_attention(recommendation: dict) -> bool:
    return int(recommendation.get("actionable_count") or 0) > 0


def _build_summary(action: str, reason: str, remaining: int) -> str:
    if remaining > 0:
        return f"{action_ru(action)} · {_extra_actions_phrase(remaining)}"
    if action == "keep":
        return "В норме"
    if action == "skip":
        return reason or "Недостаточно данных"
    return reason


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
    actionable_count = len(actionable)
    remaining = _remaining_actionable_count(action, actionable_count)
    summary = _build_summary(action, reason, remaining)

    return {
        "advert_id": advert_id,
        "nm_id": nm_id,
        "keyword": keyword,
        "action": action,
        "reason_text": reason,
        "summary": summary,
        "actionable_count": actionable_count,
        "needs_attention": recommendation_needs_attention({"actionable_count": actionable_count}),
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
