from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ActionEvent(Base):
    __tablename__ = "action_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

