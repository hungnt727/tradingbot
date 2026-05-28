"""Tests for worker.symbols_resolver.resolve_symbols (Phase 6 slice 0007)."""
import pytest

from worker import symbols_resolver


def test_list_mode_returns_value_as_is():
    out = symbols_resolver.resolve_symbols("binance", "list", {"list": ["BTC/USDT", "ETH/USDT"]})
    assert out == ["BTC/USDT", "ETH/USDT"]


def test_top_n_mode_delegates_to_cmc(monkeypatch):
    captured = {}

    def fake_fetch(exchange, n, *, redis_conn=None):
        captured["exchange"] = exchange
        captured["n"] = n
        return ["BTC/USDT"] * n

    monkeypatch.setattr(symbols_resolver.cmc_service, "fetch_top_n", fake_fetch)
    out = symbols_resolver.resolve_symbols("bybit", "top_n", {"top_n": 3})
    assert captured == {"exchange": "bybit", "n": 3}
    assert len(out) == 3


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        symbols_resolver.resolve_symbols("binance", "wat", {})
