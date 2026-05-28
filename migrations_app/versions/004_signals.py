"""signals table

Revision ID: 004
Revises: 003
Create Date: 2026-05-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("exchange", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=5), nullable=False),
        sa.Column("timestamp_candle", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_type", sa.String(length=10), nullable=False),
        sa.Column("indicators_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("telegram_sent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("telegram_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_error", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["processes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "process_id", "exchange", "symbol", "timeframe", "timestamp_candle",
            name="uq_signals_dedupe",
        ),
    )
    op.create_index(
        "ix_signals_process_recent",
        "signals",
        ["process_id", sa.text("detected_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_signals_process_recent", table_name="signals")
    op.drop_table("signals")
