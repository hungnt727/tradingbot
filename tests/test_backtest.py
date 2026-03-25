"""
Unit tests for Backtest Engine elements.
Tests the trade simulator, metrics calculator, and basic engine flow.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backtest.metrics import compute_metrics
from backtest.trade_simulator import TradeSimulator, TradeResult


# ---------------------------------------------------------------------------
# Trade Simulator Tests
# ---------------------------------------------------------------------------

class TestTradeSimulator:
    def test_long_trade_hits_tp(self):
        sim = TradeSimulator(fee_rate=0.001, slippage=0.000)
        
        # Define entry signal row
        signal_row = pd.Series({
            "close": 1000.0,
            "signal": 1,
            "signal_type": "LONG"
        }, name=datetime(2024,1,1))
        
        # Future candles: low doesn't hit SL (900), high hits TP (1100)
        future_df = pd.DataFrame([
            {"high": 1050, "low": 950, "close": 1000},  # Safe
            {"high": 1150, "low": 1020, "close": 1100}, # Hits TP here
        ], index=[datetime(2024,1,2), datetime(2024,1,3)])
        
        res = sim.simulate_trade(
            signal_row, sl_price=900.0, tp_price=1100.0, future_df=future_df,
            position_size=1000.0
        )
        
        assert res.exit_reason == "tp_hit"
        assert res.exit_price == 1100.0
        assert res.duration_bars == 2
        # PnL = (1100 - 1000)/1000 = +10%
        # Fee = 1000 * 0.001 * 2 = 2.0
        # PnL USD = 1000 * 0.1 - 2.0 = 98.0
        assert res.pnl_pct == pytest.approx(0.1)
        assert res.fee_usd == pytest.approx(2.0)
        assert res.pnl_usd == pytest.approx(98.0)

    def test_short_trade_hits_sl(self):
        sim = TradeSimulator(fee_rate=0.0, slippage=0.0)
        
        signal_row = pd.Series({"close": 1000.0, "signal": -1}, name=datetime(2024,1,1))
        
        # SL for short is above entry (1100). TP is below (900).
        future_df = pd.DataFrame([
            {"high": 1150, "low": 950, "close": 1050}, # Hits internal SL (high > SL)
        ], index=[datetime(2024,1,2)])
        
        res = sim.simulate_trade(signal_row, sl_price=1100.0, tp_price=900.0, future_df=future_df)
        
        assert res.exit_reason == "sl_hit"
        assert res.exit_price == 1100.0
        # PnL for short: (Entry - Exit) / Entry
        assert res.pnl_pct == pytest.approx(-0.1)

    def test_end_of_data(self):
        sim = TradeSimulator()
        signal_row = pd.Series({"close": 1000.0, "signal": 1}, name=datetime(2024,1,1))
        # Doesn't hit either SL/TP
        future_df = pd.DataFrame([
            {"high": 1050, "low": 950, "close": 1020}, 
        ], index=[datetime(2024,1,2)])
        
        res = sim.simulate_trade(signal_row, sl_price=900.0, tp_price=1100.0, future_df=future_df)
        
        assert res.exit_reason == "end_of_data"
        # Uses last close adjusted for exit slippage
        # Entry slippage applied too
        assert res.duration_bars == 1

    def test_slippage_applied(self):
        sim = TradeSimulator(fee_rate=0.0, slippage=0.01) # 1% slippage
        signal_row = pd.Series({"close": 1000.0, "signal": 1}, name=datetime(2024,1,1))
        
        future_df = pd.DataFrame([
            {"high": 1500, "low": 900, "close": 1000},
        ], index=[datetime(2024,1,2)])
        
        res = sim.simulate_trade(signal_row, sl_price=500.0, tp_price=1500.0, future_df=future_df)
        
        # Entry: 1000 * 1.01 = 1010
        # TP Exit: 1500 * 0.99 = 1485
        assert res.entry_price == pytest.approx(1010.0)
        assert res.exit_price == pytest.approx(1485.0)


# ---------------------------------------------------------------------------
# Metrics Tests
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_compute_metrics(self):
        t1 = TradeResult("S", "E", "S", "1h", "LONG", datetime(2024,1,1), 1000, 
                         exit_time=datetime(2024,1,2), exit_reason="tp_hit", 
                         pnl_usd=100.0, pnl_pct=0.1, duration_bars=1)
        t2 = TradeResult("S", "E", "S", "1h", "LONG", datetime(2024,1,3), 1000, 
                         exit_time=datetime(2024,1,4), exit_reason="sl_hit", 
                         pnl_usd=-50.0, pnl_pct=-0.05, duration_bars=1)
                         
        metrics = compute_metrics([t1, t2], initial_capital=1000.0)
        
        assert metrics.total_trades == 2
        assert metrics.winning_trades == 1
        assert metrics.losing_trades == 1
        assert metrics.win_rate == 0.5
        assert metrics.total_pnl_usd == 50.0
        assert metrics.profit_factor == 2.0     # 100 / 50
        assert metrics.avg_rr == 2.0            # 0.1 / 0.05
    
    def test_empty_trades(self):
        metrics = compute_metrics([])
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0
