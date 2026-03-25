from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from data.models.base import Base


class OHLCV(Base):
    """
    OHLCV candlestick data model.
    Stored in TimescaleDB as a hypertable partitioned by 'timestamp'.
    """
    __tablename__ = "ohlcv"

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(20), primary_key=True)   # 'binance', 'bybit'
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)     # 'BTC/USDT'
    timeframe: Mapped[str] = mapped_column(String(5), primary_key=True)   # '1m','5m','1h','1d'

    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)

    __table_args__ = (
        Index("ix_ohlcv_lookup", "exchange", "symbol", "timeframe", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<OHLCV {self.exchange} {self.symbol} {self.timeframe} "
            f"{self.timestamp} O={self.open} H={self.high} L={self.low} C={self.close} V={self.volume}>"
        )
