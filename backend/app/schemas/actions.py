from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ActionPlanRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=200)
    statuses: list[str] = Field(default_factory=lambda: ["classified"])


class ActionPlanResponse(BaseModel):
    status: str
    matched: int
    planned: int
    skipped: int
    failed: int


class ActionExecuteRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=200)
    statuses: list[str] = Field(default_factory=lambda: ["pending", "retry_pending"])


class ActionExecuteResponse(BaseModel):
    status: str
    matched: int
    executed: int
    failed: int


class ActionApprovalRequest(BaseModel):
    execute_now: bool = True


class ActionRejectRequest(BaseModel):
    reason: str | None = None


class ActionRequeueRequest(BaseModel):
    reset_attempts: bool = False


class ActionItem(BaseModel):
    id: int
    email_id: int
    intent: str
    action_type: str
    status: str
    idempotency_key: str | None
    attempts: int
    next_attempt_at: datetime | None
    error_message: str | None
    created_at: datetime
    executed_at: datetime | None
    dead_lettered_at: datetime | None
    payload: dict[str, Any] | list[Any] | None


class ActionListResponse(BaseModel):
    items: list[ActionItem]
    count: int


class ActionMutationResponse(BaseModel):
    status: str
    action: ActionItem


class ActionEventItem(BaseModel):
    id: int
    action_id: int
    event_type: str
    status: str | None
    message: str | None
    details: dict[str, Any] | list[Any] | None
    created_at: datetime


class ActionEventListResponse(BaseModel):
    items: list[ActionEventItem]
    count: int
