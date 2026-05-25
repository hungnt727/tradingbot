---
id: "0001"
title: Skeleton + health endpoint
status: ready-for-agent
type: AFK
blocked_by: []
covers_user_stories: ["#48", "#49"]
prd: ../PRD.md
plan: ../../../docs/WEB_CONTROL_PANEL_PLAN.md
---

# 0001 — Skeleton + health endpoint

## What to build

Khởi tạo bộ khung của web + worker app:

- Tạo các package mới: `web/`, `worker/`, `migrations_app/` (alembic env riêng), `scripts/` (nếu chưa có).
- File config: `alembic_app.ini` ở root trỏ về DB `tradingbot_app`.
- FastAPI app factory tối thiểu (`web/app.py`) với 1 endpoint duy nhất `GET /health` trả `{"status": "ok"}`.
- `worker/daemon.py` empty entrypoint (in 1 log "worker started" rồi `sleep` vô hạn) — placeholder cho slice 6.
- Cập nhật `.env.example` với các biến mới: `APP_DATABASE_URL`, `SESSION_SECRET_KEY`, `TELEGRAM_BOT_TOKEN`, `COINMARKETCAP_API_KEY`.
- Thêm dependencies vào `requirements.txt`: `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`, `passlib[bcrypt]`, `itsdangerous`.
- 1 empty alembic revision cho `tradingbot_app` (chưa tạo table nào — chỉ verify alembic chạy được).

Đây là tracer bullet "infra-only": chưa có business logic, nhưng có thể chạy được `uvicorn web.app:app` và `alembic -c alembic_app.ini upgrade head` không lỗi.

## Acceptance criteria

- [ ] Folder structure đúng layout đã định nghĩa trong PRD (web/, worker/, migrations_app/).
- [ ] `pip install -r requirements.txt` thành công với deps mới.
- [ ] `alembic -c alembic_app.ini upgrade head` thành công, tạo DB `tradingbot_app` (giả định DB đã được `CREATE DATABASE` trước; doc step này).
- [ ] `uvicorn web.app:app --host 0.0.0.0 --port 8000` start không lỗi, `curl localhost:8000/health` trả `{"status":"ok"}` HTTP 200.
- [ ] `python -m worker.daemon` start không lỗi, log "worker started".
- [ ] `.env.example` có đầy đủ biến mới với comment giải thích.
- [ ] Đọc `docs/WEB_CONTROL_PANEL_PLAN.md` mục "Open items" — verify biến môi trường nào cần thiết, ghi chú vào commit message nếu phát hiện gap.

## Blocked by

None — can start immediately.
