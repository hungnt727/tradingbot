---
title: Web Control Panel for Signal Bot
status: ready-for-agent
created: 2026-05-25
author: hungit9801
provenance: synthesised from grill-me session (14 grilled questions) — see docs/WEB_CONTROL_PANEL_PLAN.md for audit trail
---

# Web Control Panel for Signal Bot

## Problem Statement

Hiện tại để chạy 1 signal bot trên TradingBot, user phải SSH vào VPS và chạy CLI script (`cli/run_ema_rsi_reversal_bot.py`, `cli/run_distribution_signal_bot.py`...). Quy trình này có những vấn đề:

- **Khó cho non-tech user** — phải nhớ command, args, file `.env`, biết cách dùng `screen`/`systemd`.
- **Không có lịch sử signal** — alert chỉ tồn tại trong Telegram chat. Muốn audit "tháng trước bot phát hiện được mấy signal" → phải scroll Telegram.
- **Không multi-tenant** — 2-5 người dùng chung 1 bot CLI = chung 1 chat ID Telegram, chung 1 bộ tham số. Không ai customize riêng được.
- **Không bật/tắt từng config** — 1 user muốn chạy 2 setup khác nhau (Top 100 1H scan và watchlist 5 coins 4H scan) phải chạy 2 process CLI tách biệt + nhớ PID + tự quản lý.
- **Edit tham số = restart CLI** — đổi `--top 200` thành `--top 300` phải kill rồi chạy lại.
- **Không có ownership/separation** — admin và user không phân quyền.

## Solution

Một web app private (truy cập qua Tailscale tailnet, không public) cho 2-5 user (1 admin + 1-4 user thường). Mỗi user login bằng username/password, quản lý nhiều "process bot" độc lập của riêng mình.

Mỗi **process** = 1 strategy (v1 chỉ `EmaRsiReversal`) + bộ tham số riêng + exchange + scope symbols (Top N hoặc custom list) + interval + Telegram chat ID. User CRUD process bất kỳ lúc nào và bật/tắt độc lập.

Backend có 2 service:
- **Web (FastAPI)** — serve UI + auth + CRUD.
- **Worker daemon** — chạy nền 24/7, mỗi 10-30 giây quét DB tìm process đến hạn, crawl OHLCV, chạy strategy, lưu signal mới, gửi Telegram alert.

Có nút "Quét ngay" cho one-shot test. Có trang lịch sử signal cho audit. Tham số có thể chỉnh bất kỳ lúc nào, có hiệu lực chu kỳ kế tiếp mà không phải restart.

## User Stories

### Admin (1 người)

1. As an admin, I want to bootstrap the first admin account via a CLI script, so that I can log into the web before any user exists.
2. As an admin, I want to log into the web with username/password, so that I can manage the system.
3. As an admin, I want to log out, so that my session is invalidated immediately.
4. As an admin, I want to create new user accounts from a web page, so that I don't have to SSH into the VPS every time someone joins.
5. As an admin, I want to optionally mark a new user as admin during creation, so that I can delegate ops.
6. As an admin, I want to reset any user's password, so that I can help them when they forget it (no email setup needed).
7. As an admin, I want to delete a user account, so that ex-collaborators lose access immediately (their processes and signals cascade-delete).
8. As an admin, I want to list all users with their last activity, so that I can audit who is using the system.
9. As an admin, I want to view all processes of every user (read-only), so that I can debug when someone reports an issue.
10. As an admin, I want my own profile (Telegram chat ID, password) to work exactly like a regular user's, so that I don't have separate UX paths.

### Regular user (1-4 người)

11. As a user, I want to log in with username/password, so that I access only my own processes.
12. As a user, I want to log out, so that my session ends.
13. As a user, I want to change my own password, so that I can rotate credentials.
14. As a user, I want to save a default Telegram chat ID in my profile, so that all my processes inherit it automatically.
15. As a user, I want a "Test Telegram" button next to my chat ID field, so that I confirm the bot can reach me before saving.
16. As a user, I want to see a list of my processes with status badges (idle/running/OK/error/stuck), so that I know what's happening at a glance.
17. As a user, I want to create a new process by giving it a name, picking a strategy (v1: EmaRsiReversal only), an exchange (binance/bybit), a symbol mode (Top N or custom list), an interval (minutes between scans), an optional per-process Telegram chat ID, and strategy parameters, so that I have full control over what gets scanned and how.
18. As a user, I want the strategy params form split into Basic (5 signal-detection fields) and Advanced collapsible (5 display/orchestration fields), so that I'm not overwhelmed by 10 fields if I just want defaults.
19. As a user, I want every numeric param to have min/max bounds and tooltips, so that I can't break the bot by typing nonsense values.
20. As a user, I want to edit any field of an active process at any time, so that I can tune without stopping the bot.
21. As a user, I want my edits to take effect from the next scan cycle (not immediately mid-run), so that the bot's behavior is predictable.
22. As a user, I want to delete a process at any time, so that I can clean up experiments without first stopping.
23. As a user, I want a Start/Stop toggle per process, so that I can pause without losing config.
24. As a user, I want a "Quét ngay" (Scan now) button per process, so that I can test signal detection without waiting for the scheduled interval.
25. As a user, I want one-shot scans to return UI feedback within ~30 seconds (badge "running → OK") without blocking the page, so that I can keep working.
26. As a user, I want each process to optionally override the Telegram chat ID, so that I can send certain signals to a team group instead of my personal chat.
27. As a user, I want to customize SL/TP percentages in Advanced params, so that the Telegram message displays SL/TP values matching my actual trading strategy.
28. As a user, I want to receive Telegram alerts automatically when the worker finds a new signal, so that I don't have to check the web manually.
29. As a user, I want the bot to never send me a duplicate Telegram alert for the same candle, so that I'm not spammed if the worker scans the same candle twice.
30. As a user, I want to view a paginated history of signals per process (filter by exchange/symbol/signal_type), so that I can audit performance.
31. As a user, I want to click a signal row to see the full indicator snapshot at that moment (RSI, EMA-RSI 5/10/20, ATR, ...), so that I can debug why the bot fired.
32. As a user, I want to see which signals were successfully sent to Telegram vs failed (badge), so that I can troubleshoot delivery issues.
33. As a user, I want the bot to keep scanning even if Telegram is unreachable, so that I don't lose signals — I can recover them from the history when Telegram comes back.

### Worker daemon (system actor)

34. As the worker, I want to poll the DB every 10-30 seconds for processes that are due, so that I trigger scans on time without external scheduler.
35. As the worker, I want to read the latest process row and params from DB at the start of each cycle, so that user edits during a previous cycle take effect immediately on the next.
36. As the worker, I want to perform full backfill (~250 candles per symbol) on the very first cycle of a new process, so that the strategy has enough lookback data — and incremental fetch (only new candles since DB max timestamp) on subsequent cycles.
37. As the worker, I want to deduplicate API calls when two processes need the same `(exchange, symbol, timeframe)`, so that I don't waste exchange rate limit — the second process reads from DB (or fetches only new candles).
38. As the worker, I want to insert each detected signal with `ON CONFLICT DO NOTHING` on a per-process unique constraint, so that duplicate alerts on the same candle within the same process are impossible.
39. As the worker, I want to re-check that a process still exists in DB just before sending Telegram, so that a user deleting a process mid-cycle doesn't receive an orphan alert.
40. As the worker, I want to record `last_run_started_at` and `last_run_status='running'` before each scan, and clear them on completion, so that a reaper can detect stuck processes.
41. As the worker, I want a reaper sub-step at the start of each loop to reset any process stuck in `running` for more than 10 minutes back to `error: timeout`, so that worker crashes mid-cycle don't permanently block re-scheduling.
42. As the worker, I want Telegram send failures to be logged in `signals.telegram_error` and `processes.last_run_status` but NOT stop the process, so that the bot self-recovers when the issue is resolved.
43. As the worker, I want one-shot "Quét ngay" requests (signaled by `force_run_requested_at` in DB) to be picked up next cycle, so that the UX is unified with scheduled runs.

### Operations (admin-as-operator)

44. As an operator, I want both web and worker to run as systemd services with `Restart=always`, so that crashes auto-recover.
45. As an operator, I want the web service to bind only on the Tailscale tailnet IP (`100.x.x.x:8000`), so that the app is unreachable from the public internet by network design.
46. As an operator, I want UFW configured defense-in-depth (allow SSH + interface `tailscale0` only), so that even if the bind config is misconfigured the port stays closed.
47. As an operator, I want web and worker logs to flow to journald via stdout, so that I can `journalctl -u tradingbot-web -f` for debugging.
48. As an operator, I want config (Postgres URL, Redis URL, session secret, Telegram bot token, CMC API key) in a single `.env` file consumed by both services, so that I have one source of truth.
49. As an operator, I want the new app database (`tradingbot_app`) to have its own Alembic setup separate from the OHLCV database (`tradingbot`), so that migrations don't entangle.
50. As an operator, I want the worker to NOT depend on the existing `cli/start_scheduler.py`, so that I don't have to run two schedulers and can disable the legacy one safely.

## Implementation Decisions

### Architecture

- **Two-process deployment**: `tradingbot-web` (FastAPI) + `tradingbot-worker` (Python daemon). They communicate only through Postgres (config + scan state) and Redis (sessions + CMC cache). No direct IPC.
- **Network model**: Tailscale tailnet only. No public exposure. No HTTPS handling in code (Tailscale encrypts the tunnel).
- **Single tenancy boundary at user level**: every CRUD operation on `processes` and `signals` is gated by `owner_user_id = current_user.id` (or `current_user.is_admin` for read-only admin view).

### Database

- **Two Postgres databases on the same instance**:
  - `tradingbot` — existing, OHLCV time-series in TimescaleDB hypertable, unchanged.
  - `tradingbot_app` — new, app config (users, processes, signals).
- Worker reads/writes both: reads `tradingbot_app.processes` for schedule + writes `tradingbot.ohlcv` via existing crawler + writes `tradingbot_app.signals`.
- **Postgres role separation**: new role `tradingbot_app_user` with grants only on `tradingbot_app`. Web and worker connect with this role for app DB; reuse `postgres` (or existing role) for OHLCV.

### Schema (`tradingbot_app`)

- **`users`**: `id`, `username UNIQUE`, `password_hash` (bcrypt via passlib), `is_admin`, `default_telegram_chat_id` (nullable), `created_at`.
- **`processes`**: `id`, `owner_user_id FK ON DELETE CASCADE`, `name`, `strategy_name`, `strategy_params JSONB` (validated by Pydantic), `exchange`, `symbols_mode` (`top_n`|`list`), `symbols_value JSONB`, `interval_minutes` (CHECK ≥ 5), `telegram_chat_id` (nullable override), `is_active`, `last_run_at`, `last_run_started_at`, `last_run_status`, `force_run_requested_at`, `created_at`, `updated_at`. Indexed on `(is_active, last_run_at) WHERE is_active`.
- **`signals`**: `id`, `process_id FK ON DELETE CASCADE`, `exchange`, `symbol`, `timeframe`, `timestamp_candle`, `signal_type`, `indicators_snapshot JSONB`, `telegram_sent`, `telegram_sent_at`, `telegram_error`, `detected_at`. **UNIQUE (process_id, exchange, symbol, timeframe, timestamp_candle)** — the dedupe contract.

### Strategy support

- **v1 = only `EmaRsiReversal`**. The class exists at `strategies/ema_rsi_reversal_strategy.py`. Reused unchanged from the worker.
- Strategy params validated by a Pydantic v2 model with bounds (`ge` / `le`) on every numeric field. Defaults match the +710% baseline config.
- Form rendered server-side from the Pydantic schema with a Basic / Advanced split via HTML `<details>`.
- Timeframe is **not** user-configurable in v1 — `EmaRsiReversal` hardcodes 1H signal + 1D filter.
- Adding a new strategy in v2 = adding (a) a Pydantic params schema, (b) a form template, (c) an entry in `STRATEGY_REGISTRY`. Worker dispatches by `strategy_name`. No core refactor.

### Worker model

- **Single-threaded polling loop**, sleep 10-30s between cycles. Capacity math (5-15 active processes × 60-min interval = 1 due per 4-12 min average; per-scan cost ~30-90s) leaves significant headroom.
- **No external scheduler** (Celery, APScheduler, RQ). The loop, DB-driven schedule (`is_active AND scheduled_due OR force_run_requested_at IS NOT NULL`), and DB-driven status (`last_run_status`) are sufficient.
- **State machine for a scan cycle**: `idle → running (set last_run_started_at) → done (OK / error: ...) → idle`. Worker crash mid-`running` is healed by reaper.
- **Reaper sub-step** at the head of each loop: reset any row with `last_run_status='running' AND last_run_started_at + interval '10 minutes' < NOW()` back to `error: timeout (worker crash?)`.
- **Crawler integration**: import and call `data/crawler/binance_crawler.py` and `bybit_crawler.py` directly. Idempotent upsert at DB level (existing `ON CONFLICT DO UPDATE`) plus a check-max + incremental pattern at the worker level to avoid duplicate API calls when multiple processes share a symbol/TF.

### Telegram

- **Shared bot token** in `.env` (`TELEGRAM_BOT_TOKEN`). Admin creates one bot via BotFather, all users share it.
- **Chat ID layered**: process-level override > user default > validation error if both null and `is_active` flip requested.
- **Send failures are soft**: signal row still inserted (`telegram_sent=false`, `telegram_error='...'`), process keeps scanning, web shows warning badge, worker retries on next cycle naturally (the next signal will trigger another send attempt).
- **Message template hardcoded** in `worker/runner.py` (no per-process template customization in v1). Uses user-provided `sl_pct`, `tp1_pct`, `tp2_pct` for display-only SL/TP lines.

### Auth

- **Session-based, not JWT**. Cookie `session_id` (HttpOnly, SameSite=Lax, no Secure flag because Tailscale handles encryption). Redis key `session:{uuid} → user_id` with TTL 7 days, sliding renewal.
- **Password hash via `passlib` bcrypt**. Cost factor at library default (12) for v1.
- **Bootstrap admin via `scripts/create_admin.py`** — interactive `getpass` (no plaintext password in shell history).
- **Subsequent users created from `/admin/users`** by a logged-in admin.
- **No email password reset in v1** — admin resets via web, notifies user out-of-band (Telegram, Slack, etc.).

### CMC Top N caching

- `CMC_API_KEY` is shared in `.env`.
- Worker / web read `Top N` via a `cmc_service.fetch_top_n(exchange, n)` that checks Redis key `cmc:top_n:{exchange}:{n}` first (TTL 3600s) before hitting CMC API.
- Math: free tier 10,000 calls/month; with 1h cache → ~720 calls/month across all processes that share the same `(exchange, n)`. Comfortably under quota.

### Deployment

- **2 systemd unit files** (`tradingbot-web.service`, `tradingbot-worker.service`), both `Type=simple`, `Restart=always`, `EnvironmentFile=.env`, `Requires=tailscaled.service` for the web one.
- Web `ExecStart`: `uvicorn web.app:app --host 100.x.x.x --port 8000` (bind tailnet IP).
- UFW: `default deny incoming`, `allow 22/tcp`, `allow in on tailscale0`.
- Logging: Loguru → stdout → journald. Human-readable format in v1.

### Migration

- `alembic.ini` + `migrations/` — unchanged (OHLCV DB).
- `alembic_app.ini` + `migrations_app/versions/` — new, for `tradingbot_app` DB.
- Two separate `alembic upgrade head` invocations during deploy.

### Major modules to build

**Deep modules** (encapsulate complex behavior behind a stable, narrow interface — high test value):

1. **`worker.runner.run_one_process(process_id) -> RunResult`** — Orchestrates one full scan cycle: resolve symbols, ensure data ready, run strategy, dedupe-insert signals, send Telegram, update status. The most complex piece; everything else is plumbing.
2. **`worker.data_loader.ensure_data_ready(exchange, symbol, timeframe, min_required) -> DataFrame`** — Backfill logic: query DB max + count, decide full vs incremental fetch, upsert, return DataFrame ready for strategy. Stable interface; complex inside.
3. **`web.services.process_service`** — All CRUD operations on processes with ownership/admin authorization checks baked in. Web routes call this; tests poke it directly.
4. **`web.services.auth_service`** — `hash_password`, `verify_password`, `create_session(user_id) -> session_id`, `resolve_session(session_id) -> User | None`, `destroy_session(session_id)`.
5. **`web.services.cmc_service.fetch_top_n(exchange, n) -> list[str]`** — Cached Top N lookup. Trivial interface; Redis-aware inside.
6. **`web.services.telegram_service.send_message(chat_id, text) -> bool`** — Wraps Telegram Bot API with timeout, error classification (transient vs permanent). Returns success flag; caller logs error.

**Shallow modules** (thin glue — low test value, integration-tested only):

- FastAPI routes (`web/routes/*`) — thin handlers that delegate to services.
- Jinja2 templates — presentation only.
- SQLAlchemy ORM models — data containers.
- Pydantic schemas — data containers + validation.

## Testing Decisions

### What makes a good test

- **Test external behavior, not implementation**. Eg. `run_one_process` test feeds a fake process row and verifies (a) correct signals inserted in DB, (b) correct Telegram calls made (via mock), (c) correct status updates. Does NOT assert "the function called `_internal_helper` 3 times".
- **Integration over unit where DB is cheap**. Use a real Postgres test DB (or testcontainers) for service-layer tests instead of mocking the SQLAlchemy session. Faster to write, catches real schema bugs.
- **Mock at the external boundary**: Telegram API, CMC API, exchange (ccxt). Don't mock our own internal modules.

### Modules to test (deep modules above)

1. **`worker.runner.run_one_process`** — Highest priority. Tests:
   - Happy path: process with 2 symbols, 1 generates a signal → DB has 1 new signal row + Telegram called once + `last_run_status='OK'`.
   - Duplicate candle: run twice on same candle → second run inserts nothing, Telegram NOT called second time.
   - Telegram fail: mock returns 403 → signal still inserted, `telegram_sent=false`, `telegram_error` populated, status still `OK` with warning.
   - Process deleted mid-run: delete row between strategy run and Telegram send → no Telegram call.
   - Crash mid-cycle: simulate exception during strategy → `last_run_status='error: ...'`, `last_run_started_at` cleared.

2. **`worker.data_loader.ensure_data_ready`** — Tests:
   - DB empty → full fetch from crawler.
   - DB has 250+ candles, max_ts recent → incremental from max_ts only.
   - DB has 100 stale candles (below min_required) → falls back to full fetch.
   - Crawler returns empty → no DB write, returns existing DataFrame.

3. **`web.services.auth_service`** — Tests:
   - `hash_password` produces a different hash for the same input each call (salt).
   - `verify_password` accepts the original password and rejects others.
   - Session create + resolve roundtrip works.
   - Destroyed session no longer resolves.

4. **`web.services.process_service`** — Tests:
   - User cannot read process owned by another user (returns 404 / empty).
   - Admin can read processes of any user.
   - Edit on someone else's process by non-admin is rejected.
   - Delete cascades to signals.
   - Creating a process with `interval_minutes < 5` is rejected.

5. **`web.services.cmc_service.fetch_top_n`** — Tests:
   - First call hits CMC API and writes to Redis.
   - Second call within TTL reads from Redis (CMC API not called).
   - Cache miss after TTL expiry triggers fresh fetch.

6. **`web.services.telegram_service.send_message`** — Tests:
   - 200 OK → returns `True`.
   - 403 (bot blocked) → returns `False`, error logged.
   - Timeout → returns `False`.

### Prior art

- `tests/test_backtest.py`, `tests/test_crawler.py`, `tests/test_paper_trading.py`, `tests/test_sonicr_strategy.py`, `tests/test_timescale_client.py` — existing pytest suite using `pytest`, `pytest-asyncio`, `pytest-mock` (already in `requirements.txt`). Reuse fixtures and conventions; do not invent a parallel test framework.

## Out of Scope

The following are explicitly **not** included in v1. They may become v2 candidates after v1 ships and real usage informs priority:

- Support for strategies other than `EmaRsiReversal` (`SonicR`, `Distribution`).
- Backtest from the web UI.
- Paper trading or live trading from the web UI.
- Multi-exchange per single process (workaround: create 2 processes).
- Email-based password reset (admin-driven reset only in v1).
- Self-service signup / open registration.
- WebSocket / SSE realtime updates (HTMX polling is sufficient).
- Public JSON API (web is HTML-only in v1).
- Mobile native app.
- Per-user exchange API key (only needed if v2 introduces live trading from web).
- Internationalization / multi-language.
- Signal preview / mini-backtest button on the params form.
- Audit log of admin actions (could be added cheap as a `audit_log` table later).
- Rate limiting at the application layer (Tailscale removes the need; if web ever goes public, add then).

## Further Notes

### Things the agent must verify before/during implementation

1. **Crawler API key requirement** — Read `data/crawler/binance_crawler.py` and `bybit_crawler.py` to confirm whether public klines endpoint needs `BINANCE_API_KEY` / `BYBIT_API_SECRET`. If purely public, v1 can run without exchange keys; the plan assumes this is the case.
2. **Tailscale hostname / Magic DNS** — The VPS Tailscale hostname is operator-provided. Production `.env` needs the exact bind IP (`100.x.x.x`) or hostname.
3. **`processes.last_run_started_at` reaper threshold** — 10 minutes is a guess based on expected per-scan cost. If real scans take longer (eg. Top 300 backfill = 5-10 min), raise to 20.
4. **EmaRsiReversal dual-timeframe contract** — Verify whether the existing strategy class genuinely owns "1H signal + 1D filter" or whether the CLI bot orchestration in `cli/run_ema_rsi_reversal_bot.py` adds the 1D filter externally. If external, the worker must replicate that filter; this is a hidden coupling worth grepping.

### Suggested vertical slices for `/to-issues`

See `docs/WEB_CONTROL_PANEL_PLAN.md` section 12 for the 10-slice breakdown:

0. Skeleton  ·  1. Auth  ·  2. Admin user CRUD  ·  3. Process CRUD (no worker)  ·  4. Worker skeleton  ·  5. Worker scan logic  ·  6. Telegram alert  ·  7. Signal history UI  ·  8. One-shot "Quét ngay"  ·  9. Tailscale deploy

Recommend `/tdd` for slices 1, 3, 4, 5, 6, 8 (logic-heavy). Slices 0, 2, 7, 9 are mostly plumbing / config — integration tests sufficient.

### Audit trail

This PRD was synthesised from a `/grill-me` session of 14 interrogated decisions. The "rejected options + reasons" table is preserved in `docs/WEB_CONTROL_PANEL_PLAN.md` section 13 — consult it before revisiting any decision (eg. "why not Streamlit?", "why not Celery?", "why not public + Let's Encrypt?").

### Domain language

All terms used in this PRD conform to `CONTEXT.md` (root of the repo). Notable: a **Signal** is a row produced by a Strategy on a Candle, distinct from a **Trade** (this PRD is signal-only, no trades). The web here is a "Signal Bot" frontend — same category as the existing CLI `run_*_signal_bot.py`, not a "Trading Bot" frontend.
