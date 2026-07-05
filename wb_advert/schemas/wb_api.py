from __future__ import annotations

from pydantic import BaseModel, Field


class PilotSkuRow(BaseModel):
    nm_id: str
    product_name: str = ""
    project_id: int = 1
    wb_campaign_search: int
    wb_campaign_unified: int | None = None
    schedule: str = "always_on"
    primary_keyword: str = ""
    target_grade: str = "top_1_3"
    notes: str = ""


class NormqueryStatRow(BaseModel):
    norm_query: str = Field(alias="norm_query", default="")
    views: int = 0
    clicks: int = 0
    orders: int = 0
    cpc: float = 0
    cpm: float = 0
    ctr: float = 0
    avg_pos: float = 0
    atbs: int = 0

    model_config = {"populate_by_name": True}
