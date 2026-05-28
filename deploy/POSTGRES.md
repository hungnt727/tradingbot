# Postgres setup — `tradingbot_app` DB + limited role

Phase 6 adds a second database on the existing Postgres instance. The OHLCV DB
(`tradingbot`) is unchanged. Run as the `postgres` superuser.

```sql
-- 1. App database
CREATE DATABASE tradingbot_app;

-- 2. Dedicated limited role (do NOT let web/worker use the postgres superuser)
CREATE ROLE tradingbot_app_user WITH LOGIN PASSWORD 'a-strong-password';
GRANT ALL PRIVILEGES ON DATABASE tradingbot_app TO tradingbot_app_user;
```

Then grant schema privileges (Postgres 15+ locks down the public schema):

```sql
\connect tradingbot_app
GRANT ALL ON SCHEMA public TO tradingbot_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON TABLES TO tradingbot_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON SEQUENCES TO tradingbot_app_user;
```

## Run migrations

Two separate Alembic setups, two invocations:

```bash
alembic upgrade head                      # OHLCV DB (tradingbot)
alembic -c alembic_app.ini upgrade head   # app DB (tradingbot_app)
```

`alembic_app.ini` reads `APP_DATABASE_URL` from `.env`. Verify:

```bash
alembic -c alembic_app.ini current        # should show 004 (head)
```

> The worker connects to BOTH databases: it reads/writes OHLCV in `tradingbot`
> (via the existing crawler + TimescaleClient using `DATABASE_URL`) and
> reads/writes `tradingbot_app` (processes + signals via `APP_DATABASE_URL`).
