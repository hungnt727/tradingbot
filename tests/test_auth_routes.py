"""Integration tests for auth routes (Phase 6 slice 0002).

Drives the real FastAPI app via TestClient, with app.state.auth_service
overridden to the fake-backed instance (fakeredis + sqlite) so the same
session_factory seeds users and resolves sessions.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(auth_service):
    from web.app import app

    app.state.auth_service = auth_service
    with TestClient(app, follow_redirects=False) as c:
        yield c


class TestAuthRoutes:
    def test_home_unauthenticated_redirects_to_login(self, client):
        resp = client.get("/")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

    def test_login_success_sets_cookie_and_redirects_home(self, client, make_user):
        make_user(username="alice", password="pw")
        resp = client.post("/login", data={"username": "alice", "password": "pw"})
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"
        cookie = resp.headers.get("set-cookie", "")
        assert "session_id=" in cookie
        assert "httponly" in cookie.lower()
        assert "secure" not in cookie.lower()
        assert "samesite=lax" in cookie.lower()

    def test_login_wrong_password_rerenders_form_with_error(self, client, make_user):
        make_user(username="alice", password="pw")
        resp = client.post("/login", data={"username": "alice", "password": "WRONG"})
        assert resp.status_code == 200
        assert "set-cookie" not in resp.headers
        assert "invalid" in resp.text.lower()

    def test_authenticated_home_returns_200(self, client, make_user):
        make_user(username="alice", password="pw")
        client.post("/login", data={"username": "alice", "password": "pw"})
        resp = client.get("/")  # TestClient persists the session_id cookie
        assert resp.status_code == 200
        assert "alice" in resp.text

    def test_logout_clears_session_and_redirects_login(self, client, make_user):
        make_user(username="alice", password="pw")
        client.post("/login", data={"username": "alice", "password": "pw"})
        resp = client.post("/logout")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"
        # session destroyed + cookie cleared: home redirects again
        after = client.get("/")
        assert after.status_code == 302
