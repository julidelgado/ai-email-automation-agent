"""Add action idempotency dispatch records and dead-letter support.

Revision ID: 20260308_0005
Revises: 20260308_0004
Create Date: 2026-03-08 16:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260308_0005"
down_revision: Union[str, None] = "20260308_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("actions", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.create_index("ix_actions_idempotency_key", "actions", ["idempotency_key"], unique=True)

    op.add_column("actions", sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_actions_dead_lettered_at", "actions", ["dead_lettered_at"])

    op.create_table(
        "action_dispatches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("action_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("dispatch_status", sa.String(length=32), nullable=False, server_default=sa.text("'succeeded'")),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_action_dispatches_action_id", "action_dispatches", ["action_id"])
    op.create_index("ix_action_dispatches_idempotency_key", "action_dispatches", ["idempotency_key"], unique=True)
    op.create_index("ix_action_dispatches_dispatch_status", "action_dispatches", ["dispatch_status"])

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE actions
            SET idempotency_key = 'legacy-action-' || id
            WHERE idempotency_key IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_action_dispatches_dispatch_status", table_name="action_dispatches")
    op.drop_index("ix_action_dispatches_idempotency_key", table_name="action_dispatches")
    op.drop_index("ix_action_dispatches_action_id", table_name="action_dispatches")
    op.drop_table("action_dispatches")

    op.drop_index("ix_actions_dead_lettered_at", table_name="actions")
    op.drop_column("actions", "dead_lettered_at")

    op.drop_index("ix_actions_idempotency_key", table_name="actions")
    op.drop_column("actions", "idempotency_key")

