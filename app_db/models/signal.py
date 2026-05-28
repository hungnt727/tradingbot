"""Signal ORM model (Phase 6 slice 0006).

A *signal* is one strategy detection on one candle for one process. The
``UNIQUE (process_id, exchange, symbol, timeframe, timestamp_candle)`` is the
dedupe contract: re-scanning the same candle in the same process cannot insert
twice, so a duplicate Telegram alert is impossible.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app_db.base import Base
from app_db.models.process import JSON_VARIANT


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Signal(Base):
    __tablename__ = "signals"

    # BIGSERIAL on Postgres; plain INTEGER PK on SQLite so autoincrement works in tests.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    process_id: Mapped[int] = mapped_column(
        ForeignKey("processes.id", ondelete="CASCADE"), nullable=False
    )
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(5), nullable=False)
    timestamp_candle: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(10), nullable=False)  # 'LONG' | 'SHORT'
    indicators_snapshot: Mapped[dict] = mapped_column(JSON_VARIANT, nullable=False)
    telegram_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    telegram_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "process_id", "exchange", "symbol", "timeframe", "timestamp_candle",
            name="uq_signals_dedupe",
        ),
        Index("ix_signals_process_recent", "process_id", "detected_at"),
    )

    def __repr__(self) -> str:
        return f"<Signal {self.id} {self.symbol} {self.signal_type} @ {self.timestamp_candle}>"
