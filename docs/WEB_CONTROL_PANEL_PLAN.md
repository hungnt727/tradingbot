# Web Control Panel — Implementation Plan

> **Status:** Design chốt sau grilling session — chưa implement.
> **Created:** 2026-05-25
> **Scope:** Web UI để quản lý signal bot (chiến lược + tham số + Telegram alert) cho 2-5 user trên VPS Tailscale.

---

## 1. Mục tiêu

Xây 1 web app cho phép 2-5 user (1 admin + 1-4 user thường):

1. **Login/Logout** an toàn qua session cookie.
2. **CRUD "process bot"** — mỗi process = 1 strategy + tham số riêng + symbols + interval + Telegram chat ID. Start/Stop độc lập từng process.
3. **Chạy chiến lược tự động** — worker daemon liên tục crawl OHLCV → check signal → gửi Telegram alert khi phát hiện tín hiệu mới. Có thêm nút "Quét ngay" cho one-shot test.
4. **Xem lịch sử signal** đã phát hiện cho mỗi process.

**Không** mở trade thật. **Không** paper trade. Đây thuần là **signal bot**.

---

## 2. Architecture

```
                            ┌─────────────────────────────────────┐
                            │  Tailscale tailnet (private)        │
                            │                                     │
[User browser] ──HTTP──────►│  VPS: 100.x.x.x                     │
  via Tailscale             │                                     │
                            │  ┌─────────────────────────────┐    │
                            │  │ systemd: tradingbot-web     │    │
                            │  │  FastAPI + Jinja2 + HTMX    │────┼──► Redis (sessions, CMC cache)
                            │  │  bind 100.x.x.x:8000        │    │
                            │  └──────┬──────────────────────┘    │
                            │         ▼                            │
                            │  ┌─────────────────────────────┐    │
                            │  │ Postgres (existing)         │    │
                            │  │  DB: tradingbot   (OHLCV)   │◄───┼──┐
                            │  │  DB: tradingbot_app         │    │  │
                            │  │    users, processes,        │    │  │
                            │  │    signals                  │    │  │
                            │  └─────────────────────────────┘    │  │
                            │         ▲ poll due / 10-30s         │  │
                            │  ┌──────┴──────────────────────┐    │  │
                            │  │ systemd: tradingbot-worker  │────┼──┘
                            │  │  Python daemon              │    │
                            │  │  single-threaded loop       │────┼──► Binance/Bybit klines
                            │  └─────────────────────────────┘    │──► Telegram Bot API
                            │                                     │──► CoinMarketCap (cached)
                            └─────────────────────────────────────┘
                            UFW: chỉ allow 22/tcp + interface tailscale0
```

---

## 3. Tech stack

| Layer | Choice | Lý do |
|---|---|---|
| Web framework | **FastAPI + Jinja2 + HTMX** | Async native, Pydantic reuse, no JS framework, no Node build |
| Auth | **Session cookie + Redis store + bcrypt** (`passlib`) | Redis đã có, logout easy (delete key), industry-standard hash |
| Form validation | **Pydantic v2** | Reuse cho strategy schema |
| Database | **Postgres existing instance, 2 DB** | `tradingbot` (OHLCV, existing) + `tradingbot_app` (users/processes/signals, MỚI) |
| Cache | **Redis** | Sessions + CMC Top N response cache TTL 3600s |
| Worker | **Python daemon, single-threaded polling loop** | Match scale (5-15 process active), không cần thread pool |
| Crawler | **Reuse `data/crawler/*`** | Không viết lại, idempotent upsert |
| Telegram | **Shared bot token + per-user default chat_id + per-process override** | 1 bot dùng chung cho cả team |
| Network | **Tailscale tailnet, no public exposure** | Zero brute force / scan risk, không cần HTTPS code |
| Process supervisor | **2 systemd service** (web + worker), bind tailnet IP | Native Linux, không container overhead |
| Migration | **2 alembic setup** (`alembic.ini` + `alembic_app.ini`) | 2 DB tách bạch, không lẫn revision |
| Logging | **Loguru → stdout → journald** | `journalctl -u <service> -f` tail trực tiếp |

---

## 4. Database schema (DB `tradingbot_app`)

```sql
-- ============================================
-- USERS
-- ============================================
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,            -- bcrypt
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    default_telegram_chat_id VARCHAR(50),           -- nullable
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- PROCESSES (1 user has many processes)
-- ============================================
CREATE TABLE processes (
    id SERIAL PRIMARY KEY,
    owner_user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    strategy_name VARCHAR(50) NOT NULL,             -- 'EmaRsiReversal' (v1 only)
    strategy_params JSONB NOT NULL,                 -- validated by Pydantic schema
    exchange VARCHAR(20) NOT NULL,                  -- 'binance' | 'bybit'
    symbols_mode VARCHAR(10) NOT NULL,              -- 'top_n' | 'list'
    symbols_value JSONB NOT NULL,                   -- {"top_n": 100} | {"list": ["BTC/USDT", ...]}
    interval_minutes INT NOT NULL CHECK (interval_minutes >= 5),
    telegram_chat_id VARCHAR(50),                   -- nullable, override user default
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    last_run_at TIMESTAMPTZ,
    last_run_started_at TIMESTAMPTZ,                -- for stuck detection by reaper
    last_run_status TEXT,                           -- 'idle' | 'running' | 'OK' | 'error: ...'
    force_run_requested_at TIMESTAMPTZ,             -- "Quét ngay" one-shot flag
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_processes_owner ON processes (owner_user_id);
CREATE INDEX ix_processes_due ON processes (is_active, last_run_at) WHERE is_active;

-- ============================================
-- SIGNALS (history per process)
-- ============================================
CREATE TABLE signals (
    id BIGSERIAL PRIMARY KEY,
    process_id INT NOT NULL REFERENCES processes(id) ON DELETE CASCADE,
    exchange VARCHAR(20) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    timestamp_candle TIMESTAMPTZ NOT NULL,
    signal_type VARCHAR(10) NOT NULL,               -- 'LONG' | 'SHORT'
    indicators_snapshot JSONB NOT NULL,             -- {rsi, ema_rsi_5, ema_rsi_10, ema_rsi_20, atr, ...}
    telegram_sent BOOLEAN NOT NULL DEFAULT FALSE,
    telegram_sent_at TIMESTAMPTZ,
    telegram_error TEXT,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (process_id, exchange, symbol, timeframe, timestamp_candle)
);

CREATE INDEX ix_signals_process_recent ON signals (process_id, detected_at DESC);
```

**Notes:**
- `ON DELETE CASCADE`: xoá user → xoá process → xoá signals.
- `UNIQUE` constraint trên signals: dedupe per-process (cùng candle, cùng process → không gửi telegram lại).
- Worker pattern: `INSERT ... ON CONFLICT DO NOTHING RETURNING id` → nếu có row mới → gửi Telegram.

---

## 5. Strategy params schema (Pydantic v2)

EmaRsiReversal v1 — form 2 tier:

```python
from pydantic import BaseModel, Field

class EmaRsiReversalParams(BaseModel):
    # --- Basic (hiện luôn) ---
    rsi_period: int = Field(14, ge=2, le=100,
        description="RSI period")
    max_distance_candles: int = Field(20, ge=1, le=200,
        description="Max bars since 1H reversal candle")
    min_gap: float = Field(0.0, ge=0.0, le=0.1,
        description="Min EMA-RSI gap threshold")
    use_ema_filter: bool = Field(False,
        description="Enable EMA-200 trend filter")
    min_ema_rsi: float = Field(50.0, ge=0.0, le=100.0,
        description="ema_rsi_20 threshold")

    # --- Advanced (collapsible <details>) ---
    sl_pct: float = Field(0.05, ge=0.001, le=1.0,
        description="Stop loss % (display only in Telegram)")
    tp1_pct: float = Field(0.10, ge=0.001, le=2.0,
        description="Take profit 1 %")
    tp2_pct: float = Field(0.20, ge=0.001, le=2.0,
        description="Take profit 2 %")
    lookback: int = Field(250, ge=200, le=2000,
        description="Candles to load for indicators")
    n1d: int = Field(20, ge=1, le=100,
        description="Max bars since 1D reversal")
    m1h: int = Field(3, ge=1, le=20,
        description="Max bars since 1H reversal")
```

- Bounds chống user gõ nhầm zero/negative/quá lớn.
- Timeframe **không** trong form — hardcode 1H + 1D filter trong strategy.
- DB column `processes.strategy_params JSONB` lưu dict đã validate.

---

## 6. Worker daemon

### 6.1 Concurrency

**Single-threaded polling loop**:

```python
# worker/daemon.py (pseudo)
while True:
    reap_stuck_processes()      # reset last_run_status='running' kéo dài > 10 phút
    due = query_due_processes() # is_active AND (scheduled_due OR force_run_requested_at)
    for process in due:
        run_one_process(process)
    sleep(10)  # hoặc 30s
```

Capacity math: 5-15 process active × default 60min interval = trung bình 1 process due / 4-12 phút. 1 process quét ~1-2 phút (serial). Dư công suất nhiều lần.

Refactor sang thread pool / async là local change về sau khi cần — không cần ngay.

### 6.2 `run_one_process(p)` pattern

```python
def run_one_process(p):
    # 1. Mark started
    db.execute("UPDATE processes SET last_run_status='running',
                last_run_started_at=NOW(), force_run_requested_at=NULL
                WHERE id=:id", {"id": p.id})

    try:
        # 2. Resolve symbols (top_n via CMC cache, or static list)
        symbols = resolve_symbols(p.exchange, p.symbols_mode, p.symbols_value)

        # 3. Ensure data ready (check-max + incremental)
        for symbol in symbols:
            for tf in ["1h", "1d"]:
                ensure_data_ready(p.exchange, symbol, tf, min_required=250)

        # 4. Run strategy
        signals_found = run_ema_rsi_reversal(p.strategy_params, symbols, p.exchange)

        # 5. For each signal: insert with dedupe, send telegram
        for sig in signals_found:
            inserted = db.insert_signal_on_conflict_do_nothing(p.id, sig)
            if inserted:
                # Re-check process still exists (avoid telegram after delete)
                if not db.process_still_active(p.id):
                    continue
                chat_id = p.telegram_chat_id or p.owner.default_telegram_chat_id
                send_telegram(chat_id, format_alert(sig, p))
                db.mark_telegram_sent(sig.id)

        db.execute("UPDATE processes SET last_run_at=NOW(),
                    last_run_status='OK', last_run_started_at=NULL
                    WHERE id=:id", {"id": p.id})
    except Exception as e:
        db.execute("UPDATE processes SET last_run_at=NOW(),
                    last_run_status=:err, last_run_started_at=NULL
                    WHERE id=:id",
                   {"id": p.id, "err": f"error: {str(e)[:500]}"})
```

### 6.3 Backfill — check-max + incremental

```python
def ensure_data_ready(exchange, symbol, timeframe, min_required=250):
    max_ts, count = db.query_ohlcv_meta(exchange, symbol, timeframe)

    if max_ts is None or count < min_required:
        # Full backfill từ exchange
        candles = crawler.fetch_ohlcv(symbol, timeframe, limit=min_required + 50)
    else:
        # Incremental — chỉ nến mới
        candles = crawler.fetch_ohlcv(symbol, timeframe, since=max_ts + 1)

    if candles:
        db.upsert_ohlcv(candles)
```

→ Process B vào sau process A (cùng symbol/TF) không fetch trùng. Idempotent ở DB layer (UPSERT) + tránh duplicate ở API layer (check-max).

### 6.4 Crash recovery

Reaper ở đầu mỗi vòng loop:

```sql
UPDATE processes
SET last_run_status = 'error: timeout (worker crash?)',
    last_run_started_at = NULL
WHERE last_run_status = 'running'
  AND last_run_started_at + INTERVAL '10 minutes' < NOW();
```

Process bị stuck > 10 phút → reset → cho phép schedule lại ở chu kỳ kế tiếp.

### 6.5 Telegram fail handling

Telegram error (bot blocked, network down, chat_id sai) **không stop process**:
- Signal vẫn lưu DB (`telegram_sent=false`, `telegram_error='...'`).
- `last_run_status='OK (telegram error: ...)'` để web hiển thị warning badge.
- Chu kỳ kế tiếp tự retry — bot unblocked → alert quay lại tự động.

### 6.6 Telegram message format (hardcode template)

```
🚨 {signal_type} signal — {symbol} ({exchange})
TF: 1H | Time: {timestamp_candle} UTC

RSI: {rsi:.1f} | EMA RSI 20: {ema_rsi_20:.1f}
Entry: ${close:.2f}
SL:    ${close * (1 - sl_pct):.2f}  ({sl_pct*100:.0f}%)
TP1:   ${close * (1 + tp1_pct):.2f}  ({tp1_pct*100:.0f}%)
TP2:   ${close * (1 + tp2_pct):.2f}  ({tp2_pct*100:.0f}%)

Reason: bars_since_reversal={...}, ema_rsi_20 > 50
Process: "{process_name}" by {username}
```

---

## 7. Project structure (new folders)

```
TradingBot/
├── web/                              # ← NEW
│   ├── __init__.py
│   ├── app.py                        # FastAPI app factory + middleware
│   ├── deps.py                       # get_current_user, db_session, ...
│   ├── routes/
│   │   ├── auth.py                   # /login, /logout
│   │   ├── processes.py              # /processes, /processes/:id, start/stop/force-run
│   │   ├── signals.py                # /processes/:id/signals
│   │   ├── admin.py                  # /admin/users (CRUD users)
│   │   └── settings.py               # /settings (telegram chat_id, change password)
│   ├── templates/                    # Jinja2
│   │   ├── base.html
│   │   ├── auth/login.html
│   │   ├── processes/list.html
│   │   ├── processes/form.html
│   │   ├── signals/list.html
│   │   ├── admin/users.html
│   │   └── settings/profile.html
│   ├── static/
│   │   ├── css/app.css
│   │   ├── js/htmx.min.js
│   │   └── js/alpine.min.js
│   ├── models/                       # SQLAlchemy
│   │   ├── user.py
│   │   ├── process.py
│   │   └── signal.py
│   ├── schemas/                      # Pydantic
│   │   ├── auth.py                   # LoginIn, ...
│   │   ├── process.py                # ProcessIn, ProcessOut, SymbolsValue
│   │   └── strategy_params.py        # EmaRsiReversalParams
│   └── services/
│       ├── auth_service.py           # hash, verify, session create/delete
│       ├── user_service.py           # create_user, reset_password, list
│       ├── process_service.py        # CRUD processes
│       ├── telegram_service.py       # send_message, test_chat
│       └── cmc_service.py            # fetch_top_n_cached
│
├── worker/                           # ← NEW
│   ├── __init__.py
│   ├── daemon.py                     # main loop entry: python -m worker.daemon
│   ├── runner.py                     # run_one_process(p)
│   ├── reaper.py                     # reap_stuck_processes()
│   └── data_loader.py                # ensure_data_ready(exchange, symbol, tf)
│
├── migrations_app/                   # ← NEW (Alembic cho tradingbot_app)
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── alembic_app.ini                   # ← NEW
│
├── scripts/
│   └── create_admin.py               # ← NEW (interactive CLI bootstrap)
│
└── (existing folders unchanged)
    ├── data/                         # crawler reused
    ├── strategies/                   # EmaRsiReversal reused
    ├── backtest/
    ├── paper_trading/
    ├── dashboard/                    # existing Streamlit (giữ nguyên, độc lập)
    ├── cli/
    ├── docker/                       # Postgres + Redis stack
    ├── migrations/                   # existing Alembic cho tradingbot DB
    └── ...
```

---

## 8. Deployment

### 8.1 Systemd services

```ini
# /etc/systemd/system/tradingbot-web.service
[Unit]
Description=TradingBot Web (FastAPI)
After=network.target postgresql.service redis.service tailscaled.service
Requires=tailscaled.service

[Service]
Type=simple
User=tradingbot
WorkingDirectory=/opt/tradingbot
EnvironmentFile=/opt/tradingbot/.env
ExecStart=/opt/tradingbot/venv/bin/uvicorn web.app:app --host 100.x.x.x --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/tradingbot-worker.service
[Unit]
Description=TradingBot Worker daemon
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=tradingbot
WorkingDirectory=/opt/tradingbot
EnvironmentFile=/opt/tradingbot/.env
ExecStart=/opt/tradingbot/venv/bin/python -m worker.daemon
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 8.2 Firewall (defense-in-depth — bind tailnet IP đã đủ, ufw là backup)

```bash
ufw default deny incoming
ufw allow 22/tcp                   # SSH
ufw allow in on tailscale0         # tailnet truy cập tất cả
ufw enable
```

### 8.3 Tailscale setup

- Cài Tailscale daemon trên VPS + mỗi device user (laptop, phone).
- Admin approve mỗi device qua console.
- Magic DNS: `http://vps-hostname:8000` thay vì `http://100.x.x.x:8000`.
- Free tier: 100 device (dư cho 5 user × 2-3 device).

### 8.4 `.env` (secrets shared)

```env
# Existing
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tradingbot
REDIS_URL=redis://localhost:6379/0
BYBIT_API_KEY=...
BINANCE_API_KEY=...

# NEW for web
APP_DATABASE_URL=postgresql://tradingbot_app_user:***@localhost:5432/tradingbot_app
SESSION_SECRET_KEY=...                  # cho cookie signing
TELEGRAM_BOT_TOKEN=...                  # shared bot
COINMARKETCAP_API_KEY=...               # shared, cache 1h
```

---

## 9. Feature list (v1 scope)

### Auth
- [x] Login (POST /login → session cookie + Redis)
- [x] Logout (DELETE Redis key + clear cookie)
- [x] Session TTL 7 ngày, sliding renewal
- [x] Password hash bcrypt (passlib)
- [x] Cookie HttpOnly, SameSite=Lax (không cần Secure vì Tailscale encrypt)

### Process CRUD
- [x] List process của user hiện tại (admin xem được tất cả)
- [x] Create process: name + strategy (EmaRsiReversal only) + exchange + symbols_mode (top_n/list) + interval + Telegram chat_id (optional override) + strategy_params form 2 tier
- [x] Edit anytime — params có hiệu lực chu kỳ kế tiếp (worker re-read DB mỗi cycle)
- [x] Delete anytime — worker re-check row tồn tại trước khi send Telegram
- [x] Toggle Start/Stop (toggle `is_active`)
- [x] "Quét ngay" button → set `force_run_requested_at=NOW()`
- [x] Badge status: `idle` / `running` / `OK` / `error: ...`

### Worker
- [x] Single-threaded polling loop sleep 10-30s
- [x] Reaper: reset stuck `running > 10 phút`
- [x] Backfill chu kỳ đầu: check-max + incremental
- [x] Reuse `data/crawler/binance_crawler.py` + `bybit_crawler.py`
- [x] Per-process signal dedupe via UNIQUE + INSERT ON CONFLICT DO NOTHING
- [x] Telegram send hardcode template
- [x] Telegram fail → log warning, không stop process

### Signal history
- [x] List signals của 1 process (filter exchange/symbol/signal_type, paginate)
- [x] Status badge: telegram_sent / failed / pending
- [x] Click row → modal indicators_snapshot

### Settings (user profile)
- [x] Edit default Telegram chat_id + Test button (bắn test message)
- [x] Change password

### Admin (chỉ `is_admin=true`)
- [x] List users
- [x] Create user (set is_admin?, set default_telegram_chat_id?)
- [x] Reset password (admin set new password, notify user out-of-band)
- [x] Delete user (CASCADE xoá processes)
- [x] View tất cả process của mọi user (read-only)

### CLI
- [x] `scripts/create_admin.py` — interactive bootstrap (getpass, hide password input)

---

## 10. Out of v1 scope (v2+)

- SonicR + Distribution strategy support (cần dynamic Pydantic schema render)
- Backtest từ web UI
- Paper / Live trading từ web
- Multi-exchange per process
- Email-based self-service password reset
- Self-service signup (open registration)
- WebSocket realtime push (thay HTMX poll)
- JSON API public
- Mobile native app
- Per-user exchange API key (cần khi có Live trading)
- i18n / multi-language
- Backtest preview button trên form params

---

## 11. Open items cần verify khi implement

1. **Crawler có cần exchange API key cho public klines không?**
   Đọc [`data/crawler/binance_crawler.py`](../data/crawler/binance_crawler.py) thực tế. Nếu chỉ public klines → v1 không cần `BINANCE_API_KEY`/`BYBIT_API_KEY`.

2. **Tailscale hostname** — VPS phải đăng ký hostname trong tailnet (vd `tradingbot.tailxxx.ts.net`). Cần config Magic DNS 1 lần.

3. **VPS firewall hiện trạng** — check `ufw status` trước deploy. Đảm bảo không tự động expose port 8000 ra public.

4. **Postgres role tách bạch** — tạo role `tradingbot_app_user` với grant chỉ trên DB `tradingbot_app`. Không dùng `postgres` superuser cho web/worker.

5. **CMC free tier monitoring** — 10,000 call/tháng. Cache 1h → ~720/tháng. Monitor để biết nếu user pattern tăng đột biến.

---

## 12. Suggested implementation slices

Bẻ thành vertical slices, mỗi slice deploy được độc lập:

| Slice | Scope | Verify |
|---|---|---|
| **0. Skeleton** | Folder structure + alembic_app + scripts/create_admin.py + 1 health endpoint | `curl http://localhost:8000/health` → 200 |
| **1. Auth** | Login/logout + session Redis + bcrypt + protected route | Login UI works, session persist 7 days |
| **2. Admin user CRUD** | `/admin/users` create/list/reset-pwd/delete | Admin tạo user mới qua web, user mới login được |
| **3. Process CRUD (no worker)** | `/processes` list/create/edit/delete + strategy_params form 2 tier | Form save vào DB, không trigger worker |
| **4. Worker skeleton** | Daemon poll loop + reaper + `last_run_status` UI badge | `is_active=true` thì worker phát hiện được + update last_run_at |
| **5. Worker scan logic** | `ensure_data_ready` + reuse crawler + EmaRsiReversal invoke | Worker chạy chu kỳ, ghi signals vào DB |
| **6. Telegram alert** | Send template + per-user/per-process chat_id + Test button trong Settings | Bắn alert thật vào chat user |
| **7. Signal history UI** | `/processes/:id/signals` list + filter + paginate | User xem được history |
| **8. One-shot "Quét ngay"** | force_run_requested_at flag + UI button + worker pickup | Click button → worker pickup trong ≤ 30s |
| **9. Tailscale deploy** | Systemd service files + ufw config + Tailscale hostname | Truy cập web từ phone qua Tailscale |

Recommend dùng `/tdd` cho slice 1-8 (red-green-refactor).

---

## 13. Quyết định không chọn (audit trail)

Ghi lại để session sau biết WHY của design này:

| Vấn đề | Đã loại | Lý do |
|---|---|---|
| Public web có domain + Let's Encrypt | DuckDNS + Caddy | Tailscale loại bỏ hoàn toàn brute force risk; user 2-5 thân, install client OK |
| Streamlit (mở rộng dashboard cũ) | — | Auth multi-user yếu, khó schedule task nền |
| Multi-process / async / Celery | — | Scale 5-15 process / 60min đủ cho single-thread |
| JWT auth | — | Stateful session đơn giản hơn, Redis đã có |
| SQLite cho config | — | Worker + web concurrent write → SQLite hay lock |
| Support cả 3 strategy v1 | — | SonicR YAML ~50 fields, render form mất 50% effort web |
| Global signal dedupe (1 row / candle) | — | User A và B muốn signal history riêng |
| Block UI khi edit / delete process đang chạy | — | Worker stateless re-read DB cycle đầu mỗi vòng |
| Email password reset | — | SMTP setup phức tạp, 2-5 user out-of-band reset đủ |

---

## 14. Next steps

1. **Review plan này** — feedback gì update tại file này trước khi code.
2. **Verify open items mục 11** (đặc biệt: crawler có cần API key).
3. **Bắt đầu Slice 0 (Skeleton)** — tạo folder structure + alembic_app + bootstrap admin script.
4. Khuyến nghị workflow per-slice: `/tdd` viết test trước, implement minimal, refactor sau.

---

> **Provenance:** Plan này được synthesise từ 1 grilling session (14 câu hỏi đào sâu) — xem audit trail mục 13 cho các lựa chọn đã loại và lý do.
