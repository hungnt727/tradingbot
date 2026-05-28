"""Stuck-process reaper (Phase 6 slice 0006).

If the worker crashes mid-scan, a process is left in ``last_run_status='running'``
forever and never re-schedules. The reaper runs at the head of each loop and
resets any process stuck in ``running`` longer than the threshold.
"""
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select

from app_db.models.process import Process

STUCK_THRESHOLD_MINUTES = 10


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def reap_stuck_processes(session_factory, threshold_minutes: int = STUCK_THRESHOLD_MINUTES) -> int:
    """Reset processes stuck in 'running'; return how many were reaped."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=threshold_minutes)
    reaped = 0
    with session_factory() as db:
        stuck = db.scalars(
            select(Process).where(
                Process.last_run_status == "running",
                Process.last_run_started_at.isnot(None),
            )
        ).all()
        for p in stuck:
            if _as_utc(p.last_run_started_at) < cutoff:
                p.last_run_status = "error: timeout (worker crash?)"
                p.last_run_started_at = None
                reaped += 1
        if reaped:
            db.commit()
    if reaped:
        logger.warning(f"[reaper] reset {reaped} stuck process(es)")
    return reaped
