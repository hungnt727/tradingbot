"""Tests for web.services.auth_service.AuthService (Phase 6 slice 0002)."""
from web.services.auth_service import AuthService


class TestPasswordHashing:
    def test_hash_then_verify_roundtrip(self):
        hashed = AuthService.hash_password("correct horse battery staple")
        assert AuthService.verify_password("correct horse battery staple", hashed) is True

    def test_hash_is_salted_differs_each_call(self):
        assert AuthService.hash_password("same") != AuthService.hash_password("same")

    def test_verify_rejects_wrong_password(self):
        hashed = AuthService.hash_password("right")
        assert AuthService.verify_password("wrong", hashed) is False


class TestSessions:
    def test_create_then_resolve_returns_user(self, auth_service, make_user):
        user = make_user(username="alice")
        session_id = auth_service.create_session(user.id)
        resolved = auth_service.resolve_session(session_id)
        assert resolved is not None
        assert resolved.id == user.id
        assert resolved.username == "alice"

    def test_resolve_unknown_session_returns_none(self, auth_service):
        assert auth_service.resolve_session("does-not-exist") is None

    def test_destroyed_session_no_longer_resolves(self, auth_service, make_user):
        user = make_user()
        session_id = auth_service.create_session(user.id)
        auth_service.destroy_session(session_id)
        assert auth_service.resolve_session(session_id) is None

    def test_create_session_sets_configured_ttl(self, fake_redis, session_factory, make_user):
        svc = AuthService(fake_redis, session_factory, session_ttl=100)
        user = make_user()
        session_id = svc.create_session(user.id)
        ttl = fake_redis.ttl(f"{AuthService.SESSION_PREFIX}{session_id}")
        assert 0 < ttl <= 100

    def test_resolve_renews_ttl_sliding(self, fake_redis, session_factory, make_user):
        svc = AuthService(fake_redis, session_factory, session_ttl=100)
        user = make_user()
        session_id = svc.create_session(user.id)
        key = f"{AuthService.SESSION_PREFIX}{session_id}"
        fake_redis.expire(key, 10)  # simulate time elapsed
        svc.resolve_session(session_id)
        assert fake_redis.ttl(key) > 10
