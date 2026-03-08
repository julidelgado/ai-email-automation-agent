from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.action_event import ActionEvent


class ActionAuditService:
    @staticmethod
    def record_event(
        db: Session,
        *,
        action_id: int,
        event_type: str,
        status: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | list[Any] | None = None,
    ) -> ActionEvent:
        event = ActionEvent(
            action_id=action_id,
            event_type=event_type,
            status=status,
            message=message,
            details=details,
        )
        db.add(event)
        return event

