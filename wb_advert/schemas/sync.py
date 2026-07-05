from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class KeywordMetrics(BaseModel):
    keyword: str
    shows: int = 0
    clicks: int = 0
    spend_kopecks: int = 0
    orders: int = 0
    ctr_calculated: float | None = None
    cpc_calculated_kopecks: int | None = None
    current_bid_kopecks: int | None = None
    status: str = "pending_100_shows"


class SyncCampaignResult(BaseModel):
    wb_campaign_id: int
    nm_ids: list[int] = Field(default_factory=list)
    wb_status: str | None = None
    fullstats_ok: bool = False
    keywords_updated: int = 0
    errors: list[str] = Field(default_factory=list)


class SyncProfileResult(BaseModel):
    nm_id: str
    wb_campaign_id: int
    resolved_nm_id: int | None = None
    synced_at: datetime
    campaigns: list[SyncCampaignResult] = Field(default_factory=list)
    keywords: list[KeywordMetrics] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
