"""Integration tests for /settings routes (Phase 6 slice 0004)."""
from sqlalchemy import select

from app_db.models.user import User
from web.services import telegram_service


def _chat_id(session_factory, username):
    with session_factory() as db:
        return db.scalar(select(User).where(User.username == username)).default_telegram_chat_id


class TestProfile:
    def test_anonymous_redirected(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 307

    def test_save_chat_id_persists(self, make_user, login, session_factory):
        make_user(username="alice", password="pw")
        c = login("alice")
        resp = c.post("/settings/profile", data={"default_telegram_chat_id": "999"})
        assert resp.status_code == 303
        assert _chat_id(session_factory, "alice") == "999"

    def test_settings_page_shows_current_chat_id(self, make_user, login):
        make_user(username="alice", password="pw")
        c = login("alice")
        c.post("/settings/profile", data={"default_telegram_chat_id": "555"})
        resp = c.get("/settings")
        assert resp.status_code == 200
        assert "555" in resp.text


class TestTestTelegramButton:
    def test_success_toast(self, make_user, login, monkeypatch):
        make_user(username="alice", password="pw")
        c = login("alice")
        monkeypatch.setattr(telegram_service, "send_message", lambda *a, **k: (True, None))
        resp = c.post("/settings/test-telegram", data={"default_telegram_chat_id": "123"})
        assert resp.status_code == 200
        assert "sent successfully" in resp.text.lower()

    def test_failure_toast_shows_error(self, make_user, login, monkeypatch):
        make_user(username="alice", password="pw")
        c = login("alice")
        monkeypatch.setattr(telegram_service, "send_message", lambda *a, **k: (False, "chat not found"))
        resp = c.post("/settings/test-telegram", data={"default_telegram_chat_id": "bad"})
        assert resp.status_code == 200
        assert "chat not found" in resp.text.lower()


class TestChangePassword:
    def test_wrong_old_password_rejected(self, make_user, login, session_factory):
        make_user(username="alice", password="pw")
        c = login("alice")
        resp = c.post("/settings/password", data={"old_password": "WRONG", "new_password": "new"})
        assert resp.status_code == 400
        assert "incorrect" in resp.text.lower()

    def test_correct_old_password_updates_and_keeps_session(self, make_user, login, client):
        make_user(username="alice", password="pw")
        c = login("alice")
        resp = c.post("/settings/password", data={"old_password": "pw", "new_password": "newpw"})
        assert resp.status_code == 200
        # session still valid (no forced logout): home returns 200
        assert c.get("/").status_code == 200
        # new password works for a fresh login
        assert client.post("/login", data={"username": "alice", "password": "newpw"}).status_code == 302
