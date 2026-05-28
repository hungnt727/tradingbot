"""Tests for one-shot "Quét ngay" / force-run (Phase 6 slice 0009)."""
from datetime import datetime, timezone

from app_db.models.process import Process
from web.routes import processes as processes_route
from worker.scheduling import query_due_process_ids


class TestForceRunRoute:
    def test_owner_sets_flag(self, make_user, login, make_process, session_factory):
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, is_active=False)
        c = login("alice")
        resp = c.post(f"/processes/{proc.id}/force-run")
        assert resp.status_code == 200
        with session_factory() as db:
            assert db.get(Process, proc.id).force_run_requested_at is not None

    def test_non_owner_404(self, make_user, login, make_process, client):
        owner = make_user(username="owner", password="pw")
        make_user(username="intruder", password="pw")
        proc = make_process(owner.id)
        client.post("/login", data={"username": "intruder", "password": "pw"})
        assert client.post(f"/processes/{proc.id}/force-run").status_code == 404

    def test_works_on_inactive_process(self, make_user, login, make_process, session_factory):
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, is_active=False)
        c = login("alice")
        c.post(f"/processes/{proc.id}/force-run")
        # an inactive process with the flag is now due
        assert proc.id in query_due_process_ids(session_factory)


class TestForceRunNotifications:
    def test_click_sends_scan_requested_telegram(
        self, make_user, login, make_process, monkeypatch
    ):
        sends = []
        monkeypatch.setattr(
            processes_route, "send_message",
            lambda chat, text: (sends.append((chat, text)) or (True, None)),
        )
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, telegram_chat_id="123", is_active=False)
        c = login("alice")

        c.post(f"/processes/{proc.id}/force-run")

        assert len(sends) == 1
        chat, text = sends[0]
        assert chat == "123"
        assert "Đã yêu cầu quét" in text
        assert proc.name in text

    def test_no_chat_id_skips_telegram_but_still_queues(
        self, make_user, login, make_process, session_factory, monkeypatch
    ):
        sends = []
        monkeypatch.setattr(
            processes_route, "send_message",
            lambda chat, text: (sends.append((chat, text)) or (True, None)),
        )
        owner = make_user(username="alice", password="pw")  # no default_telegram_chat_id
        proc = make_process(owner.id, telegram_chat_id=None, is_active=False)
        c = login("alice")

        resp = c.post(f"/processes/{proc.id}/force-run")

        assert resp.status_code == 200
        assert sends == []  # no Telegram attempted when no chat anywhere
        with session_factory() as db:
            assert db.get(Process, proc.id).force_run_requested_at is not None


class TestConcurrentForceRun:
    def test_two_processes_both_due(self, make_user, make_process, session_factory):
        a = make_user(username="a")
        b = make_user(username="b")
        p1 = make_process(a.id, is_active=False)
        p2 = make_process(b.id, is_active=False)
        with session_factory() as db:
            for pid in (p1.id, p2.id):
                db.get(Process, pid).force_run_requested_at = datetime.now(timezone.utc)
            db.commit()
        due = query_due_process_ids(session_factory)
        assert p1.id in due and p2.id in due
