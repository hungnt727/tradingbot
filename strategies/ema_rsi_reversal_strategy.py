import numpy as np
import pandas as pd
import pandas_ta as ta
from typing import Optional

from strategies.base_strategy import BaseStrategy


class EmaRsiReversalStrategy(BaseStrategy):
    """
    EMA RSI Reversal Strategy
    
    Định nghĩa nến đảo chiều:
        - ema_rsi_5 < ema_rsi_10 < ema_rsi_20
        - nến trước đó KHÔNG thỏa mãn điều kiện trên
    
    Tín hiệu (SHORT):
        - bars_since_reversal < max_distance_candles
        - ema_rsi_20 > 50
    """
    
    name: str = "EmaRsiReversal"
    timeframe: str = "1h"
    
    def __init__(self, rsi_period: int = 14, max_distance_candles: int = 20):
        self.rsi_period = rsi_period
        self.max_distance_candles = max_distance_candles
        self.min_candles_required = 100

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.validate_df(df):
            raise ValueError("DataFrame validation failed.")
            
        df = df.copy()
        
        # 1. Tính RSI
        rsi = ta.rsi(df['close'], length=self.rsi_period)
        df['rsi'] = rsi
        
        # 2. Tính EMA của RSI
        if rsi is not None and not rsi.dropna().empty:
            df['ema_rsi_5'] = ta.ema(rsi, length=5)
            df['ema_rsi_10'] = ta.ema(rsi, length=10)
            df['ema_rsi_20'] = ta.ema(rsi, length=20)
        else:
            df['ema_rsi_5'] = np.nan
            df['ema_rsi_10'] = np.nan
            df['ema_rsi_20'] = np.nan
            
        # 3. Xác định nến đảo chiều (suy yếu)
        # Điểm bắt đầu suy yếu: 5 < 10 < 20
        is_downward = (df['ema_rsi_5'] < df['ema_rsi_10']) & (df['ema_rsi_10'] < df['ema_rsi_20'])
        is_downward_prev = is_downward.shift(1).fillna(False)
        
        df['is_reversal'] = is_downward & (~is_downward_prev)
        
        # 4. Đếm số nến từ nến đảo chiều gần nhất
        # Tạo mask ở các vị trí có is_reversal = True
        reversal_indices = df.index[df['is_reversal']]
        
        # Tạo cột bars_since_reversal
        # Cách hiệu quả: Dùng forward fill
        reversal_series = pd.Series(np.nan, index=df.index)
        reversal_series[df['is_reversal']] = np.arange(len(df[df['is_reversal']]))
        reversal_series = reversal_series.ffill()
        
        # Index của nến reversal gần nhất
        last_reversal_idx_series = pd.Series(np.nan, index=df.index)
        last_reversal_idx_series[df['is_reversal']] = df.reset_index().index[df['is_reversal']]
        last_reversal_idx_series = last_reversal_idx_series.ffill()
        
        # Số nến tính từ reversal = index hiện tại - index của reversal gần nhất
        current_idx_series = pd.Series(df.reset_index().index.values, index=df.index)
        
        df['bars_since_reversal'] = current_idx_series - last_reversal_idx_series
        
        # Tính khoảng giá ATR để làm stoploss nếu cần
        atr = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['atr'] = atr
        
        return df

    def generate_signals(self, df: pd.DataFrame, is_live: bool = False) -> pd.DataFrame:
        """
        Tạo tín hiệu SHORT dựa trên chỉ báo được cấu hình cho khung thời gian này.
        """
        df = df.copy()
        
        df['signal'] = 0
        df['signal_type'] = ''
        df['entry_reason'] = ''
        
        # Tín hiệu SHORT khi:
        # 1. Thời gian kể từ khi bắt đầu suy yếu (bars_since_reversal) < max_distance_candles
        # 2. ema_rsi_20 > 50 (RSI vẫn nằm ở ngưỡng cao)
        # 3. Nến hiện tại VẪN ĐANG ở trạng thái suy yếu (5 < 10 < 20)
        
        is_downward = (df['ema_rsi_5'] < df['ema_rsi_10']) & (df['ema_rsi_10'] < df['ema_rsi_20'])
        condition = (df['bars_since_reversal'] < self.max_distance_candles) & (df['ema_rsi_20'] > 50) & is_downward
        
        df.loc[condition, 'signal'] = -1
        df.loc[condition, 'signal_type'] = 'SHORT'
        df.loc[condition, 'entry_reason'] = 'EMA_RSI_REVERSAL'
        
        return df

    def get_sl_tp(
        self,
        entry_price: float,
        signal: int,
        atr: Optional[float] = None,
    ) -> tuple[float, float]:
        """Tính toán SL / TP (có thể chỉnh sửa theo yêu cầu)"""
        # Trả về giá trị tham khảo, cụ thể được tính ở Bot.
        if signal == -1:  # SHORT
            if atr:
                sl = entry_price + (atr * 2)
                tp = entry_price - (atr * 3)
            else:
                sl = entry_price * 1.05
                tp = entry_price * 0.90
            return sl, tp
            
        return entry_price * 0.95, entry_price * 1.10
