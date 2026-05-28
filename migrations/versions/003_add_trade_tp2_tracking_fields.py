"""add trade tp2_price, tp1_hit, trade_metadata

The Trade model gained tp2_price / tp1_hit / trade_metadata after revision 002
was written, but no migration was created — leaving the live `trades` table
behind the model and breaking any `select(Trade)` (e.g. the dashboard). This
adds the missing columns. Additive + nullable/defaulted, so existing rows are
unaffected.

Revision ID: 003
Revises: 002
Create Date: 2026-05-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("tp2_price", sa.Float(), nullable=True))
    op.add_column(
        "trades",
        sa.Column("tp1_hit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("trades", sa.Column("trade_metadata", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("trades", "trade_metadata")
    op.drop_column("trades", "tp1_hit")
    op.drop_column("trades", "tp2_price")
