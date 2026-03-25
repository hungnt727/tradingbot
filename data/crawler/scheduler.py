"""
APScheduler-based incremental data sync scheduler.
Runs cron jobs for each configured (exchange, symbol, timeframe) combination
to fetch new candles since the last saved timestamp.
"""
import os
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from data.crawler.binance_crawler import BinanceCrawler
from data.crawler.bybit_crawler import BybitCrawler
from data.crawler.base_crawler import BaseCrawler
from data.storage.timescale_client import TimescaleClient

# Cron expressions for each timeframe
TIMEFRAME_CRON = {
    "1m":  {"minute": "*/1"},
    "5m":  {"minute": "*/5"},
    "15m": {"minute": "*/15"},
    "30m": {"minute": "*/30"},
    "1h":  {"minute": "1", "hour": "*/1"},
    "4h":  {"minute": "1", "hour": "*/4"},
    "1d":  {"minute": "1", "hour": "0"},
}


def sync_job(
    crawler: BaseCrawler,
    db: TimescaleClient,
    symbol: str,
    timeframe: str,
) -> None:
    """
    Incremental sync job: fetch candles since the last stored candle and upsert into DB.
    """
    exchange = crawler.exchange_id
    logger.info(f"[{exchange}] Syncing {symbol} {timeframe}...")

    try:
        last_candle_time = db.get_last_candle(exchange, symbol, timeframe)

        # If no data yet, fetch last 1000 candles (SonicR needs 620 for EMA610)
        if last_candle_time is None:
            df = crawler.fetch_latest_candles(symbol, timeframe, limit=1000)
        else:
            # Fetch from last candle onwards (small batch)
            df = crawler.fetch_ohlcv_historical(
                symbol, timeframe, since=last_candle_time, limit=500
            )

        if df.empty:
            logger.debug(f"[{exchange}] No new candles for {symbol} {timeframe}")
            return

        records = crawler.df_to_records(df)
        count = db.upsert_ohlcv(records)
        logger.success(f"[{exchange}] Synced {count} candles for {symbol} {timeframe}")

    except Exception as e:
        logger.error(f"[{exchange}] Sync failed for {symbol} {timeframe}: {e}")


class DataScheduler:
    """
    Manages scheduled incremental sync jobs for multiple exchanges, symbols, timeframes.
    """

    def __init__(self, database_url: str):
        self.db = TimescaleClient(database_url)
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self._crawlers: dict[str, BaseCrawler] = {}

    def add_exchange(self, crawler: BaseCrawler) -> None:
        """Register an exchange crawler."""
        self._crawlers[crawler.exchange_id] = crawler
        logger.info(f"Registered exchange: {crawler.exchange_id}")

    def add_job(self, exchange: str, symbol: str, timeframe: str) -> None:
        """Add a sync job for a specific exchange/symbol/timeframe."""
        if exchange not in self._crawlers:
            raise ValueError(f"Exchange '{exchange}' not registered. Call add_exchange() first.")

        cron_kwargs = TIMEFRAME_CRON.get(timeframe)
        if not cron_kwargs:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        crawler = self._crawlers[exchange]
        job_id = f"{exchange}_{symbol.replace('/', '_')}_{timeframe}"

        self.scheduler.add_job(
            sync_job,
            CronTrigger(**cron_kwargs),
            args=[crawler, self.db, symbol, timeframe],
            id=job_id,
            name=f"Sync {exchange} {symbol} {timeframe}",
            replace_existing=True,
            misfire_grace_time=60,
        )
        logger.info(f"Scheduled job: {job_id} (cron: {cron_kwargs})")

    def add_custom_job(self, func, cron_kwargs: dict, job_id: str, name: str) -> None:
        """Add a general-purpose scheduled job (e.g. reporting)."""
        self.scheduler.add_job(
            func,
            CronTrigger(**cron_kwargs),
            id=job_id,
            name=name,
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info(f"Scheduled custom job: {job_id} (cron: {cron_kwargs})")

    def start(self) -> None:
        """Start the scheduler (non-blocking)."""
        logger.info(f"Starting scheduler with {len(self.scheduler.get_jobs())} jobs...")
        self.scheduler.start()

    def stop(self) -> None:
        """Gracefully shutdown the scheduler."""
        logger.info("Stopping scheduler...")
        self.scheduler.shutdown()
        logger.success("Scheduler stopped.")
