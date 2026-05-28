"""processes table

Revision ID: 003
Revises: 002
Create Date: 2026-05-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("strategy_name", sa.String(length=50), nullable=False),
        sa.Column("strategy_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("exchange", sa.String(length=20), nullable=False),
        sa.Column("symbols_mode", sa.String(length=10), nullable=False),
        sa.Column("symbols_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.Text(), nullable=True),
        sa.Column("force_run_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("interval_minutes >= 5", name="ck_processes_interval_min"),
    )
    op.create_index("ix_processes_owner", "processes", ["owner_user_id"])
    op.create_index(
        "ix_processes_due",
        "processes",
        ["is_active", "last_run_at"],
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index("ix_processes_due", table_name="processes")
    op.drop_index("ix_processes_owner", table_name="processes")
    op.drop_table("processes")
