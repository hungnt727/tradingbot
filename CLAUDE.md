# TradingBot — Project Conventions

Crypto Trading Bot framework. Pipeline gồm 5 phase: **Data Crawler → Strategy Engine → Backtesting → Paper Trading → Live Trading (Freqtrade)**. Tích hợp Binance/Bybit qua `ccxt`, lưu OHLCV trong **TimescaleDB**, real-time cache trong **Redis**, dashboard bằng **Streamlit**, cảnh báo qua **Telegram**.

Xem [README.md](./README.md) cho hướng dẫn vận hành đầy đủ.

## Cấu trúc module

| Thư mục | Vai trò |
|---|---|
| [`data/`](./data/) | Crawler (`base_crawler`, `binance_crawler`, `bybit_crawler`) + Models (SQLAlchemy: `OHLCV`, `Trade`, `ExchangeInfo`) + Storage (`TimescaleClient`, `redis_client`) |
| [`strategies/`](./strategies/) | `BaseStrategy` ABC + các strategy: `SonicRStrategy`, `EmaRsiReversalStrategy`, `DistributionStrategy`. Freqtrade wrapper trong [`strategies/freqtrade/`](./strategies/freqtrade/) |
| [`backtest/`](./backtest/) | Engine mô phỏng nến (`engine.py`, `trade_simulator.py`), metrics (QuantStats), HTML report, runner scripts |
| [`paper_trading/`](./paper_trading/) | Realtime engine (`engine.py`) + `PortfolioManager` ghi trade vào DB |
| [`live/`](./live/) | Freqtrade Docker stack + `user_data/` config + setup script |
| [`cli/`](./cli/) | Runners CLI: `download_data`, `start_scheduler`, `run_backtest`, `run_paper_*`, `run_*_signal_bot`, `bulk_download` |
| [`dashboard/`](./dashboard/) | Streamlit UI theo dõi paper trade (`app.py`) |
| [`config/strategies/`](./config/strategies/) | YAML config từng strategy (params, filters, risk management) |
| [`docker/`](./docker/) | Postgres/TimescaleDB + Redis compose stack |
| [`migrations/`](./migrations/) | Alembic revisions |
| [`utils/`](./utils/) | Telegram bot client |
| [`tests/`](./tests/) | Pytest suite (`test_*.py`) |
| [`scripts/`](./scripts/) | Dev helpers (DB checks, cache update) |

## Language & tooling

- **Python 3.10+** (xem `requirements.txt`).
- **pip + venv** là package manager mặc định của dự án này — không dùng `uv`. Cài bằng `pip install -r requirements.txt` trong `venv/` (Windows: `venv\Scripts\activate`).
- **SQLAlchemy 2.0 + Alembic** cho ORM/migration. TimescaleDB hypertable trên bảng `ohlcv`.
- **pandas / pandas-ta / numpy** cho tính toán indicator. **ccxt** cho exchange.
- **APScheduler** cho incremental sync.
- **QuantStats + Plotly** cho backtest report HTML.
- **Streamlit** cho dashboard.
- **Loguru** cho logging — không dùng `print()` trong code service/library.
- **Pytest + pytest-asyncio + pytest-mock** cho test.
- **Click** cho CLI runner trong `cli/`.

## Code style

- `snake_case` cho functions, variables, files, modules.
- `PascalCase` cho classes (e.g. `SonicRStrategy`, `TimescaleClient`).
- Type hints trên public function/method. Modern syntax (`list[str]`, `X | None`, `Optional[X]` cũng OK vì code hiện tại dùng cả hai).
- Strategy mới: kế thừa `strategies.base_strategy.BaseStrategy`, implement `compute_indicators` / `generate_signals` / `get_sl_tp`. Set `name` và `timeframe` class attribute.
- Imports thứ tự: stdlib → third-party (pandas, ccxt, sqlalchemy) → local (`data.*`, `strategies.*`, `paper_trading.*`).

## Architecture patterns

Dự án được tổ chức theo **5 phase** — giữ nguyên ranh giới này khi thêm tính năng:

- **Phase 1 — Data Layer**: `data/crawler/` (kế thừa `BaseCrawler`, mỗi sàn 1 class) đẩy OHLCV vào `data/storage/timescale_client.py`. Real-time push cache qua `redis_client`. Scheduler chạy nền bằng APScheduler.
- **Phase 2 — Strategy Engine**: stateless. Mỗi strategy ABC chỉ thao tác trên DataFrame, không gọi DB/exchange. Config chiến lược ở `config/strategies/<name>.yaml`.
- **Phase 3 — Backtest**: `backtest/engine.py` + `trade_simulator.py` (mô phỏng phí + slippage). Runner ở `backtest/run_*.py`, output HTML report vào `output/reports/`.
- **Phase 4 — Paper Trading**: `paper_trading/engine.py` poll OHLCV mới → gọi strategy → mở/đóng paper trade qua `PortfolioManager`. Dashboard Streamlit đọc cùng DB. Thông báo qua `utils/telegram_bot.py`.
- **Phase 5 — Live**: KHÔNG viết code execute order trong repo này. Chỉ cung cấp Freqtrade wrapper (`strategies/freqtrade/sonicr_ft.py`) + Docker stack trong `live/`. Tất cả risk/order management do Freqtrade lo.

Quy tắc: 
- **Strategy không gọi DB hoặc HTTP** — chỉ nhận DataFrame và trả DataFrame. Tránh side-effect.
- **Engine (backtest hoặc paper) là nơi duy nhất orchestrate** strategy + storage + portfolio.
- **CLI runner trong `cli/` thì mỏng** — chỉ parse args và gọi engine.

## Secrets & config

- API key (Binance, Bybit, Telegram, CMC) đọc từ `.env` qua `python-dotenv`. Không hardcode key trong code.
- `.env.example` là source-of-truth cho các biến cần thiết. `.env` thật được gitignore.
- Strategy parameter (SL/TP, indicator length, filter) đặt trong `config/strategies/*.yaml`, KHÔNG hardcode vào class trừ default fallback.
- Freqtrade exchange credentials trong `live/user_data/config.json` (file này gitignored).

## Output & data

- Backtest report HTML → `output/reports/` (gitignored).
- `data/top_300_cache.json` và `data/cache/` được gitignore — cache nội bộ, không commit.
- Log file (`*.log`, `logs/`) gitignore.
- Migrations Alembic ở `migrations/versions/` — commit chúng vào git như bình thường.

## Common dev loop

```bash
# Kích hoạt venv
venv\Scripts\activate                  # Windows
source venv/bin/activate               # Linux/Mac

# Cài/cập nhật deps
pip install -r requirements.txt

# Khởi động DB stack
cd docker && docker compose up -d && cd ..

# Migrations
alembic upgrade head

# Tải dữ liệu
python cli/download_data.py --exchange binance --symbol BTC/USDT --timeframe 1h --start 2024-01-01

# Backtest
python cli/run_backtest.py --strategy SonicRStrategy --exchange binance --symbol BTC/USDT --timeframe 1h --start 2024-01-01

# Paper trade
python cli/run_paper_ema_rsi.py --top 100

# Dashboard
streamlit run dashboard/app.py

# Test
pytest

# Live (Freqtrade Docker)
cd live && docker compose up -d
```

## Telegram & Signal bots

Khi thêm signal/notification cho 1 strategy mới:
- Reuse `utils/telegram_bot.py` — không tạo client mới.
- Đặt `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID` trong `.env`.
- Signal bot CLI nằm trong `cli/run_*_signal_bot.py`, phải hỗ trợ `--oneshot` cho dry-test và `--interval` cho loop.
- Idempotent: bot chạy lại không gửi trùng tín hiệu của cùng 1 cây nến (đối chiếu timestamp).
- Log URL/ID kết quả khi gửi thông báo.

---

## Behavioral guidelines (Karpathy-inspired)

> Source: [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) — verbatim, MIT-licensed. Derived from [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876) on LLM coding pitfalls.
>
> **Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks (typo fixes, obvious one-liners), use judgment — not every change needs full rigor.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

**The test:** Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

### Trading-specific cautions

Trading code có hậu quả tài chính. Áp dụng các quy tắc bổ sung:

- **Không thay đổi `risk_management` (sl_pct, tp_levels, max_holding) trong YAML khi không được yêu cầu trực tiếp** — đây là tham số đã được backtest/tune. Đề xuất rồi đợi user confirm.
- **Đừng "improve" trade simulator** (phí, slippage, mô hình close-on-bar) trừ khi user yêu cầu — thay đổi nhỏ làm vô hiệu kết quả backtest cũ.
- **Phase 5 (Live) là DRY-RUN mặc định** — không tự ý đổi `dry_run: false` trong `live/user_data/config.json`.
- **Không commit `.env`**, `live/user_data/config.json` chứa credentials, hoặc bất kỳ file API key nào.
- Khi thêm signal/order logic, viết test trước (TDD) — bug trong indicator hoặc signal logic = mất tiền thật ở phase 5.

---

## Available skills (Matt Pocock)

Có 13 skills được cài tại [`.claude/skills/`](./.claude/skills/) (và mirror tại [`.agents/skills/`](./.agents/skills/)) từ [mattpocock/skills](https://github.com/mattpocock/skills) (MIT-licensed). Khoá tại [`skills-lock.json`](./skills-lock.json). Xem chi tiết tiếng Việt tại [docs/mattpocock-skills/README.md](./docs/mattpocock-skills/README.md).

### Trước khi code → "Think Before Coding"

- **`/grill-me`** — Stress-test plan bằng câu hỏi đào sâu. Dùng **trước mỗi thay đổi không tầm thường**.
- **`/grill-with-docs`** — Như `/grill-me` nhưng đối chiếu plan với `CONTEXT.md` + ADR. Dùng khi thay đổi đụng vào domain/architecture (vd thêm strategy mới, đổi cách lưu OHLCV).
- **`/zoom-out`** — Giải thích 1 file trong bối cảnh hệ thống. Dùng trước khi đụng module lạ (vd sửa [`paper_trading/engine.py`](./paper_trading/engine.py) hoặc [`backtest/trade_simulator.py`](./backtest/trade_simulator.py)).
- **`/to-prd`** — Tổng hợp cuộc thảo luận thành PRD. Dùng sau brainstorm dài, trước khi code.
- **`/to-issues`** — Bẻ plan/PRD thành vertical slice issues. Dùng khi feature lớn hơn 1 session.

### Trong khi code → "Simplicity First" + "Goal-Driven Execution"

- **`/tdd`** — Red → green → refactor. Dùng cho bug fix (viết test reproduce trước) và feature mới. **Đặc biệt cần thiết cho indicator/signal code.**
- **`/diagnose`** — Reproduce → minimise → hypothesise → instrument → fix → regression-test. Dùng cho bug khó (vd "paper trade không khớp backtest", "indicator tính sai sau update").
- **`/prototype`** — Build prototype throw-away. Dùng khi thử thiết kế mới (vd thử filter mới cho SonicR, thử 1 risk management variant).

### Sau khi code → "Surgical Changes"

- **`/improve-codebase-architecture`** — Quét cơ hội refactor, tham chiếu `CONTEXT.md` + ADR. Chạy **định kỳ vài ngày 1 lần**, không đợi codebase rotten.

### Workflow helpers

- **`/caveman`** — Mode siêu nén ~75% token. Khi muốn câu trả lời ngắn gọn.
- **`/handoff`** — Compact conversation thành handoff doc. Dùng cuối session dài.
- **`/write-a-skill`** — Tạo skill mới trong [`.claude/skills/`](./.claude/skills/). Dùng khi lặp workflow ≥ 3 lần.

### Setup (1 lần / repo)

- **`/setup-matt-pocock-skills`** — Cấu hình issue tracker, triage labels, vị trí docs/ADR. Đã chạy 1 phần — xem [`docs/agents/`](./docs/agents/) (nếu có).

### Flow gợi ý cho 1 feature mới (vd: thêm strategy mới)

```
1. /grill-with-docs        → align về what + why, cập nhật CONTEXT.md
2. /to-prd                 → ghi lại agreement
3. /to-issues              → bẻ thành vertical slices
4. Với mỗi slice:
   /tdd                    → red → green → refactor
5. Định kỳ:
   /improve-codebase-architecture  → giữ entropy thấp
```

### Mapping Karpathy ↔ skill

| Karpathy principle | Skill |
|---|---|
| 1. Think Before Coding | `/grill-me`, `/grill-with-docs`, `/zoom-out` |
| 2. Simplicity First | `/prototype` |
| 3. Surgical Changes | `/improve-codebase-architecture`, `/zoom-out` |
| 4. Goal-Driven Execution | `/tdd`, `/diagnose` |

> Nếu chỉ nhớ 2: **`/grill-with-docs`** trước khi code và **`/tdd`** trong khi code.

## Agent infrastructure

### Issue tracker

Local markdown — issues và PRDs lưu dưới `.scratch/<feature-slug>/` (tạo khi cần). Khi `/setup-matt-pocock-skills` đã chạy thì xem `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. Ghi dưới dạng `Status:` trong từng issue file.

### Domain docs

[CONTEXT-MAP.md](./CONTEXT-MAP.md) ở root trỏ tới [CONTEXT.md](./CONTEXT.md) — định nghĩa ngôn ngữ domain (OHLCV, Signal, Position, Strategy, Backtest, Paper Trade, Live Trade...).
