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

    def search_report_product_search_texts(
        self,
        begin: date,
        end: date,
        nm_ids: list[int],
        *,
        limit: int = 100,
        top_order_by: str = "openCard",
        order_field: str = "openCard",
        order_mode: str = "desc",
    ) -> HttpResult:
        body: dict[str, Any] = {
            "currentPeriod": {"start": begin.isoformat(), "end": end.isoformat()},
            "nmIds": nm_ids,
            "topOrderBy": top_order_by,
            "orderBy": {"field": order_field, "mode": order_mode},
            "limit": limit,
            "offset": 0,
        }
        return self.http.request(
            self.base,
            "POST",
            "/api/v2/search-report/product/search-texts",
            json_body=body,
        )

    def nm_report_create_download(
        self,
        download_id: str,
        nm_ids: list[int],
        start: date,
        end: date,
        *,
        report_name: str = "funnel_detail_history",
        timezone: str = "Europe/Moscow",
    ) -> HttpResult:
        body: dict[str, Any] = {
            "id": download_id,
            "reportType": "DETAIL_HISTORY_REPORT",
            "userReportName": report_name,
            "params": {
                "nmIDs": nm_ids,
                "subjectIDs": [],
                "brandNames": [],
                "tagIDs": [],
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "timezone": timezone,
                "aggregationLevel": "day",
                "skipDeletedNm": False,
            },
        }
        return self.http.request(
            self.base,
            "POST",
            "/api/v2/nm-report/downloads",
            json_body=body,
        )

    def nm_report_download_status(self, download_ids: list[str]) -> HttpResult:
        params = {"filter[downloadIds]": ",".join(download_ids)}
        return self.http.request(
            self.base,
            "GET",
            "/api/v2/nm-report/downloads",
            params=params,
        )

    def nm_report_download_file(self, download_id: str) -> tuple[int | None, bytes, str | None]:
        return self.http.request_bytes(
            self.base,
            "GET",
            f"/api/v2/nm-report/downloads/file/{download_id}",
        )

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
