"""
Distribution Strategy Backtest - Chạy backtest trên top N coin với chiến lược phân phối đỉnh.
Fetch dữ liệu trực tiếp từ exchange qua ccxt.
"""
import os
import sys
import argparse
import requests
import pandas as pd
import numpy as np
import ccxt
from loguru import logger

sys.stdout.reconfigure(encoding='utf-8')

# Import strategy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.distribution_strategy import DistributionStrategy
from cli.run_paper_top_300 import get_top_coins

# Cấu hình
TOP_N_COINS = 300
TIMEFRAME = '4h'  # timeframe mặc định cho distribution strategy
LOOKBACK_CANDLES = 500  # Số nến gần nhất để tìm tín hiệu

# Khởi tạo exchange
exchange = ccxt.bybit({'options': {'defaultType': 'linear'}})


def fetch_data(symbol, timeframe, limit=500):
    """Lấy dữ liệu OHLCV từ exchange"""
    try:
        timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
        since = exchange.milliseconds() - limit * timeframe_ms
        all_ohlcv = []
        
        while len(all_ohlcv) < limit:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
            if not ohlcv:
                break
            
            # Loại bỏ nến trùng lặp
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
        logger.error(f"Lỗi lấy dữ liệu {symbol}: {e}")
        return None


def simulate_trade(df, entry_idx, entry_price, side, strategy_cfg):
    """
    Simulate 1 trade với SL/TP/Timeout cho SHORT.
    """
    rm = strategy_cfg.get("risk_management", {})
    
    sl_pct = rm.get("sl_pct", 0.05)
    tp_levels = rm.get("tp_levels", [0.05, 0.10, 0.15])
    tp_size = rm.get("tp_size", 0.33)
    max_holding = rm.get("max_holding", 30)
    
    # Initial SL/TP (SHORT: SL above, TP below)
    if side == "SHORT":
        sl_price = entry_price * (1 + sl_pct)
        tp_prices = [entry_price * (1 - tp) for tp in tp_levels]
    else:
        sl_price = entry_price * (1 - sl_pct)
        tp_prices = [entry_price * (1 + tp) for tp in tp_levels]
    
    tp_hit = [False] * len(tp_levels)
    remaining = 1.0
    total_pnl = 0.0
    exit_reason = "TIMEOUT"
    exit_candle = None
    
    for i in range(1, len(df) - entry_idx):
        candle = df.iloc[entry_idx + i]
        
        # Check SL
        if side == "SHORT":
            if candle["high"] >= sl_price:
                pnl = ((entry_price - sl_price) / entry_price) * remaining
                total_pnl += pnl
                exit_reason = f"SL_HIT"
                exit_candle = i
                remaining = 0
                break
        else:
            if candle["low"] <= sl_price:
                pnl = ((sl_price - entry_price) / entry_price) * remaining
                total_pnl += pnl
                exit_reason = f"SL_HIT"
                exit_candle = i
                remaining = 0
                break
        
        # Check TPs
        for tp_idx, tp_price in enumerate(tp_prices):
            if tp_hit[tp_idx]:
                continue
            
            if side == "SHORT":
                hit = candle["low"] <= tp_price
            else:
                hit = candle["high"] >= tp_price
            
            if hit:
                tp_hit[tp_idx] = True
                tp_pct = tp_levels[tp_idx]
                
                if tp_idx < len(tp_levels) - 1:
                    size = tp_size
                    remaining -= size
                else:
                    size = remaining
                    remaining = 0
                
                pnl = tp_pct * size
                total_pnl += pnl
                
                if remaining <= 0:
                    exit_reason = f"TP{tp_idx + 1}_HIT"
                    exit_candle = i
                    break
        
        if remaining <= 0:
            break
        
        # Max holding timeout
        if i >= max_holding:
            if remaining > 0:
                if side == "SHORT":
                    curr_pnl = (entry_price - candle["close"]) / entry_price
                else:
                    curr_pnl = (candle["close"] - entry_price) / entry_price
                
                if total_pnl + (curr_pnl * remaining) > 0:
                    total_pnl += curr_pnl * remaining
                    exit_reason = "TIMEOUT_PROFIT"
                else:
                    exit_reason = "TIMEOUT_LOSS"
                
                exit_candle = i
                remaining = 0
                break
    
    # End of data
    if remaining > 0:
        last_candle = df.iloc[-1]
        if side == "SHORT":
            curr_pnl = (entry_price - last_candle["close"]) / entry_price
        else:
            curr_pnl = (last_candle["close"] - entry_price) / entry_price
        
        total_pnl += curr_pnl * remaining
        exit_candle = len(df) - 1 - entry_idx
        exit_reason = "END_OF_DATA"
    
    return {
        "pnl_pct": total_pnl,
        "exit_candles": exit_candle or max_holding,
        "exit_reason": exit_reason,
        "tp_hit": tp_hit,
    }


def backtest_symbol(symbol, strategy, timeframe):
    """Backtest 1 symbol"""
    # Cần nhiều dữ liệu cho swing window và EMA
    total_candles_needed = strategy.swing_window + strategy.min_candles_required + LOOKBACK_CANDLES
    
    df = fetch_data(symbol, timeframe, limit=total_candles_needed)
    if df is None or len(df) < total_candles_needed:
        return []
    
    try:
        df_ind = strategy.compute_indicators(df)
        df_sig = strategy.generate_signals(df_ind)
    except Exception as e:
        logger.warning(f"Error processing {symbol}: {e}")
        return []
    
    # Chỉ tìm tín hiệu trong N nến gần nhất
    start_idx = len(df) - LOOKBACK_CANDLES
    trades = []
    
    # Find SHORT signals
    sig_rows = df_sig[df_sig["signal"] == -1]
    
    for idx_val in sig_rows.index:
        idx = df_sig.index.get_loc(idx_val)
        if idx < start_idx:
            continue
        
        row = df_sig.iloc[idx]
        result = simulate_trade(df_sig, idx, row["close"], row["signal_type"], strategy.config)
        
        trades.append({
            "symbol": symbol,
            "entry_time": row.name.strftime("%m-%d %H:%M") if hasattr(row.name, "strftime") else str(row.name),
            "entry_price": row["close"],
            "pnl_pct": result["pnl_pct"],
            "exit_candles": result["exit_candles"],
            "exit_reason": result["exit_reason"],
            "range_position": row.get("range_position", 0),
            "distribution_score": row.get("distribution_score", 0),
            "entry_reason": row.get("entry_reason", ""),
        })
    
    return trades


def run_optimization():
    """
    Chạy optimization để tìm best parameters.
    """
    print("=" * 70)
    print("DISTRIBUTION STRATEGY - PARAMETER OPTIMIZATION")
    print("=" * 70)
    
    # Lấy danh sách coin
    print(f"\n[1/3] Đang lấy top {TOP_N_COINS} coin...")
    symbols = get_top_coins(limit=TOP_N_COINS)
    
    # Filter symbols có trên Bybit
    try:
        markets = exchange.load_markets()
        symbols = [s for s in symbols if s in markets]
        print(f"    Tìm thấy {len(symbols)} coin trên Bybit")
    except Exception as e:
        print(f"    Lỗi load markets: {e}")
        return
    
    # Test different parameter combinations
    param_grid = [
        # upper_zone_threshold, swing_window, require_ema_bearish, require_volume_spike
        {"upper_zone_threshold": 0.70, "swing_window": 20, "require_ema_bearish": True, "require_volume_spike": False, "name": "Conservative"},
        {"upper_zone_threshold": 0.65, "swing_window": 20, "require_ema_bearish": True, "require_volume_spike": False, "name": "Strict Upper Zone"},
        {"upper_zone_threshold": 0.75, "swing_window": 15, "require_ema_bearish": True, "require_volume_spike": False, "name": "Wider Zone"},
        {"upper_zone_threshold": 0.70, "swing_window": 30, "require_ema_bearish": True, "require_volume_spike": False, "name": "Longer Swing"},
        {"upper_zone_threshold": 0.70, "swing_window": 20, "require_ema_bearish": False, "require_volume_spike": True, "name": "Volume Spike Focus"},
        {"upper_zone_threshold": 0.60, "swing_window": 20, "require_ema_bearish": False, "require_volume_spike": False, "name": "Relaxed Filters"},
        {"upper_zone_threshold": 0.80, "swing_window": 20, "require_ema_bearish": True, "require_volume_spike": False, "name": "Very Top Focus"},
        {"upper_zone_threshold": 0.70, "swing_window": 25, "require_ema_bearish": True, "require_volume_spike": False, "name": "Mid Swing"},
    ]
    
    results = []
    
    for params in param_grid:
        print(f"\n[2/3] Testing: {params['name']}")
        print(f"        upper_zone={params['upper_zone_threshold']}, swing={params['swing_window']}, ema_bear={params['require_ema_bearish']}, vol_spike={params['require_volume_spike']}")
        
        # Create strategy with params
        strategy = DistributionStrategy()
        strategy.upper_zone_threshold = params["upper_zone_threshold"]
        strategy.swing_window = params["swing_window"]
        strategy.require_ema_bearish = params["require_ema_bearish"]
        strategy.require_volume_spike = params["require_volume_spike"]
        
        all_trades = []
        symbols_tested = 0
        
        for i, symbol in enumerate(symbols[:50]):  # Test trên 50 coin để nhanh
            trades = backtest_symbol(symbol, strategy, TIMEFRAME)
            all_trades.extend(trades)
            symbols_tested += 1
            if (i + 1) % 10 == 0:
                print(f"        Progress: {i+1}/50 coins...")
        
        if all_trades:
            wins = sum(1 for t in all_trades if t["pnl_pct"] > 0)
            wr = (wins / len(all_trades)) * 100
            total_pnl = sum(t["pnl_pct"] for t in all_trades) * 100
            avg_pnl = total_pnl / len(all_trades)
            
            results.append({
                "name": params["name"],
                "params": params,
                "trades": len(all_trades),
                "win_rate": wr,
                "total_pnl": total_pnl,
                "avg_pnl": avg_pnl,
                "trades_list": all_trades,
            })
            
            print(f"        Result: {len(all_trades)} trades, WR={wr:.1f}%, PnL={total_pnl:+.2f}%, Avg={avg_pnl:+.2f}%")
        else:
            print(f"        No trades found")
            results.append({
                "name": params["name"],
                "params": params,
                "trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_pnl": 0,
                "trades_list": [],
            })
    
    # Print summary
    print("\n" + "=" * 70)
    print("OPTIMIZATION RESULTS SUMMARY")
    print("=" * 70)
    print(f"{'Name':<25} | {'Trades':>6} | {'WinRate':>8} | {'TotalPnL':>10} | {'AvgPnL':>8}")
    print("-" * 70)
    
    sorted_results = sorted(results, key=lambda x: -x["total_pnl"])
    for r in sorted_results:
        print(f"{r['name']:<25} | {r['trades']:>6} | {r['win_rate']:>7.1f}% | {r['total_pnl']:>+9.2f}% | {r['avg_pnl']:>+7.2f}%")
    
    # Best result
    best = sorted_results[0]
    print("\n" + "=" * 70)
    print(f"BEST PARAMETERS: {best['name']}")
    print(f"  upper_zone_threshold: {best['params']['upper_zone_threshold']}")
    print(f"  swing_window: {best['params']['swing_window']}")
    print(f"  require_ema_bearish: {best['params']['require_ema_bearish']}")
    print(f"  require_volume_spike: {best['params']['require_volume_spike']}")
    print(f"  Win Rate: {best['win_rate']:.1f}%")
    print(f"  Total PnL: {best['total_pnl']:+.2f}%")
    print(f"  Avg PnL: {best['avg_pnl']:+.2f}%")
    print("=" * 70)
    
    # Run full backtest with best params
    print(f"\n[3/3] Running full backtest with best parameters on top {TOP_N_COINS} coins...")
    
    best_strategy = DistributionStrategy()
    best_strategy.upper_zone_threshold = best["params"]["upper_zone_threshold"]
    best_strategy.swing_window = best["params"]["swing_window"]
    best_strategy.require_ema_bearish = best["params"]["require_ema_bearish"]
    best_strategy.require_volume_spike = best["params"]["require_volume_spike"]
    
    all_trades_full = []
    for i, symbol in enumerate(symbols):
        trades = backtest_symbol(symbol, best_strategy, TIMEFRAME)
        all_trades_full.extend(trades)
        if (i + 1) % 50 == 0:
            print(f"    Progress: {i+1}/{len(symbols)} coins...")
    
    if all_trades_full:
        wins = sum(1 for t in all_trades_full if t["pnl_pct"] > 0)
        wr = (wins / len(all_trades_full)) * 100
        total_pnl = sum(t["pnl_pct"] for t in all_trades_full) * 100
        avg_pnl = total_pnl / len(all_trades_full)
        
        print(f"\nFULL BACKTEST RESULTS:")
        print(f"  Total Trades: {len(all_trades_full)}")
        print(f"  Win Rate: {wr:.1f}%")
        print(f"  Total PnL: {total_pnl:+.2f}%")
        print(f"  Avg PnL: {avg_pnl:+.2f}%")
        
        # Top 10 best trades
        sorted_trades = sorted(all_trades_full, key=lambda x: -x["pnl_pct"])[:10]
        print(f"\n  TOP 10 BEST TRADES:")
        for t in sorted_trades:
            print(f"    {t['symbol']}: {t['pnl_pct']*100:+.2f}% @ {t['entry_price']:.4f}")
        
        # Save results
        os.makedirs("output", exist_ok=True)
        df_trades = pd.DataFrame(all_trades_full)
        output_file = f"output/distribution_backtest_top{TOP_N_COINS}_{TIMEFRAME}_best.csv"
        df_trades.to_csv(output_file, index=False)
        print(f"\n  Results saved to: {output_file}")
    
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Distribution Strategy Backtest")
    parser.add_argument("--top", type=int, default=300, help="So luong top coin (mac dinh 300)")
    parser.add_argument("--timeframe", type=str, default="4h", help="Khung thoi gian (mac dinh 4h)")
    parser.add_argument("--optimize", action="store_true", help="Chay optimization tim best params")
    args = parser.parse_args()
    
    global TOP_N_COINS, TIMEFRAME
    TOP_N_COINS = args.top
    TIMEFRAME = args.timeframe
    
    if args.optimize:
        run_optimization()
    else:
        # Simple backtest với default params
        print("=" * 70)
        print(f"DISTRIBUTION STRATEGY BACKTEST - TOP {TOP_N_COINS} ({TIMEFRAME})")
        print("=" * 70)
        
        # Lấy danh sách coin
        print(f"\nĐang lấy top {TOP_N_COINS} coin...")
        symbols = get_top_coins(limit=TOP_N_COINS)
        
        # Filter symbols có trên Bybit
        try:
            markets = exchange.load_markets()
            symbols = [s for s in symbols if s in markets]
            print(f"   Tìm thấy {len(symbols)} coin trên Bybit")
        except Exception as e:
            print(f"   Lỗi load markets: {e}")
            return
        
        strategy = DistributionStrategy()
        
        all_trades = []
        for i, symbol in enumerate(symbols):
            trades = backtest_symbol(symbol, strategy, TIMEFRAME)
            all_trades.extend(trades)
            if (i + 1) % 50 == 0:
                print(f"   Progress: {i+1}/{len(symbols)} coins...")
        
        if all_trades:
            wins = sum(1 for t in all_trades if t["pnl_pct"] > 0)
            losses = len(all_trades) - wins
            wr = (wins / len(all_trades)) * 100
            total_pnl = sum(t["pnl_pct"] for t in all_trades) * 100
            avg_pnl = total_pnl / len(all_trades)
            
            print(f"\nKET QUA:")
            print(f"  Tong coin co tin hieu: {len(set(t['symbol'] for t in all_trades))}")
            print(f"  Tong giao dich: {len(all_trades)}")
            print(f"  Win Rate: {wr:.1f}% ({wins}W/{losses}L)")
            print(f"  Tong PnL: {total_pnl:+.2f}%")
            print(f"  PnL TB/giao dich: {avg_pnl:+.2f}%")
            
            # Save
            os.makedirs("output", exist_ok=True)
            df_trades = pd.DataFrame(all_trades)
            output_file = f"output/distribution_backtest_top{TOP_N_COINS}_{TIMEFRAME}.csv"
            df_trades.to_csv(output_file, index=False)
            print(f"\nDa luu: {output_file}")
        else:
            print("\nKhong tim thay tin hieu nao")
        
        print("=" * 70)


if __name__ == "__main__":
    main()
