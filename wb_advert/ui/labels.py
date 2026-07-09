"""Russian UI labels for dashboard templates."""

from __future__ import annotations

ACTION_RU: dict[str, str] = {
    "keep": "Оставить",
    "raise_bid": "Поднять ставку",
    "lower_bid": "Снизить ставку",
    "exclude_keyword": "Исключить ключ",
    "promote_managed": "В managed",
    "skip": "Пропустить",
    "retest_keyword": "Перетестировать",
}

STATUS_RU: dict[str, str] = {
    "managed": "Управляется",
    "excluded": "Исключён",
    "pending_100_shows": "Ждём 100 показов",
}

GRADE_RU: dict[str, str] = {
    "top_1_3": "топ 1–3",
    "pos_10_20": "поз. 10–20",
}

CYCLE_RU: dict[str, str] = {
    "ok": "ок",
    "stale": "устарело",
    "error": "ошибка",
    "running": "выполняется",
    "unknown": "неизвестно",
}

ALERT_RU: dict[str, str] = {
    "stock_zero": "Нет остатка",
    "cpc_over_limit": "CPC выше лимита",
    "parser_429": "Парсер 429",
}


def action_ru(code: str | None) -> str:
    if not code:
        return "—"
    return ACTION_RU.get(code, code.replace("_", " "))


def status_ru(code: str | None) -> str:
    if not code:
        return "—"
    return STATUS_RU.get(code, code.replace("_", " "))


def grade_ru(code: str | None) -> str:
    if not code:
        return "—"
    return GRADE_RU.get(code, code)


def cycle_ru_label(code: str | None) -> str:
    if not code:
        return "—"
    return CYCLE_RU.get(code, code)


def alert_ru(code: str | None) -> str:
    if not code:
        return "—"
    return ALERT_RU.get(code, code.replace("_", " "))
