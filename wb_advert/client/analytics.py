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
    def stocks_report_wb_warehouses(
        self,
        begin: date,
        end: date,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> HttpResult:
        body = {
            "currentPeriod": {"start": begin.isoformat(), "end": end.isoformat()},
            "stockType": "",
            "skipDeletedNm": True,
            "limit": limit,
            "offset": offset,
        }
        return self.http.request(
            self.base,
            "POST",
            "/api/analytics/v1/stocks-report/wb-warehouses",
            json_body=body,
        )
