# TradingBot — Domain Context

Ngôn ngữ domain dùng xuyên suốt repo. Mọi PR/issue/PRD phải dùng từ canonical, không dùng từ trong "Avoid". Nếu phát hiện thuật ngữ mới chưa định nghĩa → thêm vào "Flagged ambiguities" rồi cập nhật vào đây.

---

## Language

### Data layer

**OHLCV (candle)**
Một cây nến giá tại 1 timeframe — gồm `timestamp`, `open`, `high`, `low`, `close`, `volume`. Đơn vị dữ liệu cơ bản, lưu trong TimescaleDB hypertable [`ohlcv`](./data/models/ohlcv.py).
_Avoid_: "bar" (dùng "candle"), "kline" (dùng nội bộ ccxt thôi, không expose ra layer trên).

**Symbol**
Cặp giao dịch dạng `BASE/QUOTE` (ví dụ `BTC/USDT`). Format thống nhất theo ccxt.
_Avoid_: "pair" (chỉ dùng khi nói về quote/base pair theo nghĩa khái niệm; với mã giao dịch luôn gọi là "symbol"), "ticker" (ticker là giá realtime, khác symbol).

**Exchange**
Sàn giao dịch (hiện hỗ trợ `binance`, `bybit`). Đại diện bởi Crawler kế thừa [`BaseCrawler`](./data/crawler/base_crawler.py).
_Avoid_: "venue", "broker".

**Timeframe**
Khoảng thời gian 1 nến: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`, `1w`. Dùng đúng string ccxt format.
_Avoid_: "interval", "resolution".

### Strategy layer

**Strategy**
Một class kế thừa [`BaseStrategy`](./strategies/base_strategy.py), không gọi DB/HTTP — chỉ thao tác trên DataFrame. Phải implement `compute_indicators`, `generate_signals`, `get_sl_tp`. Mỗi strategy có YAML config trong [`config/strategies/`](./config/strategies/).
_Avoid_: "algo", "model" (dùng strategy).

**Indicator**
Cột tính toán thêm vào DataFrame OHLCV (EMA, RSI, ATR, SuperTrend, Ichimoku, …). Tính trong `Strategy.compute_indicators()`.

**Signal**
Tín hiệu vào lệnh do strategy sinh ra: cột `signal` (1=LONG, -1=SHORT, 0=HOLD) và `signal_type` (`'LONG'|'SHORT'|''`) trong DataFrame. Một signal CHƯA phải là một trade — engine quyết định có mở trade không.
_Avoid_: "alert" (alert là thông báo Telegram, không phải tín hiệu nội bộ), "entry" (entry là sự kiện đã thực sự mở trade).

**Setup**
Một biến thể cấu hình của strategy (vd "SonicR Long" vs "SonicR Short" trong [`sonicr_strategy.yaml`](./config/strategies/sonicr_strategy.yaml)). Strategy có thể có nhiều setup bật/tắt độc lập.

**SL / TP**
Stop-loss / Take-profit price. Có thể là %-based hoặc ATR-based tùy strategy. Cấu hình trong YAML `risk_management`.

**TP1 / TP2**
Take-profit tiered — chốt 50% vị thế ở TP1, 50% còn lại ở TP2. Sau khi đạt TP1, SL có thể được dời (`no_move_sl_after_tp1=false`) hoặc giữ nguyên (`no_move_sl_after_tp1=true`).

### Backtest layer

**Backtest**
Mô phỏng chiến lược trên dữ liệu lịch sử qua [`backtest/engine.py`](./backtest/engine.py) + [`trade_simulator.py`](./backtest/trade_simulator.py). Output: metrics (Win Rate, PnL, Drawdown) + HTML report (QuantStats) trong `output/reports/`.
_Avoid_: "simulation" (dùng "backtest" cho lịch sử, "paper trading" cho realtime).

**Trade simulator**
Module mô phỏng phí + slippage + close-on-bar trong backtest. Là source-of-truth cho cách trade được match — KHÔNG đổi không xin phép.

**Lookback**
Số nến lịch sử nạp vào để tính indicator (ví dụ `--lookback 10000`).

### Paper Trading layer

**Paper Trading**
Mô phỏng strategy realtime — nhận OHLCV mới từ Crawler, gọi Strategy, mở/đóng trade qua [`PortfolioManager`](./paper_trading/portfolio.py) ghi vào DB. KHÔNG dùng tiền thật. Khác Backtest ở chỗ chạy theo thời gian thực + có dashboard + Telegram.
_Avoid_: "demo trade", "fake trade", "simulation" (đã reserved cho backtest).

**Position (paper)**
Vị thế đang mở trong paper trading. Có `entry_price`, `current_sl`, `tp_levels`, `side` (LONG/SHORT), `status` (`OPEN`/`CLOSED`).

**Cooldown**
Khoảng thời gian (phút) sau khi đóng 1 trade trên 1 symbol trước khi engine cho phép mở trade mới trên symbol đó. Tránh re-entry nhiễu.

### Live Trading layer

**Live Trading**
Giao dịch tiền thật qua **Freqtrade** Docker stack trong [`live/`](./live/). Strategy được wrap bằng Freqtrade adapter trong [`strategies/freqtrade/`](./strategies/freqtrade/). Repo này **không tự execute order** — Freqtrade lo phần đó.

**Dry-run**
Mode Freqtrade chạy như paper nhưng dùng giá realtime của exchange. Mặc định `dry_run: true` trong `live/user_data/config.json`. Đổi sang `false` = bắt đầu trade thật.

### Signal Bot

**Signal Bot**
Bot quét tín hiệu và gửi Telegram, KHÔNG mở trade thật cũng KHÔNG mở paper trade. Chỉ là alert. Ví dụ: [`cli/run_distribution_signal_bot.py`](./cli/run_distribution_signal_bot.py), [`cli/run_ema_rsi_reversal_bot.py`](./cli/run_ema_rsi_reversal_bot.py).
_Avoid_: gọi nó là "trading bot" — đây là alert bot, không trade.

---

## Relationships

```
Exchange ──crawls──> OHLCV ──hypertable──> TimescaleDB
                       │
                       ▼
                  Strategy ──compute──> Indicator ──generate──> Signal
                                                                  │
                          ┌───────────────────────────────────────┤
                          ▼                       ▼               ▼
                      Backtest             Paper Trading      Signal Bot
                          │                       │               │
                          ▼                       ▼               ▼
                  HTML report + metrics    Position + Dashboard  Telegram
                                                  │
                                                  └─► (when proven) Live Trading via Freqtrade
```

Một **Strategy** sinh ra nhiều **Signal**. Một **Signal** có thể trở thành:
- 1 row trong backtest result (Backtest path)
- 1 **Position** mở qua `PortfolioManager` (Paper path)
- 1 Telegram message (Signal Bot path)
- 1 order thật do Freqtrade execute (Live path)

Đường đi nào kích hoạt là tùy CLI runner ở `cli/`.

---

## Flagged ambiguities

- ~~"bot" có 2 nghĩa~~ — đã resolve: **Signal Bot** (alert only) vs **Paper Trading bot** vs **Live Trading bot** (Freqtrade). Luôn prefix rõ.
- ~~"trade" vs "signal"~~ — đã resolve: **Signal** là tín hiệu trong DataFrame (chưa execute). **Trade** là vị thế đã mở (paper hoặc live).
- "freqtrade strategy" vs "BaseStrategy" — chúng là 2 class khác nhau. `BaseStrategy` (repo này) làm việc trên DataFrame, không biết exchange. `strategies/freqtrade/sonicr_ft.py` là Freqtrade adapter wrap logic core. Khi nói "strategy" không kèm context, mặc định là `BaseStrategy`.

---

## ADR (Architecture Decision Records)

Khi có quyết định kiến trúc lớn (đổi DB engine, đổi cách lưu trade, đổi mô hình SL/TP, v.v.), tạo file `docs/adr/NNNN-tieu-de.md`. Hiện chưa có ADR — sẽ khởi tạo khi `/setup-matt-pocock-skills` hoặc khi cần.
