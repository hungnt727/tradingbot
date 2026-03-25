#!/bin/bash
# Init script for TimescaleDB - runs on first startup

set -e

echo "Initializing TimescaleDB extensions and tables..."

# Create TimescaleDB extension
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
EOSQL

echo "TimescaleDB extension created."

# Create hypertable for OHLCV data
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create OHLCV table
    CREATE TABLE IF NOT EXISTS ohlcv (
        id BIGSERIAL,
        exchange TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL,
        open NUMERIC NOT NULL,
        high NUMERIC NOT NULL,
        low NUMERIC NOT NULL,
        close NUMERIC NOT NULL,
        volume NUMERIC NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (exchange, symbol, timeframe, timestamp)
    );

    -- Create TimescaleDB hypertable
    SELECT create_hypertable('ohlcv', 'timestamp', if_not_exists => TRUE);

    -- Create index for faster queries
    CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_timeframe ON ohlcv (symbol, timeframe, timestamp DESC);

    -- Create trades table
    CREATE TABLE IF NOT EXISTS trades (
        id BIGSERIAL PRIMARY KEY,
        exchange TEXT NOT NULL,
        symbol TEXT NOT NULL,
        strategy TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        side TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        entry_price NUMERIC,
        exit_price NUMERIC,
        position_size NUMERIC,
        pnl_usd NUMERIC,
        pnl_pct NUMERIC,
        trade_metadata JSONB,
        opened_at TIMESTAMPTZ DEFAULT NOW(),
        closed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- Create indexes for trades
    CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades (symbol);
    CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);
    CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades (strategy);
    CREATE INDEX IF NOT EXISTS idx_trades_opened_at ON trades (opened_at DESC);

    -- Create exchange_info table
    CREATE TABLE IF NOT EXISTS exchange_info (
        id BIGSERIAL PRIMARY KEY,
        exchange TEXT NOT NULL,
        symbol TEXT NOT NULL,
        info JSONB NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(exchange, symbol)
    );

    -- Enable TimescaleDB on trades table (optional - for time-series analytics)
    -- SELECT create_hypertable('trades', 'opened_at', if_not_exists => TRUE);

EOSQL

echo "Database tables created successfully!"
