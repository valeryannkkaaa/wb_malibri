from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import httpx

from wb_advert.config import settings, require_token

MAX_RETRIES = 5
RETRY_429_BASE_SEC = 20
RETRY_5XX_BASE_SEC = 10
RETRY_TRANSPORT_BASE_SEC = 15


def _is_retryable_status(status: int | None) -> bool:
    if status == 429:
        return True
    return status is not None and status >= 500


def _is_transport_failure(result: "HttpResult") -> bool:
    return result.status is None


class HttpResult:
    def __init__(self, status: int | None, body: str, transport: str = "httpx", error: str | None = None):
        self.status = status
        self.body = body
        self.transport = transport
        self.error = error

    def json(self) -> Any:
        return json.loads(self.body) if self.body else None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300


class WbHttpClient:
    """HTTP client with rate-limit pause and SSL fallback (urllib)."""

    def __init__(
        self,
        token: str | None = None,
        pause_sec: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.token = (token or settings.wb_api_token or require_token()).strip()
        self.pause_sec = pause_sec if pause_sec is not None else settings.request_pause_sec
        self.max_retries = max_retries if max_retries is not None else MAX_RETRIES
        self._httpx = httpx.Client(timeout=60.0, http2=False)
        self._curl = shutil.which("curl.exe") or shutil.which("curl")

    def close(self) -> None:
        self._httpx.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.token, "Content-Type": "application/json"}

    def request(
        self,
        base_url: str,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | list | None = None,
    ) -> HttpResult:
        url = base_url.rstrip("/") + path
        last: HttpResult | None = None

        for attempt in range(self.max_retries):
            last = self._single_request(url, method, params, json_body)
            if not _is_retryable_status(last.status) and not _is_transport_failure(last):
                time.sleep(self.pause_sec)
                return last
            if _is_transport_failure(last):
                wait = min(RETRY_TRANSPORT_BASE_SEC * (attempt + 1), 60)
                hint = (last.error or "network/SSL error")[:80]
                print(
                    f"  [WB] transport error on {method} {path} - wait {wait}s "
                    f"({hint}) (retry {attempt + 1}/{self.max_retries})",
                    flush=True,
                )
                time.sleep(wait)
                continue
            if last.status == 429:
                wait = min(RETRY_429_BASE_SEC * (attempt + 1), 90)
                label = "429 rate limit"
            else:
                wait = min(RETRY_5XX_BASE_SEC * (attempt + 1), 30)
                label = f"HTTP {last.status} server error"
            print(
                f"  [WB] {label} on {method} {path} - wait {wait}s "
                f"(retry {attempt + 1}/{self.max_retries})",
                flush=True,
            )
            time.sleep(wait)

        assert last is not None
        return last

    def _single_request(
        self,
        url: str,
        method: str,
        params: dict | None,
        json_body: dict | list | None,
    ) -> HttpResult:
        # Python 3.14 + advert-api: httpx SSL often fails; curl works when network is OK.
        if sys.platform == "win32" and self._curl and "advert-api.wildberries.ru" in url:
            curl_first = self._curl_request(url, method, params, json_body)
            if curl_first and curl_first.status is not None:
                return curl_first

        try:
            resp = self._httpx.request(
                method,
                url,
                headers=self._headers(),
                params=params,
                json=json_body,
            )
            return HttpResult(resp.status_code, resp.text)
        except httpx.HTTPError as exc:
            fb = self._request_fallback(url, method, params, json_body)
            if fb and fb.status is not None:
                return fb
            err = str(exc)
            if fb and fb.error:
                err = f"{err}; curl: {fb.error}"
            return HttpResult(None, "", error=err)

    def _request_fallback(
        self,
        url: str,
        method: str,
        params: dict | None,
        json_body: dict | list | None,
    ) -> HttpResult | None:
        if self._curl:
            fb = self._curl_request(url, method, params, json_body)
            if fb and fb.status is not None:
                return fb
            curl_err = fb
        else:
            curl_err = None
        fb = self._urllib_request(url, method, params, json_body)
        if fb and fb.status is not None:
            return fb
        return curl_err

    def _curl_request(
        self,
        url: str,
        method: str,
        params: dict | None,
        json_body: dict | list | None,
    ) -> HttpResult | None:
        if not self._curl:
            return None
        if params:
            url = f"{url}?{urlencode(params, doseq=True)}"
        cmd = [
            self._curl,
            "-sS",
            "--http1.1",
        ]
        if sys.platform == "win32":
            cmd.append("--ssl-no-revoke")
        cmd.extend([
            "-w",
            "\n__HTTP__%{http_code}",
            "-H",
            f"Authorization: {self.token}",
            "-H",
            "Content-Type: application/json",
            "-X",
            method,
            url,
        ])
        if json_body is not None:
            cmd.extend(["-d", json.dumps(json_body)])
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
            raw = (proc.stdout or b"").decode("utf-8", errors="replace")
            if "\n__HTTP__" not in raw:
                err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()[:120]
                err = err or f"curl exit {proc.returncode}"
                return HttpResult(None, "", transport="curl", error=err)
            body, status_str = raw.rsplit("\n__HTTP__", 1)
            status = int(status_str)
            if status == 0:
                err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()[:120] or "curl HTTP 000"
                return HttpResult(None, "", transport="curl", error=err)
            return HttpResult(status, body, transport="curl")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return HttpResult(None, "", transport="curl", error=str(exc))

    def _urllib_request(
        self,
        url: str,
        method: str,
        params: dict | None,
        json_body: dict | list | None,
    ) -> HttpResult | None:
        if params:
            url = f"{url}?{urlencode(params, doseq=True)}"
        data = json.dumps(json_body).encode() if json_body is not None else None
        req = Request(url, data=data, method=method, headers=self._headers())
        try:
            with urlopen(req, timeout=60) as resp:
                return HttpResult(resp.status, resp.read().decode(), transport="urllib")
        except HTTPError as exc:
            return HttpResult(exc.code, exc.read().decode(), transport="urllib")
        except OSError:
            return None
