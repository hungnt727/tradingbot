"""
Backtest Metrics — computes performance statistics from a list of TradeResult.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from backtest.trade_simulator import TradeResult


@dataclass
class BacktestMetrics:
    """Summary statistics for a backtest run."""
    total_trades:    int   = 0
    winning_trades:  int   = 0
    losing_trades:   int   = 0
    win_rate:        float = 0.0   # %
    total_return:    float = 0.0   # %
    total_pnl_usd:   float = 0.0
    total_fees_usd:  float = 0.0

    avg_win_pct:     float = 0.0
    avg_loss_pct:    float = 0.0
    avg_rr:          float = 0.0   # Reward/Risk ratio

    profit_factor:   float = 0.0   # Gross profit / Gross loss
    max_drawdown:    float = 0.0   # % from peak equity
    sharpe_ratio:    float = 0.0   # Annualised (252 trading days)
    sortino_ratio:   float = 0.0   # Annualised downside deviation

    avg_duration_bars: float = 0.0
    long_trades:     int   = 0
    short_trades:    int   = 0
    sl_hits:         int   = 0
    tp_hits:         int   = 0

    def to_dict(self) -> dict:
        return {
            "Total Trades":       self.total_trades,
            "Win Rate (%)":       round(self.win_rate * 100, 2),
            "Total Return (%)":   round(self.total_return * 100, 2),
            "Total P&L (USD)":    round(self.total_pnl_usd, 2),
            "Total Fees (USD)":   round(self.total_fees_usd, 2),
            "Profit Factor":      round(self.profit_factor, 3),
            "Max Drawdown (%)":   round(self.max_drawdown * 100, 2),
            "Sharpe Ratio":       round(self.sharpe_ratio, 3),
            "Sortino Ratio":      round(self.sortino_ratio, 3),
            "Avg Win (%)":        round(self.avg_win_pct * 100, 2),
            "Avg Loss (%)":       round(self.avg_loss_pct * 100, 2),
            "Avg R:R":            round(self.avg_rr, 2),
            "Avg Duration (bars)": round(self.avg_duration_bars, 1),
            "SL Hits":            self.sl_hits,
            "TP Hits":            self.tp_hits,
            "Long Trades":        self.long_trades,
            "Short Trades":       self.short_trades,
        }

    def print_summary(self) -> None:
        print("\n" + "=" * 46)
        print("  BACKTEST RESULTS")
        print("=" * 46)
        for k, v in self.to_dict().items():
            print(f"  {k:<24} {v}")
        print("=" * 46 + "\n")


def compute_metrics(
    trades: list[TradeResult],
    initial_capital: float = 10_000.0,
    risk_free_rate: float  = 0.0,
    bars_per_year: int     = 8760,      # 1h bars per year
) -> BacktestMetrics:
    """
    Compute comprehensive performance metrics from a list of TradeResult.

    Args:
        trades:          List of completed trades.
        initial_capital: Starting capital in USD.
        risk_free_rate:  Annual risk-free rate (default 0.0).
        bars_per_year:   Used to annualise Sharpe/Sortino (8760 for 1h bars).

    Returns:
        BacktestMetrics dataclass with all statistics.
    """
    m = BacktestMetrics()

    if not trades:
        return m

    m.total_trades  = len(trades)
    m.long_trades   = sum(1 for t in trades if t.signal_type == "LONG")
    m.short_trades  = sum(1 for t in trades if t.signal_type == "SHORT")
    m.sl_hits       = sum(1 for t in trades if t.exit_reason == "sl_hit")
    m.tp_hits       = sum(1 for t in trades if t.exit_reason == "tp_hit")
    m.total_fees_usd = sum(t.fee_usd for t in trades)
    m.avg_duration_bars = np.mean([t.duration_bars for t in trades])

    pnl_pcts = [t.pnl_pct for t in trades]
    pnl_usds = [t.pnl_usd for t in trades]

    wins  = [t for t in trades if t.pnl_usd > 0]
    loses = [t for t in trades if t.pnl_usd <= 0]

    m.winning_trades = len(wins)
    m.losing_trades  = len(loses)
    m.win_rate       = m.winning_trades / m.total_trades if m.total_trades else 0.0

    m.avg_win_pct  = np.mean([t.pnl_pct for t in wins])  if wins  else 0.0
    m.avg_loss_pct = np.mean([t.pnl_pct for t in loses]) if loses else 0.0

    # Reward/Risk ratio
    if loses and m.avg_loss_pct != 0:
        m.avg_rr = abs(m.avg_win_pct / m.avg_loss_pct)

    # Profit Factor
    gross_profit = sum(t.pnl_usd for t in wins)
    gross_loss   = abs(sum(t.pnl_usd for t in loses))
    m.profit_factor = gross_profit / gross_loss if gross_loss else float("inf")

    # Total P&L and Return
    m.total_pnl_usd = sum(pnl_usds)
    m.total_return  = m.total_pnl_usd / initial_capital

    # Equity curve and Max Drawdown
    equity_curve = _compute_equity_curve(trades, initial_capital)
    m.max_drawdown = _compute_max_drawdown(equity_curve)

    # Sharpe & Sortino (annualised)
    returns_arr = np.array(pnl_pcts)
    if len(returns_arr) > 1 and returns_arr.std() > 0:
        excess = returns_arr - (risk_free_rate / bars_per_year)
        m.sharpe_ratio  = (excess.mean() / excess.std()) * np.sqrt(bars_per_year)

        downside = returns_arr[returns_arr < 0]
        if len(downside) > 0:
            downside_std = downside.std()
            if downside_std > 0:
                m.sortino_ratio = (returns_arr.mean() / downside_std) * np.sqrt(bars_per_year)

    return m


def _compute_equity_curve(
    trades: list[TradeResult], initial_capital: float
) -> pd.Series:
    """Build cumulative equity curve from trades sorted by exit time."""
    sorted_trades = sorted(
        [t for t in trades if t.exit_time is not None],
        key=lambda t: t.exit_time,
    )
    equity = initial_capital
    timestamps, values = [], []
    for trade in sorted_trades:
        equity += trade.pnl_usd
        timestamps.append(trade.exit_time)
        values.append(equity)
    return pd.Series(values, index=timestamps) if timestamps else pd.Series([initial_capital])


def _compute_max_drawdown(equity_curve: pd.Series) -> float:
    """Compute the maximum drawdown as a fraction from peak."""
    if equity_curve.empty or len(equity_curve) < 2:
        return 0.0
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    return float(drawdown.min())
