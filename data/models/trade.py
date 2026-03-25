from datetime import datetime
from sqlalchemy import String, Numeric, DateTime, Enum, Float
from sqlalchemy.orm import Mapped, mapped_column
import enum

from .base import Base


class TradeSide(enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class TradeStatus(enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Trade(Base):
    """
    Model for storing individual trades (paper or live).
    Records entries, exits, PnL, and status.
    """
    __tablename__ = 'trades'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Identification
    exchange: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(20), nullable=False)
    
    # Trade characteristics
    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide), nullable=False)
    status: Mapped[TradeStatus] = mapped_column(Enum(TradeStatus), default=TradeStatus.OPEN, index=True)
    
    # Entry
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    position_size: Mapped[float] = mapped_column(Float, nullable=False)  # USD value
    
    # Risk Management
    sl_price: Mapped[float] = mapped_column(Float, nullable=True)
    tp_price: Mapped[float] = mapped_column(Float, nullable=True)
    tp2_price: Mapped[float] = mapped_column(Float, nullable=True)
    
    # Exit
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str] = mapped_column(String(50), nullable=True)  # sl_hit, tp_hit, exit_signal, force_exit
    
    # Performance
    pnl_usd: Mapped[float] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float] = mapped_column(Float, nullable=True)
    fee_usd: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Advanced tracking
    tp1_hit: Mapped[bool] = mapped_column(default=False)
    trade_metadata: Mapped[str] = mapped_column(String(500), nullable=True)  # For storing extra info like bar_count

    def __repr__(self) -> str:
        return f"<Trade {self.side.name} {self.symbol} {self.status.name} PnL={self.pnl_usd}>"
