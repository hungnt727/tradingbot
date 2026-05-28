---
id: "0006"
title: Worker end-to-end scan + signal insert + Telegram alert
status: done
type: AFK
blocked_by: ["0004", "0005"]
covers_user_stories: ["#28", "#29", "#33", "#34", "#35", "#36", "#37", "#38", "#39", "#40", "#41", "#42"]
prd: ../PRD.md
plan: ../../../docs/WEB_CONTROL_PANEL_PLAN.md
---

# 0006 — Worker end-to-end scan

## What to build

Slice **lớn nhất** — toàn bộ logic worker. Sau slice này, tạo 1 process active qua UI → vài chu kỳ sau nhận Telegram alert thật.

- Alembic migration tạo bảng `signals` (đầy đủ schema + UNIQUE + INDEX theo PRD).
- `worker/data_loader.py`: `ensure_data_ready(exchange, symbol, timeframe, min_required=250) -> pd.DataFrame`. Logic check-max + incremental theo PRD section "Worker model — Backfill":
  - Query `MAX(timestamp)` + `COUNT(*)` cho cặp (exchange, symbol, timeframe) trong DB `tradingbot`.
  - Nếu rỗng / count < min_required → fetch full lookback từ crawler.
  - Ngược lại → fetch incremental từ `max_ts + 1`.
  - Upsert qua `TimescaleClient.upsert_ohlcv` (existing, idempotent).
  - Trả DataFrame ready cho strategy (query DB lại sau upsert).
- `worker/runner.py`: `run_one_process(process_id) -> RunResult`. Orchestrator theo PRD section "Worker daemon — run_one_process pattern":
  1. Mark `last_run_status='running'`, `last_run_started_at=NOW()`, clear `force_run_requested_at`.
  2. Resolve symbols (slice này chỉ support `list` mode — top_n raise NotImplementedError, slice 7 hoàn thiện).
  3. Loop symbols: `ensure_data_ready(exchange, symbol, "1h")` và `ensure_data_ready(exchange, symbol, "1d")` cho EmaRsiReversal dual-timeframe.
  4. Instantiate `EmaRsiReversalStrategy` với params từ DB, gọi `compute_indicators` + `generate_signals`.
  5. Lọc signal mới (last candle window theo `m1h`/`n1d` params).
  6. Cho mỗi signal: `INSERT INTO signals ... ON CONFLICT DO NOTHING RETURNING id`. Nếu RETURNING không rỗng:
     - Re-check `SELECT 1 FROM processes WHERE id=? AND is_active`. Nếu missing → skip telegram (process đã bị xoá / stop mid-run).
     - Resolve chat_id: `process.telegram_chat_id OR process.owner.default_telegram_chat_id`.
     - Gọi `telegram_service.send_message`. Update `signals.telegram_sent`, `telegram_sent_at`, `telegram_error`.
  7. Update `processes.last_run_at=NOW()`, `last_run_status='OK'` hoặc `'OK (telegram error: ...)'`, clear `last_run_started_at`.
  8. Catch exception → `last_run_status='error: <exc message truncated 500 chars>'`.
- `worker/reaper.py`: `reap_stuck_processes()`. SQL: reset row với `last_run_status='running' AND last_run_started_at + interval '10 minutes' < NOW()` về `error: timeout (worker crash?)`.
- `worker/daemon.py`: main loop:
  ```
  while True:
      reap_stuck_processes()
      due = query_due_processes()  # is_active AND (scheduled_due OR force_run_requested_at NOT NULL)
      for p in due:
          run_one_process(p.id)
      sleep(15)
  ```
- Telegram message template hardcoded trong `runner.py` theo PRD section "Worker — 6.6 Telegram message format".
- Status badge trong UI (slice 5 đã có placeholder) update đọc `last_run_status` — cập nhật template `processes/list.html` để render badge màu sắc:
  - `idle` → grey
  - `running` → yellow + spinner
  - `OK` → green
  - `OK (telegram error: ...)` → green + warning icon, tooltip lỗi
  - `error: ...` → red, tooltip lỗi
  - `stuck` (last_run_started_at > 10min ago) → orange — but reaper sẽ reset trước khi UI thấy.
- HTMX polling cho process list page: refresh status badge mỗi 5s (`hx-trigger="every 5s"`).

## Acceptance criteria

- [ ] Migration `signals` chạy thành công, UNIQUE constraint enforce.
- [ ] Tạo 1 process active qua UI slice 5 với `list: ["BTC/USDT"]`, interval=5min, exchange=binance.
- [ ] Trong vòng ≤30s, worker pickup → backfill ~250 nến BTC/USDT 1H + 1D → run strategy → status badge `running → OK`.
- [ ] Nếu strategy phát hiện signal → row mới trong `signals` table, message Telegram đến chat của user.
- [ ] Chạy lại worker chu kỳ 2 (interval=5min): KHÔNG fetch trùng ~250 nến (verify qua log) — chỉ fetch incremental delta (vài nến). DB không có duplicate.
- [ ] Same candle dedupe: chạy chu kỳ trên cùng candle 14:00 → INSERT trả empty → KHÔNG gửi telegram lại.
- [ ] Telegram fail (sửa chat_id sai trong process) → signal vẫn lưu (`telegram_sent=false`, `telegram_error='...'`), status badge "OK (telegram error: ...)", process vẫn tiếp tục chu kỳ kế tiếp.
- [ ] Delete process mid-run (manual SQL `is_active=false` lúc worker đang chạy) → re-check rule abort send telegram. (Hard to test deterministically — verify bằng unit test với mock sleep.)
- [ ] Force crash worker (kill -9 giữa scan) → row stuck `last_run_status='running'`. Restart worker → reaper reset về `error: timeout`. Chu kỳ kế tiếp pick up lại.
- [ ] Edit params của active process → chu kỳ kế tiếp dùng params mới (worker re-read DB mỗi cycle, không cache).
- [ ] Test plan cho `run_one_process` (deep module, highest priority):
  - Happy path: 2 symbols, 1 ra signal → 1 row signal + 1 telegram call + status OK.
  - Duplicate candle: run 2 lần → second insert empty, không telegram.
  - Telegram fail (mock 403): signal vẫn lưu, error logged, status OK with warning.
  - Process deleted mid-run: no telegram.
  - Exception during strategy: status `error: ...`, `last_run_started_at` cleared.
- [ ] Test plan cho `ensure_data_ready`:
  - DB rỗng → full fetch.
  - DB 250+ candles → incremental only.
  - DB 100 stale → fallback full fetch.
  - Crawler trả empty → không ghi, return existing DataFrame.

## Notes for the agent

- **Verify open item từ PRD**: EmaRsiReversal dual-timeframe contract — đọc `strategies/ema_rsi_reversal_strategy.py` + `cli/run_ema_rsi_reversal_bot.py` để xem 1D filter ở đâu (class hay CLI). Nếu CLI sở hữu → worker phải replicate. Grep `signal_1d`, `n1d`, `daily` trong CLI.
- Tránh tự sửa `strategies/ema_rsi_reversal_strategy.py` — chỉ instantiate và gọi public methods.
- Reuse `data/crawler/binance_crawler.py` + `bybit_crawler.py` + `data/storage/timescale_client.py` không refactor.

## Blocked by

- 0004 (telegram_service)
- 0005 (processes table + UI để tạo process test)
