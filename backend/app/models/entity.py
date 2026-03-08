from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id", ondelete="CASCADE"), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

