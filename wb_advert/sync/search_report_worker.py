from __future__ import annotations

from datetime import date

from wb_advert.client.analytics import AnalyticsClient
from wb_advert.sync.search_report_mappers import extract_search_text_items, map_search_text_item

SEARCH_LIMIT = 100
TRUNCATION_WARNING = (
    "search-texts: warning: received {count} keywords (limit={limit}); list may be truncated"
)


def is_blocking_error(error: str) -> bool:
    return ": warning:" not in error


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

        print(f"  -> search-texts (nm_id={nm_id}, limit={SEARCH_LIMIT})...", flush=True)
        result = self.analytics.search_report_product_search_texts(
            begin,
            end,
            [nm_id],
            limit=SEARCH_LIMIT,
        )
        if not result.ok:
            detail = result.error or result.body[:120]
            errors.append(f"search-texts: HTTP {result.status} {detail}")
            return [], errors
        print(f"     HTTP {result.status}", flush=True)

        batch = extract_search_text_items(result.json())
        items = [map_search_text_item(row) for row in batch]

        if len(batch) == SEARCH_LIMIT:
            errors.append(
                TRUNCATION_WARNING.format(count=len(batch), limit=SEARCH_LIMIT),
            )

        if not items:
            errors.append("search-texts: HTTP 200 but 0 keywords in period")
        return items, errors
