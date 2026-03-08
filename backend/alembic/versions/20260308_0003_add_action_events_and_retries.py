"""Add action_events timeline and retry scheduling fields.

Revision ID: 20260308_0003
Revises: 20260308_0002
Create Date: 2026-03-08 02:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260308_0003"
down_revision: Union[str, None] = "20260308_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("actions", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_actions_next_attempt_at", "actions", ["next_attempt_at"])

    op.create_table(
        "action_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("action_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_action_events_action_id", "action_events", ["action_id"])
    op.create_index("ix_action_events_status", "action_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_action_events_status", table_name="action_events")
    op.drop_index("ix_action_events_action_id", table_name="action_events")
    op.drop_table("action_events")

    op.drop_index("ix_actions_next_attempt_at", table_name="actions")
    op.drop_column("actions", "next_attempt_at")

