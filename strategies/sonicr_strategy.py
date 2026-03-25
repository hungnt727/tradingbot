"""
SonicR Strategy — refactored from sonicr_scanner.py into the BaseStrategy framework.

Strategy Logic:
    LONG  when: EMA34 > EMA89 > EMA200 > EMA610
                AND EMA_RSI_5 > EMA_RSI_10 AND EMA_RSI_5 > EMA_RSI_20
    SHORT when: EMA34 < EMA89 < EMA200 < EMA610
                AND EMA_RSI_5 < EMA_RSI_10 AND EMA_RSI_5 < EMA_RSI_20

    A signal fires when state transitions from non-signal to signal
    within the last `signal_window` candles.

Optional Filters (per setup config):
    - Min EMA spread (EMA34/89/200)
    - Min EMA34 threshold
    - Ichimoku Cloud (close > Span B)
    - Volume > Volume MA(20)
    - HTF Supertrend direction
    - Max EMA200/EMA610 cross distance
"""
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import pandas_ta as ta
import yaml
from loguru import logger

from strategies.base_strategy import BaseStrategy


class SonicRStrategy(BaseStrategy):
    """
    SonicR Strategy implementation.
    Reads configuration from config/strategies/sonicr_strategy.yaml.
    """

    name = "SonicRStrategy"

    _DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "strategies" / "sonicr_strategy.yaml"

    def __init__(self, config_path: Optional[str] = None):
        cfg_path = config_path or self._DEFAULT_CONFIG_PATH
        with open(cfg_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.timeframe = self.config.get("timeframe", "1h")
        self.htf_timeframe = self.config.get("htf_timeframe", "4h")

        ind = self.config.get("indicators", {})
        self.ema_lengths       = ind.get("ema_lengths", [34, 89, 200, 610])
        self.rsi_period        = ind.get("rsi_period", 14)
        self.ema_rsi_lengths   = ind.get("ema_rsi_lengths", [5, 10, 20])
        self.st_length         = ind.get("supertrend_length", 10)
        self.st_multiplier     = ind.get("supertrend_multiplier", 3.0)
        self.vol_ma_period     = ind.get("volume_ma_period", 20)
        self.atr_period        = ind.get("atr_period", 14)

        sig = self.config.get("signal", {})
        self.lookback_candles      = sig.get("lookback_candles", 3)
        self.signal_window         = sig.get("signal_window", 5)
        self.min_candles_required  = sig.get("min_candles_required", 620)

        rm = self.config.get("risk_management", {})
        self.sl_pct = rm.get("sl_pct", 0.02)
        self.tp_levels = rm.get("tp_levels", [0.02, 0.04])
        self.tp_size = rm.get("tp_size", 0.5)
        self.max_holding = rm.get("max_holding", 100)
        self.sl_atr_mult = rm.get("sl_atr_multiplier", 1.5)
        self.tp_atr_mult = rm.get("tp_atr_multiplier", 3.0)

        self.setups = self.config.get("setups", [
            {"name": "SonicR Long",  "signal_type": "LONG",  "enabled": True},
            {"name": "SonicR Short", "signal_type": "SHORT", "enabled": True},
        ])
        
        # Track last crossover index per symbol and setup to prevent repeat entries
        # Format: { symbol: { setup_name: last_cross_idx } }
        self.last_cross_indices = {}
        
        # NEW: Apply timeframe-specific overrides
        self.apply_timeframe_config()

        logger.info(f"[SonicRStrategy] Loaded from {cfg_path} (TF: {self.timeframe})")

    def apply_timeframe_config(self):
        """Override global parameters with timeframe-specific ones if defined."""
        configs = self.config.get("timeframe_configs", {})
        if self.timeframe in configs:
            c = configs[self.timeframe]
            logger.info(f"[SonicRStrategy] Applying overrides for {self.timeframe}: {c}")
            
            # 1. Risk Management
            self.sl_pct = c.get("sl_pct", self.sl_pct)
            self.tp_levels = c.get("tp_levels", self.tp_levels)
            
            # Update the config dict as well so other methods see it
            if "risk_management" not in self.config:
                self.config["risk_management"] = {}
            self.config["risk_management"]["sl_pct"] = self.sl_pct
            self.config["risk_management"]["tp_levels"] = self.tp_levels

            # 2. Filters (max_ema_gap_pct)
            if "max_ema_gap_pct" in c:
                gap = c["max_ema_gap_pct"]
                if "filters" not in self.config:
                    self.config["filters"] = {}
                self.config["filters"]["max_ema_gap_pct"] = gap
                
                # Also update setups if they have an explicit override
                for setup in self.setups:
                    if "max_ema_gap_pct" in setup:
                        setup["max_ema_gap_pct"] = gap

    # ------------------------------------------------------------------
    # Indicators
    # ------------------------------------------------------------------

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all SonicR indicators on the DataFrame.

        Adds columns:
            ema_34, ema_89, ema_200, ema_610
            rsi, ema_rsi_5, ema_rsi_10, ema_rsi_20
            atr
            vol_ma_20
            supertrend, supertrend_dir   (optional)
            ichimoku_a, ichimoku_b       (optional)
        """
        df = df.copy()

        # EMA Stack
        for length in self.ema_lengths:
            df[f"ema_{length}"] = ta.ema(df["close"], length=length)

        # RSI + EMA of RSI
        df["rsi"] = ta.rsi(df["close"], length=self.rsi_period)
        for length in self.ema_rsi_lengths:
            df[f"ema_rsi_{length}"] = ta.ema(df["rsi"], length=length)

        # ATR (for SL/TP)
        df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=self.atr_period)

        # Volume MA
        df["vol_ma_20"] = df["volume"].rolling(window=self.vol_ma_period).mean()

        # SuperTrend (for HTF filter — also computed on LTF for signal use)
        try:
            sti = ta.supertrend(
                df["high"], df["low"], df["close"],
                length=self.st_length,
                multiplier=self.st_multiplier,
            )
            if sti is not None and not sti.empty:
                df = pd.concat([df, sti], axis=1)
                # Find the direction column (SUPERTd_length_multiplier)
                dir_cols = [c for c in df.columns if c.startswith("SUPERTd_")]
                if dir_cols:
                    df["supertrend_dir"] = df[dir_cols[0]]
        except Exception as e:
            logger.debug(f"[SonicRStrategy] SuperTrend failed: {e}")
            df["supertrend_dir"] = np.nan

        # Ichimoku
        try:
            ichimoku_data, _ = ta.ichimoku(df["high"], df["low"], df["close"])
            if ichimoku_data is not None and not ichimoku_data.empty:
                df = pd.concat([df, ichimoku_data], axis=1)
                cols = list(ichimoku_data.columns)
                # Span A and Span B are first two columns
                if len(cols) >= 2:
                    df["ichimoku_a"] = ichimoku_data[cols[0]]
                    df["ichimoku_b"] = ichimoku_data[cols[1]]
        except Exception as e:
            logger.debug(f"[SonicRStrategy] Ichimoku failed: {e}")
            df["ichimoku_a"] = np.nan
            df["ichimoku_b"] = np.nan

        return df

    # ------------------------------------------------------------------
    # Signal Detection
    # ------------------------------------------------------------------

    def generate_signals(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        htf_df: Optional[pd.DataFrame] = None,
        is_live: bool = False,
    ) -> pd.DataFrame:
        """
        Generate LONG/SHORT signals using window-based reversal detection.
        """
        df = df.copy()
        df["signal"]          = 0
        df["signal_type"]     = ""
        df["reversal_dist"]   = -1
        df["cross_distance"]  = -1
        
        n = len(df)
        if n < self.min_candles_required:
            return df

        # Initialize tracking for this symbol if not present
        if symbol not in self.last_cross_indices:
            self.last_cross_indices[symbol] = {setup["name"]: None for setup in self.setups}

        # Get EMA pair config for crossover distance
        filters = self.config.get("filters", {})
        ema_pair_str = str(filters.get("cross_distance_ema_pair", "200_610"))

        required_cols = ["ema_34", "ema_89", "ema_200", "ema_610",
                         "ema_rsi_5", "ema_rsi_10", "ema_rsi_20"]

        # Precompute state arrays (vectorized)
        ema_long  = (df["ema_34"] > df["ema_89"]) & (df["ema_89"] > df["ema_200"]) & (df["ema_34"] > df["ema_610"])
        ema_short = (df["ema_34"] < df["ema_89"]) & (df["ema_89"] < df["ema_200"]) & (df["ema_34"] < df["ema_610"])
        rsi_long  = (df["ema_rsi_5"] > df["ema_rsi_10"]) & (df["ema_rsi_5"] > df["ema_rsi_20"])
        rsi_short = (df["ema_rsi_5"] < df["ema_rsi_10"]) & (df["ema_rsi_5"] < df["ema_rsi_20"])

        state_long  = ema_long  & rsi_long
        state_short = ema_short & rsi_short

        htf_st_dir = self._get_htf_supertrend_dir(htf_df)



        if is_live:
            scan_indices = range(max(self.min_candles_required, n - self.lookback_candles), n)
        else:
            scan_indices = range(self.min_candles_required, n)
            # Reset tracking for backtest
            self.last_cross_indices[symbol] = {setup["name"]: None for setup in self.setups}

        for curr_idx in scan_indices:
            row = df.iloc[curr_idx]
            curr_ts = df.index[curr_idx] # Timestamp

            if any(pd.isna(row.get(c)) for c in required_cols):
                continue

            for setup in self.setups:
                if not setup.get("enabled", True):
                    continue

                sig_type = setup["signal_type"]
                is_long, is_short = False, False
                reversal_dist = -1

                if sig_type == "LONG" and state_long.iloc[curr_idx]:
                    is_long, reversal_dist = self._find_reversal(curr_idx, state_long, n, True)
                elif sig_type == "SHORT" and state_short.iloc[curr_idx]:
                    is_short, reversal_dist = self._find_reversal(curr_idx, state_short, n, False)

                if not is_long and not is_short:
                    continue

                # BLOCK if we already fired on this exact candle timestamp
                if curr_ts == self.last_cross_indices[symbol][setup["name"]]:
                    continue

                # Apply filters
                win_indices = list(range(max(0, curr_idx - reversal_dist), curr_idx + 1))
                if not self._apply_filters(df, setup, win_indices, is_long, htf_st_dir):
                    continue

                # Record signal
                sig_val = 1 if is_long else -1
                df.at[df.index[curr_idx], "signal"]        = sig_val
                df.at[df.index[curr_idx], "signal_type"]   = "LONG" if is_long else "SHORT"
                df.at[df.index[curr_idx], "reversal_dist"] = reversal_dist
                df.at[df.index[curr_idx], "cross_distance"] = self._compute_cross_distance(df, curr_idx, ema_pair_str)
                
                # Update persistent tracker with CURRENT TIMESTAMP
                self.last_cross_indices[symbol][setup["name"]] = curr_ts
                break

        return df

    # ------------------------------------------------------------------
    # SL / TP
    # ------------------------------------------------------------------

    def get_sl_tp(
        self,
        entry_price: float,
        signal: int,
        atr: Optional[float] = None,
    ) -> tuple[float, float]:
        """
        Calculate stop-loss and take-profit using ATR multiples.

        For LONG  (signal=1):  SL below entry, TP above entry
        For SHORT (signal=-1): SL above entry, TP below entry
        """
        if atr is None or atr <= 0:
            # Fallback to 2% / 4%
            sl_pct = 0.02
            tp_pct = 0.04
            if signal == 1:
                return entry_price * (1 - sl_pct), entry_price * (1 + tp_pct)
            else:
                return entry_price * (1 + sl_pct), entry_price * (1 - tp_pct)

        sl_dist = atr * self.sl_atr_mult
        tp_dist = atr * self.tp_atr_mult

        if signal == 1:   # LONG
            return entry_price - sl_dist, entry_price + tp_dist
        else:             # SHORT
            return entry_price + sl_dist, entry_price - tp_dist

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_reversal(
        self,
        curr_idx: int,
        state_series: pd.Series,
        n: int,
        is_long_search: bool,
    ) -> tuple[bool, int]:
        """
        Search backwards within signal_window for the candle where
        the state flipped from False → True.

        Returns:
            (signal_found: bool, reversal_dist: int)
        """
        for k in range(self.signal_window):
            target_idx = curr_idx - k
            prev_idx   = target_idx - 1
            if prev_idx < 0 or target_idx < 0:
                break

            k_state    = state_series.iloc[target_idx]
            prev_state = state_series.iloc[prev_idx]

            if k_state and not prev_state:
                return True, k
            if not k_state:
                break

        return False, -1

    def _apply_filters(
        self,
        df: pd.DataFrame,
        setup: dict,
        win_indices: list[int],
        is_long: bool,
        htf_st_dir: Optional[int],
    ) -> bool:
        """Apply all configured filters. Return True if all pass."""
        filters = self.config.get("filters", {})

        # 0. EMA distance filter
        min_ema_dist = setup.get("min_ema_distance", filters.get("min_ema_distance", 0))
        if min_ema_dist > 0:
            dist_ok = any(
                max(df.iloc[idx]["ema_34"], df.iloc[idx]["ema_89"], df.iloc[idx]["ema_200"]) -
                min(df.iloc[idx]["ema_34"], df.iloc[idx]["ema_89"], df.iloc[idx]["ema_200"]) >= min_ema_dist
                for idx in win_indices
            )
            if not dist_ok:
                return False

        # 0b. Min EMA34
        min_ema_34 = setup.get("min_ema_34", filters.get("min_ema_34", 0))
        if min_ema_34 > 0:
            if not any(df.iloc[idx]["ema_34"] > min_ema_34 for idx in win_indices):
                return False

        # 1. Ichimoku filter
        if setup.get("enable_ichimoku", filters.get("enable_ichimoku", False)):
            if "ichimoku_b" in df.columns:
                ichi_ok = any(
                    (is_long and df.iloc[idx]["close"] > df.iloc[idx]["ichimoku_b"]) or
                    (not is_long and df.iloc[idx]["close"] < df.iloc[idx]["ichimoku_b"])
                    for idx in win_indices
                )
                if not ichi_ok:
                    return False

        # 2. Volume filter
        if setup.get("enable_volume_filter", filters.get("enable_volume_filter", False)):
            if "vol_ma_20" in df.columns:
                vol_ok = any(
                    pd.notna(df.iloc[idx]["vol_ma_20"]) and
                    df.iloc[idx]["volume"] > df.iloc[idx]["vol_ma_20"]
                    for idx in win_indices
                )
                if not vol_ok:
                    return False

        # 3. HTF Supertrend filter
        if setup.get("enable_htf_supertrend", filters.get("enable_htf_supertrend", False)):
            if htf_st_dir is None:
                return False
            if is_long and htf_st_dir != 1:
                return False
            if not is_long and htf_st_dir != -1:
                return False

        # 4. Volatility Spike Filter (Max Candle Size vs ATR)
        val_spike = setup.get("max_candle_size_atr")
        if val_spike is None:
            val_spike = filters.get("max_candle_size_atr", 0)
        
        max_candle_size_atr = float(val_spike or 0)
        if max_candle_size_atr > 0 and "atr" in df.columns:
            # Check if any candle in the signal window is too large
            for idx in win_indices:
                row = df.iloc[idx]
                candle_range = float(row["high"] - row["low"])
                atr_val = float(row["atr"])
                if pd.notna(atr_val) and atr_val > 0:
                    if candle_range > max_candle_size_atr * atr_val:
                        return False

        # 5. EMA Crossover Distance Filter
        max_cross_ago = setup.get("max_cross_ago", filters.get("max_cross_ago", 0))
        if max_cross_ago > 0:
            pair_val = setup.get("cross_distance_ema_pair")
            if pair_val is None:
                pair_val = filters.get("cross_distance_ema_pair", "200_610")
            
            ema_pair_str = str(pair_val)
            last_idx = win_indices[-1]
            cross_dist = self._compute_cross_distance(df, last_idx, ema_pair_str)
            if cross_dist > max_cross_ago:
                return False

        # 6. EMA Gap Filter (Price too far from EMA 200/610)
        max_ema_gap = setup.get("max_ema_gap_pct", filters.get("max_ema_gap_pct", 0))
        if max_ema_gap > 0:
            last_idx = win_indices[-1]
            price = df.iloc[last_idx]["close"]
            ema_200 = df.iloc[last_idx]["ema_200"]
            ema_610 = df.iloc[last_idx]["ema_610"]
            
            if pd.notna(ema_200) and abs(price - ema_200) / ema_200 > max_ema_gap:
                return False
            if pd.notna(ema_610) and abs(price - ema_610) / ema_610 > max_ema_gap:
                return False

        return True

    def _compute_cross_distance(self, df: pd.DataFrame, curr_idx: int, ema_pair_str: str) -> int:
        """
        Count candles since the last crossover of the specified EMA pair.
        ema_pair_str format: "200_610", "89_200", or "34_89"
        """
        try:
            parts = ema_pair_str.split("_")
            fast_col = f"ema_{parts[0]}"
            slow_col = f"ema_{parts[1]}"
        except Exception:
            # Fallback
            fast_col, slow_col = "ema_200", "ema_610"

        for j in range(curr_idx, 0, -1):
            c_j   = df.iloc[j]
            c_prev = df.iloc[j - 1]
            
            if pd.isna(c_j.get(slow_col)) or pd.isna(c_prev.get(slow_col)):
                continue
                
            crossed_up   = c_j[fast_col] > c_j[slow_col] and c_prev[fast_col] <= c_prev[slow_col]
            crossed_down = c_j[fast_col] < c_j[slow_col] and c_prev[fast_col] >= c_prev[slow_col]
            
            if crossed_up or crossed_down:
                return curr_idx - j
        return 9999  # No cross found in history

    def _get_htf_supertrend_dir(self, htf_df: Optional[pd.DataFrame]) -> Optional[int]:
        """Extract last Supertrend direction from an HTF DataFrame."""
        if htf_df is None or htf_df.empty:
            return None
        if "supertrend_dir" in htf_df.columns:
            val = htf_df["supertrend_dir"].dropna()
            if not val.empty:
                return int(val.iloc[-1])
        return None
