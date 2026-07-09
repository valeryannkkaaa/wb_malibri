#!/usr/bin/env python
"""Quick WB API connectivity check (advert + analytics). Retries intermittent SSL."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.config import require_token, env_file_used  # noqa: E402

ADVERT_URL = "https://advert-api.wildberries.ru/adv/v1/balance"
ANALYTICS_URL = "https://seller-analytics-api.wildberries.ru/"
RETRIES = 4
RETRY_PAUSE_SEC = 8


def probe_curl(url: str, token: str, *, auth: bool) -> tuple[int | None, str]:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return None, "curl not found"
    cmd = [curl, "-sS", "--http1.1", "--ssl-no-revoke", "-m", "20", "-w", "\n__HTTP__%{http_code}"]
    if auth:
        cmd.extend(["-H", f"Authorization: {token}"])
    cmd.append(url)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=25, check=False)
    except OSError as exc:
        return None, str(exc)
    raw = (proc.stdout or b"").decode("utf-8", errors="replace")
    err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
    if "__HTTP__" not in raw:
        return None, err or f"curl exit {proc.returncode}"
    body, code_str = raw.rsplit("\n__HTTP__", 1)
    code = int(code_str)
    if code == 0:
        return None, err or "curl HTTP 000 (SSL/network)"
    return code, (body.strip() or err)


def probe_httpx(url: str, token: str, *, auth: bool) -> tuple[int | None, str]:
    headers = {"Authorization": token} if auth else {}
    try:
        with httpx.Client(timeout=20.0, http2=False) as client:
            resp = client.get(url, headers=headers)
        return resp.status_code, resp.text[:200]
    except httpx.HTTPError as exc:
        return None, str(exc)


def probe_with_retries(url: str, token: str, *, auth: bool) -> tuple[int | None, str, str]:
    last_err = ""
    for attempt in range(RETRIES):
        if attempt:
            time.sleep(RETRY_PAUSE_SEC)
            print(f"  retry {attempt + 1}/{RETRIES}...", flush=True)
        code, body = probe_curl(url, token, auth=auth)
        if code is not None:
            return code, body, "curl"
        last_err = body
        code, body = probe_httpx(url, token, auth=auth)
        if code is not None:
            return code, body, "httpx"
        last_err = body or last_err
    return None, last_err, ""


def classify(code: int | None, body: str) -> str:
    if code is None:
        return "fail"
    if 200 <= code < 300:
        return "ok"
    if code == 429:
        return "rate_limit"
    if code == 401 and "withdrawn" in body.lower():
        return "token_revoked"
    if code == 401:
        return "unauthorized"
    if code == 403:
        return "forbidden"
    return "warn"


def main() -> int:
    token = require_token()
    env = env_file_used()
    print(f"Token: {env or '(unknown)'} ({len(token)} chars)\n")

    print(f"[advert-api] GET {ADVERT_URL}")
    code, body, transport = probe_with_retries(ADVERT_URL, token, auth=True)
    status = classify(code, body)
    advert_ok = status in ("ok", "rate_limit")

    if status == "token_revoked":
        print(f"  FAIL HTTP 401: token withdrawn — create new token in WB seller cabinet\n")
        print("Update WB_API_TOKEN in wb_advert_probe\\.env (do not commit to git).")
        return 1
    if status == "unauthorized":
        print(f"  FAIL HTTP 401 via {transport}: {body[:120]}\n")
        print("Check WB_API_TOKEN in wb_advert_probe\\.env")
        return 1
    if status == "ok":
        print(f"  OK HTTP {code} via {transport}: {body[:100]}\n")
    elif status == "rate_limit":
        print(f"  OK host reachable via {transport}, HTTP 429 - wait 10 min\n")
    elif status == "fail":
        print(f"  FAIL after {RETRIES} tries: {body[:120]}\n")
    else:
        print(f"  WARN HTTP {code}: {body[:120]}\n")

    if not advert_ok:
        print(f"[analytics-api] GET {ANALYTICS_URL}")
        acode, abody = probe_curl(ANALYTICS_URL, token, auth=False)
        if acode in (401, 403):
            print(f"  OK TLS HTTP {acode} - internet works, advert-api SSL is intermittent\n")
        elif acode is None:
            print(f"  FAIL: {abody[:80]}\n")
        else:
            print(f"  HTTP {acode}\n")

    if advert_ok:
        print("Ready: .\\run_sync_pilot.ps1 -ResolveOnly")
        return 0

    print("advert-api still down (intermittent SSL to advert-api.wildberries.ru).")
    print("This flips OK/FAIL every few minutes on some networks - keep retrying check_api.")
    print()
    print("Try: wait 5-10 min | mobile hotspot | disable VPN/antivirus HTTPS scan")
    print("Progress in CSV is safe - resume when check shows OK.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
