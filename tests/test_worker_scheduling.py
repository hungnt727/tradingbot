"""Tests for the reaper + due-process selection (Phase 6 slice 0006)."""
from datetime import datetime, timedelta, timezone

from app_db.models.process import Process
from worker.reaper import reap_stuck_processes
from worker.scheduling import query_due_process_ids


def _set(session_factory, pid, **fields):
    with session_factory() as db:
        p = db.get(Process, pid)
        for k, v in fields.items():
            setattr(p, k, v)
        db.commit()


class TestReaper:
    def test_resets_long_running(self, make_user, make_process, session_factory):
        owner = make_user(username="a")
        proc = make_process(owner.id)
        _set(session_factory, proc.id, last_run_status="running",
             last_run_started_at=datetime.now(timezone.utc) - timedelta(minutes=15))
        assert reap_stuck_processes(session_factory) == 1
        with session_factory() as db:
            p = db.get(Process, proc.id)
            assert p.last_run_status.startswith("error: timeout")
            assert p.last_run_started_at is None

    def test_leaves_recent_running(self, make_user, make_process, session_factory):
        owner = make_user(username="a")
        proc = make_process(owner.id)
        _set(session_factory, proc.id, last_run_status="running",
             last_run_started_at=datetime.now(timezone.utc) - timedelta(minutes=2))
        assert reap_stuck_processes(session_factory) == 0
        with session_factory() as db:
            assert db.get(Process, proc.id).last_run_status == "running"


class TestDueSelection:
    def test_never_run_active_is_due(self, make_user, make_process, session_factory):
        owner = make_user(username="a")
        proc = make_process(owner.id, is_active=True)
        assert proc.id in query_due_process_ids(session_factory)

    def test_inactive_not_due(self, make_user, make_process, session_factory):
        owner = make_user(username="a")
        proc = make_process(owner.id, is_active=False)
        assert query_due_process_ids(session_factory) == []

    def test_recent_run_not_due(self, make_user, make_process, session_factory):
        owner = make_user(username="a")
        proc = make_process(owner.id, interval_minutes=60, is_active=True)
        _set(session_factory, proc.id, last_run_at=datetime.now(timezone.utc) - timedelta(minutes=10))
        assert proc.id not in query_due_process_ids(session_factory)

    def test_elapsed_interval_is_due(self, make_user, make_process, session_factory):
        owner = make_user(username="a")
        proc = make_process(owner.id, interval_minutes=5, is_active=True)
        _set(session_factory, proc.id, last_run_at=datetime.now(timezone.utc) - timedelta(minutes=10))
        assert proc.id in query_due_process_ids(session_factory)

    def test_force_run_due_even_when_inactive(self, make_user, make_process, session_factory):
        owner = make_user(username="a")
        proc = make_process(owner.id, is_active=False)
        _set(session_factory, proc.id, force_run_requested_at=datetime.now(timezone.utc))
        assert proc.id in query_due_process_ids(session_factory)
