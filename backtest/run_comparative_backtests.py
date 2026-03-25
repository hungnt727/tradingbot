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

SCENARIOS = {
    "Baseline (Current)": {
        "sl_pct": 0.10,
        "tp_levels": [0.05, 0.10],
        "tp_size": 0.5,
        "use_atr_sl": False,
        "use_trailing_stop": False,
        "use_rsi_exit": False
    },
    "Optimized 1: Tight SL (5%)": {
        "sl_pct": 0.05,
        "tp_levels": [0.05, 0.10],
        "tp_size": 0.5,
        "use_atr_sl": False,
        "use_trailing_stop": False,
        "use_rsi_exit": False
    },
    "Optimized 2: ATR-based SL (2*ATR)": {
        "sl_pct": 0.10,
        "tp_levels": [0.05, 0.10],
        "tp_size": 0.5,
        "use_atr_sl": True,
        "atr_mult": 2.0,
        "use_trailing_stop": False,
        "use_rsi_exit": False
    },
    "Optimized 3: Trailing Stop (3-Candle High)": {
        "sl_pct": 0.10,
        "tp_levels": [0.05, 0.10],
        "tp_size": 0.5,
        "use_atr_sl": False,
        "use_trailing_stop": True,
        "use_rsi_exit": False
    },
    "Optimized 4: RSI Signal Exit (<30)": {
        "sl_pct": 0.10,
        "tp_levels": [0.05, 0.10],
        "tp_size": 0.5,
        "use_atr_sl": False,
        "use_trailing_stop": False,
        "use_rsi_exit": True
    }
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

    results = []

    for name, config in SCENARIOS.items():
        logger.info(f">>> Running Scenario: {name}")
        
        strategy_1d = EmaRsiReversalStrategy(max_distance_candles=20, use_ema_filter=True)
        strategy_1h = EmaRsiReversalStrategy(max_distance_candles=3, min_gap=2.0)
        
        trades, wr, pnl, stats = run_backtest_mtf(db, symbols, strategy_1d, strategy_1h, lookback=lookback, config=config)
        count = len(trades)
        
        results.append({
            "Scenario": name,
            "Trades": count,
            "Win Rate": f"{wr:.1f}%",
            "Total PnL": f"{pnl:+.1f}%",
            "Avg PnL/Trade": f"{(pnl/count if count > 0 else 0):+.2f}%",
            "TP-Hit": stats.get("TP2", {"count": 0})["count"] + stats.get("RSI_Exit", {"count": 0})["count"],
            "SL-Hit": stats.get("SL", {"count": 0})["count"]
        })

    # Output comparison table
    print("\n" + "="*80)
    print(f"COMPARATIVE BACKTEST RESULTS (Top {top}, {lookback} candles)")
    print("="*80)
    
    df_results = pd.DataFrame(results)
    print(df_results.to_markdown(index=False))
    print("="*80)

if __name__ == "__main__":
    main()
