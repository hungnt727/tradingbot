"""Process ORM model (Phase 6 slice 0005).

A *process* = one strategy + its params + symbols scope + schedule + Telegram
target, owned by one user. JSONB columns and the partial index degrade to
plain JSON / full index on non-Postgres dialects (SQLite in tests).
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app_db.base import Base

# JSONB on Postgres, JSON (TEXT-backed) elsewhere so tests can use SQLite.
JSON_VARIANT = JSON().with_variant(JSONB, "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Process(Base):
    __tablename__ = "processes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    strategy_params: Mapped[dict] = mapped_column(JSON_VARIANT, nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    symbols_mode: Mapped[str] = mapped_column(String(10), nullable=False)  # 'top_n' | 'list'
    symbols_value: Mapped[dict] = mapped_column(JSON_VARIANT, nullable=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    force_run_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    owner = relationship("User")

    __table_args__ = (
        CheckConstraint("interval_minutes >= 5", name="ck_processes_interval_min"),
        Index("ix_processes_owner", "owner_user_id"),
        Index("ix_processes_due", "is_active", "last_run_at", postgresql_where=text("is_active")),
    )

    def __repr__(self) -> str:
        return f"<Process {self.id} {self.name!r} active={self.is_active}>"
