from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TaskItem(BaseModel):
    id: int
    email_id: int
    title: str
    description: str | None
    due_text: str | None
    status: str
    created_at: datetime


class TaskListResponse(BaseModel):
    items: list[TaskItem]
    count: int

