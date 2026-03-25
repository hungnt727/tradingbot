import os
import sys
import pandas as pd
from loguru import logger
from dotenv import load_dotenv

# Allow importing from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.storage.timescale_client import TimescaleClient
from strategies.ema_rsi_reversal_strategy import EmaRsiReversalStrategy
from cli.run_distribution_signal_bot import get_top_coins
from backtest.run_ema_rsi_reversal_backtest import run_backtest_mtf

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

BASELINE_CONFIG = {
    "sl_pct": 0.10,
    "tp_levels": [0.05, 0.10],
    "tp_size": 0.5,
    "use_atr_sl": False,
    "use_trailing_stop": False,
    "use_rsi_exit": False
}

def main():
    top = 300
    lookback = 10000
    
    db = TimescaleClient(DATABASE_URL)
    
    # Get symbols
    logger.info(f"Fetching Top {top} coins...")
    top_symbols = get_top_coins(limit=top)
    
    # Filter symbols in DB
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        db_symbols = [r[0] for r in conn.execute(
            text("SELECT DISTINCT symbol FROM ohlcv WHERE timeframe='1h'")
        ).fetchall()]
    
    symbols = []
    for s in top_symbols:
        s_variants = [s, f"{s}:USDT", f"{s}/USDT:USDT"]
        for v in s_variants:
            if v in db_symbols:
                symbols.append(v)
                break

    logger.info(f"Running Baseline Backtest on {len(symbols)} coins...")
    
    strategy_1d = EmaRsiReversalStrategy(max_distance_candles=20, use_ema_filter=True)
    strategy_1h = EmaRsiReversalStrategy(max_distance_candles=3, min_gap=2.0)
    
    trades, wr, pnl, stats = run_backtest_mtf(db, symbols, strategy_1d, strategy_1h, lookback=lookback, config=BASELINE_CONFIG)
    
    if not trades:
        print("No trades found.")
        return

    # Convert to DataFrame for sorting
    df_trades = pd.DataFrame(trades)
    
    # Format entry_time to string
    df_trades['entry_time'] = df_trades['entry_time'].dt.strftime('%Y-%m-%d %H:%M')
    df_trades['pnl_pct'] = df_trades['pnl'] * 100

    # Sort
    df_winners = df_trades.sort_values(by='pnl', ascending=False).head(10)
    df_losers = df_trades.sort_values(by='pnl', ascending=True).head(10)

    print("\n" + "="*80)
    print("DETAILED BASELINE REPORT: TOP 10 WINNERS")
    print("="*80)
    print(df_winners[['symbol', 'entry_time', 'pnl_pct', 'reason']].to_markdown(index=False))
    
    print("\n" + "="*80)
    print("DETAILED BASELINE REPORT: TOP 10 LOSERS")
    print("="*80)
    print(df_losers[['symbol', 'entry_time', 'pnl_pct', 'reason']].to_markdown(index=False))
    
    print("\n" + "="*80)
    print(f"SUMMARY: Total Trades: {len(trades)} | Win Rate: {wr:.1f}% | Total PnL: {pnl:+.1f}%")
    print("="*80)

if __name__ == "__main__":
    main()
