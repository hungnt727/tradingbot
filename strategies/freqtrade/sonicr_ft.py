"""
Freqtrade IStrategy wrapper for SonicRStrategy.

Wraps the internal SonicRStrategy into Freqtrade's IStrategy interface.
Requires Freqtrade to be installed: pip install freqtrade
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

try:
    from freqtrade.strategy import IStrategy, merge_informative_pair
    from freqtrade.strategy.parameters import BooleanParameter, DecimalParameter, IntParameter
    _FREQTRADE_AVAILABLE = True
except ImportError:
    _FREQTRADE_AVAILABLE = False
    # Provide a stub so the file can be imported without Freqtrade installed
    class IStrategy:  # type: ignore
        pass

from strategies.sonicr_strategy import SonicRStrategy as _SonicRCore


class SonicRStrategy(IStrategy):  # type: ignore[misc]
    """
    Freqtrade strategy powered by SonicRStrategy core logic.

    Usage in Freqtrade:
        freqtrade trade --strategy SonicRStrategy --strategy-path strategies/freqtrade
    """

    # ------------------------------------------------------------------
    # Freqtrade metadata
    # ------------------------------------------------------------------
    INTERFACE_VERSION = 3
    can_short = True

    timeframe     = "1h"
    inf_timeframe = "4h"   # HTF for Supertrend filter

    # Static SL/TP (ATR-based in custom_stoploss / custom_exit if needed)
    stoploss    = -0.03     # -3% baseline
    minimal_roi = {"0": 0.06}  # 6% baseline

    # Process only new candles for performance
    process_only_new_candles = True

    # Use custom stoploss
    use_custom_stoploss = False

    # ------------------------------------------------------------------
    # Internal core strategy
    # ------------------------------------------------------------------

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._core = _SonicRCore()

    # ------------------------------------------------------------------
    # Informative pairs (HTF data)
    # ------------------------------------------------------------------

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(p, self.inf_timeframe) for p in pairs]

    # ------------------------------------------------------------------
    # Indicators
    # ------------------------------------------------------------------

    def populate_indicators(self, df: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """Compute SonicR indicators on LTF data."""
        df = self._core.compute_indicators(df)

        # Merge HTF data for Supertrend filter
        if self.dp:
            inf_df = self.dp.get_pair_dataframe(
                pair=metadata["pair"], timeframe=self.inf_timeframe
            )
            if not inf_df.empty:
                inf_df = self._core.compute_indicators(inf_df)
                # Rename HTF supertrend dir column to avoid collision
                if "supertrend_dir" in inf_df.columns:
                    inf_df = inf_df[["date", "supertrend_dir"]].rename(
                        columns={"supertrend_dir": "htf_supertrend_dir"}
                    )
                    df = merge_informative_pair(
                        df, inf_df, self.timeframe, self.inf_timeframe,
                        ffill=True, append_timeframe=False,
                    )

        return df

    # ------------------------------------------------------------------
    # Entry / Exit
    # ------------------------------------------------------------------

    def populate_entry_trend(self, df: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """Generate entry signals using SonicR window-based reversal."""
        df = self._core.generate_signals(df)

        df["enter_long"]  = (df["signal"] == 1).astype(int)
        df["enter_short"] = (df["signal"] == -1).astype(int)
        df["enter_tag"]   = df["setup_name"]

        return df

    def populate_exit_trend(self, df: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        Exit when EMA stack OR EMA-RSI conditions flip against the trade.
        For simplicity, SL/TP via minimal_roi and stoploss handles exits.
        """
        # Exit LONG when EMA stack goes bearish
        exit_long = (
            (df["ema_34"] < df["ema_89"]) |
            (df["ema_rsi_5"] < df["ema_rsi_10"])
        )
        # Exit SHORT when EMA stack goes bullish
        exit_short = (
            (df["ema_34"] > df["ema_89"]) |
            (df["ema_rsi_5"] > df["ema_rsi_10"])
        )

        df["exit_long"]  = exit_long.astype(int)
        df["exit_short"] = exit_short.astype(int)

        return df
