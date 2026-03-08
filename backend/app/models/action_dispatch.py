from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ActionDispatch(Base):
    __tablename__ = "action_dispatches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    dispatch_status: Mapped[str] = mapped_column(String(32), default="succeeded", index=True, nullable=False)
    output: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

