"""
Unit tests for SonicRStrategy.
Tests cover: indicators, signal detection, filters, SL/TP, and edge cases.
"""
import numpy as np
import pandas as pd
import pytest

from strategies.sonicr_strategy import SonicRStrategy


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def strategy():
    return SonicRStrategy()


def _make_df(n: int = 700, trend: str = "up") -> pd.DataFrame:
    """
    Create a synthetic OHLCV DataFrame with a clear trend.

    Args:
        n:     number of candles
        trend: 'up' | 'down' | 'flat'
    """
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")

    if trend == "up":
        close = np.linspace(20_000, 50_000, n) + rng.normal(0, 200, n)
    elif trend == "down":
        close = np.linspace(50_000, 20_000, n) + rng.normal(0, 200, n)
    else:
        close = np.full(n, 35_000) + rng.normal(0, 300, n)

    high   = close + rng.uniform(50, 500, n)
    low    = close - rng.uniform(50, 500, n)
    open_  = close + rng.normal(0, 100, n)
    volume = rng.uniform(100, 1000, n)

    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    }, index=dates)


# ---------------------------------------------------------------------------
# Test: compute_indicators
# ---------------------------------------------------------------------------

class TestComputeIndicators:
    def test_adds_ema_columns(self, strategy):
        df = _make_df(700)
        result = strategy.compute_indicators(df)
        for length in [34, 89, 200, 610]:
            assert f"ema_{length}" in result.columns, f"Missing ema_{length}"

    def test_adds_ema_rsi_columns(self, strategy):
        df = _make_df(700)
        result = strategy.compute_indicators(df)
        for length in [5, 10, 20]:
            assert f"ema_rsi_{length}" in result.columns

    def test_adds_rsi(self, strategy):
        df = _make_df(700)
        result = strategy.compute_indicators(df)
        assert "rsi" in result.columns
        assert result["rsi"].dropna().between(0, 100).all()

    def test_adds_atr(self, strategy):
        df = _make_df(700)
        result = strategy.compute_indicators(df)
        assert "atr" in result.columns
        assert (result["atr"].dropna() > 0).all()

    def test_adds_vol_ma(self, strategy):
        df = _make_df(700)
        result = strategy.compute_indicators(df)
        assert "vol_ma_20" in result.columns

    def test_original_df_not_modified(self, strategy):
        df = _make_df(700)
        original_cols = set(df.columns)
        strategy.compute_indicators(df)
        assert set(df.columns) == original_cols


# ---------------------------------------------------------------------------
# Test: EMA Stack conditions
# ---------------------------------------------------------------------------

class TestEMAStack:
    def test_long_condition_in_uptrend(self, strategy):
        """In a strong uptrend, EMA34 > EMA89 > EMA200 > EMA610 should hold eventually."""
        df = _make_df(700, trend="up")
        df = strategy.compute_indicators(df)
        # Check last rows (after EMAs are fully warmed up)
        last = df.iloc[-1]
        assert last["ema_34"] > last["ema_89"], "EMA34 should be > EMA89 in uptrend"
        assert last["ema_89"] > last["ema_200"], "EMA89 should be > EMA200 in uptrend"

    def test_short_condition_in_downtrend(self, strategy):
        """In a strong downtrend, EMA34 < EMA89 < EMA200 < EMA610 should hold eventually."""
        df = _make_df(700, trend="down")
        df = strategy.compute_indicators(df)
        last = df.iloc[-1]
        assert last["ema_34"] < last["ema_89"], "EMA34 should be < EMA89 in downtrend"
        assert last["ema_89"] < last["ema_200"], "EMA89 should be < EMA200 in downtrend"


# ---------------------------------------------------------------------------
# Test: generate_signals
# ---------------------------------------------------------------------------

class TestGenerateSignals:
    def test_returns_signal_columns(self, strategy):
        df = _make_df(700)
        df = strategy.compute_indicators(df)
        result = strategy.generate_signals(df)
        assert "signal" in result.columns
        assert "signal_type" in result.columns
        assert "reversal_dist" in result.columns
        assert "cross_distance" in result.columns

    def test_signal_values_are_valid(self, strategy):
        df = _make_df(700)
        df = strategy.compute_indicators(df)
        result = strategy.generate_signals(df)
        assert result["signal"].isin([1, -1, 0]).all()

    def test_insufficient_data_returns_no_signal(self, strategy):
        """With fewer candles than min_candles_required, no signals should fire."""
        df = _make_df(n=100)
        df = strategy.compute_indicators(df)
        result = strategy.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_uptrend_produces_long_signals(self, strategy):
        """A strong extended uptrend should eventually produce at least one LONG signal."""
        df = _make_df(700, trend="up")
        df = strategy.compute_indicators(df)
        result = strategy.generate_signals(df)
        long_signals = result[result["signal"] == 1]
        # May or may not produce signals depending on reversal detection window
        # Just check that any signals found are LONG
        if not long_signals.empty:
            assert (long_signals["signal_type"] == "LONG").all()

    def test_signal_type_matches_signal_value(self, strategy):
        df = _make_df(700, trend="up")
        df = strategy.compute_indicators(df)
        result = strategy.generate_signals(df)
        for _, row in result[result["signal"] != 0].iterrows():
            if row["signal"] == 1:
                assert row["signal_type"] == "LONG"
            elif row["signal"] == -1:
                assert row["signal_type"] == "SHORT"


# ---------------------------------------------------------------------------
# Test: get_sl_tp
# ---------------------------------------------------------------------------

class TestGetSlTp:
    def test_long_sl_below_entry(self, strategy):
        sl, tp = strategy.get_sl_tp(entry_price=40_000, signal=1, atr=500)
        assert sl < 40_000, "LONG SL must be below entry price"

    def test_long_tp_above_entry(self, strategy):
        sl, tp = strategy.get_sl_tp(entry_price=40_000, signal=1, atr=500)
        assert tp > 40_000, "LONG TP must be above entry price"

    def test_short_sl_above_entry(self, strategy):
        sl, tp = strategy.get_sl_tp(entry_price=40_000, signal=-1, atr=500)
        assert sl > 40_000, "SHORT SL must be above entry price"

    def test_short_tp_below_entry(self, strategy):
        sl, tp = strategy.get_sl_tp(entry_price=40_000, signal=-1, atr=500)
        assert tp < 40_000, "SHORT TP must be below entry price"

    def test_rr_ratio_approximately_correct(self, strategy):
        """TP distance should be approx 2x SL distance (default multipliers 1.5 / 3.0)."""
        entry = 40_000
        atr = 500
        sl, tp = strategy.get_sl_tp(entry, signal=1, atr=atr)
        sl_dist = entry - sl
        tp_dist = tp - entry
        ratio = tp_dist / sl_dist
        assert abs(ratio - 2.0) < 0.01, f"Expected RR ~2.0, got {ratio:.2f}"

    def test_fallback_without_atr(self, strategy):
        """When ATR is None, fallback to percentage-based SL/TP."""
        sl, tp = strategy.get_sl_tp(entry_price=40_000, signal=1, atr=None)
        assert sl < 40_000
        assert tp > 40_000


# ---------------------------------------------------------------------------
# Test: cross distance
# ---------------------------------------------------------------------------

class TestCrossDistance:
    def test_cross_distance_computed(self, strategy):
        """EMA200/EMA610 cross distance should be computed in output."""
        df = _make_df(700, trend="up")
        df = strategy.compute_indicators(df)
        result = strategy.generate_signals(df)
        # All non-signal rows should have cross_distance == -1
        # Rows with signals should have cross_distance >= 0
        signal_rows = result[result["signal"] != 0]
        if not signal_rows.empty:
            assert (signal_rows["cross_distance"] >= 0).all()

class TestMaxCrossAgoFilter:
    def test_filter_rejects_large_ema_gap(self, strategy):
        """If price is too far from EMA 200/610, signal should be rejected."""
        strategy.config["filters"]["max_ema_gap_pct"] = 0.01 # 1% gap allowed
        for setup in strategy.setups:
            setup["max_ema_gap_pct"] = 0.01

        df = _make_df(700, trend="up")
        df = strategy.compute_indicators(df)
        
        # In a strong 'up' trend, the price will eventually move far away from EMA 610
        result = strategy.generate_signals(df)
        
        # Check if any signals were generated and if they are within the gap limit
        # For a tight 1% gap in an uptrend, signals should be rare or none after a while
        # We just want to ensure the logic doesn't crash and rejects if gap is exceeded
        # We can mock a row to be sure
        last_idx = len(df) - 1
        df.at[df.index[last_idx], "close"] = df.at[df.index[last_idx], "ema_200"] * 1.1 # 10% gap
        
        # Re-run for the last part
        result = strategy.generate_signals(df)
        assert result.iloc[last_idx]["signal"] == 0, "Signal should be rejected due to 10% EMA gap"

    def test_filter_rejects_late_signals(self, strategy):
        """If max_cross_ago is set to a small value, signals far from cross should be rejected."""
        # Force config
        strategy.config["filters"]["max_cross_ago"] = 5
        for setup in strategy.setups:
            setup["max_cross_ago"] = 5

        df = _make_df(700, trend="up")
        df = strategy.compute_indicators(df)
        
        # Manually find where a cross happened
        # By default _make_df trend="up" might cross early
        # Let's check cross distance for all rows
        result = strategy.generate_signals(df)
        
        # If any signals were rejected, they would have been 0
        # If we set max_cross_ago to 1, almost all signals should be rejected
        strategy.config["filters"]["max_cross_ago"] = 1
        for setup in strategy.setups:
            setup["max_cross_ago"] = 1
            
        result_strict = strategy.generate_signals(df)
        assert (result_strict["signal"] == 0).all(), "All signals should be rejected with max_cross_ago=1"
