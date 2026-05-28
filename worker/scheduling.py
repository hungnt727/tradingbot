"""Due-process selection for the worker loop (Phase 6 slice 0006).

A process is *due* when it has a pending force-run, or it is active and its
interval has elapsed since the last run. Computed in Python (not SQL interval
math) — the active set is tiny (5-15) and this stays dialect-agnostic + testable.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app_db.models.process import Process


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def query_due_process_ids(session_factory, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(timezone.utc)
    with session_factory() as db:
        candidates = db.scalars(
            select(Process).where(
                or_(Process.is_active.is_(True), Process.force_run_requested_at.isnot(None))
            )
        ).all()
        due: list[int] = []
        for p in candidates:
            if p.force_run_requested_at is not None:
                due.append(p.id)  # force-run fires regardless of schedule / active
                continue
            if not p.is_active:
                continue
            if p.last_run_at is None:
                due.append(p.id)
                continue
            if now - _as_utc(p.last_run_at) >= timedelta(minutes=p.interval_minutes):
                due.append(p.id)
        return due
