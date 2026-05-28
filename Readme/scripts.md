# Quản lý 2 service Phase 6 bằng PowerShell script

Phase 6 (Web Control Panel) gồm 2 OS process cần chạy 24/7 trong dev:

| Service | Vai trò | Port | Script |
|---|---|---|---|
| **worker** | Daemon loop polling DB, quét OHLCV, gọi strategy, ghi Signal, gửi Telegram alert | — | [`scripts/worker.ps1`](../scripts/worker.ps1) |
| **web** | FastAPI UI để user CRUD Process + xem Signal history | 8000 | [`scripts/web.ps1`](../scripts/web.ps1) |

Cả 2 script có **cùng interface 5 subcommand**: `start`, `stop`, `restart`, `status`, `log`.

> Lưu ý: Start/Stop trên web UI ≠ start/stop worker. UI chỉ flip `is_active` của 1 Process row. Worker daemon là OS process riêng, quản lý bằng `scripts/worker.ps1`. Xem [getting-started.md](./getting-started.md) cho phân biệt khái niệm.

---

## Lần đầu setup (chỉ chạy 1 lần)

Nếu PowerShell từ chối chạy script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Cho phép tất cả script đã ký + script local của bạn chạy (an toàn cho dev).

---

## 5 subcommand

Chạy từ thư mục project (`D:\Projects\Crypto\TradingBot`).

### `start` — khởi động ngầm

```powershell
.\scripts\worker.ps1 start
.\scripts\web.ps1 start
```

- Chạy ở **hidden window** — đóng PowerShell cũng không ảnh hưởng.
- **Idempotent**: nếu service đã chạy, in cảnh báo và thoát (không start trùng).
- stdout → `logs\worker.log` / `logs\web.log`; stderr → `logs\worker.err.log` / `logs\web.err.log`.
- `web.ps1 start` mặc định bật `--reload` → sau khi start, mỗi lần bạn sửa code Python, uvicorn auto-reload, không cần restart lại.
- Nếu start **fail** (vd Postgres chưa lên, port đã chiếm, .env thiếu), script in tail của error log + exit 1 — không silent fail.

### `stop` — dừng

```powershell
.\scripts\worker.ps1 stop
.\scripts\web.ps1 stop
```

- **Idempotent**: nếu không chạy, in cảnh báo và thoát.
- `web.ps1 stop` kill cả master + reload-child (uvicorn `--reload` spawn 2 process).
- Detect process qua `CommandLine` (worker) hoặc `CommandLine` + port listener (web — child process đôi khi không expose CommandLine).

### `restart` — load code mới

```powershell
.\scripts\worker.ps1 restart
.\scripts\web.ps1 restart
```

= `stop` + **xoá toàn bộ `__pycache__`** + sleep 1s + `start`. Đây là cách nhanh nhất để load code Python mới khi:
- Sửa `worker/runner.py`, `worker/data_loader.py`, `worker/symbols_resolver.py`, etc. → **restart worker**.
- Sửa `web/routes/*.py`, `web/services/*.py`, `web/app.py` → **web tự reload nhờ `--reload`**, không cần restart trừ khi đổi config startup.
- Cập nhật `requirements.txt` (cài deps mới) → restart cả 2.

> Vì sao bước xoá `__pycache__`? Khi sửa cùng 1 module nhiều lần liên tiếp rồi restart, Python đôi khi import lại bytecode cũ (gặp khi thêm strategy mới vào `STRATEGY_REGISTRY` → worker báo `Unknown strategy 'X'` dù source đã có). Xoá `__pycache__` triệt để loại trừ scenario này. Process đang chạy không bị ảnh hưởng — Python regenerate `.pyc` khi import lần sau.

### `status` — xem trạng thái

```powershell
.\scripts\worker.ps1 status
.\scripts\web.ps1 status
```

In:
- PID + thời điểm start (so sánh với mtime file Python để biết code có lỗi thời không).
- Port đang listen (web only).
- Đường dẫn + dung lượng log file.

### `log` — tail log live

```powershell
.\scripts\worker.ps1 log
.\scripts\web.ps1 log
```

Hiển thị 30 dòng cuối rồi follow (`Get-Content -Wait`). `Ctrl+C` để thoát mà không ảnh hưởng service.

> Loguru (worker) mặc định ghi vào **stderr** → check `logs\worker.err.log` cho dòng "worker started" và lỗi. `logs\worker.log` thường rỗng trừ khi có `print()` (không nên dùng trong code service).

---

## Workflow phổ biến

### Sau khi `git pull` hoặc sửa code worker

```powershell
.\scripts\worker.ps1 restart
.\scripts\worker.ps1 status         # confirm PID + time mới
.\scripts\worker.ps1 log            # xem worker tick live
```

### Sau khi sửa code web

Nhờ `--reload`, không cần restart. Refresh trang là đủ. Nếu cần restart cứng (vd đổi env var):

```powershell
.\scripts\web.ps1 restart
```

Session cookie nằm trong Redis nên không phải đăng nhập lại.

### Boot full stack (sau reboot máy)

```powershell
cd D:\Projects\Crypto\TradingBot
docker compose -f docker\docker-compose.yml up -d     # Postgres + Redis
.\scripts\worker.ps1 start
.\scripts\web.ps1 start
```

Worker và web đều load `.env` qua `python-dotenv` — không cần set env vars thủ công.

### Tắt nhẹ nhàng (trước khi shutdown)

```powershell
.\scripts\worker.ps1 stop
.\scripts\web.ps1 stop
docker compose -f docker\docker-compose.yml down
```

---

## Vị trí log

```
logs/
├── worker.log         # stdout của worker (thường rỗng)
├── worker.err.log     # stderr + loguru của worker — đây là log chính
├── web.log            # stdout của uvicorn — access log + print()
└── web.err.log        # stderr — loguru, exception traceback
```

Folder `logs/` đã trong `.gitignore`. Xoá tự do nếu chiếm dung lượng.

---

## Python lookup priority

Cả 2 script tự dò Python theo thứ tự:

1. `venv\Scripts\python.exe` — nếu project có venv (chưa có ở dev hiện tại)
2. `%LOCALAPPDATA%\Programs\Python\Python313\python.exe` — Python user-install
3. `python` trên PATH — fallback

Nếu cả 3 đều fail, script throw `"Python not found..."`.

Sau này nếu muốn dùng venv:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Script tự pick venv mà không cần sửa.

---

## Troubleshooting

| Lỗi | Nguyên nhân thường gặp |
|---|---|
| `web start FAILED ... port 8000 already in use` | uvicorn cũ chưa stop, hoặc app khác chiếm port. Chạy `.\scripts\web.ps1 status` xem PID. |
| `worker start FAILED ... could not connect to server` | Postgres chưa lên. `docker ps` xem container, `docker compose up -d` để khởi động. |
| `Python not found (looked in venv, AppData Python313, PATH)` | Python chưa cài đúng chỗ. Edit `Find-Python` trong .ps1 thêm path mới. |
| Script tự exit kèm parser error có ký tự lạ | File `.ps1` save bằng UTF-8 nhưng PowerShell 5.1 đọc Windows-1252. Save lại bằng ASCII (chỉ ASCII chars trong string output). |
| Telegram không đến sau Start/Stop/Quét ngay | Web (uvicorn) chưa restart sau khi sửa route → `.\scripts\web.ps1 restart`. |
| `last_run_status` không cập nhật trên web | Worker không chạy → `.\scripts\worker.ps1 status`. Hoặc browser chưa poll mới — HTMX poll mỗi 3s, đợi vài giây. |

---

## Liên quan

- [getting-started.md](./getting-started.md) — overview kiến trúc 5 phase + dev loop.
- [`docker/docker-compose.yml`](../docker/docker-compose.yml) — stack Postgres + Redis + pgadmin.
- [`worker/daemon.py`](../worker/daemon.py) — entrypoint của worker.
- [`web/app.py`](../web/app.py) — entrypoint của FastAPI.
- [`.env.example`](../.env.example) — danh sách env vars cần điền `.env`.
