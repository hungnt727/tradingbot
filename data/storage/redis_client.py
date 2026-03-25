import json
from typing import Any, Optional

import redis
from loguru import logger


class RedisClient:
    """
    Client for Redis — used as cache for real-time tick data and pub/sub messaging.
    """

    TICK_PREFIX = "tick:"
    CANDLE_CHANNEL_PREFIX = "candle:"

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.client = redis.from_url(redis_url, decode_responses=True)
        self.pubsub = self.client.pubsub()
        logger.info(f"Redis connected: {redis_url}")

    def ping(self) -> bool:
        """Check Redis connection."""
        try:
            return self.client.ping()
        except Exception as e:
            logger.error(f"Redis ping failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Tick Data (latest price per symbol)
    # ------------------------------------------------------------------

    def set_latest_tick(self, exchange: str, symbol: str, data: dict, ttl: int = 60) -> None:
        """
        Store latest tick data in Redis with a TTL (default 60s).

        Args:
            exchange: Exchange name, e.g. 'binance'
            symbol:   Market symbol, e.g. 'BTC/USDT'
            data:     Dict with price, volume, timestamp, etc.
            ttl:      Time-to-live in seconds
        """
        key = f"{self.TICK_PREFIX}{exchange}:{symbol.replace('/', '_')}"
        self.client.setex(key, ttl, json.dumps(data))

    def get_latest_tick(self, exchange: str, symbol: str) -> Optional[dict]:
        """Retrieve latest tick data for a symbol."""
        key = f"{self.TICK_PREFIX}{exchange}:{symbol.replace('/', '_')}"
        raw = self.client.get(key)
        return json.loads(raw) if raw else None

    # ------------------------------------------------------------------
    # Pub/Sub — Real-time candle events
    # ------------------------------------------------------------------

    def publish_candle(self, exchange: str, symbol: str, timeframe: str, candle: dict) -> None:
        """
        Publish a completed candle to a Redis channel.
        Channel format: candle:binance:BTC_USDT:1h
        """
        channel = f"{self.CANDLE_CHANNEL_PREFIX}{exchange}:{symbol.replace('/', '_')}:{timeframe}"
        self.client.publish(channel, json.dumps(candle))
        logger.debug(f"Published candle to {channel}")

    def subscribe_candles(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        callback: Any,
    ) -> None:
        """
        Subscribe to candle events for a symbol and call callback on each message.

        Args:
            callback: Callable receiving a dict with candle data
        """
        channel = f"{self.CANDLE_CHANNEL_PREFIX}{exchange}:{symbol.replace('/', '_')}:{timeframe}"
        self.pubsub.subscribe(**{channel: lambda msg: callback(json.loads(msg["data"]))})
        logger.info(f"Subscribed to {channel}")
        self.pubsub.run_in_thread(sleep_time=0.01, daemon=True)

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        serialized = json.dumps(value) if not isinstance(value, str) else value
        if ttl:
            self.client.setex(key, ttl, serialized)
        else:
            self.client.set(key, serialized)

    def get(self, key: str) -> Optional[Any]:
        raw = self.client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def delete(self, key: str) -> None:
        self.client.delete(key)
