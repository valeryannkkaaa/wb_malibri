"""Apply optimizer suggestions to Wildberries API (phase 2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from wb_advert.client.promotion import PromotionClient
from wb_advert.executor.guards import APPLY_ACTIONS, get_apply_settings, validate_bid_kopecks
from wb_advert.schemas.optimizer import DecisionSuggestion, OptimizeResult
from wb_advert.storage.apply_log import append_apply_record


@dataclass
class ApplyItemResult:
    advert_id: int
    nm_id: str
    keyword: str
    action: str
    ok: bool
    dry_run: bool = False
    http_status: int | None = None
    detail: str = ""


@dataclass
class ApplyBatchResult:
    dry_run: bool
    can_apply: bool
    blocked_reasons: list[str] = field(default_factory=list)
    items: list[ApplyItemResult] = field(default_factory=list)

    @property
    def applied_count(self) -> int:
        return sum(1 for i in self.items if i.ok and not i.dry_run)

    @property
    def failed_count(self) -> int:
        return sum(1 for i in self.items if not i.ok)


def _apply_one(
    client: PromotionClient,
    result: OptimizeResult,
    suggestion: DecisionSuggestion,
    *,
    dry_run: bool,
) -> ApplyItemResult:
    advert_id = int(result.advert_id)
    nm_id = int(result.nm_id) if result.nm_id else 0
    action = suggestion.action
    keyword = suggestion.keyword
    after = suggestion.after_state or {}

    if action not in APPLY_ACTIONS:
        return ApplyItemResult(
            advert_id=advert_id,
            nm_id=result.nm_id,
            keyword=keyword,
            action=action,
            ok=False,
            dry_run=dry_run,
            detail="action not applicable via API",
        )

    if not nm_id:
        return ApplyItemResult(
            advert_id=advert_id,
            nm_id=result.nm_id,
            keyword=keyword,
            action=action,
            ok=False,
            dry_run=dry_run,
            detail="nm_id missing",
        )

    if action in ("raise_bid", "lower_bid"):
        new_bid = after.get("bid_kopecks")
        if not new_bid:
            return ApplyItemResult(
                advert_id=advert_id,
                nm_id=result.nm_id,
                keyword=keyword,
                action=action,
                ok=False,
                dry_run=dry_run,
                detail="after_state.bid_kopecks missing",
            )
        err = validate_bid_kopecks(int(new_bid))
        if err:
            return ApplyItemResult(
                advert_id=advert_id,
                nm_id=result.nm_id,
                keyword=keyword,
                action=action,
                ok=False,
                dry_run=dry_run,
                detail=err,
            )
        if dry_run:
            return ApplyItemResult(
                advert_id=advert_id,
                nm_id=result.nm_id,
                keyword=keyword,
                action=action,
                ok=True,
                dry_run=True,
                detail=f"dry-run: bid → {int(new_bid)/100:.2f}₽",
            )
        resp = client.normquery_set_bids(advert_id, nm_id, keyword, int(new_bid))
        ok = resp.ok
        detail = (resp.body or resp.error or "")[:200]
        return ApplyItemResult(
            advert_id=advert_id,
            nm_id=result.nm_id,
            keyword=keyword,
            action=action,
            ok=ok,
            http_status=resp.status,
            detail=detail if not ok else f"bid → {int(new_bid)/100:.2f}₽",
        )

    if action == "exclude_keyword":
        if dry_run:
            return ApplyItemResult(
                advert_id=advert_id,
                nm_id=result.nm_id,
                keyword=keyword,
                action=action,
                ok=True,
                dry_run=True,
                detail="dry-run: exclude keyword",
            )
        resp = client.normquery_set_minus(advert_id, nm_id, [keyword])
        ok = resp.ok
        detail = (resp.body or resp.error or "")[:200]
        return ApplyItemResult(
            advert_id=advert_id,
            nm_id=result.nm_id,
            keyword=keyword,
            action=action,
            ok=ok,
            http_status=resp.status,
            detail=detail if not ok else "excluded",
        )

    return ApplyItemResult(
        advert_id=advert_id,
        nm_id=result.nm_id,
        keyword=keyword,
        action=action,
        ok=False,
        dry_run=dry_run,
        detail="unsupported action",
    )


def apply_optimizer_results(
    results: list[OptimizeResult],
    *,
    dry_run: bool = False,
    client: PromotionClient | None = None,
) -> ApplyBatchResult:
    settings = get_apply_settings()
    if not settings["can_apply"] and not dry_run:
        return ApplyBatchResult(
            dry_run=False,
            can_apply=False,
            blocked_reasons=settings["blocked_reasons"],
        )

    promo = client or PromotionClient()
    batch = ApplyBatchResult(
        dry_run=dry_run,
        can_apply=settings["can_apply"],
        blocked_reasons=settings["blocked_reasons"],
    )

    for result in results:
        for suggestion in result.suggestions:
            if suggestion.action not in APPLY_ACTIONS:
                continue
            item = _apply_one(promo, result, suggestion, dry_run=dry_run)
            batch.items.append(item)
            append_apply_record(
                {
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                    "dry_run": dry_run,
                    "advert_id": item.advert_id,
                    "nm_id": item.nm_id,
                    "keyword": item.keyword,
                    "action": item.action,
                    "ok": item.ok,
                    "http_status": item.http_status,
                    "detail": item.detail,
                    "reason_code": suggestion.reason_code,
                }
            )

    return batch
