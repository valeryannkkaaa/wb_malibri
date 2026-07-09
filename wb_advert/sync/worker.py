from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from wb_advert.client.promotion import PromotionClient
from wb_advert.constants import PENDING_NM_PREFIX
from wb_advert.import_data.csv_loader import lookup_nm_id_for_campaign
from wb_advert.schemas.sync import KeywordMetrics, SyncCampaignResult, SyncProfileResult
from wb_advert.storage.pilot_store import load_config
from wb_advert.sync.mappers import map_normquery_stats


class SyncWorker:
    """Phase 0 sync: normquery stats + CTR/CPC (TZ §5.2)."""

    def __init__(self, promotion: PromotionClient | None = None, pilot_csv: Path | None = None) -> None:
        self.promotion = promotion or PromotionClient()
        self.pilot_csv = pilot_csv or (Path(__file__).resolve().parents[2] / "data" / "pilot" / "pilot_skus.csv")

    def resolve_nm_id(self, advert_id: int, *, allow_api: bool = True) -> int | None:
        cached = lookup_nm_id_for_campaign(advert_id, self.pilot_csv)
        if cached:
            print(f"  -> nm_id from pilot_skus.csv: {cached}", flush=True)
            return cached

        if not allow_api:
            return None

        print("  -> get campaign detail (nm_id) via API...", flush=True)
        detail = self.promotion.get_advert(advert_id)
        if not detail.ok:
            print(f"     failed HTTP {detail.status} (rate limit? use --nm-id or fill pilot_skus.csv)", flush=True)
            return None
        ids = self.promotion.extract_nm_ids_from_detail(detail.json())
        if ids:
            print(f"     nm_id={ids[0]}", flush=True)
            return ids[0]
        return None

    def _fetch_keywords(
        self,
        advert_id: int,
        nm_id: int,
        begin: date,
        end: date,
    ) -> tuple[list[KeywordMetrics], list[str]]:
        errors: list[str] = []
        print(f"  -> normquery/stats (nm_id={nm_id})...", flush=True)
        stats = self.promotion.normquery_stats(advert_id, nm_id, begin, end)
        if not stats.ok:
            detail = stats.error or stats.body[:120]
            errors.append(f"normquery_stats: HTTP {stats.status} {detail}")
            return [], errors
        print(f"     HTTP {stats.status}", flush=True)

        print(f"  -> normquery/get-bids (nm_id={nm_id})...", flush=True)
        bids = self.promotion.normquery_get_bids(advert_id, nm_id)
        if not bids.ok:
            errors.append(f"normquery_get_bids: HTTP {bids.status} {bids.body[:120]}")
        else:
            print(f"     HTTP {bids.status}", flush=True)

        keywords = map_normquery_stats(stats.json(), bids.json() if bids.ok else None)
        if stats.ok and not keywords:
            errors.append("normquery_stats: HTTP 200 but 0 keywords in period")
        return keywords, errors

    def sync_campaign(
        self,
        advert_id: int,
        nm_id: int | None = None,
        *,
        try_resolve_nm: bool = True,
        with_fullstats: bool = False,
    ) -> tuple[SyncCampaignResult, list[KeywordMetrics]]:
        result = SyncCampaignResult(wb_campaign_id=advert_id)
        errors: list[str] = []

        if nm_id is None and try_resolve_nm:
            nm_id = self.resolve_nm_id(advert_id, allow_api=True)
        elif nm_id is None and not try_resolve_nm:
            nm_id = self.resolve_nm_id(advert_id, allow_api=False)

        if not nm_id:
            errors.append(
                f"nm_id unknown for campaign {advert_id} — "
                f"run: python -m scripts.resolve_nm --advert-id {advert_id} "
                f"or sync with --nm-id <nm_id>"
            )

        end = date.today()
        begin = end - timedelta(days=7)

        keywords: list[KeywordMetrics] = []
        if nm_id:
            result.nm_ids = [nm_id]
            keywords, kw_errors = self._fetch_keywords(advert_id, nm_id, begin, end)
            errors.extend(kw_errors)
            result.keywords_updated = len(keywords)

        if with_fullstats:
            print("  -> fullstats...", flush=True)
            fs = self.promotion.fullstats(advert_id, begin, end)
            result.fullstats_ok = fs.ok
            if fs.ok:
                print(f"     HTTP {fs.status}", flush=True)
            else:
                errors.append(f"fullstats: HTTP {fs.status} {fs.body[:120]}")
        elif self._fullstats_enabled():
            print("  -> fullstats skipped (not scheduled this run)", flush=True)

        result.errors = errors
        return result, keywords

    @staticmethod
    def _fullstats_enabled() -> bool:
        config = load_config()
        if config.get("token_type") == "personal":
            return True
        sync_cfg = config.get("sync") or {}
        return bool(sync_cfg.get("fullstats_enabled"))

    def sync_profile(
        self,
        nm_id_label: str,
        wb_campaign_id: int,
        resolved_nm_id: int | None = None,
        *,
        try_resolve_nm: bool = True,
        with_fullstats: bool = False,
    ) -> SyncProfileResult:
        campaign, keywords = self.sync_campaign(
            wb_campaign_id,
            resolved_nm_id,
            try_resolve_nm=try_resolve_nm,
            with_fullstats=with_fullstats,
        )
        resolved = campaign.nm_ids[0] if campaign.nm_ids else None

        return SyncProfileResult(
            nm_id=str(resolved) if resolved else nm_id_label,
            wb_campaign_id=wb_campaign_id,
            resolved_nm_id=resolved,
            synced_at=datetime.now(timezone.utc),
            campaigns=[campaign],
            keywords=keywords,
            errors=campaign.errors,
        )

    @staticmethod
    def pending_nm(advert_id: int) -> str:
        return f"{PENDING_NM_PREFIX}{advert_id}"
