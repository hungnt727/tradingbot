"""Tests for web.services.telegram_service (Phase 6 slice 0004).

httpx is mocked at the boundary; we never hit the network.
"""
import httpx
import pytest

from web.services import telegram_service


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")


def test_success_returns_true_none(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(200, {"ok": True}))
    ok, error = telegram_service.send_message("123", "hi")
    assert ok is True
    assert error is None


def test_403_blocked_is_permanent(monkeypatch):
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _FakeResponse(403, {"description": "Forbidden: bot was blocked by the user"}),
    )
    ok, error = telegram_service.send_message("123", "hi")
    assert ok is False
    assert "blocked" in error.lower()
    assert not error.startswith("transient")


def test_400_chat_not_found_is_permanent(monkeypatch):
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _FakeResponse(400, {"description": "Bad Request: chat not found"}),
    )
    ok, error = telegram_service.send_message("bad", "hi")
    assert ok is False
    assert "chat not found" in error.lower()


def test_timeout_is_transient(monkeypatch):
    def _raise(*a, **k):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "post", _raise)
    ok, error = telegram_service.send_message("123", "hi")
    assert ok is False
    assert error.startswith("transient")


def test_500_is_transient(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(500, text="server error"))
    ok, error = telegram_service.send_message("123", "hi")
    assert ok is False
    assert error.startswith("transient")


def test_missing_token_returns_error(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    ok, error = telegram_service.send_message("123", "hi")
    assert ok is False
    assert "TELEGRAM_BOT_TOKEN" in error


def test_missing_chat_id_returns_error():
    ok, error = telegram_service.send_message("", "hi")
    assert ok is False
    assert "chat id" in error.lower()
