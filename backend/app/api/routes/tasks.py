from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.task import Task
from app.schemas.tasks import TaskItem, TaskListResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskListResponse, status_code=status.HTTP_200_OK)
def list_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> TaskListResponse:
    statement = select(Task).order_by(Task.created_at.desc(), Task.id.desc()).limit(limit)
    if status_filter:
        statement = statement.where(Task.status == status_filter)

    tasks = list(db.scalars(statement))
    items = [
        TaskItem(
            id=task.id,
            email_id=task.email_id,
            title=task.title,
            description=task.description,
            due_text=task.due_text,
            status=task.status,
            created_at=task.created_at,
        )
        for task in tasks
    ]
    return TaskListResponse(items=items, count=len(items))

