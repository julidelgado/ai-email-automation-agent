"""Initial schema for AI Email Automation Agent.

Revision ID: 20260308_0001
Revises:
Create Date: 2026-03-08 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260308_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("sender", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("external_id", name="uq_emails_external_id"),
    )
    op.create_index("ix_emails_sender", "emails", ["sender"])
    op.create_index("ix_emails_received_at", "emails", ["received_at"])

    op.create_table(
        "classifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email_id", sa.Integer(), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_classifications_email_id", "classifications", ["email_id"])
    op.create_index("ix_classifications_intent", "classifications", ["intent"])

    op.create_table(
        "entities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_key", sa.String(length=128), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_entities_email_id", "entities", ["email_id"])
    op.create_index("ix_entities_entity_type", "entities", ["entity_type"])

    op.create_table(
        "actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email_id", sa.Integer(), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_actions_email_id", "actions", ["email_id"])
    op.create_index("ix_actions_status", "actions", ["status"])

    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("intent", sa.String(length=64), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("min_confidence", sa.Float(), nullable=False, server_default="0.75"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("intent", name="uq_rules_intent"),
    )
    op.create_index("ix_rules_is_active", "rules", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_rules_is_active", table_name="rules")
    op.drop_table("rules")

    op.drop_index("ix_actions_status", table_name="actions")
    op.drop_index("ix_actions_email_id", table_name="actions")
    op.drop_table("actions")

    op.drop_index("ix_entities_entity_type", table_name="entities")
    op.drop_index("ix_entities_email_id", table_name="entities")
    op.drop_table("entities")

    op.drop_index("ix_classifications_intent", table_name="classifications")
    op.drop_index("ix_classifications_email_id", table_name="classifications")
    op.drop_table("classifications")

    op.drop_index("ix_emails_received_at", table_name="emails")
    op.drop_index("ix_emails_sender", table_name="emails")
    op.drop_table("emails")

