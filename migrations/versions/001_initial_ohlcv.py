"""Initial schema: ohlcv and exchange_info tables with TimescaleDB hypertable.

Revision ID: 001
Revises:
Create Date: 2024-01-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ohlcv table
    op.create_table(
        "ohlcv",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("timeframe", sa.String(5), nullable=False),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.Numeric(30, 8), nullable=False),
        sa.PrimaryKeyConstraint("time", "exchange", "symbol", "timeframe"),
    )

    # Create composite index for fast queries
    op.create_index(
        "ix_ohlcv_lookup",
        "ohlcv",
        ["exchange", "symbol", "timeframe", sa.text("time DESC")],
    )

    # Convert to TimescaleDB hypertable (partitioned by time)
    op.execute("""
        SELECT create_hypertable(
            'ohlcv', 'time',
            if_not_exists => TRUE,
            migrate_data  => TRUE
        );
    """)

    # Create exchange_info table
    op.create_table(
        "exchange_info",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("exchange", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("markets", sa.Text, nullable=True),
        sa.Column("timeframes", sa.Text, nullable=True),
        sa.Column("rate_limit", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("exchange_info")
    op.drop_index("ix_ohlcv_lookup", table_name="ohlcv")
    op.drop_table("ohlcv")
