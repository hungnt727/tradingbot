"""
Unit tests for CCXT-based crawlers.
Mocks ccxt exchange responses to avoid hitting real APIs.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data.crawler.binance_crawler import BinanceCrawler
from data.crawler.bybit_crawler import BybitCrawler


# Sample raw OHLCV as returned by ccxt: [timestamp_ms, O, H, L, C, V]
MOCK_CANDLES = [
    [1704067200000, 42000.0, 42500.0, 41800.0, 42200.0, 100.5],
    [1704070800000, 42200.0, 42800.0, 42100.0, 42600.0, 95.3],
    [1704074400000, 42600.0, 43000.0, 42400.0, 42900.0, 88.1],  # last candle (dropped)
]


@pytest.fixture
def binance_crawler():
    with patch("ccxt.binance") as mock_cls:
        mock_exchange = MagicMock()
        mock_exchange.rateLimit = 100
        mock_exchange.timeframes = {"1m": "1m", "1h": "1h", "1d": "1d"}
        mock_cls.return_value = mock_exchange
        crawler = BinanceCrawler()
        crawler.exchange = mock_exchange
        return crawler


@pytest.fixture
def bybit_crawler():
    with patch("ccxt.bybit") as mock_cls:
        mock_exchange = MagicMock()
        mock_exchange.rateLimit = 100
        mock_exchange.timeframes = {"1m": "1m", "1h": "1h", "1d": "1d"}
        mock_cls.return_value = mock_exchange
        crawler = BybitCrawler()
        crawler.exchange = mock_exchange
        return crawler


class TestBaseCrawlerParsing:
    def test_parse_ohlcv_returns_dataframe(self, binance_crawler):
        df = binance_crawler._parse_ohlcv(MOCK_CANDLES, "BTC/USDT", "1h")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2  # Last candle dropped

    def test_parse_ohlcv_columns(self, binance_crawler):
        df = binance_crawler._parse_ohlcv(MOCK_CANDLES, "BTC/USDT", "1h")
        expected_cols = {"time", "open", "high", "low", "close", "volume", "exchange", "symbol", "timeframe"}
        assert expected_cols.issubset(set(df.columns))

    def test_parse_empty_returns_empty_df(self, binance_crawler):
        df = binance_crawler._parse_ohlcv([], "BTC/USDT", "1h")
        assert df.empty

    def test_exchange_symbol_timeframe_set(self, binance_crawler):
        df = binance_crawler._parse_ohlcv(MOCK_CANDLES, "ETH/USDT", "4h")
        assert (df["exchange"] == "binance").all()
        assert (df["symbol"] == "ETH/USDT").all()
        assert (df["timeframe"] == "4h").all()


class TestFetchLatestCandles:
    def test_returns_dataframe(self, binance_crawler):
        binance_crawler.exchange.fetch_ohlcv.return_value = MOCK_CANDLES
        df = binance_crawler.fetch_latest_candles("BTC/USDT", "1h", limit=100)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2  # Last one dropped

    def test_handles_exception_gracefully(self, binance_crawler):
        import ccxt
        binance_crawler.exchange.fetch_ohlcv.side_effect = ccxt.NetworkError("timeout")
        df = binance_crawler.fetch_latest_candles("BTC/USDT", "1h")
        assert df.empty


class TestDfToRecords:
    def test_converts_to_list_of_dicts(self, binance_crawler):
        df = binance_crawler._parse_ohlcv(MOCK_CANDLES, "BTC/USDT", "1h")
        records = binance_crawler.df_to_records(df)
        assert isinstance(records, list)
        assert len(records) == 2
        assert "time" in records[0]
        assert "open" in records[0]
        assert isinstance(records[0]["open"], float)


class TestBybitCrawler:
    def test_exchange_id(self, bybit_crawler):
        assert bybit_crawler.exchange_id == "bybit"

    def test_fetch_latest(self, bybit_crawler):
        bybit_crawler.exchange.fetch_ohlcv.return_value = MOCK_CANDLES
        df = bybit_crawler.fetch_latest_candles("BTC/USDT", "1h")
        assert not df.empty
        assert (df["exchange"] == "bybit").all()
