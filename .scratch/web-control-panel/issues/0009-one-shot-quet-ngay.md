---
id: "0009"
title: One-shot "Quét ngay"
status: ready-for-agent
type: AFK
blocked_by: ["0006"]
covers_user_stories: ["#24", "#25", "#43"]
prd: ../PRD.md
plan: ../../../docs/WEB_CONTROL_PANEL_PLAN.md
---

# 0009 — One-shot "Quét ngay"

## What to build

Cho phép user trigger 1 chu kỳ scan ngay không cần đợi `interval_minutes`:

- Cột `force_run_requested_at` đã có trong schema từ slice 5. Slice này chỉ wire up logic.
- Route `POST /processes/:id/force-run`:
  - Authz: owner hoặc admin.
  - Set `force_run_requested_at = NOW()`.
  - **KHÔNG** chạy strategy trực tiếp — chỉ set flag, worker pickup.
  - Return HTMX fragment update badge `running...` (optimistic UI).
- Update query trong `worker/daemon.py` (từ slice 6): pickup khi:
  ```
  is_active=true AND (
    (last_run_at IS NULL OR last_run_at + interval = scheduled_due)
    OR force_run_requested_at IS NOT NULL
  )
  ```
- `worker/runner.py` đầu mỗi run clear `force_run_requested_at = NULL` (đã làm ở slice 6 step 1 — verify).
- Reduce worker sleep từ 15s xuống **5-10s** để force-run responsive (≤30s từ click → kết quả). Document trade-off CPU không đáng kể.
- UI: thêm button "Quét ngay" trong `processes/list.html` mỗi row, bên cạnh Start/Stop. Disabled khi `is_active=false` (chỉ active process mới run được — hoặc cho phép force-run trên inactive? PRD say UX feature is for "test" → cho phép cả inactive).
- HTMX polling intensify: sau click "Quét ngay", polling status badge 2s/lần thay vì 5s mặc định, đến khi `last_run_status != 'running'` thì revert 5s/lần. Implement bằng `hx-trigger="every 2s"` trên element có class temporary.

## Acceptance criteria

- [ ] User click "Quét ngay" → POST trả 200 + HTMX swap badge `running...`.
- [ ] Trong vòng ≤30s từ click → status badge update `running → OK` (hoặc `error: ...`).
- [ ] Nếu có signal mới → row hiện trong signal history (slice 8) ngay sau khi worker xong.
- [ ] Force-run trên process `is_active=false` cũng work (chỉ scan 1 lần, không enable auto schedule).
- [ ] Spam click "Quét ngay" trong 10s → chỉ 1 scan thực sự chạy (force_run_requested_at là 1 row → worker pickup 1 lần rồi clear).
- [ ] Hai user spam force-run trên 2 process khác nhau → cả 2 đều được xử lý (single-threaded worker xử lý tuần tự, không lost).
- [ ] Worker sleep giảm xuống 5-10s không gây CPU > 5% (verify systemd `systemctl status tradingbot-worker`).
- [ ] HTMX poll 2s reverts về 5s khi badge != running (DOM-based class swap hoặc trigger condition).
- [ ] Test plan:
  - `force_run_requested_at` set → next worker cycle picks up regardless of `last_run_at + interval`.
  - After run completes, `force_run_requested_at` cleared.
  - Concurrent force-run trên 2 process → cả 2 chạy (tuần tự trong cùng worker loop).

## Blocked by

- 0006 (worker + status state machine + HTMX badge)
