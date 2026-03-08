from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RuleItem(BaseModel):
    id: int
    intent: str
    action_type: str
    min_confidence: float
    requires_approval: bool
    is_active: bool
    description: str | None
    created_at: datetime
    updated_at: datetime


class RuleListResponse(BaseModel):
    items: list[RuleItem]
    count: int


class RuleUpdateRequest(BaseModel):
    min_confidence: float = Field(ge=0.0, le=1.0)
    requires_approval: bool
    is_active: bool


class RuleMutationResponse(BaseModel):
    status: str
    rule: RuleItem


class RuleBulkUpdateItem(BaseModel):
    id: int
    min_confidence: float = Field(ge=0.0, le=1.0)
    requires_approval: bool
    is_active: bool


class RuleBulkUpdateRequest(BaseModel):
    rules: list[RuleBulkUpdateItem] = Field(min_length=1, max_length=200)


class RuleBulkUpdateResponse(BaseModel):
    status: str
    updated_count: int
    rules: list[RuleItem]
