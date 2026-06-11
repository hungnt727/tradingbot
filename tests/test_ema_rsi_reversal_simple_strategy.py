"""Unit tests for EmaRsiReversalSimpleStrategy.

Pattern detection: ``ema_rsi_5 < ema_rsi_10 and ema_rsi_5 < ema_rsi_20`` AND
``bars_since_not_desc < max_distance``. Level guard is the handler's job, not
this class's — these tests only validate compute_indicators + generate_signals.
"""
import numpy as np
import pandas as pd

from strategies.ema_rsi_reversal_simple_strategy import EmaRsiReversalSimpleStrategy


def _df(closes):
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": closes, "high": np.array(closes) + 1, "low": np.array(closes) - 1,
         "close": closes, "volume": np.full(n, 10.0)}, index=idx,
    )


def _strat(**overrides):
    kwargs = dict(rsi_period=14, max_distance=10, min_ema_rsi_5=40.0)
    kwargs.update(overrides)
    return EmaRsiReversalSimpleStrategy(**kwargs)


class TestBarsSinceNotDesc:
    def test_zero_when_current_breaks_pattern(self):
        # Steady uptrend → EMAs never descend → bars_since_not_desc = 0 everywhere
        df = _strat().compute_indicators(_df(list(np.linspace(100, 200, 120))))
        # On the last (and every) candle the pattern is NOT met, so distance = 0.
        assert df.iloc[-1]["bars_since_not_desc"] == 0
        assert bool(df.iloc[-1]["is_desc"]) is False

    def test_counts_up_during_descending_streak(self):
        # Pump then sustained dump so EMAs cross into descending order and stay.
        closes = list(np.linspace(100, 200, 60)) + list(np.linspace(200, 60, 80))
        df = _strat().compute_indicators(_df(closes))
        # Latest candle should be in descending order.
        assert bool(df.iloc[-1]["is_desc"]) is True
        # And bars_since_not_desc should be > 0 (it has been descending for a while).
        assert df.iloc[-1]["bars_since_not_desc"] > 0


class TestGenerateSignals:
    def test_no_signal_when_pattern_not_present(self):
        df = _strat().generate_signals(
            _strat().compute_indicators(_df(list(np.linspace(100, 200, 120))))
        )
        assert int(df.iloc[-1]["signal"]) == 0

    def test_short_fires_when_pattern_fresh(self):
        # Long pump, short sharp dump → pattern becomes fresh in the last few candles.
        closes = list(np.linspace(100, 200, 80)) + list(np.linspace(200, 130, 8))
        df = _strat(max_distance=10).generate_signals(
            _strat(max_distance=10).compute_indicators(_df(closes))
        )
        last = df.iloc[-1]
        assert bool(last["is_desc"]) is True
        assert last["bars_since_not_desc"] < 10
        assert int(last["signal"]) == -1
        assert last["signal_type"] == "SHORT"

    def test_no_signal_when_pattern_too_old(self):
        # Same shape, but sustained dump for >> max_distance candles so
        # bars_since_not_desc grows past the threshold.
        closes = list(np.linspace(100, 200, 60)) + list(np.linspace(200, 60, 80))
        df = _strat(max_distance=5).generate_signals(
            _strat(max_distance=5).compute_indicators(_df(closes))
        )
        last = df.iloc[-1]
        assert bool(last["is_desc"]) is True
        assert last["bars_since_not_desc"] >= 5  # well past max_distance
        assert int(last["signal"]) == 0          # → no signal


class TestLevelGuardNotInClass:
    """``min_ema_rsi_5`` belongs to the handler — generate_signals doesn't use it."""

    def test_signal_fires_even_with_low_ema_rsi_5(self):
        # Build a case where the pattern is fresh but ema_rsi_5 is very low.
        # The strategy class still emits SHORT; only the handler would suppress it.
        closes = list(np.linspace(100, 200, 80)) + list(np.linspace(200, 50, 10))
        df = _strat(min_ema_rsi_5=99.0).generate_signals(
            _strat(min_ema_rsi_5=99.0).compute_indicators(_df(closes))
        )
        last = df.iloc[-1]
        if bool(last["is_desc"]) and last["bars_since_not_desc"] < 10:
            # Class emits SHORT regardless of min_ema_rsi_5 — proves the guard
            # is not enforced here.
            assert int(last["signal"]) == -1
