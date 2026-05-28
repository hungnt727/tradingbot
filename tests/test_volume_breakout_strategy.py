"""Unit tests for VolumeBreakoutStrategy (the reversal interpretation).

Pump + high vol → expect reversal DOWN → emit SHORT (signal = -1).
Dump + high vol → expect reversal UP   → emit LONG  (signal =  1).
"""
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import pytest

from strategies.volume_breakout_strategy import VolumeBreakoutStrategy


def _df(closes, volumes):
    n = len(closes)
    idx = pd.date_range(
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        periods=n,
        freq="1h",
    )
    return pd.DataFrame(
        {"open": closes, "high": np.array(closes) + 1, "low": np.array(closes) - 1,
         "close": closes, "volume": volumes},
        index=idx,
    )


def _strat(**overrides):
    kwargs = dict(vol_mult=3.0, vol_lookback=10, price_pct=0.30, price_lookback=10)
    kwargs.update(overrides)
    return VolumeBreakoutStrategy(**kwargs)


class TestComputeIndicators:
    def test_sma_excludes_current_candle(self):
        # 10 quiet candles at price 100, vol 10. Then 1 noisy candle.
        closes = [100.0] * 10 + [150.0]
        volumes = [10.0] * 10 + [99.0]
        df = _strat().compute_indicators(_df(closes, volumes))

        # On the last (noisy) candle, the SMAs must look BACKWARD only:
        # vol_sma = avg of indices 0..9 = 10.0 → vol_ratio = 99 / 10 = 9.9
        # close_sma = 100.0 → price_ratio = 150 / 100 = 1.5
        last = df.iloc[-1]
        assert last["vol_sma"] == pytest.approx(10.0)
        assert last["close_sma"] == pytest.approx(100.0)
        assert last["vol_ratio"] == pytest.approx(9.9)
        assert last["price_ratio"] == pytest.approx(1.5)


class TestGenerateSignals:
    def test_pump_emits_short(self):
        # Vol 9.9× SMA, price 1.5× SMA — both >> thresholds → SHORT (reversal expected).
        closes = [100.0] * 10 + [150.0]
        volumes = [10.0] * 10 + [99.0]
        df = _strat().generate_signals(_strat().compute_indicators(_df(closes, volumes)))
        assert int(df.iloc[-1]["signal"]) == -1
        assert df.iloc[-1]["signal_type"] == "SHORT"

    def test_dump_emits_long(self):
        # Vol spike + price collapses to 0.5× SMA → LONG (reversal up expected).
        closes = [100.0] * 10 + [50.0]
        volumes = [10.0] * 10 + [99.0]
        df = _strat().generate_signals(_strat().compute_indicators(_df(closes, volumes)))
        assert int(df.iloc[-1]["signal"]) == 1
        assert df.iloc[-1]["signal_type"] == "LONG"

    def test_no_volume_spike_no_signal(self):
        # Price spike but volume normal → no signal (both conditions required).
        closes = [100.0] * 10 + [150.0]
        volumes = [10.0] * 11  # vol_ratio = 1.0 (below mult=3)
        df = _strat().generate_signals(_strat().compute_indicators(_df(closes, volumes)))
        assert int(df.iloc[-1]["signal"]) == 0

    def test_no_price_move_no_signal(self):
        # Volume spike but price unchanged → no signal.
        closes = [100.0] * 11
        volumes = [10.0] * 10 + [99.0]
        df = _strat().generate_signals(_strat().compute_indicators(_df(closes, volumes)))
        assert int(df.iloc[-1]["signal"]) == 0

    def test_small_price_move_below_threshold_no_signal(self):
        # +10% price move with vol spike → below 30% threshold → no signal.
        closes = [100.0] * 10 + [110.0]
        volumes = [10.0] * 10 + [99.0]
        df = _strat().generate_signals(_strat().compute_indicators(_df(closes, volumes)))
        assert int(df.iloc[-1]["signal"]) == 0


class TestParamsAreApplied:
    def test_lower_vol_mult_fires_more(self):
        closes = [100.0] * 10 + [150.0]
        volumes = [10.0] * 10 + [25.0]  # vol_ratio = 2.5

        strict = _strat(vol_mult=3.0).generate_signals(
            _strat(vol_mult=3.0).compute_indicators(_df(closes, volumes))
        )
        loose = _strat(vol_mult=2.0).generate_signals(
            _strat(vol_mult=2.0).compute_indicators(_df(closes, volumes))
        )
        assert int(strict.iloc[-1]["signal"]) == 0   # 2.5 < 3.0
        assert int(loose.iloc[-1]["signal"]) == -1   # 2.5 > 2.0, pump → SHORT
