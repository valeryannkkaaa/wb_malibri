from __future__ import annotations

import time
from datetime import date
from uuid import uuid4

from wb_advert.client.analytics import AnalyticsClient
from wb_advert.sync.funnel_mappers import (
    extract_csv_from_zip,
    extract_download_status,
    parse_funnel_csv,
)

MAX_POLL_ATTEMPTS = 30
POLL_INTERVAL_SEC = 10
INITIAL_LOOKBACK_DAYS = 365

_TERMINAL_STATUSES = frozenset({"SUCCESS", "FAILED", "FAILURE", "ERROR"})


class FunnelWorker:
    """Fetch WB nm-report detail history (daily funnel) for one pilot nm_id."""

    def __init__(
        self,
        analytics: AnalyticsClient | None = None,
        *,
        max_poll_attempts: int = MAX_POLL_ATTEMPTS,
        poll_interval_sec: float = POLL_INTERVAL_SEC,
    ) -> None:
        self.analytics = analytics or AnalyticsClient()
        self.max_poll_attempts = max_poll_attempts
        self.poll_interval_sec = poll_interval_sec

    def fetch_nm_funnel(
        self,
        nm_id: int,
        start: date,
        end: date,
        *,
        pending_download_id: str | None = None,
    ) -> tuple[list[dict], list[str], str | None]:
        errors: list[str] = []
        download_id = pending_download_id

        if download_id:
            print(f"  -> resume pending report {download_id}...", flush=True)
        else:
            download_id = str(uuid4())
            print(f"  -> create nm-report download {download_id}...", flush=True)
            result = self.analytics.nm_report_create_download(
                download_id,
                [nm_id],
                start,
                end,
            )
            if not result.ok:
                detail = result.error or result.body[:120]
                errors.append(f"nm-report create: HTTP {result.status} {detail}")
                return [], errors, None
            print(f"     HTTP {result.status}", flush=True)

        status, poll_errors, still_pending = self._poll_until_ready(download_id)
        errors.extend(poll_errors)
        if still_pending:
            return [], errors, download_id
        if status != "SUCCESS":
            errors.append(f"nm-report status: {status or 'unknown'}")
            return [], errors, None

        rows, fetch_errors = self._download_and_parse(download_id)
        errors.extend(fetch_errors)
        return rows, errors, None

    def _poll_until_ready(self, download_id: str) -> tuple[str | None, list[str], bool]:
        errors: list[str] = []
        status: str | None = None

        for attempt in range(1, self.max_poll_attempts + 1):
            if attempt > 1:
                time.sleep(self.poll_interval_sec)
            print(f"  -> poll status ({attempt}/{self.max_poll_attempts})...", flush=True)
            result = self.analytics.nm_report_download_status([download_id])
            if not result.ok:
                detail = result.error or result.body[:120]
                errors.append(f"nm-report poll: HTTP {result.status} {detail}")
                return None, errors, False
            status = extract_download_status(result.json(), download_id)
            if status in _TERMINAL_STATUSES:
                print(f"     status={status}", flush=True)
                return status, errors, False

        errors.append(
            f"nm-report poll: timeout after {self.max_poll_attempts} attempts "
            f"(still {status or 'pending'})",
        )
        return status, errors, True

    def _download_and_parse(self, download_id: str) -> tuple[list[dict], list[str]]:
        errors: list[str] = []
        print("  -> download report zip...", flush=True)
        status, body, transport_error = self.analytics.nm_report_download_file(download_id)
        if status is None or status < 200 or status >= 300:
            detail = transport_error or f"HTTP {status}"
            errors.append(f"nm-report download: {detail}")
            return [], errors

        csv_text = extract_csv_from_zip(body)
        if csv_text is None:
            errors.append("nm-report download: invalid or empty zip")
            return [], errors

        rows = parse_funnel_csv(csv_text)
        if not rows:
            errors.append("nm-report download: empty CSV")
            return [], errors

        print(f"     {len(rows)} day row(s)", flush=True)
        return rows, errors
