import json
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from data.models.base import Base
from data.models.ohlcv import OHLCV


class TimescaleClient:
    """
    Client for interacting with TimescaleDB (PostgreSQL).
    Handles connection, schema creation, and OHLCV data operations.
    """

    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, pool_pre_ping=True, pool_size=10)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        logger.info(f"TimescaleDB connected: {database_url.split('@')[-1]}")

    def init_db(self) -> None:
        """Create all tables and set up TimescaleDB hypertable."""
        Base.metadata.create_all(self.engine)
        with self.engine.connect() as conn:
            # Create hypertable (ignore if already exists)
            conn.execute(text("""
                SELECT create_hypertable(
                    'ohlcv', 'timestamp',
                    if_not_exists => TRUE,
                    migrate_data => TRUE
                );
            """), execution_options={"autocommit": True})
            conn.commit()
        logger.info("Database initialized and hypertable created.")

    def upsert_ohlcv(self, records: list[dict]) -> int:
        """
        Bulk upsert OHLCV records into the database.

        Args:
            records: List of dicts with keys:
                     time, exchange, symbol, timeframe, open, high, low, close, volume

        Returns:
            Number of records upserted.
        """
        if not records:
            return 0

        stmt = insert(OHLCV).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["timestamp", "exchange", "symbol", "timeframe"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

        logger.debug(f"Upserted {len(records)} OHLCV records.")
        return len(records)

    def query_ohlcv(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Query OHLCV data as a pandas DataFrame.

        Returns:
            DataFrame with columns: time, open, high, low, close, volume
        """
        end = end or datetime.utcnow()

        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT timestamp, open, high, low, close, volume
                    FROM ohlcv
                    WHERE exchange = :exchange
                      AND symbol   = :symbol
                      AND timeframe = :timeframe
                      AND timestamp BETWEEN :start AND :end
                    ORDER BY timestamp ASC
                """),
                {
                    "exchange": exchange,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "start": start,
                    "end": end,
                },
            )
            rows = result.fetchall()

        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df.set_index("time", inplace=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        logger.debug(f"Queried {len(df)} rows for {exchange} {symbol} {timeframe}")
        return df

    def get_last_candle(
        self, exchange: str, symbol: str, timeframe: str
    ) -> Optional[datetime]:
        """
        Get the timestamp of the most recent candle for a given market.

        Returns:
            datetime of the latest candle, or None if no data exists.
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT MAX(timestamp)
                    FROM ohlcv
                    WHERE exchange  = :exchange
                      AND symbol    = :symbol
                      AND timeframe = :timeframe
                """),
                {"exchange": exchange, "symbol": symbol, "timeframe": timeframe},
            )
            row = result.fetchone()

        last_time = row[0] if row else None
        logger.debug(f"Last candle for {exchange} {symbol} {timeframe}: {last_time}")
        return last_time

    def query_latest_ohlcv(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Query the N latest OHLCV records."""
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT timestamp, open, high, low, close, volume
                    FROM ohlcv
                    WHERE exchange = :exchange
                      AND symbol   = :symbol
                      AND timeframe = :timeframe
                    ORDER BY timestamp DESC
                    LIMIT :limit
                """),
                {
                    "exchange": exchange,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "limit": limit,
                },
            )
            rows = result.fetchall()

        # result is DESC, we need ASC for indicators
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df.set_index("time", inplace=True)
        df.sort_index(ascending=True, inplace=True)
        
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        return df

    def get_available_symbols(self, exchange: str, timeframe: str) -> list[str]:
        """Return list of symbols available in DB for a given exchange and timeframe."""
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT DISTINCT symbol
                    FROM ohlcv
                    WHERE exchange = :exchange AND timeframe = :timeframe
                    ORDER BY symbol
                """),
                {"exchange": exchange, "timeframe": timeframe},
            )
            return [row[0] for row in result.fetchall()]
