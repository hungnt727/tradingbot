"""Signal history queries (Phase 6 slice 0008).

``list_signals`` enforces process ownership (owner or admin → else
``ProcessNotFound`` = 404), applies dynamic filters, and paginates. Sorted
``detected_at DESC`` to ride the ``ix_signals_process_recent`` index.
"""
import math
from dataclasses import dataclass
from datetime import datetime, time, timezone

from sqlalchemy import func, select

from app_db.models.process import Process
from app_db.models.signal import Signal
from web.services.process_service import ProcessNotFound

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


class SignalNotFound(Exception):
    """Raised when a signal id is missing within an authorized process."""


@dataclass
class SignalFilters:
    exchange: str | None = None
    symbol: str | None = None
    signal_type: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def _authorize_process(db, process_id: int, user) -> Process:
    process = db.get(Process, process_id)
    if process is None or (process.owner_user_id != user.id and not user.is_admin):
        raise ProcessNotFound("Process not found.")
    return process


def _apply_filters(stmt, f: SignalFilters):
    if f.exchange:
        stmt = stmt.where(Signal.exchange == f.exchange)
    if f.symbol:
        stmt = stmt.where(Signal.symbol == f.symbol.upper())
    if f.signal_type:
        stmt = stmt.where(Signal.signal_type == f.signal_type.upper())
    if f.date_from:
        stmt = stmt.where(Signal.detected_at >= f.date_from)
    if f.date_to:
        stmt = stmt.where(Signal.detected_at <= f.date_to)
    return stmt


def list_signals(
    session_factory,
    process_id: int,
    user,
    *,
    filters: SignalFilters | None = None,
    page: int = 1,
    size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[Signal], int, int]:
    """Return ``(rows, total_count, page_count)`` for the process' signals."""
    filters = filters or SignalFilters()
    size = max(1, min(size, MAX_PAGE_SIZE))
    page = max(1, page)

    with session_factory() as db:
        _authorize_process(db, process_id, user)

        base = _apply_filters(select(Signal).where(Signal.process_id == process_id), filters)
        total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = list(
            db.scalars(
                base.order_by(Signal.detected_at.desc()).offset((page - 1) * size).limit(size)
            )
        )
        for r in rows:
            db.expunge(r)

        page_count = max(1, math.ceil(total / size))
        return rows, total, page_count


def get_signal(session_factory, process_id: int, signal_id: int, user) -> Signal:
    """Fetch one signal within an authorized process (for the detail modal)."""
    with session_factory() as db:
        _authorize_process(db, process_id, user)
        sig = db.get(Signal, signal_id)
        if sig is None or sig.process_id != process_id:
            raise SignalNotFound("Signal not found.")
        db.expunge(sig)
        return sig


def parse_date(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    """Parse a ``YYYY-MM-DD`` filter value to a tz-aware datetime, or None."""
    if not value:
        return None
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
    t = time(23, 59, 59) if end_of_day else time(0, 0, 0)
    return datetime.combine(d, t, tzinfo=timezone.utc)
