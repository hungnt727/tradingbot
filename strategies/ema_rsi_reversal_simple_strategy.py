"""EMA-RSI Reversal Simple — pattern-only variant of EmaRsiReversal.

Three checks per timeframe:
  1. ``ema_rsi_5 < ema_rsi_10 < ema_rsi_20`` on the latest candle ("descending order").
  2. The descending order started within the last ``max_distance`` candles —
     i.e. ``bars_since_not_desc < max_distance``.

The level check ``ema_rsi_5 > min_ema_rsi_5`` is applied only at the signal
candle inside the handler (not here) so each TF can be evaluated identically.
"""
from typing import Optional

import numpy as np
import pandas as pd
import pandas_ta as ta

from strategies.base_strategy import BaseStrategy


class EmaRsiReversalSimpleStrategy(BaseStrategy):
    name: str = "EmaRsiReversalSimple"
    timeframe: str = "1h"

    def __init__(self, rsi_period: int = 14, max_distance: int = 10, min_ema_rsi_5: float = 40.0):
        self.rsi_period = rsi_period
        self.max_distance = max_distance
        self.min_ema_rsi_5 = min_ema_rsi_5

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.validate_df(df):
            raise ValueError("DataFrame validation failed.")
        df = df.copy()

        rsi = ta.rsi(df["close"], length=self.rsi_period)
        df["rsi"] = rsi

        if rsi is not None and not rsi.dropna().empty:
            df["ema_rsi_5"] = ta.ema(rsi, length=5)
            df["ema_rsi_10"] = ta.ema(rsi, length=10)
            df["ema_rsi_20"] = ta.ema(rsi, length=20)
        else:
            df["ema_rsi_5"] = np.nan
            df["ema_rsi_10"] = np.nan
            df["ema_rsi_20"] = np.nan

        df["is_desc"] = (df["ema_rsi_5"] < df["ema_rsi_10"]) & (df["ema_rsi_10"] < df["ema_rsi_20"])

        # bars_since_not_desc: number of candles since the most recent candle
        # that did NOT satisfy the descending order. A small value means the
        # pattern just emerged; a large value means it has been holding for a
        # long time (no longer "fresh"). Computed via positional ffill.
        pos = np.arange(len(df))
        not_desc_pos = pd.Series(
            np.where(~df["is_desc"], pos.astype(float), np.nan),
            index=df.index,
        ).ffill()
        df["bars_since_not_desc"] = pos - not_desc_pos
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        # Pattern signal only — level threshold (ema_rsi_5 > min) is applied by
        # the handler at the 1H signal candle.
        df = df.copy()
        condition = df["is_desc"] & (df["bars_since_not_desc"] < self.max_distance)
        df["signal"] = 0
        df.loc[condition, "signal"] = -1
        df["signal_type"] = df["signal"].map({-1: "SHORT", 0: ""})
        return df

    def get_sl_tp(
        self,
        entry_price: float,
        signal: int,
        atr: Optional[float] = None,
    ) -> tuple[float, float]:
        if signal == -1:  # SHORT
            return entry_price * 1.05, entry_price * 0.90
        return entry_price * 0.95, entry_price * 1.10
