"""HTTP middleware: enforce portal session on advert pages and API."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from wb_advert.auth import get_session_user_id, is_protected_path, portal_auth_response
from wb_advert import config


class PortalSessionAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        secret = (config.settings.portal_session_secret or "").strip()
        if not secret:
            return await call_next(request)
        path = request.url.path
        if not is_protected_path(path):
            return await call_next(request)
        if get_session_user_id(request) is None:
            return portal_auth_response(request)
        return await call_next(request)
