"""Orchestration tests for the EmaRsiReversalSimple handler.

Focus: TF fetch order (1W → 1D → 1H), short-circuit behavior, and the level
guard at 1H. Strategy-internal logic is covered in
``test_ema_rsi_reversal_simple_strategy.py``.
"""
import numpy as np
import pandas as pd

from worker.strategy_handlers import ema_rsi_reversal_simple as handler


def _df(closes, freq: str = "1h"):
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {"open": closes, "high": np.array(closes) + 1, "low": np.array(closes) - 1,
         "close": closes, "volume": np.full(n, 10.0)}, index=idx,
    )


def _descending_df(n=120, freq="1h"):
    """Long pump + short (8-candle) sharp dump at the end → fresh descending
    EMA-RSI pattern on the latest candle (``bars_since_not_desc`` ≈ a few)."""
    dump_len = 8
    pump_len = n - dump_len
    closes = list(np.linspace(100, 200, pump_len)) + list(np.linspace(200, 130, dump_len))
    return _df(closes, freq)


def _ascending_df(n=120, freq="1h"):
    """Steady uptrend — EMAs never descend."""
    return _df(list(np.linspace(100, 200, n)), freq)


class TestScanOrchestration:
    def _patch(self, monkeypatch, dfs_by_tf):
        """``dfs_by_tf`` maps tf -> DataFrame (or None). Returns the call log."""
        calls: list[str] = []

        def fake(ex, sym, tf, min_required=250):
            calls.append(tf)
            return dfs_by_tf.get(tf)

        monkeypatch.setattr(handler, "ensure_data_ready", fake)
        return calls

    def test_1w_blocks_short_circuits_before_1d_and_1h(self, monkeypatch):
        calls = self._patch(monkeypatch, {"1w": _ascending_df(120, "W")})
        s, _ = handler.build({})
        result = handler.scan(s, s, "binance", "BTC/USDT", {})
        assert result is None
        assert calls == ["1w"]

    def test_1d_blocks_short_circuits_before_1h(self, monkeypatch):
        calls = self._patch(monkeypatch, {
            "1w": _descending_df(120, "W"),
            "1d": _ascending_df(120, "D"),
        })
        s, _ = handler.build({})
        result = handler.scan(s, s, "binance", "BTC/USDT", {})
        assert result is None
        assert calls == ["1w", "1d"]

    def test_all_3_fire_returns_signal(self, monkeypatch):
        calls = self._patch(monkeypatch, {
            "1w": _descending_df(120, "W"),
            "1d": _descending_df(150, "D"),
            "1h": _descending_df(150, "h"),
        })
        s, _ = handler.build({"min_ema_rsi_5": 0.0})  # disable level guard for this test
        result = handler.scan(s, s, "binance", "BTC/USDT", {"min_ema_rsi_5": 0.0})
        assert calls == ["1w", "1d", "1h"]
        # Result is None unless ema_rsi_5 happens to be > 0 (it will be) AND
        # 1H pattern fires fresh. With descending_df and a low guard, expect SHORT.
        assert result is not None
        assert result["signal_type"] == "SHORT"
        assert result["symbol"] == "BTC/USDT"

    def test_1h_level_guard_blocks_when_ema_rsi_5_too_low(self, monkeypatch):
        """Even if all 3 TFs show the pattern, a high min_ema_rsi_5 should block."""
        calls = self._patch(monkeypatch, {
            "1w": _descending_df(120, "W"),
            "1d": _descending_df(150, "D"),
            "1h": _descending_df(150, "h"),
        })
        # 99.0 is unreachable for a typical ema_rsi_5 → guard always blocks.
        s, _ = handler.build({"min_ema_rsi_5": 99.0})
        result = handler.scan(s, s, "binance", "BTC/USDT", {"min_ema_rsi_5": 99.0})
        assert result is None
        assert calls == ["1w", "1d", "1h"]  # all 3 were fetched, then blocked at level

    def test_missing_1w_data_blocks(self, monkeypatch):
        calls = self._patch(monkeypatch, {"1w": None})
        s, _ = handler.build({})
        result = handler.scan(s, s, "binance", "BTC/USDT", {})
        assert result is None
        assert calls == ["1w"]
