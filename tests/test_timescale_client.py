"""
Unit tests for TimescaleClient.
Uses pytest-mock to avoid requiring a real database connection.
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data.storage.timescale_client import TimescaleClient


@pytest.fixture
def mock_engine():
    """Create a mock SQLAlchemy engine."""
    with patch("data.storage.timescale_client.create_engine") as mock_create:
        mock_engine = MagicMock()
        mock_create.return_value = mock_engine
        yield mock_engine


@pytest.fixture
def client(mock_engine):
    return TimescaleClient("postgresql://test:test@localhost/testdb")


SAMPLE_RECORDS = [
    {
        "time": datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "open": 42000.0,
        "high": 42500.0,
        "low": 41800.0,
        "close": 42200.0,
        "volume": 100.5,
    }
]


class TestUpsertOHLCV:
    def test_empty_records_returns_zero(self, client):
        assert client.upsert_ohlcv([]) == 0

    def test_upsert_returns_count(self, client, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        result = client.upsert_ohlcv(SAMPLE_RECORDS)
        assert result == 1


class TestQueryOHLCV:
    def test_returns_dataframe(self, client, mock_engine):
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2024, 1, 1, tzinfo=timezone.utc), 42000.0, 42500.0, 41800.0, 42200.0, 100.5)
        ]

        df = client.query_ohlcv(
            "binance", "BTC/USDT", "1h",
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_empty_result_returns_empty_df(self, client, mock_engine):
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        df = client.query_ohlcv(
            "binance", "BTC/USDT", "1h",
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert df.empty


class TestGetLastCandle:
    def test_returns_datetime_when_data_exists(self, client, mock_engine):
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        expected = datetime(2024, 6, 1, tzinfo=timezone.utc)
        mock_conn.execute.return_value.fetchone.return_value = (expected,)

        result = client.get_last_candle("binance", "BTC/USDT", "1h")
        assert result == expected

    def test_returns_none_when_no_data(self, client, mock_engine):
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (None,)

        result = client.get_last_candle("binance", "BTC/USDT", "1h")
        assert result is None
