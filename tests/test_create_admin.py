"""Tests for scripts.create_admin core logic (Phase 6 slice 0002)."""
import pytest

from scripts.create_admin import UserExistsError, create_admin_user
from web.services.auth_service import AuthService


class TestCreateAdmin:
    def test_creates_admin_with_hashed_password(self, session_factory):
        user = create_admin_user(session_factory, "boss", "s3cret")
        assert user.is_admin is True
        assert user.username == "boss"
        assert user.password_hash != "s3cret"
        assert AuthService.verify_password("s3cret", user.password_hash)

    def test_duplicate_username_raises(self, session_factory):
        create_admin_user(session_factory, "boss", "pw1")
        with pytest.raises(UserExistsError):
            create_admin_user(session_factory, "boss", "pw2")
