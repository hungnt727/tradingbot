"""
Abstract base class for all trading strategies.
Every strategy must inherit from this class and implement the abstract methods.
"""
from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd


class BaseStrategy(ABC):
    """
    Abstract base class for trading strategies.

    Subclasses must implement:
        - name: str class attribute
        - timeframe: str class attribute
        - compute_indicators(df) -> DataFrame
        - generate_signals(df) -> DataFrame
        - get_sl_tp(entry_price, signal, atr) -> (float, float)
    """

    name: str = "BaseStrategy"
    timeframe: str = "1h"

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all technical indicators needed by this strategy.

        Args:
            df: OHLCV DataFrame with columns [open, high, low, close, volume].
                Index must be DatetimeIndex (UTC).

        Returns:
            DataFrame with additional indicator columns appended.
        """
        ...

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trading signals based on computed indicators.

        Args:
            df: DataFrame returned by compute_indicators().

        Returns:
            DataFrame with columns added:
                - signal      : int  → 1=LONG, -1=SHORT, 0=HOLD
                - signal_type : str  → 'LONG' | 'SHORT' | ''
        """
        ...

    @abstractmethod
    def get_sl_tp(
        self,
        entry_price: float,
        signal: int,
        atr: Optional[float] = None,
    ) -> tuple[float, float]:
        """
        Calculate stop-loss and take-profit prices for an entry.

        Args:
            entry_price: The price at which the position is entered.
            signal:      1 for LONG, -1 for SHORT.
            atr:         Average True Range value (used for ATR-based SL/TP).

        Returns:
            Tuple of (stop_loss_price, take_profit_price).
        """
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def validate_df(self, df: pd.DataFrame) -> bool:
        """Check that DataFrame has required OHLCV columns."""
        required = {"open", "high", "low", "close", "volume"}
        return required.issubset(set(df.columns))

    def to_dict(self) -> dict:
        """Return strategy metadata as a dict (for logging/backtest reports)."""
        return {
            "name": self.name,
            "timeframe": self.timeframe,
        }

    def __repr__(self) -> str:
        return f"<{self.name} timeframe={self.timeframe}>"
