from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from wb_advert.client.base import WbHttpClient, HttpResult
from wb_advert.client.fullstats_parse import extract_nm_ids_from_fullstats
from wb_advert.config import settings
from wb_advert.constants import FULLSTATS_PAUSE_SEC


class PromotionClient:
    def __init__(self, http: WbHttpClient | None = None) -> None:
        self.http = http or WbHttpClient()
        self.base = settings.promotion_base

    def list_adverts(self) -> HttpResult:
        return self.http.request(self.base, "GET", "/api/advert/v2/adverts")

    def get_advert(self, advert_id: int) -> HttpResult:
        return self.http.request(
            self.base,
            "GET",
            "/api/advert/v2/adverts",
            params={"ids": str(advert_id)},
        )

    def balance(self) -> HttpResult:
        return self.http.request(self.base, "GET", "/adv/v1/balance")

    def fullstats(self, advert_id: int, begin: date, end: date) -> HttpResult:
        old_pause = self.http.pause_sec
        self.http.pause_sec = FULLSTATS_PAUSE_SEC
        try:
            return self.http.request(
                self.base,
                "GET",
                "/adv/v3/fullstats",
                params={
                    "ids": str(advert_id),
                    "beginDate": begin.isoformat(),
                    "endDate": end.isoformat(),
                },
            )
        finally:
            self.http.pause_sec = old_pause

    def normquery_stats(
        self,
        advert_id: int,
        nm_id: int,
        begin: date,
        end: date,
    ) -> HttpResult:
        return self.http.request(
            self.base,
            "POST",
            "/adv/v0/normquery/stats",
            json_body={
                "from": begin.isoformat(),
                "to": end.isoformat(),
                "items": [{"advert_id": advert_id, "nm_id": nm_id}],
            },
        )

    def normquery_get_bids(self, advert_id: int, nm_id: int) -> HttpResult:
        return self.http.request(
            self.base,
            "POST",
            "/adv/v0/normquery/get-bids",
            json_body={"items": [{"advert_id": advert_id, "nm_id": nm_id}]},
        )

    def normquery_list(self, advert_id: int, nm_id: int) -> HttpResult:
        return self.http.request(
            self.base,
            "POST",
            "/adv/v0/normquery/list",
            json_body={"items": [{"advertId": advert_id, "nmId": nm_id}]},
        )

    def bids_min(
        self,
        advert_id: int,
        nm_id: int,
        *,
        payment_type: str = "cpm",
        placement_types: list[str] | None = None,
    ) -> HttpResult:
        return self.http.request(
            self.base,
            "POST",
            "/api/advert/v1/bids/min",
            json_body={
                "advert_id": advert_id,
                "nm_ids": [nm_id],
                "payment_type": payment_type,
                "placement_types": placement_types or ["search"],
            },
        )

    def normquery_set_bids(
        self,
        advert_id: int,
        nm_id: int,
        keyword: str,
        bid_kopecks: int,
    ) -> HttpResult:
        """Per-cluster bid for manual search campaigns (type 9)."""
        return self.http.request(
            self.base,
            "POST",
            "/adv/v0/normquery/bids",
            json_body={
                "items": [
                    {
                        "advert_id": advert_id,
                        "nm_id": nm_id,
                        "norm_query_bids": [
                            {"norm_query": keyword, "bid": bid_kopecks},
                        ],
                    }
                ]
            },
        )

    def normquery_set_minus(
        self,
        advert_id: int,
        nm_id: int,
        keywords: list[str],
    ) -> HttpResult:
        """Exclude normquery clusters from search ads."""
        return self.http.request(
            self.base,
            "POST",
            "/adv/v0/normquery/set-minus",
            json_body={
                "items": [
                    {
                        "advert_id": advert_id,
                        "nm_id": nm_id,
                        "norm_queries": keywords,
                    }
                ]
            },
        )

    def patch_auction_bids(
        self,
        advert_id: int,
        nm_id: int,
        bid_kopecks: int,
        *,
        placement: str = "search",
    ) -> HttpResult:
        """Campaign nm-level bid (manual bid type). bid in kopecks."""
        return self.http.request(
            self.base,
            "PATCH",
            "/api/advert/v1/bids",
            json_body=[
                {
                    "advert_id": advert_id,
                    "nm_bids": [
                        {
                            "nm": nm_id,
                            "bid": bid_kopecks,
                            "placement": placement,
                        }
                    ],
                }
            ],
        )

    @staticmethod
    def extract_nm_ids_from_detail(data: Any) -> list[int]:
        ids: list[int] = []
        if not isinstance(data, dict):
            return ids
        adverts = data.get("adverts") or []
        blocks = adverts if isinstance(adverts, list) else [adverts]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            nm_lists = (
                block.get("nm_settings")
                or block.get("nmSettings")
                or block.get("nms")
                or []
            )
            for nm in nm_lists:
                if isinstance(nm, dict):
                    nid = nm.get("nm_id") or nm.get("nmId") or nm.get("nm")
                    if nid:
                        ids.append(int(nid))
                elif isinstance(nm, int):
                    ids.append(nm)
        return ids

    @staticmethod
    def extract_nm_ids_from_bids(data: dict[str, Any]) -> list[int]:
        ids: list[int] = []
        for b in data.get("bids") or []:
            nid = b.get("nm_id") or b.get("nmId")
            if nid:
                ids.append(int(nid))
        return ids

    extract_nm_ids_from_fullstats = staticmethod(extract_nm_ids_from_fullstats)
