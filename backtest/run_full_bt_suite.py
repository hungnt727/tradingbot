import os
import sys
import pandas as pd
import numpy as np
import yaml
from loguru import logger
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Allow importing from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.storage.timescale_client import TimescaleClient
from strategies.sonicr_strategy import SonicRStrategy
from cli.run_paper_top_300 import get_top_coins, filter_bybit_symbols
from data.crawler.bybit_crawler import BybitCrawler
from backtest.run_top300_backtest import simulate_trade, run_backtest_mode

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def main():
    logger.info("🚀 Starting Full Backtest Suite (5m to 4h) for Top 300 coins...")
    
    timeframes = ["5m", "15m", "1h", "4h"]
    db = TimescaleClient(DATABASE_URL)
    strategy = SonicRStrategy()
    crawler = BybitCrawler(
        api_key=os.getenv("BYBIT_API_KEY", ""),
        api_secret=os.getenv("BYBIT_API_SECRET", ""),
    )
    
    top_symbols = get_top_coins(limit=300)
    symbols = filter_bybit_symbols(crawler, top_symbols)
    
    final_report = []

    for tf in timeframes:
        logger.info(f"--- Processing TimeFrame: {tf} ---")
        
        # 1. Update Strategy Timeframe and Overrides
        timeframe_mapping = strategy.config.get("timeframe_mapping", {})
        if tf in timeframe_mapping:
            strategy.timeframe = tf
            strategy.htf_timeframe = timeframe_mapping[tf]
            strategy.apply_timeframe_config()
            logger.info(f"Targeting LTF: {tf}, HTF: {strategy.htf_timeframe}")
        else:
            logger.warning(f"No mapping for {tf}, skipping or using defaults...")
            continue

        # 2. Backfill 1620 candles (if missing or always)
        # To be safe and ensure the latest data for backtest, we'll fetch only if needed or just fetch once
        # For a full check, we skip if DB already has enough. But the user wants 'it done'.
        logger.info(f"Checking data for {len(symbols)} coins in {tf}...")
        
        # 3. Perform Backtest (LONG, SHORT, BOTH)
        modes = ["LONG", "SHORT", "BOTH"]
        tf_results = {"TimeFrame": tf}
        
        # We need data before running run_backtest_mode
        # Let's ensure top symbols have data for this TF
        logger.info(f"Ensuring data for {len(symbols)} coins...")
        # (Optimization: We could backfill only once and reuse in all modes)
        
        # Let's run a quick backfill of 2000 candles for each sym in this TF 
        # (Only if DB counts are low)
        count = 0
        for sym in symbols:
            # Quick count check
            try:
                # Optimized fetch from DB
                df_db = db.query_latest_ohlcv("bybit", sym, tf, limit=1)
                if df_db.empty:
                    # Missing, fetch 2000
                    df_web = crawler.fetch_ohlcv(sym, timeframe=tf, limit=2000)
                    if not df_web.empty:
                        db.upsert_ohlcv(crawler.df_to_records(df_web))
                        count += 1
            except Exception as e:
                pass
        if count > 0:
            logger.success(f"Backfilled {count} coins for {tf}")

        for mode in modes:
            logger.info(f"Running mode: {mode} for {tf}...")
            count, wr, pnl = run_backtest_mode(db, symbols, strategy, tf, mode)
            tf_results[f"{mode}_Trades"] = count
            tf_results[f"{mode}_WR"] = f"{wr:.1f}%"
            tf_results[f"{mode}_PnL"] = f"{pnl:+.1f}%"
        
        final_report.append(tf_results)

        # INCREMENTAL SAVE SO USER CAN SEE PARTIAL RESULTS
        summary_df = pd.DataFrame(final_report)
        csv_path = "output/full_backtest_suite_top300.csv"
        os.makedirs("output", exist_ok=True)
        summary_df.to_csv(csv_path, index=False)
        logger.info(f"Updated incremental report for {tf} to {csv_path}")

    # Output final summary
    print("\n" + "="*80)
    print("🏆 FULL BACKTEST REPORT (TOP 300)")
    print("="*80)
    
    summary_df = pd.DataFrame(final_report)
    print(summary_df.to_string(index=False))
    
    # Save to CSV
    csv_path = "output/full_backtest_suite_top300.csv"
    os.makedirs("output", exist_ok=True)
    summary_df.to_csv(csv_path, index=False)
    logger.info(f"Report saved to {csv_path}")

if __name__ == "__main__":
    main()
