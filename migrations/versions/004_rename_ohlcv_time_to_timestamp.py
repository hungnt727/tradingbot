"""Rename ohlcv.time to ohlcv.timestamp to match the ORM model.

Migration 001 created the column as ``time``, but the application code —
the ORM model in data/models/ohlcv.py, the raw SQL in
data/storage/timescale_client.py, the docker/init-db.sql reference, and
every Phase 6 worker query — all use ``timestamp``. Tests didn't catch the
drift because they build SQLite schemas from the model via create_all,
bypassing the migration.

PostgreSQL tracks columns by attribute number, so a plain RENAME updates
the PK constraint, the ix_ohlcv_lookup index, and the TimescaleDB
hypertable's time dimension all in one shot without re-creation.

Revision ID: 004
Revises: 003
Create Date: 2026-05-28

"""
from typing import Sequence, Union

import sqlalchemy as sa  # noqa: F401
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("ohlcv", "time", new_column_name="timestamp")


def downgrade() -> None:
    op.alter_column("ohlcv", "timestamp", new_column_name="time")
