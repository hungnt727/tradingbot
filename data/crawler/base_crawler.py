"""
Base crawler abstract class.
All exchange-specific crawlers must inherit from this class.
"""
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Callable, Optional

import ccxt
import pandas as pd
from loguru import logger


# Mapping of timeframe string to milliseconds
TIMEFRAME_MS = {
    "1m":  60_000,
    "3m":  180_000,
    "5m":  300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h":  3_600_000,
    "2h":  7_200_000,
    "4h":  14_400_000,
    "6h":  21_600_000,
    "12h": 43_200_000,
    "1d":  86_400_000,
    "1w":  604_800_000,
}


class BaseCrawler(ABC):
    """
    Abstract base class for exchange crawlers.

    Subclasses must implement:
        - exchange_id: str class attribute
        - _create_exchange(): return a ccxt exchange instance
    """

    exchange_id: str = ""

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.exchange: ccxt.Exchange = self._create_exchange()
        logger.info(f"[{self.exchange_id}] Crawler initialized (testnet={testnet})")

    @abstractmethod
    def _create_exchange(self) -> ccxt.Exchange:
        """Instantiate and return the ccxt exchange object."""
        ...

    # ------------------------------------------------------------------
    # REST — Historical OHLCV
    # ------------------------------------------------------------------

    def fetch_ohlcv_historical(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[datetime] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV candles for a symbol.

        Args:
            symbol:    Market symbol, e.g. 'BTC/USDT'
            timeframe: Candle timeframe, e.g. '1h'
            since:     Start datetime (UTC). Defaults to 1 year ago.
            limit:     Max candles per request (exchange-limited).

        Returns:
            DataFrame with columns [time, open, high, low, close, volume].
        """
        if since is None:
            # Default: last 365 days
            since_ms = int((time.time() - 365 * 86400) * 1000)
        else:
            since_ms = int(since.replace(tzinfo=timezone.utc).timestamp() * 1000)

        all_candles: list[list] = []
        tf_ms = TIMEFRAME_MS.get(timeframe, 3_600_000)
        logger.info(f"[{self.exchange_id}] Fetching {symbol} {timeframe} since {since}")

        while True:
            try:
                candles = self.exchange.fetch_ohlcv(
                    symbol, timeframe=timeframe, since=since_ms, limit=limit
                )
            except ccxt.RateLimitExceeded:
                logger.warning(f"[{self.exchange_id}] Rate limit hit. Sleeping 10s...")
                time.sleep(10)
                continue
            except ccxt.NetworkError as e:
                logger.error(f"[{self.exchange_id}] Network error: {e}. Retrying in 5s...")
                time.sleep(5)
                continue

            if not candles:
                break

            all_candles.extend(candles)
            logger.debug(f"[{self.exchange_id}] Fetched {len(candles)} candles, total={len(all_candles)}")

            # If we got fewer than limit, there's no more data
            if len(candles) < limit:
                break

            # Advance since to last candle timestamp + 1 interval
            since_ms = candles[-1][0] + tf_ms

            # Throttle to respect rate limits
            time.sleep(self.exchange.rateLimit / 1000)

        return self._parse_ohlcv(all_candles, symbol, timeframe)

    def fetch_latest_candles(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> pd.DataFrame:
        """Fetch the most recent N candles (used for incremental sync)."""
        try:
            candles = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            return self._parse_ohlcv(candles, symbol, timeframe)
        except Exception as e:
            logger.error(f"[{self.exchange_id}] Error fetching latest candles: {e}")
            return pd.DataFrame()

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: Optional[int] = None, limit: int = 100
    ) -> pd.DataFrame:
        """
        Alias for fetch_latest_candles for compatibility with existing code.
        Used by backtest and paper trading scripts that expect ccxt-style API.
        """
        return self.fetch_latest_candles(symbol, timeframe, limit)

    def _parse_ohlcv(
        self, raw: list[list], symbol: str, timeframe: str
    ) -> pd.DataFrame:
        """Parse raw ccxt OHLCV list into a structured DataFrame."""
        if not raw:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df["exchange"] = self.exchange_id
        df["symbol"] = symbol
        df["timeframe"] = timeframe

        # Drop last (incomplete/live) candle
        df = df.iloc[:-1]
        return df

    # ------------------------------------------------------------------
    # REST — Market Info
    # ------------------------------------------------------------------

    def fetch_markets(self) -> list[str]:
        """Return list of all available USDT-quoted market symbols."""
        try:
            markets = self.exchange.load_markets()
            usdt_markets = [
                s for s, info in markets.items()
                if info.get("quote") == "USDT" and info.get("active", True)
            ]
            logger.info(f"[{self.exchange_id}] Found {len(usdt_markets)} USDT markets")
            return usdt_markets
        except Exception as e:
            logger.error(f"[{self.exchange_id}] Error fetching markets: {e}")
            return []

    def get_supported_timeframes(self) -> list[str]:
        """Return list of timeframes supported by this exchange."""
        try:
            return list(self.exchange.timeframes.keys())
        except Exception:
            return list(TIMEFRAME_MS.keys())

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def df_to_records(self, df: pd.DataFrame) -> list[dict]:
        """Convert OHLCV DataFrame rows to list of dicts for DB upsert."""
        records = []
        for _, row in df.iterrows():
            records.append({
                "timestamp": row["time"].to_pydatetime(),
                "exchange":  row["exchange"],
                "symbol":    row["symbol"],
                "timeframe": row["timeframe"],
                "open":      float(row["open"]),
                "high":      float(row["high"]),
                "low":       float(row["low"]),
                "close":     float(row["close"]),
                "volume":    float(row["volume"]),
            })
        return records
