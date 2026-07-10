from __future__ import annotations

import time
from typing import Any

from curl_cffi import requests as cffi
from curl_cffi.const import CurlHttpVersion
from curl_cffi.requests import RequestsError

from wb_advert.parser.regions import normalize_region_key, resolve_dest

SEARCH_URL = "https://u-search.wb.ru/exactmatch/ru/common/v18/search"
PRODUCTS_PER_PAGE = 100
DEFAULT_PAUSE_SEC = 0.4

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.wildberries.ru/",
    "Accept": "*/*",
}


def _extract_products(data: Any) -> list[dict]:
    if not isinstance(data, dict):
        return []
    products = data.get("products")
    if products:
        return [p for p in products if isinstance(p, dict)]
    nested = data.get("data")
    if isinstance(nested, dict) and nested.get("products"):
        return [p for p in nested["products"] if isinstance(p, dict)]
    return []


class WbSearchParser:
    """Organic search position for nm_id by keyword (public search API, no auth)."""

    def __init__(
        self,
        *,
        dest: str | None = None,
        region: str | None = None,
        pause_sec: float = DEFAULT_PAUSE_SEC,
        max_pages: int = 5,
        max_retries: int = 3,
    ) -> None:
        self.region_key = normalize_region_key(region)
        self.dest = resolve_dest(region, dest)
        self.pause_sec = max(0.1, float(pause_sec))
        self.max_pages = max(1, max_pages)
        self.max_retries = max_retries
        self._impersonate = "chrome120"
        self._session = cffi.Session(headers=DEFAULT_HEADERS)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> WbSearchParser:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _backoff_sleep(self, attempt: int, *, rate_limited: bool = False) -> None:
        if rate_limited:
            time.sleep(min(5.0, self.pause_sec * (2**attempt)))
            return
        if attempt:
            time.sleep(self.pause_sec * attempt)

    def _fetch_page(self, query: str, page: int) -> tuple[int, list[dict], str | None]:
        params = {
            "appType": "1",
            "curr": "rub",
            "dest": self.dest,
            "lang": "ru",
            "page": str(page),
            "query": query,
            "resultset": "catalog",
            "limit": str(PRODUCTS_PER_PAGE),
            "sort": "popular",
            "spp": "30",
            "suppressSpellcheck": "false",
        }
        last_err: str | None = None
        for attempt in range(self.max_retries):
            self._backoff_sleep(attempt)
            time.sleep(self.pause_sec)
            try:
                resp = self._session.get(
                    SEARCH_URL,
                    params=params,
                    timeout=30,
                    impersonate=self._impersonate,
                    http_version=CurlHttpVersion.V1_1,
                )
            except RequestsError as exc:
                last_err = str(exc)
                continue
            if resp.status_code == 429:
                last_err = "HTTP 429 rate limit"
                self._backoff_sleep(attempt + 1, rate_limited=True)
                continue
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                continue
            try:
                products = _extract_products(resp.json())
            except ValueError:
                last_err = "invalid JSON"
                continue
            return resp.status_code, products, None
        return 0, [], last_err

    def find_position(self, query: str, nm_id: int) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {
                "found": False,
                "position": None,
                "error": "empty query",
                "nm_id": nm_id,
                "region_key": self.region_key,
            }

        scanned = 0
        for page in range(1, self.max_pages + 1):
            _status, products, err = self._fetch_page(query, page)
            if err:
                return {
                    "found": False,
                    "position": None,
                    "error": err,
                    "nm_id": nm_id,
                    "keyword": query,
                    "page": page,
                    "dest": self.dest,
                    "region_key": self.region_key,
                    "scanned": scanned,
                }
            if not products:
                break
            for idx, product in enumerate(products, start=1):
                scanned += 1
                pid = product.get("id") or product.get("nmId") or product.get("nm_id")
                if pid is not None and int(pid) == int(nm_id):
                    position = (page - 1) * PRODUCTS_PER_PAGE + idx
                    return {
                        "found": True,
                        "position": position,
                        "error": None,
                        "nm_id": nm_id,
                        "keyword": query,
                        "page": page,
                        "dest": self.dest,
                        "region_key": self.region_key,
                        "scanned": scanned,
                    }

        return {
            "found": False,
            "position": None,
            "error": f"not in top {scanned or self.max_pages * PRODUCTS_PER_PAGE}",
            "nm_id": nm_id,
            "keyword": query,
            "dest": self.dest,
            "region_key": self.region_key,
            "scanned": scanned,
        }


def find_nm_position(
    query: str,
    nm_id: int,
    *,
    dest: str | None = None,
    region: str | None = None,
    pause_sec: float = DEFAULT_PAUSE_SEC,
    max_pages: int = 5,
) -> dict[str, Any]:
    with WbSearchParser(dest=dest, region=region, pause_sec=pause_sec, max_pages=max_pages) as parser:
        return parser.find_position(query, nm_id)
