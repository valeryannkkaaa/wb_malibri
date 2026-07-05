"""
Standalone WB Advert API probe — independent module for Phase 0 discovery.

Usage:
  set WB_API_TOKEN=...   (or copy .env.example → .env)
  python probe.py
  python probe.py --json report.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import httpx
from dotenv import load_dotenv

load_dotenv()

PROMOTION_BASE = "https://advert-api.wildberries.ru"
ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
MARKETPLACE_BASE = "https://marketplace-api.wildberries.ru"
CONTENT_BASE = "https://content-api.wildberries.ru"

# Endpoints grouped by MVP need (see docs/MVP_Phases_0-2_Requirements.md)
ENDPOINTS: list[dict[str, Any]] = [
    # Phase 0 — sync campaigns (count last: redundant + strict rate limit)
    {"group": "promotion", "name": "adverts_v2", "method": "GET", "path": "/api/advert/v2/adverts"},
    {"group": "promotion", "name": "balance", "method": "GET", "path": "/adv/v1/balance", "delay_after": 1.0},
    {"group": "promotion", "name": "fullstats_v3", "method": "GET", "path": "/adv/v3/fullstats", "params_builder": "fullstats", "delay_after": 7.0},
    # Phase 0 — keyword stats (needs advert_id from adverts_v2)
    {"group": "promotion", "name": "normquery_stats", "method": "POST", "path": "/adv/v0/normquery/stats", "body_builder": "normquery_stats"},
    {"group": "promotion", "name": "normquery_get_bids", "method": "POST", "path": "/adv/v0/normquery/get-bids", "body_builder": "normquery_bids"},
    {"group": "promotion", "name": "normquery_list", "method": "POST", "path": "/adv/v0/normquery/list", "body_builder": "normquery_list"},
    {"group": "promotion", "name": "bids_min", "method": "POST", "path": "/api/advert/v1/bids/min", "body_builder": "bids_min"},
    # Phase 1 — analytics (v3 sales funnel replaced deprecated v2 nm-report)
    {
        "group": "analytics",
        "name": "sales_funnel_v3",
        "method": "POST",
        "path": "/api/analytics/v3/sales-funnel/products",
        "body_builder": "sales_funnel_v3",
    },
    {
        "group": "analytics",
        "name": "stocks_report",
        "method": "POST",
        "path": "/api/analytics/v1/stocks-report/wb-warehouses",
        "body_builder": "stocks_report",
    },
    # FBS orders (marketplace scope) — for operational sync, not advert CTR
    {
        "group": "marketplace",
        "name": "orders_new",
        "method": "GET",
        "path": "/api/v3/orders/new",
    },
    {"group": "promotion", "name": "campaign_count", "method": "GET", "path": "/adv/v1/promotion/count", "delay_after": 1.0},
]


@dataclass
class ProbeResult:
    name: str
    group: str
    method: str
    path: str
    status: int | None
    ok: bool
    error: str | None = None
    sample_keys: list[str] = field(default_factory=list)
    sample: Any = None
    write_required: bool = False


def base_url(group: str) -> str:
    return {
        "promotion": PROMOTION_BASE,
        "analytics": ANALYTICS_BASE,
        "marketplace": MARKETPLACE_BASE,
        "content": CONTENT_BASE,
    }[group]


def headers(token: str) -> dict[str, str]:
    return {"Authorization": token, "Content-Type": "application/json"}


def sample_keys(obj: Any, limit: int = 12) -> list[str]:
    if isinstance(obj, dict):
        return list(obj.keys())[:limit]
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return list(obj[0].keys())[:limit]
    return []


def truncate_sample(obj: Any, max_items: int = 2) -> Any:
    if isinstance(obj, list):
        return obj[:max_items]
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= 8:
                out["..."] = f"{len(obj) - 8} more keys"
                break
            out[k] = truncate_sample(v, max_items) if isinstance(v, (list, dict)) else v
        return out
    return obj


@dataclass
class HttpOutcome:
    status: int | None
    text: str
    transport: str = "httpx"
    error: str | None = None

    def json(self) -> Any:
        return json.loads(self.text)


class WbAdvertProbe:
    def __init__(self, token: str, advert_id: int | None = None) -> None:
        self.token = token
        self._client = httpx.Client(timeout=60.0, http2=False)
        self._context: dict[str, Any] = {}
        if advert_id:
            self._context["advert_id"] = advert_id
        self._curl = shutil.which("curl.exe") or shutil.which("curl")

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        group: str,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | list | None = None,
    ) -> HttpOutcome:
        base = base_url(group) + path
        try:
            resp = self._client.request(
                method,
                base,
                headers=headers(self.token),
                params=params,
                json=json_body,
            )
            return HttpOutcome(status=resp.status_code, text=resp.text, transport="httpx")
        except httpx.HTTPError as exc:
            err = str(exc)
            if "SSL" in err or "EOF" in err:
                url = f"{base}?{urlencode(params, doseq=True)}" if params else base
                fallback = self._request_fallback(url, method, json_body)
                if fallback:
                    return fallback
            return HttpOutcome(status=None, text="", transport="httpx", error=err)

    def _request_fallback(
        self,
        url: str,
        method: str,
        json_body: dict | list | None,
    ) -> HttpOutcome | None:
        if self._curl:
            outcome = self._request_curl(url, method, json_body)
            if outcome:
                return outcome
        return self._request_urllib(url, method, json_body)

    def _request_curl(
        self,
        url: str,
        method: str,
        json_body: dict | list | None,
    ) -> HttpOutcome | None:
        if not self._curl:
            return None
        cmd = [
            self._curl,
            "-sS",
            "-w",
            "\n__HTTP__%{http_code}",
            "-H",
            f"Authorization: {self.token}",
            "-H",
            "Content-Type: application/json",
            "-X",
            method,
            url,
        ]
        if json_body is not None:
            cmd.extend(["-d", json.dumps(json_body)])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45, check=False)
            if proc.returncode != 0:
                return None
            raw = proc.stdout
            if "\n__HTTP__" not in raw:
                return None
            body, status_str = raw.rsplit("\n__HTTP__", 1)
            return HttpOutcome(status=int(status_str), text=body, transport="curl")
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def _request_urllib(
        self,
        url: str,
        method: str,
        json_body: dict | list | None,
    ) -> HttpOutcome | None:
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
        req = Request(
            url,
            data=data,
            method=method,
            headers=headers(self.token),
        )
        try:
            with urlopen(req, timeout=45) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                return HttpOutcome(status=resp.status, text=text, transport="urllib")
        except HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            return HttpOutcome(status=exc.code, text=text, transport="urllib")
        except URLError:
            return None

    def _extract_first_campaign(self, adverts_data: Any) -> dict | None:
        """Parse GET /api/advert/v2/adverts list response — pick active type 9 campaign."""
        if not isinstance(adverts_data, dict):
            return None

        candidates: list[tuple[int, str, int]] = []
        for block in adverts_data.get("adverts") or []:
            if int(block.get("type") or 0) != 9:
                continue
            status = int(block.get("status") or 0)
            items = block.get("advert_list") or block.get("advertList") or []
            for item in items:
                advert_id = item.get("advertId") or item.get("advert_id")
                if advert_id:
                    # status 9 = active campaigns (most relevant for pilot)
                    candidates.append((0 if status == 9 else 1, item.get("changeTime") or "", int(advert_id)))

        if candidates:
            candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
            return {"advert_id": candidates[0][2], "type": 9}

        for block in adverts_data.get("adverts") or []:
            for item in block.get("advert_list") or block.get("advertList") or []:
                advert_id = item.get("advertId") or item.get("advert_id")
                if advert_id:
                    return {"advert_id": int(advert_id), "type": block.get("type")}
        return None

    def _resolve_campaign_context(self, advert_id: int) -> None:
        self._context["advert_id"] = advert_id
        detail = self._fetch_adverts_detail(advert_id)
        if detail:
            self._context["nm_ids"] = detail.get("nm_ids") or []
            self._context["campaign_detail"] = detail.get("detail")
        else:
            self._context.setdefault("nm_ids", [])

    def _fetch_adverts_detail(self, advert_id: int) -> dict | None:
        for params in (
            {"ids": str(advert_id)},
            {"ids[]": str(advert_id)},
            {"id": str(advert_id)},
            {"id[]": str(advert_id)},
        ):
            resp = self._request(
                "promotion",
                "GET",
                "/api/advert/v2/adverts",
                params=params,
            )
            if resp.status != 200:
                continue
            data = resp.json()
            parsed = self._parse_advert_detail(data, advert_id)
            if parsed:
                return parsed
        return None

    def _parse_advert_detail(self, data: Any, advert_id: int) -> dict | None:
        if not isinstance(data, dict):
            return None
        adverts = data.get("adverts")
        if not adverts:
            return None

        blocks = adverts if isinstance(adverts, list) else [adverts]
        first: dict | None = None
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("advertId") in (advert_id, str(advert_id)):
                first = block
                break
            if block.get("nmSettings") or block.get("nms"):
                first = block
                break
        if first is None and blocks and isinstance(blocks[0], dict):
            first = blocks[0]

        if not isinstance(first, dict):
            return None

        nm_ids: list[int] = []
        for nm in first.get("nmSettings") or first.get("nms") or first.get("autoParams", {}).get("nms") or []:
            if isinstance(nm, dict):
                nid = nm.get("nm") or nm.get("nm_id") or nm.get("nmId")
                if nid:
                    nm_ids.append(int(nid))
            elif isinstance(nm, int):
                nm_ids.append(nm)
        return {"advert_id": advert_id, "nm_ids": nm_ids, "detail": first}

    def _harvest_nm_ids(self, endpoint_name: str, data: Any) -> None:
        found: list[int] = []
        if not isinstance(data, dict):
            return

        if endpoint_name == "normquery_get_bids":
            for bid in data.get("bids") or []:
                nid = bid.get("nm_id") or bid.get("nmId")
                if nid:
                    found.append(int(nid))
        elif endpoint_name == "normquery_stats":
            for block in data.get("stats") or []:
                nid = block.get("nm_id") or block.get("nmId")
                if nid:
                    found.append(int(nid))
                for row in block.get("stat") or block.get("stats") or []:
                    if isinstance(row, dict):
                        nid = row.get("nm_id") or row.get("nmId")
                        if nid:
                            found.append(int(nid))
        elif endpoint_name == "fullstats_v3":
            for day in data.get("days") or []:
                for app in day.get("apps") or []:
                    for sku in app.get("nms") or app.get("nm") or []:
                        if isinstance(sku, dict):
                            nid = sku.get("nmId") or sku.get("nm_id") or sku.get("nm")
                            if nid:
                                found.append(int(nid))

        if found:
            merged = list(dict.fromkeys([*(self._context.get("nm_ids") or []), *found]))
            self._context["nm_ids"] = merged

    def _build_body(self, builder: str) -> dict | list | None:
        ctx = self._context
        advert_id = ctx.get("advert_id")
        nm_id = (ctx.get("nm_ids") or [0])[0] if ctx.get("nm_ids") else 0
        today = date.today()
        week_ago = today - timedelta(days=7)

        if builder == "normquery_stats":
            if not advert_id:
                return None
            return {
                "from": week_ago.isoformat(),
                "to": today.isoformat(),
                "items": [{"advert_id": advert_id, "nm_id": nm_id or 0}],
            }
        if builder == "normquery_bids":
            if not advert_id:
                return None
            return {"items": [{"advert_id": advert_id, "nm_id": nm_id or 0}]}
        if builder == "normquery_list":
            if not advert_id:
                return None
            return {"items": [{"advertId": advert_id, "nmId": nm_id or 0}]}
        if builder == "bids_min":
            if not advert_id or not nm_id:
                return None
            return {"advert_id": advert_id, "nm_id": nm_id, "payment_type": "cpm"}
        if builder == "sales_funnel_v3":
            body: dict[str, Any] = {
                "selectedPeriod": {"start": week_ago.isoformat(), "end": today.isoformat()},
                "limit": 10,
                "offset": 0,
            }
            if nm_id:
                body["nmIds"] = [nm_id]
            return body
        if builder == "stocks_report":
            return {
                "currentPeriod": {"start": week_ago.isoformat(), "end": today.isoformat()},
                "stockType": "",
                "skipDeletedNm": True,
                "limit": 10,
                "offset": 0,
            }
        return None

    def _build_params(self, builder: str) -> dict | None:
        if builder == "fullstats":
            advert_id = self._context.get("advert_id")
            if not advert_id:
                return None
            today = date.today()
            week_ago = today - timedelta(days=7)
            return {
                "ids": str(advert_id),
                "beginDate": week_ago.isoformat(),
                "endDate": today.isoformat(),
            }
        return None

    def probe_endpoint(self, spec: dict[str, Any]) -> ProbeResult:
        name = spec["name"]
        group = spec["group"]
        method = spec["method"]
        path = spec["path"]
        read_only_builders = {
            "normquery_stats",
            "normquery_bids",
            "normquery_list",
            "bids_min",
            "sales_funnel_v3",
            "stocks_report",
        }
        write_required = method in ("POST", "PATCH", "PUT", "DELETE") and spec.get("body_builder") not in read_only_builders

        params = spec.get("params")
        if spec.get("params_builder"):
            params = self._build_params(spec["params_builder"])
            if params is None:
                return ProbeResult(
                    name=name,
                    group=group,
                    method=method,
                    path=path,
                    status=None,
                    ok=False,
                    error="skipped: need advert_id from adverts_v2 first",
                )

        json_body = None
        if spec.get("body_builder"):
            json_body = self._build_body(spec["body_builder"])
            if json_body is None:
                return ProbeResult(
                    name=name,
                    group=group,
                    method=method,
                    path=path,
                    status=None,
                    ok=False,
                    error="skipped: need advert_id/nm_id from adverts_v2 first",
                )

        try:
            resp = self._request(group, method, path, params=params, json_body=json_body)
            if resp.error and resp.status is None:
                return ProbeResult(
                    name=name,
                    group=group,
                    method=method,
                    path=path,
                    status=None,
                    ok=False,
                    error=f"{resp.error} (tip: try curl or Python 3.11/3.12 if SSL persists)",
                )

            ok = resp.status is not None and 200 <= resp.status < 300
            err = None
            data = None
            if ok:
                try:
                    data = resp.json()
                except Exception:
                    data = resp.text[:500]
                if name == "adverts_v2" and isinstance(data, dict):
                    camp = self._extract_first_campaign(data)
                    if camp:
                        self._resolve_campaign_context(camp["advert_id"])
                    elif data.get("all"):
                        self._context["adverts_parse_note"] = (
                            f"list has {data.get('all')} campaigns but no advert_list in response; use --advert-id"
                        )
                elif ok and isinstance(data, dict):
                    self._harvest_nm_ids(name, data)
            else:
                err = resp.text[:300]
            result = ProbeResult(
                name=name,
                group=group,
                method=method,
                path=path,
                status=resp.status,
                ok=ok,
                error=err,
                sample_keys=sample_keys(data) if data else [],
                sample=truncate_sample(data) if data else None,
                write_required=write_required,
            )
            if ok and resp.transport != "httpx":
                result.error = f"via {resp.transport}"
            return result
        except httpx.HTTPError as exc:
            return ProbeResult(
                name=name,
                group=group,
                method=method,
                path=path,
                status=None,
                ok=False,
                error=str(exc),
            )

    def run_all(self) -> list[ProbeResult]:
        if self._context.get("advert_id") and "nm_ids" not in self._context:
            self._resolve_campaign_context(int(self._context["advert_id"]))
            time.sleep(1.0)

        results: list[ProbeResult] = []
        for spec in ENDPOINTS:
            results.append(self.probe_endpoint(spec))
            time.sleep(float(spec.get("delay_after", 1.2)))
        return results


def print_report(results: list[ProbeResult], context: dict[str, Any]) -> None:
    print("\n=== WB Advert API Probe ===\n")
    if context.get("advert_id"):
        print(f"Sample campaign: advert_id={context['advert_id']}, nm_ids={context.get('nm_ids')}\n")
    elif context.get("adverts_parse_note"):
        print(f"Note: {context['adverts_parse_note']}\n")

    ok_r = [r for r in results if r.ok]
    fail_r = [r for r in results if not r.ok]

    print(f"OK: {len(ok_r)} / {len(results)}\n")
    for r in results:
        mark = "OK" if r.ok else "FAIL"
        print(f"  [{mark}] {r.group:12} {r.method:4} {r.path}")
        if r.status:
            print(f"         HTTP {r.status}")
        if r.error:
            print(f"         {r.error[:120]}")
        if r.ok and r.sample_keys:
            print(f"         keys: {', '.join(r.sample_keys)}")
        if r.ok and r.error and r.error.startswith("via "):
            print(f"         {r.error}")

    print("\n--- MVP mapping ---")
    phase0_read = ["campaign_count", "adverts_v2", "normquery_stats", "fullstats_v3", "balance"]
    phase0_ok = [r.name for r in ok_r if r.name in phase0_read]
    print(f"Phase 0 read endpoints working: {phase0_ok}")
    missing = [n for n in phase0_read if n not in phase0_ok]
    if missing:
        print(f"Phase 0 blocked/missing: {missing}")

    if fail_r:
        rate_limited = [
            r.name for r in fail_r if r.error and "too many requests" in r.error.lower()
        ]
        if rate_limited:
            print(f"\nRate limited (429), retry in 1-2 min: {', '.join(rate_limited)}")
        hard_fail = [r for r in fail_r if r.name not in rate_limited]
        if hard_fail:
            print("\n--- Other failures ---")
            for r in hard_fail:
                print(f"  {r.name}: {r.error or 'unknown'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe WB Advert API with read token")
    parser.add_argument("--json", help="Write full JSON report to file")
    parser.add_argument("--advert-id", type=int, help="Pilot campaign ID for dependent checks")
    args = parser.parse_args()

    token = os.environ.get("WB_API_TOKEN", "").strip()
    if not token:
        print("Set WB_API_TOKEN in .env or environment", file=sys.stderr)
        return 1

    probe = WbAdvertProbe(token, advert_id=args.advert_id)
    try:
        results = probe.run_all()
        print_report(results, probe._context)

        if args.json:
            from pathlib import Path

            out = Path(args.json)
            payload = {
                "context": {
                    k: v for k, v in probe._context.items() if k != "campaign_detail"
                },
                "results": [asdict(r) for r in results],
            }
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\nReport saved: {out}")
    finally:
        probe.close()

    return 0 if any(r.ok for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
