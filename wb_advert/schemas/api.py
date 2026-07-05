from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProductSummary(BaseModel):
    advert_id: int
    nm_id: str
    primary_keyword: str | None = None
    target_grade: str = "top_1_3"
    schedule: str = "always_on"
    notes: str | None = None
    keyword_count: int = 0
    keywords_saved: bool = False
    has_economics: bool = False
    max_drr_pct: str = "15"
    top_stats: dict | None = None
    sync_errors: list[str] = Field(default_factory=list)


class DashboardResponse(BaseModel):
    optimizer_mode: str
    synced_at: datetime | str | None = None
    product_count: int
    total_keywords: int
    total_orders_7d: int
    with_economics: int
    keywords_saved: int
    products: list[ProductSummary]


class ProductDetailResponse(ProductSummary):
    keywords: list[dict] = Field(default_factory=list)
    keywords_synced_at: str | None = None
    notes: str | None = None
