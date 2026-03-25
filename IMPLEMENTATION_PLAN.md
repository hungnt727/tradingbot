# Tạo Project Structure & Phase 1 — Data Crawler

Xây dựng toàn bộ cấu trúc thư mục dự án và triển khai Phase 1: hệ thống thu thập dữ liệu OHLCV từ sàn Binance và Bybit, lưu vào TimescaleDB, với real-time feed qua Redis.

---

## Proposed Changes

### Infrastructure

#### [NEW] `docker/docker-compose.yml`
- TimescaleDB (PostgreSQL 16 + TimescaleDB extension)
- Redis 7
- pgAdmin 4 (Web UI quản lý DB)

#### [NEW] `.env.example`
Các biến môi trường cần thiết: DB credentials, Exchange API keys, Redis URL

---

### Project Root Files

#### [NEW] `requirements.txt`
Dependencies: `ccxt`, `sqlalchemy`, `alembic`, `redis`, `apscheduler`, `pandas`, `pandas-ta`, `python-dotenv`, `click`, `loguru`, `pytest`

#### [NEW] `.gitignore`
Loại trừ: `.env`, `__pycache__`, `*.pyc`, `data/`, `logs/`

#### [NEW] `README.md`
Hướng dẫn cài đặt và sử dụng nhanh

---

### Data Layer — Models

#### [NEW] `data/models/base.py`
SQLAlchemy `DeclarativeBase`

#### [NEW] `data/models/ohlcv.py`
Model `OHLCV`: `time`, `exchange`, `symbol`, `timeframe`, `open`, `high`, `low`, `close`, `volume`

#### [NEW] `data/models/exchange_info.py`
Model `ExchangeInfo`: metadata sàn (tên, markets, rate limits)

---

### Data Layer — Storage

#### [NEW] `data/storage/timescale_client.py`
- Kết nối PostgreSQL/TimescaleDB
- `upsert_ohlcv(records)`: bulk insert/upsert
- `query_ohlcv(exchange, symbol, tf, start, end)`: truy vấn dữ liệu
- `get_last_candle(exchange, symbol, tf)`: lấy candle mới nhất

#### [NEW] `data/storage/redis_client.py`
- Kết nối Redis
- `set_latest_tick(symbol, data)` / `get_latest_tick(symbol)`
- `publish_candle(channel, data)` — pub/sub cho real-time

---

### Data Layer — Migrations (Alembic)

#### [NEW] `alembic.ini`
#### [NEW] `migrations/env.py`
#### [NEW] `migrations/versions/001_initial_ohlcv.py`
- Tạo bảng `ohlcv`, `exchange_info`
- Convert `ohlcv` thành TimescaleDB hypertable
- Tạo unique index tổng hợp

```sql
CREATE TABLE ohlcv (
    time        TIMESTAMPTZ NOT NULL,
    exchange    VARCHAR(20) NOT NULL,
    symbol      VARCHAR(20) NOT NULL,
    timeframe   VARCHAR(5)  NOT NULL,
    open        NUMERIC(20,8),
    high        NUMERIC(20,8),
    low         NUMERIC(20,8),
    close       NUMERIC(20,8),
    volume      NUMERIC(30,8)
);
SELECT create_hypertable('ohlcv', 'time');
CREATE UNIQUE INDEX ON ohlcv (exchange, symbol, timeframe, time DESC);
```

---

### Data Layer — Crawlers

#### [NEW] `data/crawler/base_crawler.py`
Abstract class với:
- `fetch_ohlcv_historical(symbol, tf, since, limit)` — gọi REST API
- `fetch_markets()` — lấy danh sách cặp giao dịch
- `start_websocket(symbols, callback)` — kết nối WebSocket

#### [NEW] `data/crawler/binance_crawler.py`
Implement `BaseCrawler` cho Binance qua `ccxt`

#### [NEW] `data/crawler/bybit_crawler.py`
Implement `BaseCrawler` cho Bybit qua `ccxt`

#### [NEW] `data/crawler/scheduler.py`
APScheduler jobs:
- Incremental sync: chạy cron theo từng timeframe (`1m`, `5m`, `1h`, `1d`)
- Lấy candle từ `last_candle_time` đến `now` và upsert vào DB

---

### CLI Tools

#### [NEW] `cli/download_data.py`
Download dữ liệu lịch sử:
```bash
python cli/download_data.py \
  --exchange binance \
  --symbol BTC/USDT \
  --timeframe 1h \
  --start 2024-01-01
```

#### [NEW] `cli/start_scheduler.py`
Khởi động incremental sync scheduler (chạy liên tục)

---

### Tests

#### [NEW] `tests/test_timescale_client.py`
Unit test: upsert, query, get_last_candle (dùng mock hoặc test DB)

#### [NEW] `tests/test_crawler.py`
Unit test: mock ccxt responses, kiểm tra parse OHLCV đúng định dạng

---

## Cấu Trúc Thư Mục Sau Phase 1

```
TradingBot/
├── data/
│   ├── __init__.py
│   ├── crawler/
│   │   ├── __init__.py
│   │   ├── base_crawler.py
│   │   ├── binance_crawler.py
│   │   ├── bybit_crawler.py
│   │   └── scheduler.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── ohlcv.py
│   │   └── exchange_info.py
│   └── storage/
│       ├── __init__.py
│       ├── timescale_client.py
│       └── redis_client.py
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_ohlcv.py
├── cli/
│   ├── download_data.py
│   └── start_scheduler.py
├── docker/
│   └── docker-compose.yml
├── tests/
│   ├── test_timescale_client.py
│   └── test_crawler.py
├── config/                   # (Phase 2: strategy configs)
├── strategies/               # (Phase 2)
├── backtest/                 # (Phase 3)
├── paper_trading/            # (Phase 4)
├── live/                     # (Phase 5)
├── alembic.ini
├── requirements.txt
├── .env.example
├── .gitignore
├── PLAN.md
├── IMPLEMENTATION_PLAN.md    # File này
└── README.md
```

---

## Verification Plan

### Automated Tests
```bash
# Cài dependency
pip install -r requirements.txt

# Chạy unit tests
pytest tests/ -v
```

### Manual Verification

**Bước 1 — Khởi động Docker services:**
```bash
cd docker
docker compose up -d
docker compose ps   # Tất cả service phải ở trạng thái running
```
Truy cập pgAdmin: [http://localhost:5050](http://localhost:5050)

**Bước 2 — Chạy DB migration:**
```bash
alembic upgrade head
```
Kiểm tra trong pgAdmin: bảng `ohlcv` tồn tại và là TimescaleDB hypertable

**Bước 3 — Download dữ liệu lịch sử:**
```bash
python cli/download_data.py \
  --exchange binance \
  --symbol BTC/USDT \
  --timeframe 1h \
  --start 2024-01-01
```
Kiểm tra: `SELECT count(*) FROM ohlcv WHERE symbol='BTC/USDT';` → có dữ liệu

**Bước 4 — Chạy scheduler:**
```bash
python cli/start_scheduler.py
```
Kiểm tra: sau 1 chu kỳ timeframe, candle mới được cập nhật vào DB

---

> **Ghi chú**: Sau khi Phase 1 hoàn thành và có đủ dữ liệu, tiếp tục sang **Phase 2** (Strategy Engine).

---

# Phase 2 — Strategy Engine: SonicR

Refactor `sonicr_scanner.py` thành framework chiến lược chuẩn tích hợp với backtest và Freqtrade.

## Phân Tích sonicr_scanner.py

### Logic Cốt Lõi

| Thành Phần | Chi Tiết |
|---|---|
| **EMA Stack** | EMA(34), EMA(89), EMA(200), EMA(610) trên `close` |
| **EMA-RSI** | RSI(14) → EMA(5), EMA(10), EMA(20) của RSI |
| **Supertrend HTF** | Higher timeframe Supertrend (length=10, multiplier=3) |
| **Ichimoku** | Filter tuỳ chọn: close > Span B |
| **Volume MA(20)** | Filter tuỳ chọn: volume > vol_ma_20 |
| **Cross Distance** | Số nến từ lần EMA200/EMA610 cắt nhau gần nhất |

### Điều Kiện Tín Hiệu

```
LONG:  EMA34 > EMA89 > EMA200 > EMA610  AND  EMA_RSI_5 > EMA_RSI_10  AND  EMA_RSI_5 > EMA_RSI_20
SHORT: EMA34 < EMA89 < EMA200 < EMA610  AND  EMA_RSI_5 < EMA_RSI_10  AND  EMA_RSI_5 < EMA_RSI_20
```

**Window-based Reversal**: Tìm điểm `not_state → state` trong cửa sổ `signal_window` nến gần nhất.

---

## Proposed Changes

### Strategy Framework

#### [NEW] `strategies/base_strategy.py`
Abstract `BaseStrategy` với:
- `compute_indicators(df)` → DataFrame
- `generate_signals(df)` → DataFrame với cột `signal`, `signal_type`, `reversal_dist`
- `get_sl_tp(entry_price, signal, atr)` → `(sl_price, tp_price)`

---

### SonicR Core

#### [NEW] `strategies/sonicr_strategy.py`
`SonicRStrategy(BaseStrategy)` — refactor từ `sonicr_scanner.py`:
- `compute_indicators()`: EMA stack, EMA-RSI, Supertrend, Ichimoku, Volume MA
- `generate_signals()`: window reversal + tất cả filters + cross_distance
- `get_sl_tp()`: ATR × multiplier

#### [NEW] `config/strategies/sonicr_strategy.yaml`
```yaml
name: SonicRStrategy
timeframe: "1h"
htf_timeframe: "4h"
indicators:
  ema_lengths: [34, 89, 200, 610]
  rsi_period: 14
  ema_rsi_lengths: [5, 10, 20]
  supertrend_length: 10
  supertrend_multiplier: 3.0
signal:
  lookback_candles: 3
  signal_window: 5
  min_candles_required: 610
filters:
  min_ema_distance: 0
  min_ema_34: 0
  enable_ichimoku: false
  enable_volume_filter: false
  enable_htf_supertrend: false
  max_cross_ago: 0
risk_management:
  sl_atr_multiplier: 1.5
  tp_atr_multiplier: 3.0
setups:
  - name: "SonicR Long"
    signal_type: "LONG"
    enabled: true
  - name: "SonicR Short"
    signal_type: "SHORT"
    enabled: true
```

---

### Freqtrade Integration

#### [NEW] `strategies/freqtrade/sonicr_ft.py`
- Extends Freqtrade `IStrategy`
- `populate_indicators()` → gọi `SonicRStrategy.compute_indicators()`
- `populate_entry_trend()` → cột `enter_long` / `enter_short`
- `populate_exit_trend()` → cột `exit_long` / `exit_short`
- `stoploss`, `minimal_roi` từ YAML config

---

### Tests

#### [NEW] `tests/test_sonicr_strategy.py`
- `test_ema_stack_long/short` — EMA alignment detection
- `test_ema_rsi_momentum` — EMA-RSI filter
- `test_window_reversal_detection` — window-based signal
- `test_filters` — Ichimoku, Volume, Supertrend filters
- `test_get_sl_tp` — ATR-based SL/TP calculation
- `test_no_signal_when_insufficient_data` — edge cases

---

## Cấu Trúc Thư Mục Sau Phase 2

```
strategies/
├── __init__.py
├── base_strategy.py          # Abstract base
├── sonicr_strategy.py        # SonicR core logic
└── freqtrade/
    ├── __init__.py
    └── sonicr_ft.py          # Freqtrade IStrategy wrapper
config/
└── strategies/
    └── sonicr_strategy.yaml  # Strategy parameters
tests/
└── test_sonicr_strategy.py
```

## Verification Plan — Phase 2

### Automated Tests
```bash
pytest tests/test_sonicr_strategy.py -v
```

### Manual Signal Check
```bash
python -c "
import pandas as pd
from strategies.sonicr_strategy import SonicRStrategy

# Load sample data (CSV hoặc từ DB)
df = pd.read_csv('sample_ohlcv.csv', parse_dates=['time'], index_col='time')
s = SonicRStrategy()
df = s.compute_indicators(df)
df = s.generate_signals(df)
signals = df[df['signal'] != 0]
print(f'Found {len(signals)} signals')
print(signals[['signal_type','close','reversal_dist']].tail(10))
"
```

---

# Phase 3 — Backtesting Engine

Chạy chiến lược (SonicR và các chiến lược khác) trên dữ liệu lịch sử từ TimescaleDB, mô phỏng lệnh + phí + slippage, và xuất báo cáo chi tiết.

## Proposed Changes

### Core Engine

#### [NEW] `backtest/trade_simulator.py`
Mô phỏng vòng đời lệnh: entry → SL hit / TP hit / exit signal.
- Tính P&L theo % và USD từng lệnh
- Áp dụng `fee_rate` (maker/taker) và `slippage`
- Trả về `TradeResult` dataclass

#### [NEW] `backtest/metrics.py`
Tính toán các metrics từ danh sách `TradeResult`:
Sharpe, Max Drawdown, Win Rate, Profit Factor, Total Return, Avg RR

#### [NEW] `backtest/engine.py`
Core backtest loop:
1. Load OHLCV từ TimescaleDB (hoặc DataFrame)
2. `compute_indicators()` → `generate_signals()`
3. Với mỗi signal: tính SL/TP → simulate trade
4. Return `BacktestResult` (trades + metrics + equity curve)

#### [NEW] `backtest/report.py`
Xuất báo cáo HTML với `quantstats` + bảng lệnh chi tiết.

### CLI

#### [NEW] `cli/run_backtest.py`
```bash
python cli/run_backtest.py \
  --strategy SonicRStrategy \
  --exchange binance --symbol BTC/USDT --timeframe 1h \
  --start 2024-01-01 --end 2025-01-01 \
  --capital 10000 --fee 0.001
```

## Verification Plan

### Automated Tests
```bash
pytest tests/test_backtest.py -v
```

### Manual Check
```bash
python cli/run_backtest.py \
  --strategy SonicRStrategy \
  --exchange binance --symbol BTC/USDT --timeframe 1h \
  --start 2024-01-01 --end 2025-01-01
# → Xuất báo cáo HTML + in metrics ra terminal
```

---

# Phase 4 — Paper Trading

Môi trường giao dịch ảo theo thời gian thực (real-time). Sử dụng Data Crawler từ Phase 1 để lấy dữ liệu, áp dụng Strategy từ Phase 2 và quản lý danh mục đầu tư ảo.

## Proposed Changes

### Database Models

#### [NEW] `data/models/trade.py`
SQLAlchemy model `Trade` để lưu trạng thái lệnh ảo:
- `id`, `exchange`, `symbol`, `strategy`, `timeframe`
- `side` (LONG/SHORT)
- `entry_time`, `entry_price`, `position_size`
- `sl_price`, `tp_price`
- `status` (OPEN/CLOSED)
- `exit_time`, `exit_price`, `pnl_usd`, `exit_reason`

#### [NEW] `migrations/versions/002_create_trades_table.py`
Alembic migration cho bảng `trades`.

### Portfolio Management

#### [NEW] `paper_trading/portfolio.py`
Quản lý số dư và trạng thái vị thế:
- `get_balance()`
- `open_trade(...)` (Lưu vào DB `status='OPEN'`)
- `close_trade(...)` (Cập nhật DB `status='CLOSED'`, tính PnL)
- `get_open_trades()`
- `update_trailing_sl(...)` (Tuỳ chọn)

### Paper Trading Engine

#### [NEW] `paper_trading/engine.py`
Vòng lặp chạy mỗi phút (cronjob hoặc loop):
1. Quét các `open_trades`. Kiểm tra giá hiện tại (từ Redis/Timescale) xem có hit SL/TP không → Nếu có, gọi `close_trade`.
2. Lấy danh sách nến hiện tại từ TimescaleDB.
3. Chạy `compute_indicators()` và `generate_signals()`.
4. Nếu có tín hiệu ENTRY mới:
   - Kiểm tra xem đã có lệnh mở cho cặp này chưa (để tránh nhồi lệnh nếu không cấu hình).
   - Tính toán position size dựa trên risk management.
   - Gọi `open_trade`.
5. Đẩy thông báo qua Telegram (nếu có config).

### CLI

#### [NEW] `cli/run_paper_sync.py`
Script chạy Paper Trading Engine:
```bash
python cli/run_paper_sync.py --strategy SonicRStrategy --symbols "BTC/USDT,ETH/USDT" --timeframe 1h
```

## Verification Plan

### Automated Tests
```bash
pytest tests/test_paper_trading.py -v
```

### Manual Check
1. Bật Data Crawler (`start_scheduler.py`) từ Phase 1 để dữ liệu luôn được update vào DB.
2. Khởi động `python cli/run_paper_sync.py ...`
4. Chờ giá quét qua SL/TP và kiểm tra xem lệnh có chuyển sang `CLOSED` không.

---

# Phase 5 — Live Trading (Freqtrade)

Triển khai giao dịch thật (Live Trading) sử dụng framework mã nguồn mở **Freqtrade**. Thay vì tự code Live Engine từ đầu (rất rủi ro về mặt an toàn vốn, kết nối API, xử lý lỗi mạng), chúng ta sẽ mount chiến lược `SonicR` đã tạo ở Phase 2 vào Freqtrade và để Freqtrade quản lý vòng đời lệnh thực tế.

## Proposed Changes

### Freqtrade Structure setup

Tạo cấu trúc thư mục `live/` dành riêng cho Freqtrade:
```
live/
├── docker-compose.yml
└── user_data/
    ├── config.json
    └── strategies/
        └── sonicr_ft.py (symlink hoặc copy từ project chính)
```

#### [NEW] `live/docker-compose.yml`
Chứa service `freqtrade`. Bọc (mount) thư mục `strategies` bằng các volumes thích hợp để Bot có thể đọc được chiến lược và dùng Python env đã cài đủ thư viện (pandas-ta).

#### [NEW] `live/user_data/config.json`
Chứa các thiết lập quan trọng của Freqtrade để trade thật:
- `dry_run`: `false` (Trade tiền thật) hoặc `true` (Trade ảo). Mặc định để `true` cho an toàn lúc test tích hợp.
- `exchange`: Khai báo API key, Secret key của Binance/Bybit.
- `stake_currency`: USDT
- `stake_amount`: Số lượng tiền gán cho từng lệnh.
- `max_open_trades`: Giới hạn số lệnh mở đồng thời (Risk management).
- `pairlist`: Danh sách các cặp token muốn bot chạy (như StaticPairList: BTC/USDT, ETH/USDT).
- `telegram`: Setup thông báo đẩy về Telegram cá nhân.

#### [NEW] `live/scripts/setup_freqtrade.py`
Script tự động hoá việc copy/link các file chiến lược từ `strategies/` sang `live/user_data/strategies/` và khởi tạo file config mặc định.

### Hoạt Động Của Hệ Thống Khi Chạy Live

Khi chạy Live bằng Freqtrade:
1. Bạn start Container Freqtrade trong thư mục `live/`.
2. Freqtrade lấy API tự connect với Binance/Bybit.
3. Freqtrade nạp class `SonicRStrategy` từ `sonicr_ft.py` (Wrapper Freqtrade đã làm ở Phase 2).
4. Wrapper này gọi vào `SonicRStrategy` gốc của ta. Hàm `compute_indicators()` và `generate_signals()` sẽ được gọi ở mỗi cây nến mới.
5. Freqtrade nhận column `enter_long`, `enter_short`, `exit_long`, `exit_short` ở dataframe trả ra và tự động đặt lệnh, quản lý SL/TP trên sàn.

## Verification Plan

### Manual Verification
1. Chạy setup: `python live/scripts/setup_freqtrade.py`
2. Chỉnh sửa file `live/user_data/config.json`, đưa API key vào (bắt buộc dùng Read-Only API key cho bước test).
3. Chạy `docker compose up -d` trong thư mục `live/`.
4. Xem log Bot bằng `docker compose logs -f freqtrade`.
5. Đảm bảo bot khởi động không có lỗi và báo đã kết nối Exchange, đang chạy ở chế độ **Dry-Run**.

