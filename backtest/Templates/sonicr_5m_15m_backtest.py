import os
import requests
import pandas as pd
import numpy as np
import pandas_ta as ta
import ccxt
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- CẤU HÌNH ---
COINMARKETCAP_API_KEY = 'a2d1ccdd-c9b4-4e30-b3ac-c0ed36849565'
TOP_N_COINS = 100

# Cấu hình cho từng khung thờ gian
TIMEFRAME_CONFIGS = {
    '5m': {
        'sl_pct': 0.01,      # 1%
        'tp_levels': [0.01, 0.02],  # 1%, 2%
        'tp_position_size': 0.50,   # 50% mỗi lần
        'max_holding': 100,  # ~8 giờ
        'htf': '1h'
    },
    '15m': {
        'sl_pct': 0.02,      # 2%
        'tp_levels': [0.02, 0.04],  # 2%, 4%
        'tp_position_size': 0.50,   # 50% mỗi lần
        'max_holding': 80,   # ~20 giờ
        'htf': '4h'
    }
}

# Sonic R Config
SUPER_TREND_LENGTH = 10
SUPER_TREND_MULTIPLIER = 3.0
SONICR_SIGNAL_WINDOW = 1
SONICR_SETUP = {
    'name': 'SonicR Short',
    'enabled': True,
    'signal_type': 'SHORT',
    'enable_ichimoku': False,
    'enable_volume_filter': False,
    'enable_super_trend': False,
    'enable_htf_super_trend': True,
    'max_cross_ago': 1000
}

exchange = ccxt.bybit({
    'options': {'defaultType': 'linear'}
})

def get_top_coins():
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'
    parameters = {'start': '1', 'limit': str(TOP_N_COINS), 'convert': 'USDT'}
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': COINMARKETCAP_API_KEY}
    try:
        response = requests.get(url, params=parameters, headers=headers)
        data = response.json()
        if 'data' in data:
            symbols = [f"{coin['symbol']}/USDT" for coin in data['data']]
            markets = exchange.load_markets()
            return [s for s in symbols if s in markets]
    except Exception as e:
        print(f"Lỗi: {e}")
    return []

def get_ohlcv(symbol, timeframe, limit=1000):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except:
        return None

def calculate_indicators(df):
    if df is None or len(df) < 610:
        return None
    try:
        df['ema_34'] = ta.ema(df['close'], length=34)
        df['ema_89'] = ta.ema(df['close'], length=89)
        df['ema_200'] = ta.ema(df['close'], length=200)
        df['ema_610'] = ta.ema(df['close'], length=610)
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['ema_rsi_5'] = ta.ema(df['rsi'], length=5)
        df['ema_rsi_10'] = ta.ema(df['rsi'], length=10)
        df['ema_rsi_20'] = ta.ema(df['rsi'], length=20)
        df['vol_ma_20'] = df['volume'].rolling(window=20).mean()
        
        sti = ta.supertrend(df['high'], df['low'], df['close'], 
                           length=SUPER_TREND_LENGTH, multiplier=SUPER_TREND_MULTIPLIER)
        if sti is not None and not sti.empty:
            df = pd.concat([df, sti], axis=1)
    except:
        return None
    return df

def check_sonicr_signal(df, idx, htf_df=None):
    if df is None or len(df) < 610 or idx < 610 or idx >= len(df):
        return False
    
    candle = df.iloc[idx]
    if pd.isna(candle['ema_34']) or pd.isna(candle['ema_89']) or \
       pd.isna(candle['ema_200']) or pd.isna(candle['ema_610']) or \
       pd.isna(candle['ema_rsi_5']) or pd.isna(candle['ema_rsi_10']) or pd.isna(candle['ema_rsi_20']):
        return False
    
    # HTF check
    htf_st_dir = None
    if htf_df is not None and not htf_df.empty:
        try:
            htf_sti = ta.supertrend(htf_df['high'], htf_df['low'], htf_df['close'],
                                   length=SUPER_TREND_LENGTH, multiplier=SUPER_TREND_MULTIPLIER)
            if htf_sti is not None and not htf_sti.empty:
                htf_df_temp = pd.concat([htf_df, htf_sti], axis=1)
                cols = [c for c in htf_df_temp.columns if c.startswith('SUPERTd_')]
                if cols:
                    htf_st_dir = htf_df_temp.iloc[-1][cols[0]]
        except:
            pass
    
    c = candle['close']
    e34, e89, e200, e610 = candle['ema_34'], candle['ema_89'], candle['ema_200'], candle['ema_610']
    
    # SHORT conditions
    ema_ok = (e34 < e89 and e89 < e200 and e200 < e610)
    ema_rsi_ok = (candle['ema_rsi_5'] < candle['ema_rsi_10'] and candle['ema_rsi_5'] < candle['ema_rsi_20'])
    htf_st_ok = htf_st_dir is None or htf_st_dir < 0
    
    curr_state = ema_ok and ema_rsi_ok
    if not curr_state or not htf_st_ok:
        return False
    
    # Check reversal
    for k in range(SONICR_SIGNAL_WINDOW + 1):
        if idx - k - 1 < 0:
            break
        prev = df.iloc[idx - k - 1]
        p_ema_ok = (prev['ema_34'] < prev['ema_89'] < prev['ema_200'] < prev['ema_610'])
        p_ema_rsi_ok = (prev['ema_rsi_5'] < prev['ema_rsi_10'] and prev['ema_rsi_5'] < prev['ema_rsi_20'])
        p_state = p_ema_ok and p_ema_rsi_ok
        
        if k == 0 and p_state:
            break
        if curr_state and not p_state:
            return True
        if not p_state:
            break
    return False

def simulate_trade(df, entry_idx, entry_price, config):
    """Mô phỏng giao dịch với TP 2 mức."""
    if entry_idx >= len(df) - 1:
        return None
    
    sl_pct = config['sl_pct']
    tp_levels = config['tp_levels']
    tp_position_size = config['tp_position_size']
    max_holding = config['max_holding']
    
    sl_price = entry_price * (1 + sl_pct)
    tp1_hit = False
    tp2_hit = False
    tp1_candle_idx = None
    tp2_candle_idx = None
    remaining_position = 1.0
    total_pnl = 0.0
    exit_reason = 'TIMEOUT'
    exit_price = None
    exit_candle = None
    
    for i in range(1, min(max_holding + 1, len(df) - entry_idx)):
        candle = df.iloc[entry_idx + i]
        
        # Check SL
        if candle['high'] >= sl_price:
            sl_pct_from_entry = (sl_price - entry_price) / entry_price
            pnl = sl_pct_from_entry * remaining_position
            total_pnl += pnl
            exit_price = sl_price
            exit_candle = i
            exit_reason = f'SL_HIT_{remaining_position*100:.0f}%'
            remaining_position = 0
            break
        
        # Check TP1
        if not tp1_hit:
            tp1_price = entry_price * (1 - tp_levels[0])
            if candle['low'] <= tp1_price:
                tp_pnl = tp_levels[0] * tp_position_size
                total_pnl += tp_pnl
                tp1_hit = True
                tp1_candle_idx = i
                remaining_position -= tp_position_size
                sl_price = entry_price  # Dồi SL lên BE
        
        # Check TP2
        if tp1_hit and not tp2_hit:
            tp2_price = entry_price * (1 - tp_levels[1])
            if candle['low'] <= tp2_price:
                tp_pnl = tp_levels[1] * tp_position_size
                total_pnl += tp_pnl
                tp2_hit = True
                tp2_candle_idx = i
                remaining_position -= tp_position_size
                exit_price = tp2_price
                exit_candle = i
                exit_reason = 'FULL_TP'
                break
        
        # Timeout với lãi
        if i >= max_holding and remaining_position > 0:
            current_pnl_pct = (entry_price - candle['close']) / entry_price
            total_current_pnl = total_pnl + (current_pnl_pct * remaining_position)
            if total_current_pnl > 0:
                pnl = current_pnl_pct * remaining_position
                total_pnl += pnl
                exit_price = candle['close']
                exit_candle = i
                exit_reason = 'TIMEOUT_PROFIT'
                remaining_position = 0
                break
        
        if remaining_position <= 0:
            break
    
    # Close remaining
    if remaining_position > 0:
        last_idx = min(entry_idx + max_holding, len(df) - 1)
        last_candle = df.iloc[last_idx]
        exit_price = last_candle['close']
        exit_candle = last_idx - entry_idx
        pnl = ((entry_price - exit_price) / entry_price) * remaining_position
        total_pnl += pnl
    
    return {
        'exit_price': exit_price,
        'exit_candles': exit_candle,
        'exit_reason': exit_reason,
        'total_pnl_pct': total_pnl,
        'tp1_hit': tp1_hit,
        'tp2_hit': tp2_hit,
        'tp1_candle': tp1_candle_idx,
        'tp2_candle': tp2_candle_idx
    }

def backtest_symbol(symbol, timeframe, config):
    df = get_ohlcv(symbol, timeframe, limit=1000)
    if df is None or len(df) < 610:
        return []
    
    df = calculate_indicators(df)
    if df is None:
        return []
    
    htf_df = get_ohlcv(symbol, config['htf'], limit=500)
    
    trades = []
    for i in range(610, len(df) - 10):
        if check_sonicr_signal(df, i, htf_df):
            candle = df.iloc[i]
            entry_price = candle['close']
            
            result = simulate_trade(df, i, entry_price, config)
            if result:
                trade = {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'entry_time': candle['timestamp'],
                    'entry_price': entry_price,
                    'exit_price': result['exit_price'],
                    'exit_candles': result['exit_candles'],
                    'exit_reason': result['exit_reason'],
                    'pnl_pct': result['total_pnl_pct'],
                    'tp1_hit': result['tp1_hit'],
                    'tp2_hit': result['tp2_hit'],
                    'tp1_candle': result['tp1_candle'],
                    'tp2_candle': result['tp2_candle']
                }
                trades.append(trade)
    
    return trades

def run_backtest_timeframe(timeframe, config, coins):
    print(f"\n{'='*80}")
    print(f"BACKTEST: {timeframe} (SL {config['sl_pct']*100}%, TP {config['tp_levels'][0]*100}%/{config['tp_levels'][1]*100}%)")
    print(f"{'='*80}")
    
    all_trades = []
    for coin in coins:
        trades = backtest_symbol(coin, timeframe, config)
        all_trades.extend(trades)
    
    print(f"Tổng giao dịch: {len(all_trades)}")
    
    if not all_trades:
        return None
    
    df_trades = pd.DataFrame(all_trades)
    
    # Stats
    wins = df_trades[df_trades['pnl_pct'] > 0]
    losses = df_trades[df_trades['pnl_pct'] <= 0]
    
    total_pnl = df_trades['pnl_pct'].sum()
    win_rate = len(wins) / len(df_trades) * 100
    
    print(f"\n--- KẾT QUẢ {timeframe} ---")
    print(f"Tổng giao dịch: {len(df_trades)}")
    print(f"Winrate: {win_rate:.2f}% ({len(wins)} thắng / {len(losses)} thua)")
    print(f"Tổng PnL: {total_pnl*100:+.2f}%")
    print(f"PnL trung bình: {df_trades['pnl_pct'].mean()*100:+.2f}%")
    
    # TP time
    tp1_candles = df_trades[df_trades['tp1_hit'] == True]['tp1_candle'].dropna()
    tp2_candles = df_trades[df_trades['tp2_hit'] == True]['tp2_candle'].dropna()
    
    multiplier = 5 if timeframe == '5m' else 15  # minutes per candle
    
    if len(tp1_candles) > 0:
        avg_tp1_min = tp1_candles.mean() * multiplier
        print(f"\nThờ gian TB đạt TP1: {tp1_candles.mean():.1f} nến ({avg_tp1_min:.0f} phút)")
    if len(tp2_candles) > 0:
        avg_tp2_min = tp2_candles.mean() * multiplier
        print(f"Thờ gian TB đạt TP2: {tp2_candles.mean():.1f} nến ({avg_tp2_min:.0f} phút)")
    
    return df_trades

def run_backtest():
    print("=" * 80)
    print("SONIC R BACKTEST - KHUNG 5M & 15M")
    print("=" * 80)
    
    print("\n📐 THAM SỐ:")
    print("  5m:  SL 1% | TP 1%/2% | Max 100 nến (~8 giờ)")
    print("  15m: SL 2% | TP 2%/4% | Max 80 nến (~20 giờ)")
    print()
    
    print("Đang lấy danh sách coin...")
    coins = get_top_coins()
    print(f"Đã tìm thấy {len(coins)} coin\n")
    
    # Backtest 5m
    results_5m = run_backtest_timeframe('5m', TIMEFRAME_CONFIGS['5m'], coins)
    
    # Backtest 15m
    results_15m = run_backtest_timeframe('15m', TIMEFRAME_CONFIGS['15m'], coins)
    
    # Summary
    print("\n" + "=" * 80)
    print("TỔNG KẾT")
    print("=" * 80)
    
    if results_5m is not None:
        print(f"\n📊 5m:  {len(results_5m)} giao dịch | Winrate: {len(results_5m[results_5m['pnl_pct']>0])/len(results_5m)*100:.1f}% | PnL: {results_5m['pnl_pct'].sum()*100:+.0f}%")
    if results_15m is not None:
        print(f"📊 15m: {len(results_15m)} giao dịch | Winrate: {len(results_15m[results_15m['pnl_pct']>0])/len(results_15m)*100:.1f}% | PnL: {results_15m['pnl_pct'].sum()*100:+.0f}%")
    
    # Save
    os.makedirs('output', exist_ok=True)
    if results_5m is not None:
        results_5m.to_csv('output/sonicr_5m_backtest.csv', index=False)
        print(f"\n✅ 5m:  output/sonicr_5m_backtest.csv")
    if results_15m is not None:
        results_15m.to_csv('output/sonicr_15m_backtest.csv', index=False)
        print(f"✅ 15m: output/sonicr_15m_backtest.csv")

if __name__ == "__main__":
    run_backtest()
