from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from data.models.base import Base


class ExchangeInfo(Base):
    """
    Metadata about exchanges and their supported markets.
    """
    __tablename__ = "exchange_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    markets: Mapped[str] = mapped_column(Text, nullable=True)        # JSON list of market symbols
    timeframes: Mapped[str] = mapped_column(Text, nullable=True)     # JSON list of timeframes
    rate_limit: Mapped[int] = mapped_column(Integer, nullable=True)  # ms between requests
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<ExchangeInfo {self.exchange} ({self.name})>"
