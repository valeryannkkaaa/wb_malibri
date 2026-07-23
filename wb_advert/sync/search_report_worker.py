from __future__ import annotations

from datetime import date

from wb_advert.client.analytics import AnalyticsClient
from wb_advert.sync.search_report_mappers import extract_search_text_items, map_search_text_item

PAGE_SIZE = 50
MAX_PAGES = 10


class SearchReportWorker:
    """Fetch WB search-report/product/search-texts for one pilot nm_id."""

    def __init__(self, analytics: AnalyticsClient | None = None) -> None:
        self.analytics = analytics or AnalyticsClient()

    def fetch_nm_search_texts(
        self,
        nm_id: int,
        begin: date,
        end: date,
    ) -> tuple[list[dict], list[str]]:
        errors: list[str] = []
        all_items: list[dict] = []
        offset = 0
        page = 0

        while page < MAX_PAGES:
            print(f"  -> search-texts (nm_id={nm_id}, offset={offset})...", flush=True)
            result = self.analytics.search_report_product_search_texts(
                begin,
                end,
                [nm_id],
                limit=PAGE_SIZE,
                offset=offset,
            )
            if not result.ok:
                detail = result.error or result.body[:120]
                errors.append(f"search-texts: HTTP {result.status} {detail}")
                return [], errors
            print(f"     HTTP {result.status}", flush=True)

            batch = extract_search_text_items(result.json())
            all_items.extend(map_search_text_item(row) for row in batch)
            page += 1
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        else:
            errors.append(
                f"search-texts: pagination stopped after {MAX_PAGES} pages "
                f"({MAX_PAGES * PAGE_SIZE} keywords max)"
            )

        if not errors and not all_items:
            errors.append("search-texts: HTTP 200 but 0 keywords in period")
        return all_items, errors
