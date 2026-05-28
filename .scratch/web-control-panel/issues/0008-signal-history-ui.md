---
id: "0008"
title: Signal history UI
status: done
type: AFK
blocked_by: ["0006"]
covers_user_stories: ["#30", "#31", "#32"]
prd: ../PRD.md
plan: ../../../docs/WEB_CONTROL_PANEL_PLAN.md
---

# 0008 — Signal history UI

## What to build

Trang history signal cho từng process:

- Route `GET /processes/:id/signals`:
  - Authz: chỉ owner hoặc admin xem được.
  - Pagination: `?page=1&size=50` (max size 200).
  - Filters: `?exchange=binance&symbol=BTC/USDT&signal_type=SHORT&from=2026-01-01&to=2026-12-31`.
  - Sort: mặc định `detected_at DESC`.
  - Query dùng index `ix_signals_process_recent`.
- Template `signals/list.html`:
  - Table với cột: detected_at, candle timestamp, exchange, symbol, signal_type, telegram status (badge), action.
  - Status badge: `telegram_sent=true` → ✓ green tooltip "Sent at X"; `false + error` → ⚠ red tooltip lỗi; `false + no error` → ⏳ pending (rare, in-flight).
  - Filter bar trên đầu — HTMX submit not full reload (return chỉ phần table).
  - Pagination nav (prev/next).
  - Click row → HTMX get fragment hiển thị modal `signals/detail_modal.html` với raw JSON `indicators_snapshot` formatted đẹp.
- Service `signal_service.list_signals(process_id, filters, page, size, user)`:
  - Authz check ownership/admin trước khi query.
  - Build SQLAlchemy query với dynamic filter clauses.
  - Return `(rows, total_count, page_count)`.
- Link tới trang history từ process list (slice 5) — add column "View signals" trong `processes/list.html`.

## Acceptance criteria

- [ ] Owner truy cập `/processes/:id/signals` → 200, list signal của process.
- [ ] User khác (non-admin) truy cập same URL → 404.
- [ ] Admin truy cập bất kỳ process nào → 200.
- [ ] Filter exchange=binance + symbol=BTC/USDT → chỉ rows khớp.
- [ ] Filter date range → chỉ rows trong khoảng.
- [ ] Pagination: page 2 trả đúng size kế tiếp; `total_count` đúng.
- [ ] Click row → modal mở hiển thị indicators_snapshot JSON đầy đủ (RSI, EMA-RSI 5/10/20, ATR, ...).
- [ ] Status badge đúng màu theo telegram_sent + telegram_error.
- [ ] HTMX filter submit không reload trang — chỉ swap table body.
- [ ] Performance: 1000+ signals trong DB, load page 1 < 200ms (verify EXPLAIN dùng đúng index).
- [ ] Test plan cho `signal_service.list_signals`:
  - Authz: non-owner non-admin → empty/error.
  - Filter combination correctness.
  - Pagination boundary (page 0, page > max).
  - Sort order.

## Blocked by

- 0006 (signals table + data)
