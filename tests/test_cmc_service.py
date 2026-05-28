"""Tests for web.services.cmc_service.fetch_top_n (Phase 6 slice 0007).

httpx mocked at the boundary; fakeredis for the cache.
"""
import httpx
import pytest

from web.services import cmc_service


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("COINMARKETCAP_API_KEY", "test-key")


def _cmc_payload(symbols):
    return {"data": [{"symbol": s} for s in symbols]}


def test_first_call_hits_cmc_and_caches(fake_redis, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "get",
                        lambda *a, **k: (calls.append(1) or _Resp(_cmc_payload(["BTC", "ETH"]))))
    out = cmc_service.fetch_top_n("binance", 2, redis_conn=fake_redis)
    assert out == ["BTC/USDT", "ETH/USDT"]
    assert len(calls) == 1
    assert fake_redis.get("cmc:top_n:binance:2") is not None


def test_second_call_uses_cache(fake_redis, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "get",
                        lambda *a, **k: (calls.append(1) or _Resp(_cmc_payload(["BTC"]))))
    cmc_service.fetch_top_n("binance", 1, redis_conn=fake_redis)
    cmc_service.fetch_top_n("binance", 1, redis_conn=fake_redis)
    assert len(calls) == 1  # second served from cache


def test_cache_miss_after_expiry_refetches(fake_redis, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "get",
                        lambda *a, **k: (calls.append(1) or _Resp(_cmc_payload(["BTC"]))))
    cmc_service.fetch_top_n("binance", 1, redis_conn=fake_redis)
    fake_redis.delete("cmc:top_n:binance:1")  # simulate TTL expiry
    cmc_service.fetch_top_n("binance", 1, redis_conn=fake_redis)
    assert len(calls) == 2


def test_different_n_uses_distinct_cache(fake_redis, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "get",
                        lambda *a, **k: (calls.append(1) or _Resp(_cmc_payload(["BTC", "ETH"]))))
    cmc_service.fetch_top_n("binance", 100, redis_conn=fake_redis)
    cmc_service.fetch_top_n("binance", 200, redis_conn=fake_redis)
    assert len(calls) == 2


def test_cmc_failure_raises(fake_redis, monkeypatch):
    def _boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", _boom)
    with pytest.raises(RuntimeError):
        cmc_service.fetch_top_n("binance", 1, redis_conn=fake_redis)
