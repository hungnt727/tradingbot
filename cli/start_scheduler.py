"""
CLI: Start the incremental data sync scheduler.
Reads job configuration from environment variables or defaults.

Usage:
    python cli/start_scheduler.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# ---------------------------------------------------------------
# Configuration — Edit this section to customize sync jobs
# ---------------------------------------------------------------
SYNC_JOBS = [
    # (exchange, symbol, timeframe)
    ("binance", "BTC/USDT",  "1h"),
    ("binance", "ETH/USDT",  "1h"),
    ("binance", "BTC/USDT",  "4h"),
    ("binance", "ETH/USDT",  "4h"),
    ("binance", "BTC/USDT",  "1d"),
    ("bybit",   "BTC/USDT",  "1h"),
    ("bybit",   "ETH/USDT",  "1h"),
]
# ---------------------------------------------------------------


def main():
    from data.crawler.binance_crawler import BinanceCrawler
    from data.crawler.bybit_crawler import BybitCrawler
    from data.crawler.scheduler import DataScheduler

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/tradingbot",
    )

    logger.info("Starting TradingBot Data Scheduler...")
    scheduler = DataScheduler(database_url)

    # Register crawlers
    scheduler.add_exchange(
        BinanceCrawler(
            api_key=os.getenv("BINANCE_API_KEY", ""),
            api_secret=os.getenv("BINANCE_API_SECRET", ""),
        )
    )
    scheduler.add_exchange(
        BybitCrawler(
            api_key=os.getenv("BYBIT_API_KEY", ""),
            api_secret=os.getenv("BYBIT_API_SECRET", ""),
        )
    )

    # Register sync jobs
    for exchange, symbol, timeframe in SYNC_JOBS:
        scheduler.add_job(exchange, symbol, timeframe)

    logger.info(f"Registered {len(SYNC_JOBS)} sync jobs. Scheduler starting...")
    scheduler.start()


if __name__ == "__main__":
    main()
