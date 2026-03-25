# 🚀 Crypto Trading Bot Framework (All-in-One)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/release/python-3100/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Đây là một framework nòng cốt (Core Framework) chuyên nghiệp dành cho việc phát triển, kiểm thử, và triển khai Bot Giao Dịch Crypto tự động. Hệ thống hỗ trợ tích hợp dữ liệu từ **Binance** & **Bybit**, quản lý Database tối ưu với **TimescaleDB**, kiểm thử với **QuantStats**, giao dịch ảo (Paper Trading) tích hợp Web Dashboard, và giao dịch thật an toàn qua **Freqtrade**.

---

## 🏗 Cấu Trúc Tổng Quan (5 Giai Đoạn)

Dự án được chia thành 5 module chính biệt lập nhưng liên kết chặt chẽ:

1. **Phase 1: Data Crawler** — Thu thập và chuẩn hoá nến (OHLCV) từ sàn, lưu trữ vào TimescaleDB.
2. **Phase 2: Strategy Engine** — Động cơ chiến lược mạnh mẽ (Tích hợp sẵn lõi thuật toán **SonicR** tốc độ cao).
3. **Phase 3: Backtesting** — Kiểm thử chiến lược trên dữ liệu quá khứ, xuất báo cáo HTML và mô phỏng phí/slippage chân thực.
4. **Phase 4: Paper Trading** — Tự động trade bằng tiền ảo với thời gian thực. Theo dõi tổng PnL trên Giao diện Web (Streamlit). Cảnh báo tin nhắn qua Telegram.
5. **Phase 5: Live Trading (Freqtrade)** — Giao dịch tiền thật bằng framework Freqtrade danh tiếng, quản lý rủi ro tối đa.

---

## ⚙️ Hướng Dẫn Cài Đặt Chung

### 1. Yêu Cầu Hệ Thống
*   **Docker** & **Docker Compose**
*   **Python 3.10+**

### 2. Cài Đặt Cơ Bản
Clone dự án và cài đặt bộ thư viện (Cài Môi Trường Ảo `venv` nếu cần):
```bash
# Tạo virtual environment
python -m venv venv

# Windows: Activate venv
venv\Scripts\activate

# Ubuntu/Linux: Activate venv
source venv/bin/activate

# Cài đặt dependencies
pip install -r requirements.txt
```

Sao chép file cấu hình tham số môi trường:
```bash
cp .env.example .env
```
*(Chỉnh sửa file `.env` để điền Keys của Sàn và Telegram nếu cần)*

### 3. Khởi Động Database (PostgreSQL/Timescale + Redis)
```bash
cd docker
docker compose up -d
cd ..
```

**Lưu ý:** Script init-db.sh sẽ tự động chạy lần đầu tiên để tạo các bảng và extension TimescaleDB.

**Nếu cần chạy lại init script (xóa toàn bộ dữ liệu):**
```bash
cd docker
docker compose down -v  # Xóa volumes
docker compose up -d    # Tạo lại database
```

**Kiểm tra database đã tạo thành công:**
```bash
docker exec -it tradingbot_timescaledb psql -U postgres -d tradingbot -c "\dt"
```

**Kết nối từ local:**
```bash
# Database URL cho .env
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/tradingbot"
```
---

## 📘 Hướng Dẫn Vận Hành Theo Từng Module

### 🗄 Phase 1: Thu Thập Dữ Liệu (Data Crawler)
Bộ công cụ giúp bạn lấy dữ liệu thị trường làm nguyên liệu cho Bot.

**Lấy dữ liệu quá khứ (Historical Data):**
```bash
# Lấy nến 1h của BTC/USDT trên Binance từ đầu năm 2024
python cli/download_data.py --exchange binance --symbol BTC/USDT --timeframe 1h --start 2024-01-01
```

**Bật Bot cập nhật real-time tự động lấy nến (Incremental Sync):**
```bash
python cli/start_scheduler.py
```

---

### 🧠 Phase 2: Tuỳ Chỉnh Chiến Lược (Strategy Engine)
Hệ thống sử dụng lớp trừu tượng `BaseStrategy`. Chiến lược mặc định là **SonicR**.

**Tham số Chiến lược SonicR**: Bạn có thể thay đổi các bộ đếm Moving Average (EMA), siêu xu hướng (SuperTrend) hay Cloud (Ichimoku) tại file cấu hình yaml:
> 📄 `config/strategies/sonicr_strategy.yaml`

---

### ⏳ Phase 3: Kiểm Thử Quá Khứ (Backtesting)
Chạy thử nghiệm chiến lược của bạn đã nạp trên tập dữ liệu lịch sử.

```bash
# Backtest BTC/USDT bằng thuật toán SonicR
python cli/run_backtest.py \
  --strategy SonicRStrategy \
  --exchange binance \
  --symbol BTC/USDT \
  --timeframe 1h \
  --start 2024-01-01
```
✅ **Kết quả**: Console sẽ in ra các thông số (Win Rate, PnL, Drawdown) và Bot sẽ tạo riêng cho bạn 1 thẻ Báo cáo Web HTML siêu chi tiết tại `output/reports/`.

---

### 🕹️ Phase 4: Giao Dịch Ảo (Paper Trading)
Chạy bot theo thời gian thực nhưng **KHÔNG DÙNG TIỀN THẬT** để nghiệm thu sức mạnh thuật toán trực tiếp. Hệ thống Paper Trading có kèm theo Giao diện theo dõi (Dashboard) & Cảnh báo Telegram.

**1. Khởi chạy Bot Trade Ảo:**
```bash
# Đánh nháp 2 đồng xu BTC & ETH
python cli/run_paper_sync.py --strategy SonicRStrategy --symbols "BTC/USDT,ETH/USDT" --timeframe 1h
```

**2. Bật Panel Quản Lý Giao Diện Web (Dashboard):**
Mở 1 Terminal mới và chạy:
```bash
streamlit run dashboard/app.py
```
Giao diện sẽ hiển thị lên Trình Duyệt Web quản lý PnL và các Lệnh đang mở (OPEN) hoặc đã đóng (CLOSED).

**3. Nhận Thông Báo Telegram (Tuỳ chọn)**
Mở file `.env`, điền thông tin sau là xong:
```env
TELEGRAM_BOT_TOKEN="xxxxxxxxx"
TELEGRAM_CHAT_ID="xxxxxxxxx"
```

---

### 📡 Distribution Signal Bot (Gửi Tín Hiệu Telegram)
Bot gửi tín hiệu SHORT dựa trên chiến lược Distribution Phase Detection. **Không cần Docker hay Database**.

**Chạy bot (quét một lần):**
```bash
# Windows
python cli/run_distribution_signal_bot.py --oneshot --top 50

# Ubuntu/Linux
python3 cli/run_distribution_signal_bot.py --oneshot --top 50
```

**Chạy bot liên tục (mặc định 1 giờ/quét):**
```bash
# Windows
python cli/run_distribution_signal_bot.py --interval 1 --top 100 --timeframe 4h

# Ubuntu/Linux
python3 cli/run_distribution_signal_bot.py --interval 1 --top 100 --timeframe 4h
```

**Các tuỳ chọn:**
- `--interval`: Khoảng thời gian giữa các lần quét (giờ)
- `--top`: Số lượng top coins để quét
- `--timeframe`: Timeframe cho chiến lược (1d, 4h, 1h...)
- `--oneshot`: Quét một lần duy nhất và thoát

**Cấu hình `.env`:**
```env
TELEGRAM_BOT_TOKEN="xxxxxxxxx"
TELEGRAM_CHAT_ID="xxxxxxxxx"
CMC_API_KEY="xxxxxxxxx"
```

**Chạy bot trong background (Ubuntu/Linux):**
```bash
# Cách 1: Dùng nohup
nohup python3 cli/run_distribution_signal_bot.py --interval 1 --top 100 --timeframe 4h > bot.log 2>&1 &

# Cách 2: Dùng screen
screen -S signalbot
python3 cli/run_distribution_signal_bot.py --interval 1 --top 100 --timeframe 4h
# Thoát screen: Ctrl+A, rồi D

# Cách 3: Dùng systemd service (khuyến nghị cho production)
# Tạo file /etc/systemd/system/signalbot.service:
sudo nano /etc/systemd/system/signalbot.service
```ini
[Unit]
Description=Distribution Signal Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/projects/tradingbot
ExecStart=/root/projects/tradingbot/venv/bin/python3 cli/run_distribution_signal_bot.py --interval 1 --top 100 --timeframe 4h
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
```bash
# Enable và chạy service
sudo systemctl enable signalbot
sudo systemctl start signalbot
sudo systemctl status signalbot
```

---

### 💸 Phase 5: Giao Dịch Tiền Thật (Live Trading - Freqtrade)
Để đảm bảo an toàn tuyệt đối về vốn và kết nối, hệ thống sử dụng Framework Giao dịch số 1 thế giới là **Freqtrade** nhưng được bọc (mount) riêng chiến lược Core SonicR của ta vào bên trong.

**1. Clone & Cài đặt môi trường:**
```bash
python live/scripts/setup_freqtrade.py
```

**2. Nhập API sàn giao dịch:**
Mở `live/user_data/config.json`, tìm tag `"exchange"` và nhập Key `binance`/`bybit` của bạn. Sửa `"dry_run": false` khi bạn thực sự muốn bot chạy bằng tài khoản thật.

**3. Khởi Tác Docker Freqtrade:**
```bash
cd live
docker compose up -d
```
Xem dữ liệu Real-time log từ Container:
```bash
docker compose logs -f freqtrade
```

---

## 🛠 Cấu Trúc Framework
```text
TradingBot/
├── backtest/                 # Mô phỏng nến & chấm điểm thuật toán
├── cli/                      # Lệnh dòng lệnh dễ sử dụng (Runners)
├── config/                   # File Config chiến lược (yaml)
├── dashboard/                # Giao diện Web Streamlit UI
├── data/                     # Crawler, Engine (SQLAlchemy) & Timescale Database
├── docker/                   # Hạ tầng CSDL Postgres & Redis
├── live/                     # Môi trường chạy Live Bot Freqtrade
├── migrations/               # Database revisions (Alembic)
├── paper_trading/            # Bot trade ảo Realtime (SQLite/Postgres)
├── strategies/               # Nơi để các Core Thuật toán Bot 
└── utils/                    # Plugin phụ trợ (Telegram Bot...)
```
