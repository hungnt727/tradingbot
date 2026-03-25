"""
Backtest Engine — manages the execution loop for testing strategies.
Loads data, applies strategy rules, generates signals, and simulates trades.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union

import pandas as pd
from loguru import logger

from backtest.metrics import BacktestMetrics, compute_metrics
from backtest.trade_simulator import TradeResult, TradeSimulator
from data.storage.timescale_client import TimescaleClient
from strategies.base_strategy import BaseStrategy


@dataclass
class BacktestResult:
    strategy_name: str
    exchange:      str
    symbol:        str
    timeframe:     str
    start_date:    datetime
    end_date:      datetime
    metrics:       BacktestMetrics
    trades:        list[TradeResult]
    equity_curve:  pd.Series


class BacktestEngine:
    """
    Core engine for running strategy backtests against historical data.

    Args:
        db_url:    PostgreSQL/TimescaleDB connection string.
        fee_rate:  Trading fee (default 0.001 = 0.1%).
        slippage:  Spread/slip assumption (default 0.0005 = 0.05%).
    """

    def __init__(
        self,
        db_url: str,
        fee_rate: float = 0.001,
        slippage: float = 0.0005,
    ):
        self.db = TimescaleClient(db_url)
        self.trade_sim = TradeSimulator(fee_rate=fee_rate, slippage=slippage)
        self.fee_rate = fee_rate

    def run(
        self,
        strategy: BaseStrategy,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        initial_capital: float = 10_000.0,
        position_size_pct: float = 1.0,  # 1.0 = 100% of equity per trade
        htf_timeframe: Optional[str] = None,
    ) -> BacktestResult:
        """
        Execute the backtest loop.

        Returns:
            BacktestResult dataclass containing full results and trade history.
        """
        end_date = end_date or datetime.utcnow()
        logger.info(
            f"Starting backtest for {strategy.name} on {exchange}:{symbol} {timeframe} "
            f"[{start_date.date()} -> {end_date.date()}]"
        )

        # 1. Load data
        df = self.db.query_ohlcv(exchange, symbol, timeframe, start_date, end_date)
        if df.empty:
            logger.warning("No data found for the specified period.")
            return self._empty_result(strategy.name, exchange, symbol, timeframe, start_date, end_date)

        # Load HTF data if needed by strategy
        htf_df = None
        if htf_timeframe:
            # Need to fetch older data to compute HTF indicators correctly
            start_htf = start_date - pd.Timedelta(days=60)
            htf_df = self.db.query_ohlcv(exchange, symbol, htf_timeframe, start_htf, end_date)
            if not htf_df.empty:
                htf_df = strategy.compute_indicators(htf_df)

        # 2. Compute indicators & generate signals
        df = strategy.compute_indicators(df)
        df = strategy.generate_signals(df, htf_df=htf_df)

        # 3. Simulate trades
        trades: list[TradeResult] = []
        equity = initial_capital

        i = 0
        n = len(df)
        while i < n:
            row = df.iloc[i]

            # If signal fired, simulate the trade life cycle
            if row.get("signal", 0) != 0:
                signal_type = row.get("signal_type", "")
                signal_val  = int(row["signal"])
                atr         = float(row.get("atr", 0))

                entry_price = row["close"]  # Assume entry at open of NEXT candle in sim
                sl, tp = strategy.get_sl_tp(entry_price, signal_val, atr=atr)

                # Future path for this trade
                future_df = df.iloc[i + 1:]

                pos_size = equity * position_size_pct
                
                trade = self.trade_sim.simulate_trade(
                    signal_row=row,
                    sl_price=sl,
                    tp_price=tp,
                    future_df=future_df,
                    position_size=pos_size,
                    strategy=strategy.name,
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                )

                trades.append(trade)
                equity += trade.pnl_usd

                # Skip index to the bar where trade closed so we don't overlap entries
                if trade.exit_time is not None:
                    # Find index of exit time
                    try:
                        exit_idx = df.index.get_loc(trade.exit_time)
                        i = exit_idx
                    except KeyError:
                        i += trade.duration_bars
                else:
                    break

            i += 1

        # 4. Compute Metrics
        metrics = compute_metrics(trades, initial_capital)
        equity_curve = pd.Series([t.pnl_usd for t in trades], index=[t.exit_time for t in trades if t.exit_time]).cumsum() + initial_capital

        logger.info(f"Backtest completed: {len(trades)} trades, Return: {metrics.total_return*100:.2f}%")

        if trades:
            metrics.print_summary()

        return BacktestResult(
            strategy_name=strategy.name,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            metrics=metrics,
            trades=trades,
            equity_curve=equity_curve,
        )

    def _empty_result(self, name, ex, sym, tf, start, end) -> BacktestResult:
        return BacktestResult(
            strategy_name=name, exchange=ex, symbol=sym, timeframe=tf,
            start_date=start, end_date=end,
            metrics=BacktestMetrics(), trades=[], equity_curve=pd.Series()
        )
