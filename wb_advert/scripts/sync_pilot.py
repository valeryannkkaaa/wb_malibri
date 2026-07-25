#!/usr/bin/env python
"""Resolve nm_ids + sync all pilot campaigns; update primary keywords in CSV."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from wb_advert.client.base import WbHttpClient  # noqa: E402
from wb_advert.client.promotion import PromotionClient  # noqa: E402
from wb_advert.config import require_token, settings, env_file_used  # noqa: E402
from wb_advert.constants import PENDING_NM_PREFIX  # noqa: E402
from wb_advert.import_data.csv_loader import (  # noqa: E402
    apply_nm_id_mapping,
    load_pilot_skus,
    update_primary_keywords,
)
from wb_advert.storage.keywords_store import campaign_keywords_synced_at, save_keywords  # noqa: E402
from wb_advert.sync.metrics import pick_primary_keyword  # noqa: E402
from wb_advert.sync.rotate import pick_rotate_batch  # noqa: E402
from wb_advert.sync.worker import SyncWorker  # noqa: E402

DEFAULT_PAUSE_SEC = 25.0

_ATTEMPT_FIELDS = ("wb_campaign_id", "nm_id", "keywords", "errors")


def merge_campaign_row(prev_row: dict, attempt_row: dict, *, now: str) -> dict:
    """Merge one campaign row: success replaces all; failure updates only the attempt."""
    if attempt_row.get("keywords", 0) > 0:
        return {**prev_row, **attempt_row, "last_attempt_at": now, "synced_at": now}
    merged = dict(prev_row)
    for key in _ATTEMPT_FIELDS:
        if key in attempt_row:
            merged[key] = attempt_row[key]
    merged["last_attempt_at"] = now
    return merged


def _has_429(errors: list[str]) -> bool:
    return any("429" in e for e in errors)


def load_sync_report(report_path: Path) -> dict:
    if not report_path.is_file():
        return {}
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_synced_from_report(report_path: Path) -> dict[int, dict]:
    data = load_sync_report(report_path)
    out: dict[int, dict] = {}
    for row in data.get("campaigns") or []:
        aid = row.get("wb_campaign_id")
        if aid and row.get("keywords", 0) > 0:
            out[int(aid)] = row
    return out


def merge_report(report_path: Path, new_campaigns: list[dict]) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    prev = load_sync_report(report_path)
    by_id = {int(c["wb_campaign_id"]): c for c in prev.get("campaigns") or [] if c.get("wb_campaign_id")}
    for row in new_campaigns:
        cid = int(row["wb_campaign_id"])
        prev_row = by_id.get(cid, {})
        by_id[cid] = merge_campaign_row(prev_row, row, now=now)
    keywords_map = dict(prev.get("primary_keywords") or {})
    for row in by_id.values():
        if row.get("top_keyword"):
            keywords_map[str(row["nm_id"])] = row["top_keyword"]
    return {
        "synced_at": now,
        "campaigns": sorted(by_id.values(), key=lambda c: c["wb_campaign_id"]),
        "primary_keywords": keywords_map,
    }


def pick_rotate_skus(ready: list, report_path: Path, limit: int = 1) -> list:
    """Pick campaign(s) least recently attempted for incremental scheduler runs."""
    data_dir = report_path.parent
    report = load_sync_report(report_path)
    by_advert = {int(c["wb_campaign_id"]): c for c in report.get("campaigns") or [] if c.get("wb_campaign_id")}
    return pick_rotate_batch(
        ready,
        entity_id=lambda sku: sku.wb_campaign_search,
        report_by_id=by_advert,
        canonical_synced_at=lambda advert_id: campaign_keywords_synced_at(advert_id, data_dir),
        limit=limit,
    )


def should_fetch_fullstats(advert_id: int, report_path: Path, *, min_hours: int = 24) -> bool:
    from wb_advert.storage.pilot_store import load_config

    config = load_config(report_path.parent)
    sync_cfg = config.get("sync") or {}
    if not sync_cfg.get("fullstats_enabled", config.get("token_type") == "personal"):
        return False
    min_hours = int(sync_cfg.get("fullstats_min_hours") or 24)
    data = load_sync_report(report_path)
    if not data:
        return True
    for row in data.get("campaigns") or []:
        if int(row.get("wb_campaign_id") or 0) != advert_id:
            continue
        if not row.get("fullstats_ok"):
            return True
        ts = row.get("fullstats_at") or campaign_keywords_synced_at(advert_id, report_path.parent)
        if not ts:
            return True
        try:
            then = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - then).total_seconds() / 3600
            return age_h >= min_hours
        except ValueError:
            return True
    return True


def resolve_pending(
    data_dir: Path,
    pause: float,
    max_retries: int,
    *,
    limit: int | None = None,
) -> dict[int, int]:
    skus_path = data_dir / "pilot_skus.csv"
    pending = [
        s.wb_campaign_search
        for s in load_pilot_skus(skus_path)
        if (s.nm_id or "").startswith(PENDING_NM_PREFIX)
    ]
    if not pending:
        print("All pilot nm_ids already resolved.", flush=True)
        return {}

    batch = pending if limit is None else pending[:limit]
    print(
        f"Resolving {len(batch)} of {len(pending)} pending nm_id(s), pause {pause}s...",
        flush=True,
    )
    http = WbHttpClient(pause_sec=pause, max_retries=max_retries)
    client = PromotionClient(http=http)
    mapping: dict[int, int] = {}
    for i, advert_id in enumerate(batch):
        if i:
            time.sleep(pause)
        print(f"  [{i + 1}/{len(batch)}] advert {advert_id}...", flush=True)
        detail = client.get_advert(advert_id)
        if not detail.ok:
            err = (detail.error or detail.body[:80] if detail.body else "")[:80]
            print(
                f"     failed HTTP {detail.status} ({err}) - wait 10 min, test curl balance, re-run",
                flush=True,
            )
            break
        ids = client.extract_nm_ids_from_detail(detail.json())
        if not ids:
            print("     no nm_id in response", flush=True)
            continue
        mapping[advert_id] = ids[0]
        print(f"     nm_id={ids[0]}", flush=True)

    if mapping:
        updated = apply_nm_id_mapping(data_dir, mapping)
        print(f"CSV updated: {', '.join(updated)}", flush=True)
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync all pilot campaigns (resumable)")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--resolve-nm", action="store_true", help="Resolve PENDING nm_ids first")
    parser.add_argument("--resolve-only", action="store_true", help="Only resolve nm_ids, no sync")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max per run (resolve-only default: 1; sync default: all pending in queue)",
    )
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SEC, help="Pause between campaigns/calls")
    parser.add_argument("--max-retries", type=int, default=2, help="HTTP retries per call (batch: keep low)")
    parser.add_argument(
        "--skip-synced",
        action="store_true",
        default=True,
        help="Skip campaigns already OK in last_sync_report.json (default: on)",
    )
    parser.add_argument(
        "--force-all",
        action="store_true",
        help="Re-sync all campaigns (disables --skip-synced)",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Sync oldest-updated campaign(s) — for scheduled incremental runs",
    )
    parser.add_argument(
        "--with-fullstats",
        action="store_true",
        help="Force fullstats on this run",
    )
    parser.add_argument("--report", type=Path, default=None, help="JSON report path")
    args = parser.parse_args()
    if args.force_all:
        args.skip_synced = False

    require_token()
    env = env_file_used()
    if env:
        print(f"Token from {env}", flush=True)
    data_dir = args.data_dir or (ROOT / settings.pilot_data_path).resolve()
    report_path = args.report or (data_dir / "last_sync_report.json")

    if args.resolve_nm or args.resolve_only:
        limit = args.limit
        if limit is None and args.resolve_only:
            limit = 1
        resolve_pending(data_dir, args.pause, args.max_retries, limit=limit)
    if args.resolve_only:
        return 0

    skus = load_pilot_skus(data_dir / "pilot_skus.csv")
    ready = [s for s in skus if s.nm_id and not s.nm_id.startswith(PENDING_NM_PREFIX)]
    pending = [s for s in skus if s.nm_id.startswith(PENDING_NM_PREFIX)]
    already_ok = load_synced_from_report(report_path) if args.skip_synced and not args.rotate else {}
    if args.rotate:
        lim = args.limit if args.limit is not None else 1
        to_sync = pick_rotate_skus(ready, report_path, lim)
        skipped = 0
    else:
        to_sync = [s for s in ready if s.wb_campaign_search not in already_ok]
        if args.limit is not None and not args.resolve_nm and not args.resolve_only:
            to_sync = to_sync[: args.limit]
        skipped = len(already_ok)

    if pending:
        print(f"{len(pending)} campaign(s) still PENDING nm_id - re-run with -ResolveNm after cooldown", flush=True)

    http = WbHttpClient(pause_sec=args.pause, max_retries=args.max_retries)
    worker = SyncWorker(promotion=PromotionClient(http=http), pilot_csv=data_dir / "pilot_skus.csv")

    batch_campaigns: list[dict] = []
    nm_to_keyword: dict[str, str] = {}
    failures = 0
    stopped_429 = False

    print(f"Sync queue: {len(to_sync)} campaign(s)" + (" (rotate)" if args.rotate else ""), flush=True)
    for i, sku in enumerate(to_sync):
        advert_id = sku.wb_campaign_search
        if stopped_429:
            break
        if i:
            time.sleep(args.pause)
        nm_id = int(sku.nm_id)
        want_fs = args.with_fullstats or should_fetch_fullstats(advert_id, report_path)
        print(f"\n[{i + 1}/{len(to_sync)}] Sync {advert_id} (nm_id={nm_id})...", flush=True)
        result = worker.sync_profile(
            nm_id_label=sku.nm_id,
            wb_campaign_id=advert_id,
            resolved_nm_id=nm_id,
            try_resolve_nm=False,
            with_fullstats=want_fs,
        )
        fs_ok = bool(result.campaigns and result.campaigns[0].fullstats_ok)
        entry = {
            "wb_campaign_id": advert_id,
            "nm_id": nm_id,
            "keywords": len(result.keywords),
            "errors": result.errors,
            "top_keyword": None,
            "fullstats_ok": fs_ok,
        }
        if fs_ok:
            entry["fullstats_at"] = datetime.now(timezone.utc).isoformat()
        if result.keywords:
            primary = pick_primary_keyword(result.keywords)
            if primary:
                nm_to_keyword[str(nm_id)] = primary
                entry["top_keyword"] = primary
                top = next((k for k in result.keywords if k.keyword == primary), result.keywords[0])
                entry["top_stats"] = {
                    "shows": top.shows,
                    "ctr": top.ctr_calculated,
                    "orders": top.orders,
                }
            save_keywords(advert_id, nm_id, result.keywords, data_dir=data_dir)
            print(f"  -> {len(result.keywords)} keywords (saved JSON)", flush=True)
        else:
            failures += 1
            print("  -> FAILED", flush=True)
            if _has_429(result.errors):
                stopped_429 = True
                print("  -> 429: stopping batch (wait 10 min, then re-run without -ResolveNm)", flush=True)
        batch_campaigns.append(entry)

    if nm_to_keyword:
        updated = update_primary_keywords(data_dir, nm_to_keyword)
        print(f"\nPrimary keywords updated in: {', '.join(updated)}", flush=True)

    report = merge_report(report_path, batch_campaigns)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {report_path}", flush=True)

    total_ok = len(already_ok) + sum(1 for c in batch_campaigns if c.get("keywords", 0) > 0)
    print(
        f"\nDone: {total_ok}/{len(ready)} campaigns with keywords "
        f"(this run: +{sum(1 for c in batch_campaigns if c.get('keywords', 0) > 0)}, "
        f"skipped {skipped}, failed {failures})",
        flush=True,
    )
    if pending or failures or stopped_429:
        print("\nResume when rate limit cools (~10 min):", flush=True)
        if pending:
            print("  .\\run_sync_pilot.ps1 -ResolveOnly          # 1 nm_id per run", flush=True)
        print("  .\\run_sync_pilot.ps1 -Pause 30               # sync keywords", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
