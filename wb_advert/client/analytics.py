from __future__ import annotations

from datetime import date
from typing import Any

from wb_advert.client.base import WbHttpClient, HttpResult
from wb_advert.config import settings


class AnalyticsClient:
    def __init__(self, http: WbHttpClient | None = None) -> None:
        self.http = http or WbHttpClient()
        self.base = settings.analytics_base

    def sales_funnel_products(
        self,
        begin: date,
        end: date,
        nm_ids: list[int] | None = None,
        limit: int = 100,
    ) -> HttpResult:
        body: dict[str, Any] = {
            "selectedPeriod": {"start": begin.isoformat(), "end": end.isoformat()},
            "limit": limit,
            "offset": 0,
        }
        if nm_ids:
            body["nmIds"] = nm_ids
        return self.http.request(
            self.base,
            "POST",
            "/api/analytics/v3/sales-funnel/products",
            json_body=body,
        )
