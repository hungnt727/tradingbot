"""
Simple SonicR Backtest - Chỉ chạy trên số nến gần đây, xuất kết quả quan trọng nhất
"""
import os
import sys
import requests
import pandas as pd
import numpy as np
import pandas_ta as ta
import ccxt

sys.stdout.reconfigure(encoding='utf-8')

# --- CẤU HÌNH ĐƠN GIẢN ---
CMC_API_KEY = 'a2d1ccdd-c9b4-4e30-b3ac-c0ed36849565'  # CoinMarketCap API Key
TOP_N_COINS = 300        # Lấy top N coin có vốn hóa lớn nhất
TIMEFRAME = '15m'        # Khung thờ gian
LOOKBACK_CANDLES = 1000  # Chỉ tìm tín hiệu trong N nến gần đây nhất
# Lưu ý: Cần lấy thêm 610 nến để tính EMA610, tổng = 610 + LOOKBACK_CANDLES

# Cấu hình giao dịch
SL_PCT = 0.02                # Stoploss 2%
TP_LEVELS = [0.02, 0.04]     # Take profit 2%, 4%
TP_SIZE = 0.50               # Đóng 50% mỗi TP
MAX_HOLDING = 100            # Tối đa 100 nến

# SonicR Config
EMA_LENGTHS = [34, 89, 200, 610]
RSI_LENGTH = 14
EMA_RSI_LENGTHS = [5, 10, 20]

# Khởi tạo exchange
exchange = ccxt.bybit({'options': {'defaultType': 'linear'}})


def get_top_coins():
    """Lấy danh sách top coin từ CoinMarketCap"""
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'
    params = {'start': '1', 'limit': str(TOP_N_COINS), 'convert': 'USDT'}
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': CMC_API_KEY}
    
    try:
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        if 'data' in data:
            symbols = [f"{coin['symbol']}/USDT" for coin in data['data']]
            markets = exchange.load_markets()
            return [s for s in symbols if s in markets]
    except Exception as e:
        print(f"❌ Lỗi lấy danh sách coin: {e}")
    
    # Fallback về BTC nếu lỗi
    return ['BTC/USDT']


def fetch_data(symbol, timeframe, limit=500):
    """Lấy dữ liệu OHLCV"""
    try:
        # Nếu limit > 1000, ta phân trang để lấy đủ dữ liệu thay vì bị giới hạn
        timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
        since = exchange.milliseconds() - limit * timeframe_ms
        all_ohlcv = []
        
        while len(all_ohlcv) < limit:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
            if not ohlcv:
                break
                
            # Loại bỏ nến trùng lặp ở biên giao cắt
            if all_ohlcv and ohlcv[0][0] <= all_ohlcv[-1][0]:
                ohlcv = [x for x in ohlcv if x[0] > all_ohlcv[-1][0]]
                if not ohlcv:
                    break
                    
            all_ohlcv.extend(ohlcv)
            since = ohlcv[-1][0] + 1
            
        df = pd.DataFrame(all_ohlcv[-limit:], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"❌ Lỗi lấy dữ liệu: {e}")
        return None


def calculate_indicators(df):
    """Tính các chỉ báo cần thiết"""
    if len(df) < 610:
        print(f"⚠️ Không đủ dữ liệu (cần 610 nến, có {len(df)})")
        return None
    
    # EMAs
    for length in EMA_LENGTHS:
        df[f'ema_{length}'] = ta.ema(df['close'], length=length)
    
    # RSI & EMA RSI
    df['rsi'] = ta.rsi(df['close'], length=RSI_LENGTH)
    for length in EMA_RSI_LENGTHS:
        df[f'ema_rsi_{length}'] = ta.ema(df['rsi'], length=length)
    
    return df


def check_short_signal(df, idx):
    """Kiểm tra tín hiệu SHORT SonicR"""
    if idx < 610:
        return False
    
    candle = df.iloc[idx]
    
    # Kiểm tra NaN
    required_cols = ['ema_34', 'ema_89', 'ema_200', 'ema_610', 'ema_rsi_5', 'ema_rsi_10', 'ema_rsi_20']
    if any(pd.isna(candle[col]) for col in required_cols):
        return False
    
    # Điều kiện EMA: 34 < 89 < 200 < 610 (xu hướng giảm)
    ema_ok = (candle['ema_34'] < candle['ema_89'] < candle['ema_200'] < candle['ema_610'])
    
    # Điều kiện RSI: ema_rsi_5 < ema_rsi_10 và ema_rsi_5 < ema_rsi_20
    rsi_ok = (candle['ema_rsi_5'] < candle['ema_rsi_10']) and (candle['ema_rsi_5'] < candle['ema_rsi_20'])
    
    if not (ema_ok and rsi_ok):
        return False
    
    # Kiểm tra reversal: nến trước KHÔNG thỏa mãn
    prev = df.iloc[idx - 1]
    prev_ema_ok = (prev['ema_34'] < prev['ema_89'] < prev['ema_200'] < prev['ema_610'])
    prev_rsi_ok = (prev['ema_rsi_5'] < prev['ema_rsi_10']) and (prev['ema_rsi_5'] < prev['ema_rsi_20'])
    
    return not (prev_ema_ok and prev_rsi_ok)


def simulate_trade(df, entry_idx, entry_price):
    """Mô phỏng 1 giao dịch SHORT"""
    sl_price = entry_price * (1 + SL_PCT)
    tp1_price = entry_price * (1 - TP_LEVELS[0])
    tp2_price = entry_price * (1 - TP_LEVELS[1])
    
    tp1_hit = tp2_hit = False
    remaining = 1.0
    total_pnl = 0.0
    exit_reason = 'TIMEOUT'
    exit_candle = None
    
    for i in range(1, len(df) - entry_idx):
        candle = df.iloc[entry_idx + i]
        
        # Check SL
        if candle['high'] >= sl_price:
            # BUG FIX: Tính đúng PnL thực tế theo mức giá Stoploss đã chạm
            # Nếu SL đã được dời về entry_price, pnl = 0 thay vì mặc định bị trừ SL_PCT
            pnl = ((entry_price - sl_price) / entry_price) * remaining
            total_pnl += pnl
            
            if sl_price == entry_price:
                exit_reason = f'SL_BREAKEVEN'
            else:
                exit_reason = f'SL_HIT_{remaining*100:.0f}%'
                
            exit_candle = i
            remaining = 0
            break
        
        # Check TP1
        if not tp1_hit and candle['low'] <= tp1_price:
            total_pnl += TP_LEVELS[0] * TP_SIZE
            tp1_hit = True
            remaining -= TP_SIZE
            sl_price = entry_price  # Dồi SL lên entry
        
        # Check TP2
        if tp1_hit and not tp2_hit and candle['low'] <= tp2_price:
            total_pnl += TP_LEVELS[1] * TP_SIZE
            tp2_hit = True
            remaining -= TP_SIZE
            exit_reason = 'FULL_TP'
            exit_candle = i
            break
        
        # Timeout với lãi
        if i >= MAX_HOLDING and remaining > 0:
            current_pnl = (entry_price - candle['close']) / entry_price
            if total_pnl + (current_pnl * remaining) > 0:
                total_pnl += current_pnl * remaining
                exit_reason = 'TIMEOUT_PROFIT'
                exit_candle = i
                remaining = 0
                break
    
    # Đóng vị thế còn lại (Kéo dài đến hết dữ liệu mà vẫn lỗ)
    if remaining > 0:
        last_candle = df.iloc[len(df) - 1]
        pnl = (entry_price - last_candle['close']) / entry_price
        total_pnl += pnl * remaining
        exit_candle = len(df) - 1 - entry_idx
        exit_reason = 'END_OF_DATA'
    
    return {
        'pnl_pct': total_pnl,
        'exit_candles': exit_candle or MAX_HOLDING,
        'exit_reason': exit_reason,
        'tp1_hit': tp1_hit,
        'tp2_hit': tp2_hit
    }


def backtest_symbol(symbol):
    """Backtest 1 symbol, trả về danh sách trades"""
    total_candles_needed = 610 + LOOKBACK_CANDLES
    
    df = fetch_data(symbol, TIMEFRAME, limit=total_candles_needed)
    if df is None:
        return []
    
    df = calculate_indicators(df)
    if df is None:
        return []
    
    # Chỉ tìm tín hiệu trong N nến gần nhất
    start_idx = len(df) - LOOKBACK_CANDLES
    trades = []
    
    for i in range(start_idx, len(df) - 5):
        if check_short_signal(df, i):
            candle = df.iloc[i]
            result = simulate_trade(df, i, candle['close'])
            
            trades.append({
                'symbol': symbol,
                'entry_time': candle['timestamp'].strftime('%m-%d %H:%M'),
                'entry_price': candle['close'],
                'pnl_pct': result['pnl_pct'],
                'exit_candles': result['exit_candles'],
                'exit_reason': result['exit_reason'],
                'tp1_hit': result['tp1_hit'],
                'tp2_hit': result['tp2_hit']
            })
    
    return trades


def run_backtest():
    """Chạy backtest trên nhiều symbol"""
    print("=" * 70)
    print(f"🚀 SIMPLE SONICR BACKTEST - MULTI COIN")
    print(f"   Timeframe: {TIMEFRAME} | Top {TOP_N_COINS} coins | {LOOKBACK_CANDLES} nến gần nhất")
    print("=" * 70)
    
    # Lấy danh sách coin
    print(f"\n📥 Đang lấy top {TOP_N_COINS} coin từ CoinMarketCap...")
    symbols = get_top_coins()
    print(f"   Tìm thấy {len(symbols)} coin trên Bybit\n")
    
    # Backtest từng coin
    all_trades = []
    for i, symbol in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {symbol}...", end=' ')
        trades = backtest_symbol(symbol)
        all_trades.extend(trades)
        print(f"{len(trades)} giao dịch")
    
    # KẾT QUẢ QUAN TRỌNG NHẤT
    print("\n" + "=" * 70)
    print("📈 KẾT QUẢ TỔNG HỢP")
    print("=" * 70)
    
    total_trades = len(all_trades)
    if total_trades == 0:
        print("\n❌ Không tìm thấy tín hiệu nào")
        return
    
    wins = sum(1 for t in all_trades if t['pnl_pct'] > 0)
    losses = total_trades - wins
    win_rate = (wins / total_trades) * 100
    total_pnl = sum(t['pnl_pct'] for t in all_trades)
    avg_pnl = total_pnl / total_trades
    
    # Hiển thị metrics chính
    print(f"\n┌{'─'*68}┐")
    print(f"│  TỔNG COIN CÓ TÍN HIỆU:  {len(set(t['symbol'] for t in all_trades)):>8}                       │")
    print(f"│  TỔNG GIAO DỊCH:         {total_trades:>8}                       │")
    print(f"│  WIN RATE:               {win_rate:>7.1f}%  ({wins}W / {losses}L)             │")
    print(f"│  TỔNG PnL:               {total_pnl*100:>+7.2f}%                          │")
    print(f"│  PnL TRUNG BÌNH/GD:      {avg_pnl*100:>+7.2f}%                          │")
    print(f"└{'─'*68}┘")
    
    # Top 10 giao dịch gần nhất
    print(f"\n📋 10 GIAO DỊCH GẦN NHẤT:")
    print(f"{'Symbol':<12} {'Time':<12} {'Entry':<10} {'PnL%':<8} {'Exit':<15}")
    print("-" * 70)
    
    for t in all_trades[-10:]:
        pnl_str = f"{t['pnl_pct']*100:+.2f}%"
        print(f"{t['symbol']:<12} {t['entry_time']:<12} {t['entry_price']:<10.2f} {pnl_str:<8} {t['exit_reason']:<15}")
    
    # Thống kê lý do thoát
    print(f"\n📊 LÝ DO THOÁT:")
    reasons = {}
    for t in all_trades:
        reasons[t['exit_reason']] = reasons.get(t['exit_reason'], 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        pct = (count / total_trades) * 100
        print(f"   {reason:<20}: {count:>3} giao dịch ({pct:>5.1f}%)")
    
    # Lưu kết quả
    os.makedirs('output', exist_ok=True)
    df_trades = pd.DataFrame(all_trades)
    output_file = f'output/simple_backtest_top{TOP_N_COINS}_{TIMEFRAME}.csv'
    df_trades.to_csv(output_file, index=False)
    print(f"\n💾 Đã lưu: {output_file}")


if __name__ == "__main__":
    run_backtest()
