"""
Trade Simulator — simulates the lifecycle of a single trade.

Given an entry signal, tracks price candle-by-candle and determines
the outcome: SL hit, TP hit, or exit signal from strategy.
Records P&L, duration, and metadata for each trade.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TradeResult:
    """Result of a single simulated trade."""
    # Identity
    strategy:    str
    exchange:    str
    symbol:      str
    timeframe:   str

    # Entry
    signal_type:  str        # 'LONG' | 'SHORT'
    entry_time:   datetime
    entry_price:  float

    # Exit
    exit_time:    Optional[datetime] = None
    exit_price:   Optional[float]   = None
    exit_reason:  str = ""          # 'sl_hit' | 'tp_hit' | 'exit_signal' | 'end_of_data'

    # SL / TP
    sl_price: float = 0.0
    tp_price: float = 0.0

    # P&L
    pnl_pct:  float = 0.0    # Percentage return
    pnl_usd:  float = 0.0    # USD return (based on position_size)
    fee_usd:  float = 0.0    # Total fees paid

    # Meta
    position_size: float = 0.0    # USD allocated to this trade
    duration_bars: int   = 0      # Number of candles the trade was open


class TradeSimulator:
    """
    Simulates trades on OHLCV data applying SL, TP, fees, and slippage.

    Args:
        fee_rate:  Maker/taker fee as decimal (e.g. 0.001 = 0.1%)
        slippage:  Slippage as decimal of price (e.g. 0.0005 = 0.05%)
    """

    def __init__(self, fee_rate: float = 0.001, slippage: float = 0.0005):
        self.fee_rate = fee_rate
        self.slippage = slippage

    def simulate_trade(
        self,
        signal_row,         # pandas Series — the candle where signal fired
        sl_price: float,
        tp_price: float,
        future_df,          # DataFrame of candles AFTER signal (for price tracking)
        position_size: float = 1000.0,
        strategy: str = "",
        exchange: str = "",
        symbol: str = "",
        timeframe: str = "",
    ) -> TradeResult:
        """
        Simulate a single trade from entry to exit.

        Entry is at the open of the NEXT candle after signal (realistic simulation).
        Exit occurs when:
            - SL is touched (using candle Low for LONG, High for SHORT)
            - TP is touched (using candle High for LONG, Low for SHORT)
            - End of data reached

        Returns:
            TradeResult with all trade details populated.
        """
        signal_type = "LONG" if signal_row.get("signal", 0) == 1 else "SHORT"

        # Slippage on entry
        slippage_mult = 1 + self.slippage if signal_type == "LONG" else 1 - self.slippage
        entry_price = signal_row["close"] * slippage_mult

        entry_time = signal_row.name if hasattr(signal_row.name, 'to_pydatetime') else None

        result = TradeResult(
            strategy=strategy,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            signal_type=signal_type,
            entry_time=entry_time,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            position_size=position_size,
        )

        if future_df is None or future_df.empty:
            result.exit_reason = "end_of_data"
            result.exit_price = entry_price
            result.exit_time = entry_time
            return result

        # Walk through future candles
        for bar_idx, (ts, candle) in enumerate(future_df.iterrows()):
            candle_high = candle["high"]
            candle_low  = candle["low"]

            if signal_type == "LONG":
                # Check SL first (conservative: assume worst happens first)
                if candle_low <= sl_price:
                    result = self._close_trade(result, sl_price, ts, "sl_hit", bar_idx + 1)
                    break
                elif candle_high >= tp_price:
                    result = self._close_trade(result, tp_price, ts, "tp_hit", bar_idx + 1)
                    break
            else:  # SHORT
                if candle_high >= sl_price:
                    result = self._close_trade(result, sl_price, ts, "sl_hit", bar_idx + 1)
                    break
                elif candle_low <= tp_price:
                    result = self._close_trade(result, tp_price, ts, "tp_hit", bar_idx + 1)
                    break
        else:
            # End of data without SL/TP hit
            last_close = future_df.iloc[-1]["close"]
            last_time  = future_df.index[-1]
            result = self._close_trade(result, last_close, last_time, "end_of_data", len(future_df))

        return result

    def _close_trade(
        self,
        result: TradeResult,
        exit_price: float,
        exit_time,
        exit_reason: str,
        duration_bars: int,
    ) -> TradeResult:
        """Apply exit price, fees, and compute final P&L."""
        slippage_mult = (1 - self.slippage) if result.signal_type == "LONG" else (1 + self.slippage)
        exit_price_adj = exit_price * slippage_mult

        # P&L
        if result.signal_type == "LONG":
            pnl_pct = (exit_price_adj - result.entry_price) / result.entry_price
        else:
            pnl_pct = (result.entry_price - exit_price_adj) / result.entry_price

        # Fees: 2 × fee_rate (entry + exit)
        fee_usd = result.position_size * 2 * self.fee_rate
        pnl_usd = result.position_size * pnl_pct - fee_usd

        result.exit_price    = exit_price_adj
        result.exit_time     = exit_time
        result.exit_reason   = exit_reason
        result.pnl_pct       = pnl_pct
        result.pnl_usd       = pnl_usd
        result.fee_usd       = fee_usd
        result.duration_bars = duration_bars
        return result
