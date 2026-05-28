"""Unit tests for the EmaRsiReversal handler — specifically the 1W filter.

The handler's ``_weekly_filter_passes`` short-circuits before fetching 1D/1H,
so we focus on its contract: returns True / False / None and the orchestration
of ``scan`` honors that.
"""
import numpy as np
import pandas as pd
import pytest

from worker.strategy_handlers import ema_rsi_reversal as handler


def _df(n: int, freq: str = "W", *, trend: str = "down") -> pd.DataFrame:
    """Build a synthetic OHLCV df with a controllable price trend.

    ``trend="down"`` produces a price series that pumps then dumps — once RSI
    falls from a peak, the EMAs of RSI stack as ``ema_rsi_5 < ema_rsi_10 <
    ema_rsi_20`` (the descending ordering the 1W filter checks for).
    ``trend="up"`` produces a steady uptrend so the EMAs stack the other way.
    """
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    if trend == "down":
        # Pump for the first 60% then steep dump. Linear segments keep RSI
        # behavior deterministic across pandas-ta versions.
        peak = int(n * 0.6)
        rise = np.linspace(100, 200, peak)
        fall = np.linspace(200, 80, n - peak)
        close = np.concatenate([rise, fall])
    else:  # "up"
        close = np.linspace(100, 200, n)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close,
         "volume": np.full(n, 10.0)}, index=idx,
    )


def _strat():
    """A default EmaRsiReversal instance — params don't matter for compute_indicators."""
    return handler.EmaRsiReversalStrategy(rsi_period=14)


class TestWeeklyFilterFunction:
    def test_returns_true_when_emas_descend(self, monkeypatch):
        monkeypatch.setattr(handler, "ensure_data_ready",
                            lambda ex, sym, tf, min_required=50: _df(120, "W", trend="down"))
        assert handler._weekly_filter_passes(_strat(), "binance", "BTC/USDT") is True

    def test_returns_false_when_emas_ascend(self, monkeypatch):
        monkeypatch.setattr(handler, "ensure_data_ready",
                            lambda ex, sym, tf, min_required=50: _df(120, "W", trend="up"))
        assert handler._weekly_filter_passes(_strat(), "binance", "BTC/USDT") is False

    def test_returns_none_when_data_missing(self, monkeypatch):
        monkeypatch.setattr(handler, "ensure_data_ready",
                            lambda ex, sym, tf, min_required=50: None)
        assert handler._weekly_filter_passes(_strat(), "binance", "BTC/USDT") is None

    def test_returns_none_when_data_too_short(self, monkeypatch):
        monkeypatch.setattr(handler, "ensure_data_ready",
                            lambda ex, sym, tf, min_required=50: _df(10, "W"))
        assert handler._weekly_filter_passes(_strat(), "binance", "BTC/USDT") is None


class TestScanWeeklyFilterOrchestration:
    def _track_fetches(self, monkeypatch, *, weekly_df, ret_others=None):
        """Patch ensure_data_ready to track which timeframes get fetched."""
        calls: list[str] = []

        def fake(ex, sym, tf, min_required=250):
            calls.append(tf)
            if tf == "1w":
                return weekly_df
            return ret_others  # default None → 1D/1H bail early in scan

        monkeypatch.setattr(handler, "ensure_data_ready", fake)
        return calls

    def test_filter_blocks_short_circuits_before_1d(self, monkeypatch):
        """When 1W EMAs ascend (filter blocks), scan returns None and never fetches 1D/1H."""
        calls = self._track_fetches(monkeypatch, weekly_df=_df(120, "W", trend="up"))
        strat_d, strat_h = handler.build({})
        result = handler.scan(strat_d, strat_h, "binance", "BTC/USDT", {})
        assert result is None
        assert calls == ["1w"]  # only 1W fetched — short-circuited

    def test_filter_passes_proceeds_to_1d(self, monkeypatch):
        """When 1W EMAs descend, scan moves on to fetch 1D (which here returns None → bail)."""
        calls = self._track_fetches(monkeypatch, weekly_df=_df(120, "W", trend="down"))
        strat_d, strat_h = handler.build({})
        result = handler.scan(strat_d, strat_h, "binance", "BTC/USDT", {})
        assert result is None  # 1D returned None → bail, but past the 1W gate
        assert calls == ["1w", "1d"]

    def test_disabled_filter_skips_weekly_fetch(self, monkeypatch):
        """use_weekly_filter=False → scan goes straight to 1D, never touches 1W."""
        calls = self._track_fetches(monkeypatch, weekly_df=_df(120, "W", trend="up"))
        strat_d, strat_h = handler.build({})
        result = handler.scan(strat_d, strat_h, "binance", "BTC/USDT",
                              {"use_weekly_filter": False})
        assert result is None
        assert calls == ["1d"]  # weekly skipped entirely

    def test_weekly_data_unavailable_blocks(self, monkeypatch):
        """If 1W returns None (no data), filter treats as 'block' — safer default."""
        calls = self._track_fetches(monkeypatch, weekly_df=None)
        strat_d, strat_h = handler.build({})
        result = handler.scan(strat_d, strat_h, "binance", "BTC/USDT", {})
        assert result is None
        assert calls == ["1w"]  # bailed at 1W, never went to 1D
