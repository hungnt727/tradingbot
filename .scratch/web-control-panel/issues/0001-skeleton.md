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

Khởi tạo bộ khung của web + worker app. Scope đã được grilling chốt (xem "Grilling decisions" cuối file):

- Tạo các package mới **ở repo root** (peer với `data/`, `strategies/`, `backtest/`, `paper_trading/`, `live/`):
  - `web/` — FastAPI app.
  - `worker/` — daemon entrypoint.
  - `migrations_app/` — alembic env riêng cho DB `tradingbot_app`.
  - `app_db/` — **shared** SQLAlchemy package (declarative `Base` + ORM models). Cả `web/` và `worker/` import từ đây. Slice 0 chỉ tạo `app_db/__init__.py`, `app_db/base.py` (declarative_base) và `app_db/models/__init__.py` rỗng — chưa có model nào.
  - `scripts/` **đã tồn tại** (chứa `check_db.py`, `update_cache.py`...) — không tạo mới. **`scripts/create_admin.py` deferred sang slice 1** vì phụ thuộc `User` model + `passlib`.
- File config: `alembic_app.ini` ở root trỏ về DB `tradingbot_app` (URL từ `APP_DATABASE_URL`).
- `migrations_app/env.py` set `target_metadata = app_db.base.Base.metadata` (sẵn sàng autogenerate cho slice 1+).
- `web/app.py`: **module-level** `app = FastAPI()` (không factory), 1 endpoint `GET /health` trả `{"status": "ok"}` dumb (không probe DB/Redis — health check thật chuyển sang slice 9).
- `worker/daemon.py`: `if __name__ == "__main__":` block, `loguru` log "worker started", `while True: time.sleep(60)`. Không Click, không signal handler — slice 4 sẽ rewrite.
- `.env.example` thêm **chỉ 2 biến mới** trong section mới `# Web Control Panel (Phase 6)` đặt sau `# Database`:
  - `APP_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tradingbot_app` + comment hướng dẫn `CREATE DATABASE tradingbot_app` (reuse `postgres` superuser; `tradingbot_app_user` role tách bạch **deferred sang slice 9**).
  - `SESSION_SECRET_KEY=change_me_generate_with_secrets_token_hex_32` + comment kèm lệnh `python -c "import secrets; print(secrets.token_hex(32))"`.
  - `TELEGRAM_BOT_TOKEN` và `COINMARKETCAP_API_KEY` **không đổi** (đã có sẵn từ phase trước, chỉ newly consumed).
- `requirements.txt` thêm **chỉ 2 deps** vào section mới `# Web Control Panel (Phase 6)` sau `# Dashboard (Phase 4)`:
  - `fastapi==<pin>`, `uvicorn[standard]==<pin>` — exact pins, chạy `pip install fastapi 'uvicorn[standard]'` rồi `pip freeze | grep -E 'fastapi|uvicorn'` để lấy version thật.
  - `jinja2`, `python-multipart`, `passlib[bcrypt]`, `itsdangerous` **deferred sang slice 1** (auth) khi thực sự cần.
- 1 empty alembic revision cho `tradingbot_app` (`def upgrade(): pass` / `def downgrade(): pass`) — verify alembic chạy được + tạo bảng `alembic_version`.

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

## Grilling decisions (2026-05-26)

Scope đã được chốt qua 9 câu grilling, audit trail:

| # | Quyết định | Lý do tóm tắt |
|---|---|---|
| Q1 | Packages ở **repo root**, peer với phase folders | Khớp convention `CLAUDE.md` |
| Q2 | DB tạo manual qua psql; reuse `postgres` superuser; `tradingbot_app_user` role deferred slice 9 | Slice 0 minimal; hardening đi cùng deployment |
| Q3 | **`app_db/` shared package** (không nest dưới `web/`); `target_metadata = app_db.base.Base.metadata`; empty revision `pass/pass` | Schema là shared infra, không "owned" bởi web hay worker. Xem `docs/adr/0001-shared-app-db-package.md` |
| Q4 | Module-level `app` (không factory); settings via `os.getenv`; `/health` dumb | Không predict shape của slice 1-9 |
| Q5 | Worker = loguru + `time.sleep(60)`; không Click; không signal handler | Placeholder phải obvious-to-replace |
| Q6 | Chỉ thêm `fastapi` + `uvicorn[standard]`; defer 4 deps còn lại sang slice 1 | Vertical slice ownership |
| Q7 | Chỉ thêm 2 env var mới; giữ nguyên `TELEGRAM_BOT_TOKEN`/`COINMARKETCAP_API_KEY` | Chúng đã có sẵn, chỉ newly consumed |
| Q8 | Không tests trong slice 0 (chưa có CI) | AC checklist là verification |
| Q9 | Open items 11.1–11.5 đều ảnh hưởng slice 5/9, không có gap env-var. `scripts/create_admin.py` deferred sang slice 1 (đã có trong issue 0002) | Đồng bộ issue ↔ plan |

Commit message phải ghi: *"Open items 11.1–11.5 deferred to slices 5/9 (no slice-0 env-var gap). create_admin.py deferred to slice 1."*
