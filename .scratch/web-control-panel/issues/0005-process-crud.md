---
id: "0005"
title: Process CRUD (custom-list mode only, no execution)
status: ready-for-agent
type: AFK
blocked_by: ["0002"]
covers_user_stories: ["#16", "#17", "#18", "#19", "#20", "#21", "#22", "#23", "#26", "#27"]
prd: ../PRD.md
plan: ../../../docs/WEB_CONTROL_PANEL_PLAN.md
---

# 0005 — Process CRUD (custom-list mode only)

## What to build

CRUD đầy đủ cho process từ web — chưa có execution (worker là slice 6).

- Alembic migration tạo bảng `processes` (đầy đủ schema theo PRD section "Schema"). Bao gồm cả cột `force_run_requested_at` (slice 9 sẽ dùng).
- `EmaRsiReversalParams` Pydantic model (theo PRD section "Strategy params schema") với 11 fields, validate bằng `ge`/`le`.
- `process_service` (deep module): `create_process(owner_user_id, data)`, `list_processes(user)` (filter theo owner, admin thấy hết), `get_process(id, user)` (404 nếu không phải owner và không admin), `update_process(id, data, user)`, `delete_process(id, user)`, `toggle_active(id, user)`. Authz check trong service, KHÔNG ở route.
- Routes (require authenticated user):
  - `GET /processes` — list của user hiện tại (admin thấy hết, có toggle).
  - `GET /processes/new` + `POST /processes` — form create.
  - `GET /processes/:id/edit` + `POST /processes/:id` — form edit.
  - `POST /processes/:id/delete` — confirm + delete.
  - `POST /processes/:id/toggle` — flip `is_active`.
- Templates:
  - `processes/list.html` — table với cột: name, strategy, exchange, symbols summary, interval, status badge (placeholder vì chưa có worker), Start/Stop button, Edit, Delete.
  - `processes/form.html` — form 2-tier: Basic params (5 fields) hiện luôn, Advanced (5 fields + 1 lookback) collapsible `<details>`. Tooltip từ Pydantic `description`. Validate bounds client-side bằng `input min=X max=Y step=...` + server-side bằng Pydantic.
- **Symbols mode chỉ hỗ trợ `list` ở slice này** — form có textarea "Symbols (one per line)". Mode `top_n` add ở slice 7 (UI có thể có radio button select mode, nhưng `top_n` option disabled + tooltip "Available in next slice").
- Update flow: cập nhật `updated_at` mỗi lần PATCH. KHÔNG block edit khi `is_active=true` (worker re-read DB mỗi cycle).
- Validation phía route: nếu `is_active=true` mà cả `processes.telegram_chat_id` lẫn `users.default_telegram_chat_id` đều NULL → error "Set a Telegram chat ID first".

## Acceptance criteria

- [ ] Migration chạy thành công, table `processes` đầy đủ cột + UNIQUE + INDEX theo PRD.
- [ ] User tạo process mới từ form → row xuất hiện trong list của user đó. KHÔNG xuất hiện trong list của user khác.
- [ ] User khác request `GET /processes/:id/edit` của process không phải của họ → 404 (KHÔNG 403, để tránh leak info "process tồn tại").
- [ ] Admin thấy tất cả process của mọi user trong `/admin/processes` (view-only — nút Edit/Delete disabled).
- [ ] Form Basic + Advanced render đúng — 5 fields trên, 6 fields trong `<details>` collapsed mặc định.
- [ ] Bounds enforce: nhập `interval_minutes=3` → form error "must be ≥ 5"; `rsi_period=1` → error.
- [ ] Edit anytime: update process với `is_active=true` thành công, KHÔNG bị block.
- [ ] Toggle Start: set `is_active=true` thành công CHỈ KHI có chat_id (user default hoặc process override), ngược lại error.
- [ ] Delete process → row biến mất, cascade chưa test được vì signals table chưa có (sẽ verify ở slice 6).
- [ ] Symbols mode chỉ `list` hoạt động. Radio top_n disabled với tooltip.
- [ ] Per-process Telegram chat_id override field hoạt động (lưu vào `processes.telegram_chat_id`, null = inherit user default).
- [ ] SL/TP percentages trong Advanced section update đúng JSONB.
- [ ] Tests cho `process_service`: ownership check, admin override, validate interval bound, validate chat_id rule.

## Blocked by

- 0002 (auth — cần current user)
