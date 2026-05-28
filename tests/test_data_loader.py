"""Tests for worker.data_loader.ensure_data_ready (Phase 6 slice 0006).

Fake client + crawler keep Postgres and the network out of the test.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd

from worker.data_loader import ensure_data_ready


def _candles_df(n: int, exchange="binance", symbol="BTC/USDT", tf="1h", start=None):
    start = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    times = [start + timedelta(hours=i) for i in range(n)]
    return pd.DataFrame({
        "time": times,
        "open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n,
        "close": [100.5] * n, "volume": [10.0] * n,
        "exchange": [exchange] * n, "symbol": [symbol] * n, "timeframe": [tf] * n,
    })


class FakeClient:
    def __init__(self, seed: pd.DataFrame | None = None):
        self.rows: list[dict] = []
        self.upsert_calls = 0
        if seed is not None:
            self.upsert_ohlcv(_records(seed))
            self.upsert_calls = 0  # don't count the seed

    def query_latest_ohlcv(self, exchange, symbol, timeframe, limit=1000):
        match = [r for r in self.rows
                 if r["exchange"] == exchange and r["symbol"] == symbol and r["timeframe"] == timeframe]
        match.sort(key=lambda r: r["timestamp"])
        match = match[-limit:]
        df = pd.DataFrame(
            [{c: r[c] for c in ["open", "high", "low", "close", "volume"]} for r in match],
            index=pd.DatetimeIndex([r["timestamp"] for r in match], name="time"),
        )
        return df

    def upsert_ohlcv(self, records):
        self.upsert_calls += 1
        existing = {(r["timestamp"], r["exchange"], r["symbol"], r["timeframe"]) for r in self.rows}
        for rec in records:
            key = (rec["timestamp"], rec["exchange"], rec["symbol"], rec["timeframe"])
            if key not in existing:
                self.rows.append(rec)
                existing.add(key)
        return len(records)


def _records(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, row in df.iterrows():
        out.append({
            "timestamp": row["time"].to_pydatetime(),
            "exchange": row["exchange"], "symbol": row["symbol"], "timeframe": row["timeframe"],
            "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]),
            "close": float(row["close"]), "volume": float(row["volume"]),
        })
    return out


class FakeCrawler:
    def __init__(self, latest=None, historical=None):
        self._latest = latest if latest is not None else _candles_df(0)
        self._historical = historical if historical is not None else _candles_df(0)
        self.latest_calls = 0
        self.historical_calls = 0

    def fetch_latest_candles(self, symbol, timeframe, limit=100):
        self.latest_calls += 1
        return self._latest

    def fetch_ohlcv_historical(self, symbol, timeframe, since=None, **kw):
        self.historical_calls += 1
        return self._historical

    def df_to_records(self, df):
        return _records(df)


def test_empty_db_triggers_full_fetch():
    client = FakeClient()
    crawler = FakeCrawler(latest=_candles_df(300))
    df = ensure_data_ready("binance", "BTC/USDT", "1h", min_required=250, client=client, crawler=crawler)
    assert crawler.latest_calls == 1
    assert crawler.historical_calls == 0
    assert len(df) >= 250


def test_enough_data_triggers_incremental():
    client = FakeClient(seed=_candles_df(260))
    # 3 brand-new candles after the seeded window
    new = _candles_df(3, start=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=260))
    crawler = FakeCrawler(historical=new)
    ensure_data_ready("binance", "BTC/USDT", "1h", min_required=250, client=client, crawler=crawler)
    assert crawler.historical_calls == 1
    assert crawler.latest_calls == 0


def test_stale_below_min_falls_back_to_full():
    client = FakeClient(seed=_candles_df(100))
    crawler = FakeCrawler(latest=_candles_df(300))
    ensure_data_ready("binance", "BTC/USDT", "1h", min_required=250, client=client, crawler=crawler)
    assert crawler.latest_calls == 1
    assert crawler.historical_calls == 0


def test_crawler_empty_no_write_returns_existing():
    client = FakeClient(seed=_candles_df(260))
    before = len(client.rows)
    crawler = FakeCrawler(historical=_candles_df(0))  # nothing new
    df = ensure_data_ready("binance", "BTC/USDT", "1h", min_required=250, client=client, crawler=crawler)
    assert len(client.rows) == before  # no upsert
    assert len(df) == 250  # returned the existing window (capped at min_required)
