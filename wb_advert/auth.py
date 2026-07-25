"""Shared portal session auth for standalone wb_advert behind wb.zhukovlab.ru."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

SESSION_USER_ID_KEY = "portal_user_id"
SESSION_USER_KEY = "portal_user"
PUBLIC_API_PATHS = {"/api/advert/health"}


def get_session_user_id(request: Request) -> int | None:
    raw = request.session.get(SESSION_USER_ID_KEY)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def is_protected_path(path: str) -> bool:
    if path in PUBLIC_API_PATHS:
        return False
    if path.startswith("/api/advert"):
        return True
    if path == "/" or path.startswith("/advert"):
        return True
    return False


def portal_auth_response(request: Request) -> Response:
    path = request.url.path
    if path.startswith("/api/advert"):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    next_path = path
    if request.url.query:
        next_path += f"?{request.url.query}"
    return RedirectResponse(url=f"/login?next={quote(next_path)}", status_code=303)
