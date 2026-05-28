# 🚀 Crypto Trading Bot Framework

Framework Crypto Trading Bot 5-phase: **Data Crawler → Strategy Engine → Backtesting → Paper Trading → Live Trading (Freqtrade)**. Tích hợp Binance/Bybit qua `ccxt`, lưu OHLCV trong **TimescaleDB**, dashboard **Streamlit**, cảnh báo **Telegram**, Web Control Panel (Phase 6) qua **FastAPI**.

## Bắt đầu ở đâu

- 📘 [Readme/getting-started.md](./Readme/getting-started.md) — cài đặt, Docker stack, hướng dẫn vận hành từng phase.
- 🛠 [Readme/scripts.md](./Readme/scripts.md) — 2 PowerShell helper (`worker.ps1`, `web.ps1`) quản lý service ở dev.
- 🚀 [Readme/deploy.md](./Readme/deploy.md) — deploy VPS qua venv + systemd (~30–45 phút).
- 🐳 [Readme/deploy-docker.md](./Readme/deploy-docker.md) — deploy VPS bằng Docker pull + compose (~10 phút).
- 🤖 [CLAUDE.md](./CLAUDE.md) — quy ước codebase + behavioral guidelines cho AI agent.
