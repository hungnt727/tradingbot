"""Volume Breakout (reversal) strategy.

Detects forced parabolic moves and bets on mean-reversion:
  - volume[t] > vol_mult × SMA(volume, vol_lookback)[t-1]
  - close[t] vs SMA(close, price_lookback)[t-1]:
      pump (> 1 + price_pct) → emit SHORT (expect reversal down)
      dump (< 1 - price_pct) → emit LONG  (expect reversal up)

The handler chooses which candle index to evaluate (1D: ``[-2]``, 1H: ``[-1]``);
this class only computes indicators on the whole DataFrame.
"""
from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy


class VolumeBreakoutStrategy(BaseStrategy):
    name: str = "VolumeBreakout"
    timeframe: str = "1h"

    def __init__(
        self,
        vol_mult: float = 3.0,
        vol_lookback: int = 10,
        price_pct: float = 0.30,
        price_lookback: int = 10,
    ):
        self.vol_mult = vol_mult
        self.vol_lookback = vol_lookback
        self.price_pct = price_pct
        self.price_lookback = price_lookback

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.validate_df(df):
            raise ValueError("DataFrame validation failed.")
        df = df.copy()
        # .shift(1) so the SMA excludes the signal candle itself —
        # the spec says "average of the 10 candles BEFORE the signal candle".
        df["vol_sma"] = df["volume"].rolling(self.vol_lookback).mean().shift(1)
        df["close_sma"] = df["close"].rolling(self.price_lookback).mean().shift(1)
        df["vol_ratio"] = df["volume"] / df["vol_sma"]
        df["price_ratio"] = df["close"] / df["close_sma"]
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        # Reversal semantics: pump → SHORT (expect down), dump → LONG (expect up).
        df = df.copy()
        vol_spike = df["vol_ratio"] > self.vol_mult
        short_cond = vol_spike & (df["price_ratio"] > 1 + self.price_pct)
        long_cond = vol_spike & (df["price_ratio"] < 1 - self.price_pct)
        df["signal"] = 0
        df.loc[long_cond, "signal"] = 1
        df.loc[short_cond, "signal"] = -1
        df["signal_type"] = df["signal"].map({1: "LONG", -1: "SHORT", 0: ""})
        return df

    def get_sl_tp(
        self,
        entry_price: float,
        signal: int,
        atr: Optional[float] = None,
    ) -> tuple[float, float]:
        # Handler owns display SL/TP via sl_pct/tp*_pct params; this is a fallback.
        if signal == -1:  # SHORT
            return entry_price * 1.05, entry_price * 0.90
        return entry_price * 0.95, entry_price * 1.10
