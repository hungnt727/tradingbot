---
id: "0003"
title: Admin user CRUD
status: ready-for-agent
type: AFK
blocked_by: ["0002"]
covers_user_stories: ["#4", "#5", "#6", "#7", "#8", "#9"]
prd: ../PRD.md
plan: ../../../docs/WEB_CONTROL_PANEL_PLAN.md
---

# 0003 — Admin user CRUD

## What to build

Trang admin để quản lý user mà không cần SSH vào VPS:

- `user_service`: `create_user(username, password, is_admin)`, `reset_password(user_id, new_password)`, `delete_user(user_id)`, `list_users() -> list[UserOut]`. Hash bằng `auth_service.hash_password`.
- Authorization dependency `require_admin` (FastAPI dependency) — raise 403 nếu `request.state.user.is_admin != True`.
- Routes (tất cả gated bằng `require_admin`):
  - `GET /admin/users` — list users với last_activity (cột mới, hoặc đọc từ `last_run_at` của process gần nhất — đơn giản thì hiển thị `created_at` cho v1).
  - `POST /admin/users` — tạo user (form fields: username, password, is_admin checkbox, default_telegram_chat_id optional).
  - `POST /admin/users/:id/reset-password` — set password mới.
  - `POST /admin/users/:id/delete` — xoá user, CASCADE xoá processes + signals của họ.
- Templates `admin/users_list.html`, `admin/user_form.html`.
- View-all-processes (read-only): `GET /admin/processes` placeholder — sẽ implement đầy đủ ở slice 0005, slice này chỉ tạo route trả "Coming in slice 5" để admin nav có link sẵn.

## Acceptance criteria

- [ ] User thường (`is_admin=false`) request `GET /admin/users` → 403 Forbidden.
- [ ] Admin tạo user mới từ form → user xuất hiện trong list → user mới login được với credentials đó.
- [ ] Admin tick "is_admin" khi create → user mới truy cập được `/admin/users`.
- [ ] Admin reset password user khác → user đó login được với password mới, KHÔNG login được với password cũ.
- [ ] Admin xoá user → user biến mất khỏi list → user đó không login được nữa.
- [ ] Admin KHÔNG xoá được chính mình (validation server-side trả error rõ ràng).
- [ ] Username unique constraint enforce — tạo trùng username → error message rõ ràng.
- [ ] Tests cho `user_service`: create, reset_password, delete cascade verify (cần slice 5 mới test được cascade — slice này test ở mức user table).

## Blocked by

- 0002 (auth + users table)
