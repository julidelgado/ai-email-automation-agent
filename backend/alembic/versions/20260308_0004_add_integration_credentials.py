"""Add integration_credentials table for encrypted OAuth token storage.

Revision ID: 20260308_0004
Revises: 20260308_0003
Create Date: 2026-03-08 05:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260308_0004"
down_revision: Union[str, None] = "20260308_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=True),
        sa.Column("encrypted_access_token", sa.Text(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("token_type", sa.String(length=64), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_integration_credentials_provider", "integration_credentials", ["provider"])
    op.create_index("ix_integration_credentials_expires_at", "integration_credentials", ["expires_at"])
    op.create_index("ix_integration_credentials_is_active", "integration_credentials", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_integration_credentials_is_active", table_name="integration_credentials")
    op.drop_index("ix_integration_credentials_expires_at", table_name="integration_credentials")
    op.drop_index("ix_integration_credentials_provider", table_name="integration_credentials")
    op.drop_table("integration_credentials")

