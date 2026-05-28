---
id: "0004"
title: User profile + Telegram service + test button
status: done
type: AFK
blocked_by: ["0002"]
covers_user_stories: ["#13", "#14", "#15"]
prd: ../PRD.md
plan: ../../../docs/WEB_CONTROL_PANEL_PLAN.md
---

# 0004 — User profile + Telegram service + test button

## What to build

Trang Settings cho user + Telegram service (primitive được slice 6 dùng lại):

- `telegram_service` (deep module): `send_message(chat_id: str, text: str) -> tuple[bool, str | None]`. Wrap Telegram Bot API qua `httpx` async. Đọc `TELEGRAM_BOT_TOKEN` từ env. Phân loại lỗi:
  - 200 OK → `(True, None)`.
  - 403 (bot blocked) hoặc 400 (invalid chat_id) → `(False, "<lý do>")` — permanent, caller log + giữ alert.
  - Timeout / 5xx → `(False, "transient: ...")` — transient, caller log + retry tự nhiên chu kỳ kế tiếp.
- Routes (require authenticated user):
  - `GET /settings` — render form với current default_telegram_chat_id, change password section.
  - `POST /settings/profile` — update default_telegram_chat_id.
  - `POST /settings/test-telegram` — gọi `send_message(default_telegram_chat_id, "Test message from TradingBot web")`. Trả về JSON `{success: bool, error?: str}` cho HTMX consume.
  - `POST /settings/password` — verify old password + hash new + update.
- Template `settings/profile.html` với Test button trigger HTMX POST, hiển thị toast inline.

## Acceptance criteria

- [ ] User lưu default_telegram_chat_id → DB update đúng cột `users.default_telegram_chat_id`.
- [ ] Test Telegram button với chat_id đúng → user nhận message thật trong Telegram, toast "Sent successfully" hiện inline (HTMX update không reload trang).
- [ ] Test Telegram button với chat_id sai → toast hiển thị lỗi specific (vd "Chat not found").
- [ ] Test Telegram button với token sai trong `.env` → toast hiển thị lỗi token rõ ràng.
- [ ] Change password: nhập sai old password → error inline, không update.
- [ ] Change password: nhập đúng → password hash update, session vẫn còn hiệu lực (KHÔNG ép logout).
- [ ] Tests cho `telegram_service.send_message`:
  - Mock `httpx` trả 200 → returns `(True, None)`.
  - Mock trả 403 → returns `(False, "...")` với reason chứa "blocked".
  - Mock raise timeout → returns `(False, "transient: ...")`.

## Blocked by

- 0002 (auth — cần current user để biết update profile của ai)
