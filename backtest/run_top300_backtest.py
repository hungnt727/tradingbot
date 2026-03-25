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
from strategies.sonicr_strategy import SonicRStrategy
from cli.run_paper_top_300 import get_top_coins

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def simulate_trade(df, entry_idx, entry_price, side, strategy_cfg):
    """Robust trade simulation with TP1/TP2 and SL-to-Breakeven."""
    sl_pct = strategy_cfg.get("risk_management", {}).get("sl_pct", 0.02)
    tp_levels = strategy_cfg.get("risk_management", {}).get("tp_levels", [0.02, 0.04])
    tp_size = strategy_cfg.get("risk_management", {}).get("tp_size", 0.5)
    max_holding = strategy_cfg.get("risk_management", {}).get("max_holding", 100)
    
    # Initial SL/TP
    if side == "LONG":
        sl_price = entry_price * (1 - sl_pct)
        tp1_price = entry_price * (1 + tp_levels[0])
        tp2_price = entry_price * (1 + tp_levels[1])
    else:
        sl_price = entry_price * (1 + sl_pct)
        tp1_price = entry_price * (1 - tp_levels[0])
        tp2_price = entry_price * (1 - tp_levels[1])
        
    tp1_hit = False
    remaining = 1.0
    total_pnl = 0.0
    
    for i in range(1, len(df) - entry_idx):
        candle = df.iloc[entry_idx + i]
        
        # Check SL
        if (side == "LONG" and candle['low'] <= sl_price) or (side == "SHORT" and candle['high'] >= sl_price):
            pnl = ((sl_price - entry_price) / entry_price if side == "LONG" else (entry_price - sl_price) / entry_price) * remaining
            total_pnl += pnl
            return total_pnl
        
        # Check TP1
        if not tp1_hit:
            hit = (side == "LONG" and candle['high'] >= tp1_price) or (side == "SHORT" and candle['low'] <= tp1_price)
            if hit:
                total_pnl += tp_levels[0] * tp_size
                tp1_hit = True
                remaining -= tp_size
                sl_price = entry_price # Move to Breakeven
                
        # Check TP2
        hit_tp2 = (side == "LONG" and candle['high'] >= tp2_price) or (side == "SHORT" and candle['low'] <= tp2_price)
        if hit_tp2:
            total_pnl += tp_levels[1] * remaining
            return total_pnl
            
        # Timeout
        if i >= max_holding:
            curr_pnl = ((candle['close'] - entry_price) / entry_price if side == "LONG" else (entry_price - candle['close']) / entry_price)
            # Only exit if profitable (as per user's rule)
            if total_pnl + (curr_pnl * remaining) > 0:
                total_pnl += curr_pnl * remaining
                return total_pnl
                
    # End of data
    last_candle = df.iloc[-1]
    curr_pnl = ((last_candle['close'] - entry_price) / entry_price if side == "LONG" else (entry_price - last_candle['close']) / entry_price)
    total_pnl += curr_pnl * remaining
    return total_pnl

def run_backtest_mode(db, symbols, strategy, timeframe, mode="BOTH"):
    """
    mode: "LONG", "SHORT", or "BOTH"
    """
    all_trades = []
    
    # Adjust strategy setups based on mode
    original_setups = [s.copy() for s in strategy.setups]
    for setup in strategy.setups:
        if mode == "LONG":
            setup["enabled"] = (setup["signal_type"] == "LONG")
        elif mode == "SHORT":
            setup["enabled"] = (setup["signal_type"] == "SHORT")
        else:
            setup["enabled"] = True

    for i, symbol in enumerate(symbols):
        if i % 10 == 0:
            logger.info(f"Progress: {i}/{len(symbols)} coins...")
        df = db.query_latest_ohlcv(exchange="bybit", symbol=symbol, timeframe=timeframe, limit=1620)
        if df.empty or len(df) < 620:
            continue
            
        df_ind = strategy.compute_indicators(df)
        df_sig = strategy.generate_signals(df_ind, symbol=symbol, is_live=False)
        
        sig_indices = df_sig[df_sig["signal"] != 0].index
        for idx_val in sig_indices:
            idx = df_sig.index.get_loc(idx_val)
            row = df_sig.iloc[idx]
            pnl = simulate_trade(df_sig, idx, row["close"], row["signal_type"], strategy.config)
            all_trades.append(pnl)
            
    # Restore setups
    strategy.setups = original_setups
    
    if not all_trades:
        return 0, 0, 0
        
    wins = sum(1 for p in all_trades if p > 0)
    win_rate = wins / len(all_trades) * 100
    total_pnl = sum(all_trades) * 100
    return len(all_trades), win_rate, total_pnl

def main():
    parser = argparse.ArgumentParser(description="SonicR Top N Backtest Script")
    parser.add_argument("--top", type=int, default=300, help="Số lượng top coin muốn chạy (mặc định 300)")
    parser.add_argument("--timeframe", type=str, default="15m", help="Khung thời gian giao dịch (mặc định 15m)")
    args = parser.parse_args()

    db = TimescaleClient(DATABASE_URL)
    strategy = SonicRStrategy()
    
    # NEW: Resolve dynamic HTF mapping from YAML
    timeframe_mapping = strategy.config.get("timeframe_mapping", {})
    if args.timeframe in timeframe_mapping:
        strategy.timeframe = args.timeframe
        strategy.htf_timeframe = timeframe_mapping[args.timeframe]
        # Re-apply config for the new timeframe
        strategy.apply_timeframe_config()
        logger.info(f"Da dat TimeFrame: {strategy.timeframe}, HTF: {strategy.htf_timeframe}")
    else:
        logger.warning(f"Khung thoi gian {args.timeframe} khong co trong mapping. Su dung mac dinh: {strategy.timeframe}/{strategy.htf_timeframe}")

    # Get symbols from CMC/Cache then filter against DB
    logger.info(f"Đang lấy danh sách Top {args.top} coins...")
    top_symbols = get_top_coins(limit=args.top)
    
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        db_symbols = [r[0] for r in conn.execute(
            text("SELECT DISTINCT symbol FROM ohlcv WHERE timeframe=:tf"), 
            {"tf": strategy.timeframe}
        ).fetchall()]
    
    # Filter: Top N coins that also exist in DB (handling :USDT suffix if present)
    symbols = []
    for s in top_symbols:
        # Match as-is or with :USDT suffix
        if s in db_symbols:
            symbols.append(s)
        elif f"{s}:USDT" in db_symbols:
            symbols.append(f"{s}:USDT")
    
    logger.info(f"Bat dau Backtest tren {len(symbols)} coins co du lieu {strategy.timeframe}...")
    
    results = []
    for mode in ["LONG", "SHORT", "BOTH"]:
        logger.info(f"Chay che do: {mode}...")
        count, wr, pnl = run_backtest_mode(db, symbols, strategy, strategy.timeframe, mode)
        results.append({"Mode": mode, "Trades": count, "WinRate": f"{wr:.1f}%", "TotalPnL": f"{pnl:+.1f}%"})
        
    print("\n" + "="*50)
    print(f"KET QUA BACKTEST TOP {args.top} ({strategy.timeframe})")
    print(f"{'MODE':<15} | {'TRADES':<10} | {'WIN RATE':<10} | {'TOTAL PnL':<10}")
    print("-" * 50)
    for res in results:
        print(f"{res['Mode']:<15} | {res['Trades']:<10} | {res['WinRate']:<10} | {res['TotalPnL']:<10}")
    print("="*50)

if __name__ == "__main__":
    main()
