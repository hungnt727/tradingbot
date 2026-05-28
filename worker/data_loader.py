"""OHLCV backfill for the worker (Phase 6 slice 0006).

``ensure_data_ready`` makes sure the OHLCV DB (``tradingbot``) holds enough
recent candles for a (exchange, symbol, timeframe), then returns them as a
DataFrame the strategy can consume. It reuses the existing crawler +
TimescaleClient unchanged:

- DB empty or below ``min_required`` → full fetch (``fetch_latest_candles``).
- Otherwise → incremental fetch from the DB max timestamp forward.

Idempotent at the DB layer (``upsert_ohlcv`` ON CONFLICT). Because two processes
sharing a (symbol, timeframe) both go through this, the second one fetches only
the delta — no duplicate API hammering.
"""
import os

import pandas as pd
from loguru import logger

from data.crawler.binance_crawler import BinanceCrawler
from data.crawler.bybit_crawler import BybitCrawler
from data.storage.timescale_client import TimescaleClient

_CLIENT: TimescaleClient | None = None
_CRAWLERS: dict[str, object] = {}


def _get_client() -> TimescaleClient:
    global _CLIENT
    if _CLIENT is None:
        url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tradingbot")
        _CLIENT = TimescaleClient(url)
    return _CLIENT


def _get_crawler(exchange: str):
    if exchange not in _CRAWLERS:
        if exchange == "binance":
            _CRAWLERS[exchange] = BinanceCrawler()  # public klines need no API key
        elif exchange == "bybit":
            _CRAWLERS[exchange] = BybitCrawler()
        else:
            raise ValueError(f"Unsupported exchange '{exchange}'")
    return _CRAWLERS[exchange]


def ensure_data_ready(
    exchange: str,
    symbol: str,
    timeframe: str,
    min_required: int = 250,
    *,
    client: TimescaleClient | None = None,
    crawler=None,
) -> pd.DataFrame:
    """Return a recent OHLCV DataFrame for the market, backfilling as needed.

    ``client`` / ``crawler`` are injectable so tests can avoid Postgres and the
    network.
    """
    client = client or _get_client()
    crawler = crawler or _get_crawler(exchange)

    # Capping the count query at ``min_required`` is enough to decide full vs
    # incremental: < min_required means "not enough history, backfill".
    existing = client.query_latest_ohlcv(exchange, symbol, timeframe, limit=min_required)
    have_enough = (not existing.empty) and len(existing) >= min_required
    max_ts = existing.index.max() if not existing.empty else None

    if not have_enough or max_ts is None:
        logger.info(f"[data] full backfill {exchange} {symbol} {timeframe} (have {len(existing)})")
        df_new = crawler.fetch_latest_candles(symbol, timeframe, limit=min_required + 50)
    else:
        logger.debug(f"[data] incremental {exchange} {symbol} {timeframe} since {max_ts}")
        df_new = crawler.fetch_ohlcv_historical(symbol, timeframe, since=max_ts.to_pydatetime())

    if df_new is not None and not df_new.empty:
        client.upsert_ohlcv(crawler.df_to_records(df_new))
        return client.query_latest_ohlcv(exchange, symbol, timeframe, limit=min_required + 50)

    # Crawler returned nothing new — return whatever we already have.
    return existing
