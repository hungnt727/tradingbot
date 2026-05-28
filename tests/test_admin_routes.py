"""Integration tests for /admin/users routes (Phase 6 slice 0003)."""
from app_db.models.user import User
from web.services.auth_service import AuthService


class TestAdminAuthorization:
    def test_anonymous_redirected_to_login(self, client):
        resp = client.get("/admin/users")
        assert resp.status_code == 307
        assert resp.headers["location"] == "/login"

    def test_regular_user_forbidden(self, make_user, login):
        make_user(username="alice", password="pw", is_admin=False)
        c = login("alice")
        resp = c.get("/admin/users")
        assert resp.status_code == 403

    def test_admin_allowed(self, make_user, login):
        make_user(username="boss", password="pw", is_admin=True)
        c = login("boss")
        resp = c.get("/admin/users")
        assert resp.status_code == 200
        assert "Users" in resp.text


class TestAdminUserCrud:
    def test_admin_creates_user_who_can_login(self, make_user, login, client, session_factory):
        make_user(username="boss", password="pw", is_admin=True)
        c = login("boss")
        resp = c.post(
            "/admin/users",
            data={"username": "newbie", "password": "secret"},
        )
        assert resp.status_code == 303
        with session_factory() as db:
            from sqlalchemy import select

            u = db.scalar(select(User).where(User.username == "newbie"))
            assert u is not None and u.is_admin is False

        # new user can authenticate
        login_resp = client.post("/login", data={"username": "newbie", "password": "secret"})
        assert login_resp.status_code == 302

    def test_create_with_is_admin_flag(self, make_user, login, session_factory):
        make_user(username="boss", password="pw", is_admin=True)
        c = login("boss")
        c.post("/admin/users", data={"username": "admin2", "password": "pw", "is_admin": "true"})
        with session_factory() as db:
            from sqlalchemy import select

            u = db.scalar(select(User).where(User.username == "admin2"))
            assert u.is_admin is True

    def test_duplicate_username_shows_error(self, make_user, login):
        make_user(username="boss", password="pw", is_admin=True)
        make_user(username="taken", password="pw")
        c = login("boss")
        resp = c.post("/admin/users", data={"username": "taken", "password": "pw"})
        assert resp.status_code == 400
        assert "already exists" in resp.text.lower()

    def test_admin_resets_password(self, make_user, login, client, session_factory):
        make_user(username="boss", password="pw", is_admin=True)
        target = make_user(username="victim", password="oldpw")
        c = login("boss")
        resp = c.post(f"/admin/users/{target.id}/reset-password", data={"new_password": "newpw"})
        assert resp.status_code == 303
        # old fails, new works
        assert client.post("/login", data={"username": "victim", "password": "oldpw"}).status_code == 200
        assert client.post("/login", data={"username": "victim", "password": "newpw"}).status_code == 302

    def test_admin_deletes_user(self, make_user, login, session_factory):
        make_user(username="boss", password="pw", is_admin=True)
        target = make_user(username="goner", password="pw")
        c = login("boss")
        resp = c.post(f"/admin/users/{target.id}/delete")
        assert resp.status_code == 303
        with session_factory() as db:
            assert db.get(User, target.id) is None

    def test_admin_cannot_delete_self(self, make_user, login, session_factory):
        boss = make_user(username="boss", password="pw", is_admin=True)
        c = login("boss")
        resp = c.post(f"/admin/users/{boss.id}/delete")
        assert resp.status_code == 400
        with session_factory() as db:
            assert db.get(User, boss.id) is not None
