"""
Distribution Strategy — Phát hiện coin đang trong giai đoạn phân phối đỉnh trên chart 1D.

Strategy Logic:
    - Nhận diện coin đang ở giai đoạn phân phối (distribution phase) khi:
        1. Giá đang ở vùng trên của range phân phối (upper_zone)
        2. Có các tín hiệu xác nhận giảm giá (EMA bear, volume spike, RSI < 50)
    - Vào SHORT khi price đang ở vùng trên của range phân phối
    - Range phân phối = Swing High - Swing Low trong N nến

Cách tính Range Phân phối:
    - swing_high = highest(high, swing_window)
    - swing_low = lowest(low, swing_window)  
    - range = swing_high - swing_low
    - upper_zone = swing_low + range * upper_zone_threshold
    - middle_zone = swing_low + range * 0.50

Tín hiệu SHORT khi:
    - close < upper_zone (giá đang ở vùng trên của range)
    - AND (EMA bearish alignment HOẶC các filter khác)
    - AND giá gần đỉnh (close gần swing_high)
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


class DistributionStrategy(BaseStrategy):
    """
    Distribution Strategy - Phát hiện giai đoạn phân phối đỉnh trên chart 1D.
    
    Reads configuration from config/strategies/distribution_strategy.yaml
    """

    name = "DistributionStrategy"

    _DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "strategies" / "distribution_strategy.yaml"

    def __init__(self, config_path: Optional[str] = None):
        cfg_path = config_path or self._DEFAULT_CONFIG_PATH
        with open(cfg_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.timeframe = self.config.get("timeframe", "1d")
        self.htf_timeframe = self.config.get("htf_timeframe", "1w")

        # Distribution detection params
        dist = self.config.get("distribution", {})
        self.lookback_period = dist.get("lookback_period", 30)
        self.range_calc_method = dist.get("range_calc_method", "swing")
        self.swing_window = dist.get("swing_window", 20)
        self.upper_zone_threshold = dist.get("upper_zone_threshold", 0.70)
        self.lower_zone_threshold = dist.get("lower_zone_threshold", 0.30)

        # Indicators
        ind = self.config.get("indicators", {})
        self.ema_lengths = ind.get("ema_lengths", [20, 50, 200])
        self.rsi_period = ind.get("rsi_period", 14)
        self.volume_ma_period = ind.get("volume_ma_period", 20)
        self.atr_period = ind.get("atr_period", 14)

        # Filters
        filt = self.config.get("filters", {})
        self.require_ema_bearish = filt.get("require_ema_bearish", True)
        self.require_volume_spike = filt.get("require_volume_spike", False)
        self.require_rsi_bearish = filt.get("require_rsi_bearish", False)
        self.min_volume_ratio = filt.get("min_volume_ratio", 1.5)
        self.require_adx_strong = filt.get("require_adx_strong", False)
        self.adx_threshold = filt.get("adx_threshold", 25)

        # Signal params
        sig = self.config.get("signal", {})
        self.lookback_candles = sig.get("lookback_candles", 3)
        self.min_candles_required = sig.get("min_candles_required", 200)
        self.cooldown_period = sig.get("cooldown_period", 5)

        # Entry zones
        entry = self.config.get("entry_zones", {})
        self.upper_range_entry = entry.get("upper_range_entry", True)
        self.middle_range_entry = entry.get("middle_range_entry", False)
        self.allow_reentry = entry.get("allow_reentry", False)

        # Risk management
        rm = self.config.get("risk_management", {})
        self.sl_pct = rm.get("sl_pct", 0.05)
        self.sl_atr_mult = rm.get("sl_atr_multiplier", 2.0)
        self.tp_levels = rm.get("tp_levels", [0.05, 0.10, 0.15])
        self.tp_size = rm.get("tp_size", 0.33)
        self.max_holding = rm.get("max_holding", 30)
        self.trailing_sl = rm.get("trailing_sl", True)
        self.trailing_atr_mult = rm.get("trailing_atr_mult", 1.5)

        # Position sizing
        pos = self.config.get("position_sizing", {})
        self.default_size_pct = pos.get("default_size_pct", 10)
        self.max_positions = pos.get("max_positions", 5)
        self.reduce_on_consecutive_losses = pos.get("reduce_on_consecutive_losses", True)
        self.max_consecutive_losses = pos.get("max_consecutive_losses", 3)

        # Setups
        self.setups = self.config.get("setups", [
            {"name": "Distribution Short", "signal_type": "SHORT", "enabled": True},
        ])

        # Track last signal index per symbol to prevent repeat entries
        self.last_signal_indices = {}
        self.cooldown_tracker = {}  # {symbol: bars_since_signal}

        logger.info(f"[DistributionStrategy] Loaded from {cfg_path} (TF: {self.timeframe})")

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Tính toán các chỉ báo cho detection phase:
        - Swing High/Low để tính range phân phối
        - EMA alignment cho trend confirmation
        - RSI, Volume, ADX cho filter
        """
        if not self.validate_df(df):
            raise ValueError("DataFrame thiếu các cột OHLCV cần thiết")

        df = df.copy()

        # 1. Swing High/Low cho range phân phối
        df["swing_high"] = df["high"].rolling(window=self.swing_window).max()
        df["swing_low"] = df["low"].rolling(window=self.swing_window).min()
        df["distribution_range"] = df["swing_high"] - df["swing_low"]

        # 2. Vùng giá (Zones)
        df["upper_zone"] = df["swing_low"] + df["distribution_range"] * self.upper_zone_threshold
        df["middle_zone"] = df["swing_low"] + df["distribution_range"] * 0.50
        df["lower_zone"] = df["swing_low"] + df["distribution_range"] * self.lower_zone_threshold

        # 3. Vị trí hiện tại trong range (0 = bottom, 1 = top)
        df["range_position"] = np.where(
            df["distribution_range"] > 0,
            (df["close"] - df["swing_low"]) / df["distribution_range"],
            0.5
        )

        # 4. Khoảng cách đến các vùng
        df["dist_to_swing_high"] = (df["swing_high"] - df["close"]) / df["close"]
        df["dist_to_upper_zone"] = (df["upper_zone"] - df["close"]) / df["close"]

        # 5. EMA cho trend confirmation
        for length in self.ema_lengths:
            df[f"ema_{length}"] = ta.ema(df["close"], length=length)

        # EMA bearish alignment: EMA20 < EMA50 < EMA200
        df["ema_bearish_alignment"] = (
            (df["ema_20"] < df["ema_50"]) & 
            (df["ema_50"] < df["ema_200"])
        ) if 200 in self.ema_lengths else False

        # 6. RSI
        df["rsi"] = ta.rsi(df["close"], length=self.rsi_period)
        df["rsi_bearish"] = df["rsi"] < 50

        # 7. Volume analysis
        df["volume_ma"] = ta.sma(df["volume"], length=self.volume_ma_period)
        df["volume_ratio"] = df["volume"] / df["volume_ma"]
        df["volume_spike"] = df["volume_ratio"] > self.min_volume_ratio

        # 8. ATR for SL/TP
        df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=self.atr_period)

        # 9. ADX for trend strength (optional filter)
        adx_data = ta.adx(df["high"], df["low"], df["close"], length=14)
        df["adx"] = adx_data[f"ADX_14"] if f"ADX_14" in adx_data.columns else 25
        df["adx_strong"] = df["adx"] > self.adx_threshold

        # 10. Price action signals
        # Kiểm tra price đang ở gần swing high (potential distribution)
        df["near_swing_high"] = df["dist_to_swing_high"] < 0.05  # within 5% of swing high
        
        # Kiểm tra có lower high trong swing window
        df["lower_highs"] = (
            df["high"] < df["high"].shift(1)
        )

        # 11. Distribution score (0-100)
        # Cao hơn = likely distribution phase hơn
        df["distribution_score"] = 0
        
        # Score: Giá ở vùng trên
        df.loc[df["range_position"] > self.upper_zone_threshold, "distribution_score"] += 40
        
        # Score: Gần swing high
        df.loc[df["near_swing_high"], "distribution_score"] += 20
        
        # Score: EMA bearish
        df.loc[df["ema_bearish_alignment"], "distribution_score"] += 20
        
        # Score: RSI bearish
        df.loc[df["rsi_bearish"], "distribution_score"] += 10
        
        # Score: Volume spike
        df.loc[df["volume_spike"], "distribution_score"] += 10

        logger.debug(f"[DistributionStrategy] Computed indicators for {len(df)} rows")

        return df

    def generate_signals(self, df: pd.DataFrame, symbol: str = None, is_live: bool = False) -> pd.DataFrame:
        """
        Generate SHORT signals when:
        1. Price is in upper zone of distribution range
        2. Has bearish confirmation filters
        
        Args:
            df: DataFrame with computed indicators
            symbol: Trading symbol (for compatibility)
            is_live: Whether running in live mode (for compatibility)
        """
        df = df.copy()
        
        # Initialize columns
        df["signal"] = 0
        df["signal_type"] = ""
        df["entry_reason"] = ""

        # Need minimum candles for valid signals
        min_candles = self.min_candles_required
        
        for i in range(min_candles, len(df)):
            row = df.iloc[i]
            prev_rows = df.iloc[max(0, i - self.lookback_candles):i]
            
            # Skip if in cooldown
            symbol = df.index[i] if hasattr(df.index[i], '__str__') else str(i)
            if symbol in self.cooldown_tracker:
                self.cooldown_tracker[symbol] -= 1
                if self.cooldown_tracker[symbol] > 0:
                    continue
                else:
                    del self.cooldown_tracker[symbol]
            
            # ==== Distribution SHORT Signal Logic ====
            
            # Condition 1: Giá đang ở vùng trên của range
            in_upper_zone = row["range_position"] > self.upper_zone_threshold
            
            # Condition 2: Giá gần swing high (đang phân phối ở đỉnh)
            near_top = row["near_swing_high"]
            
            # Condition 3: Bearish filters
            ema_ok = not self.require_ema_bearish or row["ema_bearish_alignment"]
            rsi_ok = not self.require_rsi_bearish or row["rsi_bearish"]
            vol_ok = not self.require_volume_spike or row["volume_spike"]
            adx_ok = not self.require_adx_strong or row["adx_strong"]
            
            all_filters_ok = ema_ok and rsi_ok and vol_ok and adx_ok
            
            # ==== Generate Signal ====
            if self.upper_range_entry and in_upper_zone and all_filters_ok:
                # Check if any previous candle in lookback had signal (prevent duplicate)
                prev_signals = prev_rows["signal"].values
                if not any(prev_signals == -1):  # No SHORT signal in lookback window
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_type")] = "SHORT"
                    
                    # Entry reason for logging
                    reasons = []
                    if in_upper_zone:
                        reasons.append(f"upper_zone({row['range_position']:.2f})")
                    if near_top:
                        reasons.append("near_top")
                    if row["ema_bearish_alignment"]:
                        reasons.append("ema_bear")
                    if row["rsi_bearish"]:
                        reasons.append("rsi_bear")
                    if row["volume_spike"]:
                        reasons.append("vol_spike")
                    df.iloc[i, df.columns.get_loc("entry_reason")] = ",".join(reasons)
                    
                    # Set cooldown
                    self.cooldown_tracker[symbol] = self.cooldown_period
                    
                    logger.debug(
                        f"[DistributionStrategy] SHORT @ {row['close']:.4f} "
                        f"(range_pos={row['range_position']:.2f}, score={row['distribution_score']})"
                    )

        return df

    def get_sl_tp(
        self,
        entry_price: float,
        signal: int,
        atr: Optional[float] = None,
    ) -> tuple[float, float]:
        """
        Tính SL và TP cho distribution SHORT:
        - SL: Phía trên entry (vì SHORT)
        - TP: Phía dưới entry
        """
        if signal == -1:  # SHORT
            # Stop-loss: phía trên entry
            if atr and atr > 0:
                sl = entry_price + (atr * self.sl_atr_mult)
            else:
                sl = entry_price * (1 + self.sl_pct)
            
            # Take-profit: sử dụng tp_levels đầu tiên
            tp = entry_price * (1 - self.tp_levels[0])
            
            return (sl, tp)
        else:
            # Fallback
            sl = entry_price * (1 - self.sl_pct)
            tp = entry_price * (1 + self.tp_levels[0])
            return (sl, tp)

    def get_tp_levels(self, entry_price: float) -> list[tuple[float, float]]:
        """
        Trả về các cấp TP với tỷ lệ chốt.
        Format: [(price, size_pct), ...]
        """
        levels = []
        remaining = 1.0
        
        for i, tp_pct in enumerate(self.tp_levels):
            tp_price = entry_price * (1 - tp_pct)
            if i < len(self.tp_levels) - 1:
                size = self.tp_size
            else:
                size = remaining
            levels.append((tp_price, size))
            remaining -= size
            
        return levels

    def to_dict(self) -> dict:
        """Return strategy metadata as a dict."""
        return {
            "name": self.name,
            "timeframe": self.timeframe,
            "upper_zone_threshold": self.upper_zone_threshold,
            "swing_window": self.swing_window,
            "require_ema_bearish": self.require_ema_bearish,
        }

    def __repr__(self) -> str:
        return (
            f"<DistributionStrategy TF={self.timeframe} "
            f"upper_zone={self.upper_zone_threshold:.0%}>"
        )
