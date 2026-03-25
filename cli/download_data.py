"""
CLI: Download historical OHLCV data from an exchange and store in TimescaleDB.

Usage:
    python cli/download_data.py --exchange binance --symbol BTC/USDT --timeframe 1h --start 2024-01-01
"""
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

import click
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


@click.command()
@click.option("--exchange", "-e", required=True, type=click.Choice(["binance", "bybit"]),
              help="Exchange to download from")
@click.option("--symbol", "-s", required=True, default="BTC/USDT", show_default=True,
              help="Trading pair symbol (e.g. BTC/USDT)")
@click.option("--timeframe", "-t", required=True, default="1h", show_default=True,
              type=click.Choice(["1m","5m","15m","30m","1h","4h","1d"]),
              help="Candle timeframe")
@click.option("--start", required=True, type=click.DateTime(formats=["%Y-%m-%d"]),
              help="Start date (YYYY-MM-DD)")
@click.option("--end", default=None, type=click.DateTime(formats=["%Y-%m-%d"]),
              help="End date (YYYY-MM-DD). Defaults to today.")
@click.option("--market-type", default="spot",
              type=click.Choice(["spot", "future", "linear"]),
              help="Market type (spot/future/linear)")
def download(exchange, symbol, timeframe, start, end, market_type):
    """Download historical OHLCV data and store in TimescaleDB."""
    from data.crawler.binance_crawler import BinanceCrawler
    from data.crawler.bybit_crawler import BybitCrawler
    from data.storage.timescale_client import TimescaleClient

    database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tradingbot")

    logger.info(f"Downloading {symbol} [{timeframe}] from {exchange} | {start.date()} → {end or 'now'}")

    # Init DB
    db = TimescaleClient(database_url)
    db.init_db()

    # Select crawler
    if exchange == "binance":
        crawler = BinanceCrawler(
            api_key=os.getenv("BINANCE_API_KEY", ""),
            api_secret=os.getenv("BINANCE_API_SECRET", ""),
            market_type=market_type,
        )
    elif exchange == "bybit":
        crawler = BybitCrawler(
            api_key=os.getenv("BYBIT_API_KEY", ""),
            api_secret=os.getenv("BYBIT_API_SECRET", ""),
            market_type=market_type,
        )
    else:
        raise click.BadParameter(f"Unsupported exchange: {exchange}")

    # Fetch data
    df = crawler.fetch_ohlcv_historical(symbol, timeframe, since=start)

    # Filter by end date if provided
    if end and not df.empty:
        df = df[df.index <= end] if df.index.name == "time" else df[df["time"] <= end]

    if df.empty:
        logger.warning("No data fetched. Check symbol / timeframe / date range.")
        return

    logger.info(f"Fetched {len(df)} candles. Storing in database...")

    records = crawler.df_to_records(df)
    count = db.upsert_ohlcv(records)

    logger.success(f"Done! Stored {count} candles for {exchange} {symbol} {timeframe}")


if __name__ == "__main__":
    download()
