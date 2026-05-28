"""Tests for the VolumeBreakout handler — focus on per-TF param dispatch.

The class itself is exercised in test_volume_breakout_strategy.py. Here we
verify that ``build`` wires different thresholds into the 1D and 1H instances
while sharing ``sma_lookback`` across both timeframes and across vol/price.
"""
from worker.strategy_handlers import volume_breakout as handler


class TestBuildPerTfDispatch:
    def test_defaults_when_params_empty(self):
        strat_1d, strat_1h = handler.build({})
        assert strat_1d.vol_mult == 3.0
        assert strat_1h.vol_mult == 3.0
        assert strat_1d.price_pct == 0.30
        assert strat_1h.price_pct == 0.30
        assert strat_1d.vol_lookback == strat_1h.vol_lookback == 10
        assert strat_1d.price_lookback == strat_1h.price_lookback == 10

    def test_per_tf_thresholds_apply_independently(self):
        """1D and 1H can be tuned to different strictness levels."""
        params = {
            "sma_lookback": 20,
            "vol_mult_1d": 5.0,   # stricter on 1D
            "vol_mult_1h": 2.0,   # looser on 1H
            "price_pct_1d": 0.50,
            "price_pct_1h": 0.20,
        }
        strat_1d, strat_1h = handler.build(params)
        assert strat_1d.vol_mult == 5.0
        assert strat_1h.vol_mult == 2.0
        assert strat_1d.price_pct == 0.50
        assert strat_1h.price_pct == 0.20

    def test_sma_lookback_shared_across_vol_and_price(self):
        """One ``sma_lookback`` drives both ``vol_lookback`` AND ``price_lookback``
        on each strategy instance — the user only configures this once."""
        strat_1d, strat_1h = handler.build({"sma_lookback": 15})
        assert strat_1d.vol_lookback == 15
        assert strat_1d.price_lookback == 15
        assert strat_1h.vol_lookback == 15
        assert strat_1h.price_lookback == 15

    def test_returns_two_distinct_instances(self):
        """Each TF must get its own object — otherwise modifying one's state
        (if we ever add mutable state) would leak across TFs."""
        strat_1d, strat_1h = handler.build({"vol_mult_1d": 5.0, "vol_mult_1h": 2.0})
        assert strat_1d is not strat_1h
