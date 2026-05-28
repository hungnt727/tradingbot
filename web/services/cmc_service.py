"""CoinMarketCap Top-N resolver with Redis caching (Phase 6 slice 0007).

``fetch_top_n`` returns ccxt-style symbols (``["BTC/USDT", "ETH/USDT", ...]``)
for the top ``n`` coins, cached in Redis under ``cmc:top_n:{exchange}:{n}`` for
1 hour. Capacity: CMC free tier is 10,000 calls/month; a 1-hour cache caps usage
at ~720/month per distinct (exchange, n), comfortably under quota. Processes
sharing the same (exchange, n) share one cache entry.

On CMC failure we raise (no silent fallback) so the worker records
``error: CMC unavailable`` rather than scanning a stale/empty set.
"""
import json
import os

import httpx
from loguru import logger

CMC_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
CACHE_TTL_SECONDS = 3600
DEFAULT_TIMEOUT = 30.0

_REDIS = None


def _get_redis():
    global _REDIS
    if _REDIS is None:
        import redis

        _REDIS = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
        )
    return _REDIS


def _api_key() -> str:
    key = os.getenv("COINMARKETCAP_API_KEY") or os.getenv("CMC_API_KEY")
    if not key:
        raise RuntimeError("COINMARKETCAP_API_KEY not set in .env")
    return key


def _cache_key(exchange: str, n: int) -> str:
    return f"cmc:top_n:{exchange}:{n}"


def fetch_top_n(exchange: str, n: int, *, redis_conn=None, timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    """Return the top ``n`` symbols as ``BASE/USDT``, Redis-cached for 1 hour."""
    redis_conn = redis_conn or _get_redis()
    key = _cache_key(exchange, n)

    cached = redis_conn.get(key)
    if cached:
        return json.loads(cached)

    symbols = _fetch_from_cmc(n, timeout=timeout)
    redis_conn.setex(key, CACHE_TTL_SECONDS, json.dumps(symbols))
    logger.info(f"[cmc] fetched + cached top {n} for {exchange} ({len(symbols)} symbols)")
    return symbols


def _fetch_from_cmc(n: int, *, timeout: float) -> list[str]:
    headers = {"Accepts": "application/json", "X-CMC_PRO_API_KEY": _api_key()}
    params = {"start": "1", "limit": str(n), "convert": "USDT"}
    try:
        resp = httpx.get(CMC_URL, headers=headers, params=params, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"CMC unavailable: {exc}") from exc

    data = resp.json().get("data", [])
    symbols = [f"{c['symbol'].upper()}/USDT" for c in data if c.get("symbol")]
    if not symbols:
        raise RuntimeError("CMC returned no symbols")
    return symbols
