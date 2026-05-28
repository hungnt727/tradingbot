"""Tests for web.services.user_service (Phase 6 slice 0003)."""
import pytest

from app_db.models.user import User
from web.services.auth_service import AuthService
from web.services import user_service


class TestCreateUser:
    def test_creates_with_hashed_password(self, session_factory):
        user = user_service.create_user(session_factory, "bob", "pw", is_admin=False)
        assert user.username == "bob"
        assert user.is_admin is False
        assert user.password_hash != "pw"
        assert AuthService.verify_password("pw", user.password_hash)

    def test_creates_admin_and_chat_id(self, session_factory):
        user = user_service.create_user(
            session_factory, "boss", "pw", is_admin=True, default_telegram_chat_id="123"
        )
        assert user.is_admin is True
        assert user.default_telegram_chat_id == "123"

    def test_duplicate_username_raises(self, session_factory):
        user_service.create_user(session_factory, "bob", "pw")
        with pytest.raises(user_service.UserExistsError):
            user_service.create_user(session_factory, "bob", "other")


class TestResetPassword:
    def test_changes_hash_so_new_password_verifies(self, session_factory):
        user = user_service.create_user(session_factory, "bob", "old")
        old_hash = user.password_hash
        updated = user_service.reset_password(session_factory, user.id, "new")
        assert updated.password_hash != old_hash
        assert AuthService.verify_password("new", updated.password_hash)
        assert not AuthService.verify_password("old", updated.password_hash)

    def test_unknown_user_raises(self, session_factory):
        with pytest.raises(user_service.UserNotFoundError):
            user_service.reset_password(session_factory, 9999, "x")


class TestDeleteUser:
    def test_delete_removes_user(self, session_factory):
        user = user_service.create_user(session_factory, "bob", "pw")
        user_service.delete_user(session_factory, user.id, acting_user_id=12345)
        with session_factory() as db:
            assert db.get(User, user.id) is None

    def test_cannot_delete_self(self, session_factory):
        admin = user_service.create_user(session_factory, "boss", "pw", is_admin=True)
        with pytest.raises(user_service.SelfDeleteError):
            user_service.delete_user(session_factory, admin.id, acting_user_id=admin.id)


class TestListUsers:
    def test_lists_in_id_order(self, session_factory):
        user_service.create_user(session_factory, "a", "pw")
        user_service.create_user(session_factory, "b", "pw")
        names = [u.username for u in user_service.list_users(session_factory)]
        assert names == ["a", "b"]
