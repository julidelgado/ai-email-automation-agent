from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.action import Action
from app.models.email import Email
from app.models.task import Task
from app.observability import get_metrics_registry

router = APIRouter(prefix="/metrics", tags=["metrics"])
logger = logging.getLogger(__name__)


@router.get("", status_code=status.HTTP_200_OK)
def get_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    snapshot = get_metrics_registry().snapshot()
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    db_status = "ok"
    db_error: str | None = None
    action_counts: dict[str, int] = {}
    email_counts: dict[str, int] = {}
    executed_24h = 0
    dead_letter_24h = 0
    task_total = 0
    task_open = 0
    try:
        action_counts = _count_group_by_status(db, Action.status)
        email_counts = _count_group_by_status(db, Email.status)

        executed_24h = db.execute(
            select(func.count(Action.id)).where(Action.executed_at.is_not(None), Action.executed_at >= since_24h)
        ).scalar_one()
        dead_letter_24h = db.execute(
            select(func.count(Action.id)).where(Action.dead_lettered_at.is_not(None), Action.dead_lettered_at >= since_24h)
        ).scalar_one()
        task_total = db.execute(select(func.count(Task.id))).scalar_one()
        task_open = db.execute(select(func.count(Task.id)).where(Task.status == "open")).scalar_one()
    except Exception as exc:
        db_status = "error"
        db_error = str(exc)
        logger.exception("Failed to load DB metrics snapshot.")

    queue = {
        "pending_approval": int(action_counts.get("pending_approval", 0)),
        "pending_execution": int(action_counts.get("pending", 0) + action_counts.get("retry_pending", 0)),
        "dead_letter": int(action_counts.get("dead_letter", 0)),
    }

    return {
        "status": "ok",
        "generated_at": now.isoformat(),
        "http": snapshot["http"],
        "jobs": snapshot["jobs"],
        "alerts": snapshot["alerts"],
        "actions": {
            "queue": queue,
            "status_counts": action_counts,
            "executed_last_24h": int(executed_24h or 0),
            "dead_letter_last_24h": int(dead_letter_24h or 0),
            "runtime": snapshot["actions"],
        },
        "emails": {"status_counts": email_counts},
        "tasks": {"total": int(task_total or 0), "open": int(task_open or 0)},
        "database": {"status": db_status, "error": db_error},
    }


def _count_group_by_status(db: Session, status_column) -> dict[str, int]:
    rows = db.execute(select(status_column, func.count()).group_by(status_column)).all()
    counts: dict[str, int] = {}
    for status_value, count in rows:
        key = str(status_value or "unknown")
        counts[key] = int(count)
    return counts
