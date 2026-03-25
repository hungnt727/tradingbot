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

CUSTOM_CONFIG = {
    "sl_pct": 0.05,
    "tp_levels": [0.05, 0.10, 0.15, 0.20],
    "tp_size": 0.25,
    "use_atr_sl": False,
    "use_trailing_stop": False,
    "use_rsi_exit": False,
    "no_move_sl_after_tp1": True
}

def main():
    top = 300
    lookback = 10000
    
    db = TimescaleClient(DATABASE_URL)
    
    logger.info(f"Fetching Top {top} coins...")
    top_symbols = get_top_coins(limit=top)
    
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

    logger.info(f"Running Custom Backtest (SL=5%, TP=10/20) on {len(symbols)} coins...")
    
    strategy_1d = EmaRsiReversalStrategy(max_distance_candles=20, use_ema_filter=True)
    strategy_1h = EmaRsiReversalStrategy(max_distance_candles=3, min_gap=2.0)
    
    trades, wr, pnl, stats = run_backtest_mtf(db, symbols, strategy_1d, strategy_1h, lookback=lookback, config=CUSTOM_CONFIG)
    
    print("\n" + "="*80)
    print("CUSTOM BACKTEST REPORT: SL=5%, TP1=10%, TP2=20%")
    print("="*80)
    print(f"Total Trades  : {len(trades)}")
    print(f"Win Rate      : {wr:.1f}%")
    print(f"Total PnL     : {pnl:+.1f}%")
    print("-" * 80)
    
    def print_stat(label, key):
        data = stats.get(key, {"count": 0, "pnl": 0.0})
        count = data["count"]
        pnl_pct = data["pnl"] * 100
        print(f" - {label:<25}: {count:<4} lệnh | PnL: {pnl_pct:+.2f}%")

    print_stat("Chốt lời mốc 2 (TP2)", "TP2")
    print_stat("Cán StopLoss (-5%)", "SL")
    print_stat("Ăn TP1, quay đầu hoà vốn", "TP1_BE")
    
    if trades:
        df_trades = pd.DataFrame(trades)
        df_trades['pnl_pct'] = df_trades['pnl'] * 100
        df_winners = df_trades.sort_values(by='pnl', ascending=False).head(5)
        print("\nTOP 5 WINNERS:")
        print(df_winners[['symbol', 'pnl_pct', 'reason']].to_markdown(index=False))

    print("="*80)

if __name__ == "__main__":
    main()
