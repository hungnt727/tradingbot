import os
import sys
import pandas as pd
import numpy as np
import yaml
from loguru import logger
from dotenv import load_dotenv

# Allow importing from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from data.storage.timescale_client import TimescaleClient
from strategies.ema_rsi_reversal_strategy import EmaRsiReversalStrategy
from cli.run_distribution_signal_bot import get_top_coins

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def simulate_trade(df, entry_idx, entry_price, config=None):
    """
    Simulate trade logic for EMA RSI Reversal with generic N-TP support.
    """
    if config is None:
        config = {
            "sl_pct": 0.05,
            "tp_levels": [0.10, 0.20],
            "tp_size": 0.5,
            "use_atr_sl": False,
            "atr_mult": 2.0,
            "use_trailing_stop": False,
            "use_rsi_exit": False,
            "no_move_sl_after_tp1": True
        }

    sl_pct = config.get("sl_pct", 0.10)
    tp_levels = config.get("tp_levels", [0.05, 0.10])
    num_tps = len(tp_levels)
    tp_size = config.get("tp_size", 1.0 / num_tps) # Default to equal split
    max_holding = 9600
    
    # Initial SL
    if config.get("use_atr_sl") and 'atr' in df.columns:
        atr_val = df.iloc[entry_idx]['atr']
        sl_price = entry_price * (1 + (atr_val/entry_price * config.get("atr_mult", 2.0)))
    else:
        sl_price = entry_price * (1 + sl_pct)
    
    trailing_sl_pct = config.get("trailing_sl_pct")
    
    # Target prices
    tp_prices = [entry_price * (1 - lv) for lv in tp_levels]
        
    next_tp_idx = 0
    remaining = 1.0
    total_pnl = 0.0
    
    for i in range(1, len(df) - entry_idx):
        candle = df.iloc[entry_idx + i]
        
        # Update trailing SL if enabled
        if trailing_sl_pct is not None:
            sl_price = min(sl_price, candle['close'] * (1 + trailing_sl_pct))
        
        # Check SL (SHORT: price goes up)
        if candle['high'] >= sl_price:
            pnl = ((entry_price - sl_price) / entry_price) * remaining
            total_pnl += pnl
            reason = "SL" if next_tp_idx == 0 else f"TP{next_tp_idx}_BE"
            return total_pnl, reason
        
        # Check TP(s)
        while next_tp_idx < num_tps and candle['low'] <= tp_prices[next_tp_idx]:
            # Hit a TP!
            total_pnl += tp_levels[next_tp_idx] * tp_size
            remaining -= tp_size
            next_tp_idx += 1
            
            # Update SL logic on first TP hit
            if next_tp_idx == 1:
                if config.get("use_trailing_stop"):
                    sl_price = max(df.iloc[entry_idx+i-2:entry_idx+i+1]['high']) * 1.005 
                elif config.get("trailing_after_tp1_pct") is not None:
                    sl_price = candle['close'] * (1 + config.get("trailing_after_tp1_pct"))
                elif config.get("no_move_sl_after_tp1"):
                    pass # Stay at initial SL
                elif trailing_sl_pct is None:
                    sl_price = entry_price # Move to Breakeven
            
            # If all TPs hit
            if next_tp_idx == num_tps or remaining <= 0:
                return total_pnl, f"TP{num_tps}"
                
        # Scenario 4: RSI Exit (ema_rsi_5 < 30) - Only for remaining portion
        if config.get("use_rsi_exit") and 'ema_rsi_5' in candle:
            if candle['ema_rsi_5'] < 30:
                curr_pnl = ((entry_price - candle['close']) / entry_price)
                total_pnl += curr_pnl * remaining
                return total_pnl, "RSI_Exit"

        # Trailing Stop update
        if next_tp_idx > 0:
            if config.get("use_trailing_stop"):
                new_sl = max(df.iloc[entry_idx+i-2:entry_idx+i+1]['high']) * 1.005
                sl_price = min(sl_price, new_sl)
            elif config.get("trailing_after_tp1_pct") is not None:
                new_sl = candle['close'] * (1 + config.get("trailing_after_tp1_pct"))
                sl_price = min(sl_price, new_sl)
            
        # Timeout
        if i >= max_holding:
            curr_pnl = ((entry_price - candle['close']) / entry_price)
            total_pnl += curr_pnl * remaining
            reason = "Timeout" if next_tp_idx == 0 else f"TP{next_tp_idx}_Timeout"
            return total_pnl, reason
                
    # End of data without hitting SL, TP, or max holding
    last_candle = df.iloc[-1]
    curr_pnl = ((entry_price - last_candle['close']) / entry_price)
    total_pnl += curr_pnl * remaining
    reason = "End_Of_Data" if next_tp_idx == 0 else f"TP{next_tp_idx}_EndOfData"
    return total_pnl, reason

def run_backtest_mtf(db, symbols, strategy_1d, strategy_1h, lookback=1620, config=None):
    all_trades = []
    stats = {
        "SL": {"count": 0, "pnl": 0.0},
        "TP2": {"count": 0, "pnl": 0.0},
        "TP1_BE": {"count": 0, "pnl": 0.0},
        "TP1_Timeout": {"count": 0, "pnl": 0.0},
        "RSI_Exit": {"count": 0, "pnl": 0.0},
        "Timeout": {"count": 0, "pnl": 0.0},
        "End_Of_Data": {"count": 0, "pnl": 0.0},
        "TP1_EndOfData": {"count": 0, "pnl": 0.0},
        "Open_Trades": []
    }
    
    for i, symbol in enumerate(symbols):
        if i % 10 == 0:
            logger.info(f"Progress: {i}/{len(symbols)} coins...")
            
        # 1. Fetch 1D Data
        limit_1d = int(lookback / 24) + 600
        df_1d = db.query_latest_ohlcv(exchange="bybit", symbol=symbol, timeframe="1d", limit=limit_1d)
        
        if df_1d.empty or len(df_1d) < strategy_1d.min_candles_required:
            continue
            
        # Evaluate 1D
        df_1d_ind = strategy_1d.compute_indicators(df_1d)
        df_1d_sig = strategy_1d.generate_signals(df_1d_ind)
        
        # Lọc ra các ngày 1D có tín hiệu short (-1)
        valid_1d_dates = df_1d_sig[df_1d_sig['signal'] == -1].index.date
        
        if len(valid_1d_dates) == 0:
            continue
            
        # 2. Fetch 1H Data
        df_1h = db.query_latest_ohlcv(exchange="bybit", symbol=symbol, timeframe="1h", limit=lookback)
        if df_1h.empty or len(df_1h) < strategy_1h.min_candles_required:
            continue
            
        # Evaluate 1H
        df_1h_ind = strategy_1h.compute_indicators(df_1h)
        df_1h_sig = strategy_1h.generate_signals(df_1h_ind)
        
        # 3. Simulate Trades based on MTF logic
        df_1h_sig['date'] = df_1h_sig.index.date
        
        sig_candidates = df_1h_sig[df_1h_sig["signal"] == -1]
        
        trade_entry_idx = -1
        for idx_val in sig_candidates.index:
            row = sig_candidates.loc[idx_val]
            
            if row['date'] in valid_1d_dates:
                # MỚI: Chỉ vào lệnh nếu nến cách hiện tại > lookback / 2 để tránh lệnh "Đang mở"
                idx_num = df_1h_sig.index.get_loc(idx_val)
                if (len(df_1h_sig) - 1 - idx_num) < (lookback / 2):
                    continue
                
                # If we are already in trade and haven't exited, skip
                if trade_entry_idx != -1 and idx_num < trade_entry_idx + 100: 
                    continue
                
                trade_entry_idx = idx_num
                # Simulate
                pnl, reason = simulate_trade(df_1h_sig, idx_num, row["close"], config=config)
                
                # Record detailed trade
                trade_record = {
                    "symbol": symbol,
                    "entry_time": idx_val,
                    "pnl": pnl,
                    "reason": reason
                }
                all_trades.append(trade_record)
                
                if reason in stats:
                    stats[reason]["count"] += 1
                    stats[reason]["pnl"] += pnl
                else:
                    stats[reason] = {"count": 1, "pnl": pnl}
                    
                if reason in ["End_Of_Data", "TP1_EndOfData"]:
                    stats["Open_Trades"].append({"symbol": symbol, "pnl": pnl})
                
    if not all_trades:
        return [], 0, 0, stats
        
    pnl_values = [t["pnl"] for t in all_trades]
    wins = sum(1 for p in pnl_values if p > 0)
    win_rate = wins / len(all_trades) * 100
    total_pnl = sum(pnl_values) * 100 
    return all_trades, win_rate, total_pnl, stats

def main():
    parser = argparse.ArgumentParser(description="EMA RSI Reversal Backtest Script")
    parser.add_argument("--top", type=int, default=100, help="Số lượng top coin muốn chạy (mặc định 100)")
    parser.add_argument("--lookback", type=int, default=1500, help="Số nến 1H tối đa fetch từ DB (mặc định 1500)")
    parser.add_argument("--n1d", type=int, default=20, help="Max distance nến 1D")
    parser.add_argument("--m1h", type=int, default=3, help="Max distance nến 1H")
    
    args = parser.parse_args()

    db = TimescaleClient(DATABASE_URL)
    
    strategy_1d = EmaRsiReversalStrategy(max_distance_candles=args.n1d, use_ema_filter=True, min_ema_rsi=40.0)
    strategy_1h = EmaRsiReversalStrategy(max_distance_candles=args.m1h, min_gap=3.0, min_ema_rsi=50.0)

    # Get symbols
    logger.info(f"Đang lấy danh sách Top {args.top} coins (cache/CMC)...")
    top_symbols = get_top_coins(limit=args.top)
    
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            db_symbols = [r[0] for r in conn.execute(
                text("SELECT DISTINCT symbol FROM ohlcv WHERE timeframe='1h'")
            ).fetchall()]
    except Exception as e:
        logger.error("❌ KHÔNG THỂ KẾT NỐI ĐẾN DATABASE (TimescaleDB/Postgres)!")
        logger.error("Vui lòng kiểm tra lại xem bạn đã bật Docker hoặc khởi động service Postgres chưa (localhost:5432).")
        sys.exit(1)
    
    # Filter: Top N coins that also exist in DB
    symbols = []
    for s in top_symbols:
        if s in db_symbols:
            symbols.append(s)
        elif f"{s}:USDT" in db_symbols:
            symbols.append(f"{s}:USDT")
            
        # Thử cả Bybit Linear format
        elif f"{s}/USDT:USDT" in db_symbols:
             symbols.append(f"{s}/USDT:USDT")
             
    logger.info(f"Bat dau Backtest tren {len(symbols)} coins co luu du lieu 1H...")
    
    trades, wr, pnl, stats = run_backtest_mtf(db, symbols, strategy_1d, strategy_1h, lookback=args.lookback)
    count = len(trades)
    
    print("\n" + "="*60)
    print(f"KET QUA BACKTEST Top {args.top} (Chiến lược Đảo chiều EMA RSI)")
    print(f"Tham số: 1D(<= {args.n1d}, EMA200 lọc), 1H(<= {args.m1h}, gap>=3) | TP: 10%/20% | SL: 5% (No BE)")
    print("-" * 60)
    print(f"{'TỔNG SỐ LỆNH':<15} | {'WIN RATE':<10} | {'TỔNG TỈ SUẤT (PnL)':<10}")
    print(f"{count:<15} | {wr:.1f}%      | {pnl:+.1f}%")
    print("-" * 60)
    print("CHI TIẾT ĐÓNG LỆNH:")
    
    def print_stat(label, key):
        data = stats.get(key, {"count": 0, "pnl": 0.0})
        count = data["count"]
        pnl_pct = data["pnl"] * 100
        print(f" - {label:<25}: {count:<4} lệnh | Tổng PnL: {pnl_pct:+.2f}%")

    print_stat("Chốt lời mốc 2 (TP2)", "TP2")
    print_stat("Cán StopLoss (-100%)", "SL")
    print(" ")
    print_stat("Ăn TP1, quay đầu hoà vốn", "TP1_BE")
    print_stat("Ăn TP1, kẹt (Timeout)", "TP1_Timeout")
    print_stat("Không SL/TP, kẹt Timeout", "Timeout")
    
    open_trades = stats.get("Open_Trades", [])
    open_win = [t for t in open_trades if t["pnl"] > 0]
    open_loss = [t for t in open_trades if t["pnl"] <= 0]
    
    open_win_pnl = sum(t["pnl"] for t in open_win) * 100
    open_loss_pnl = sum(t["pnl"] for t in open_loss) * 100
    
    print(f" - Đang mở CÓ LỜI (Hết dữ liệu): {len(open_win):<4} lệnh | Tổng PnL: {open_win_pnl:+.2f}%")
    print(f" - Đang mở BỊ LỖ (Hết dữ liệu) : {len(open_loss):<4} lệnh | Tổng PnL: {open_loss_pnl:+.2f}%")
    
    if open_loss:
        open_loss.sort(key=lambda x: x["pnl"])
        print("   [!] Top 3 cặp Đang Mở Lỗ lớn nhất:")
        for i, t in enumerate(open_loss[:3]):
            print(f"       {i+1}. {t['symbol']:<10}: {t['pnl']*100:+.2f}%")
            
    print("="*60)

if __name__ == "__main__":
    main()
