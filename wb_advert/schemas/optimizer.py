from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class DecisionSuggestion(BaseModel):
    keyword: str
    action: str
    reason_code: str
    reason_text: str
    before_state: dict = Field(default_factory=dict)
    after_state: dict = Field(default_factory=dict)


class OptimizeResult(BaseModel):
    advert_id: int
    nm_id: str
    mode: str = "suggest-only"
    decided_at: datetime
    skipped_reason: str | None = None
    suggestions: list[DecisionSuggestion] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
