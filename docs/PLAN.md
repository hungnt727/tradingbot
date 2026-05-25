# 🤖 Crypto Trading Bot — Kế Hoạch Chi Tiết

## Tóm Tắt Kế Hoạch

Hệ thống gồm **5 thành phần chính**, được xây dựng theo tuần tự từ thu thập dữ liệu đến giao dịch thật:

| # | Thành Phần | Công Nghệ Chính | Mục Đích |
|---|---|---|---|
| 1 | Data Crawler | ccxt, TimescaleDB, Redis | Thu thập & lưu OHLCV từ sàn |
| 2 | Strategy Engine | pandas-ta, YAML config | Viết chiến lược RSI/MACD/BB |
| 3 | Backtesting | Backtrader, quantstats | Kiểm tra chiến lược trên dữ liệu lịch sử |
| 4 | Paper Trading | Streamlit dashboard | Chạy thật không dùng tiền thật |
| 5 | Live Trading | **Freqtrade** (open-source) | Giao dịch thật với Telegram alerts |

---

## Roadmap

| Giai Đoạn | Nội Dung | Thời Gian |
|---|---|---|
| **Phase 1** | Setup DB + Data Crawler (Binance/Bybit) | 1 tuần |
| **Phase 2** | Viết 3-5 Strategy + Unit Test | 1 tuần |
| **Phase 3** | Backtest Engine + HTML Report | 1 tuần |
| **Phase 4** | Paper Trading Dashboard (Streamlit) | 3–5 ngày |
| **Phase 5** | Tích hợp Freqtrade + Deploy | 3–5 ngày |

---

## Kiến Trúc Tổng Thể

```
Crypto Exchanges (Binance / Bybit / OKX)
        │  REST / WebSocket (ccxt)
        ▼
   Data Crawler
        │
        ▼
  TimescaleDB (OHLCV lưu theo time-series)
        │
    ┌───┴───────────────┐
    ▼                   ▼
Backtesting         Real-time Feed (Redis)
    │                   │
    ▼                   ▼
Strategy          Paper Trading Engine
Optimizer              │
                       ▼
                  Freqtrade Bot
                  ├── Dry-Run Mode
                  └── Live Mode
                       │
                       ▼
               Telegram Notifications
```

---

## Cấu Trúc Thư Mục Dự Án

```
TradingBot/
├── data/
│   ├── crawler/          # CCXT crawlers (Binance, Bybit...)
│   ├── models/           # SQLAlchemy DB models
│   └── storage/          # TimescaleDB + Redis clients
├── strategies/
│   ├── base_strategy.py  # Abstract base class
│   ├── rsi_strategy.py
│   ├── macd_strategy.py
│   ├── bb_strategy.py    # Bollinger Bands
│   └── freqtrade/        # Freqtrade-format strategies
├── backtest/
│   ├── engine.py         # Core backtest loop
│   ├── metrics.py        # Sharpe, Drawdown, Win Rate...
│   └── report.py         # HTML report (quantstats)
├── paper_trading/
│   ├── engine.py         # Real-time virtual trading
│   └── dashboard.py      # Streamlit UI
├── live/
│   └── freqtrade/        # Config & deployment
├── config/
│   └── strategies/       # YAML config per strategy
├── docker/
│   ├── docker-compose.yml
│   └── Dockerfile
├── PLAN.md               # File này
└── README.md
```

---

## 1. 📡 Data Crawler

### Tech Stack
- **ccxt**: Thư viện giao tiếp với 100+ sàn (REST + WebSocket)
- **TimescaleDB**: PostgreSQL extension tối ưu cho time-series
- **Redis**: Cache tick data real-time
- **APScheduler**: Cron jobs cập nhật dữ liệu theo timeframe

### Database Schema
```sql
CREATE TABLE ohlcv (
    time        TIMESTAMPTZ NOT NULL,
    exchange    VARCHAR(20) NOT NULL,   -- 'binance', 'bybit'
    symbol      VARCHAR(20) NOT NULL,   -- 'BTC/USDT'
    timeframe   VARCHAR(5)  NOT NULL,   -- '1m', '5m', '1h', '1d'
    open        NUMERIC(20,8),
    high        NUMERIC(20,8),
    low         NUMERIC(20,8),
    close       NUMERIC(20,8),
    volume      NUMERIC(30,8),
    PRIMARY KEY (exchange, symbol, timeframe, time)
);
SELECT create_hypertable('ohlcv', 'time');
```

### Luồng Hoạt Động
1. **Historical Crawl**: Tải toàn bộ lịch sử qua REST API
2. **Incremental Sync**: Cập nhật candle mới theo cron job (mỗi timeframe)
3. **Real-time**: WebSocket → Redis → flush vào DB khi candle đóng

---

## 2. 📈 Strategy Engine

### Base Class
```python
class BaseStrategy:
    timeframe: str = "1h"

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        # Trả về cột 'signal': 1=BUY, -1=SELL, 0=HOLD
        raise NotImplementedError

    def get_sl_tp(self, entry_price: float, signal: int) -> tuple[float, float]:
        # Trả về (stop_loss_price, take_profit_price)
        raise NotImplementedError
```

### Chiến Lược Triển Khai

| Chiến Lược | Điều Kiện Entry | SL / TP |
|---|---|---|
| **RSI** | RSI < 30 (BUY), RSI > 70 (SELL) + EMA200 filter | 2% / 4% |
| **MACD** | MACD crossover Signal line | ATR×1.5 / ATR×3 |
| **RSI + MACD** | Cả 2 chỉ báo đồng thuận | 2% / 4% |
| **Bollinger Bands** | Giá chạm band + RSI confirmation | ATR×1.5 / ATR×3 |

### Config Chiến Lược (YAML)
```yaml
# config/strategies/rsi_strategy.yaml
name: RSIStrategy
timeframe: "1h"
indicators:
  rsi_period: 14
  ema_period: 200
risk_management:
  sl_type: "percentage"   # percentage | atr
  sl_value: 2.0
  tp_type: "percentage"
  tp_value: 4.0
  position_size: 10       # % vốn mỗi lệnh
  max_open_positions: 3
```

---

## 3. 🔬 Backtesting Engine

### Luồng Backtest
```
Load OHLCV từ TimescaleDB
        ↓
Tính toán Indicators
        ↓
Generate Signals (BUY/SELL/HOLD)
        ↓
Simulate Trades (xử lý SL/TP, phí, slippage)
        ↓
Tính Metrics & Xuất Báo Cáo
```

### Metrics Báo Cáo
| Metric | Mô Tả |
|---|---|
| Total Return | Tổng lợi nhuận % |
| Sharpe Ratio | Lợi nhuận điều chỉnh rủi ro |
| Max Drawdown | Mức sụt giảm tối đa |
| Win Rate | % lệnh thắng |
| Profit Factor | Gross Profit / Gross Loss |
| Total Trades | Tổng số lệnh |

### CLI
```bash
python backtest.py \
  --strategy RSIStrategy \
  --exchange binance \
  --symbol BTC/USDT \
  --timeframe 1h \
  --start 2024-01-01 \
  --end 2025-01-01 \
  --capital 10000
```

---

## 4. 📝 Paper Trading

### Cơ chế
- Real-time data feed từ WebSocket → áp dụng chiến lược trên mỗi candle mới
- Lưu lệnh ảo vào DB (`paper_trades` table)
- Dashboard Streamlit: equity curve, lệnh mở, P&L realtime

### Schema Paper Trade
```sql
CREATE TABLE paper_trades (
    id          SERIAL PRIMARY KEY,
    strategy    VARCHAR(50),
    symbol      VARCHAR(20),
    side        VARCHAR(5),      -- 'buy' | 'sell'
    entry_price NUMERIC(20,8),
    sl_price    NUMERIC(20,8),
    tp_price    NUMERIC(20,8),
    quantity    NUMERIC(20,8),
    status      VARCHAR(10),     -- 'open' | 'closed' | 'sl_hit' | 'tp_hit'
    entry_time  TIMESTAMPTZ,
    exit_time   TIMESTAMPTZ,
    exit_price  NUMERIC(20,8),
    pnl         NUMERIC(20,8)
);
```

---

## 5. 🚀 Live Trading — Freqtrade

### Tại Sao Dùng Freqtrade?
- Open-source, battle-tested, cộng đồng lớn
- Hỗ trợ Binance, Bybit, OKX và 30+ sàn qua ccxt
- Có sẵn: Backtesting, Dry-Run (Paper), Live Trading
- Tích hợp Telegram bot + Web UI
- REST API để tích hợp hệ thống ngoài

### Convert Strategy Sang Freqtrade Format
```python
# strategies/freqtrade/RSIStrategy_ft.py
from freqtrade.strategy import IStrategy
import pandas_ta as ta

class RSIStrategy(IStrategy):
    timeframe = '1h'
    stoploss = -0.02           # -2% SL
    minimal_roi = {"0": 0.04}  # 4% TP

    def populate_indicators(self, df, metadata):
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['ema200'] = ta.ema(df['close'], length=200)
        return df

    def populate_entry_trend(self, df, metadata):
        df.loc[(df['rsi'] < 30) & (df['close'] > df['ema200']), 'enter_long'] = 1
        return df

    def populate_exit_trend(self, df, metadata):
        df.loc[df['rsi'] > 70, 'exit_long'] = 1
        return df
```

### Cấu Hình Freqtrade
```json
{
  "exchange": { "name": "binance", "key": "API_KEY", "secret": "API_SECRET" },
  "dry_run": true,
  "stake_currency": "USDT",
  "stake_amount": 100,
  "max_open_trades": 3,
  "telegram": {
    "enabled": true,
    "token": "TELEGRAM_BOT_TOKEN",
    "chat_id": "CHAT_ID"
  }
}
```

### Workflow Deploy
```bash
# Bước 1: Backtest
freqtrade backtesting --strategy RSIStrategy --timerange 20240101-20250101

# Bước 2: Paper Trading (2–4 tuần)
freqtrade trade --dry-run --strategy RSIStrategy

# Bước 3: Live Trading (sau khi xác minh kết quả)
freqtrade trade --strategy RSIStrategy
```

---

## Lưu Ý Quan Trọng

> **Khuyến nghị**: Dùng Freqtrade làm backbone cho Phase 3–5 (nó đã có sẵn Backtest, Dry-run, Live). Tập trung viết chiến lược chất lượng và crawler dữ liệu riêng để kiểm soát tốt hơn.

> **Bắt đầu từ đâu**: Phase 1 (Crawler + DB) → Phase 2 (Strategy) → Phase 3 (Backtest) → xác minh kết quả → Phase 4–5.

> **Risk Management**: Không bao giờ bỏ qua SL. Chạy Paper Trading tối thiểu **2–4 tuần** trước khi live với tiền thật.
