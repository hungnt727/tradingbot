# Hướng dẫn deploy lên VPS (venv + systemd)

End-to-end deploy Phase 6 (Web Control Panel) lên 1 VPS Ubuntu/Xubuntu, truy cập qua **Tailscale** (không expose public). Target ~30–45 phút nếu chưa từng làm. Stack DB chạy bằng **Docker Compose** giống dev environment; app (web + worker) chạy bằng **venv + systemd** (path mặc định của PRD).

> File này là **walkthrough có guide** cho lần deploy đầu tiên. Khi đã quen, runbook ngắn gọn ở [`deploy/DEPLOY.md`](../deploy/DEPLOY.md) (10 bước, ~30 phút) là đủ.
>
> **Path thay thế:** [`deploy-docker.md`](./deploy-docker.md) — đóng gói app vào Docker image, chỉ cần `docker compose up -d` (~10 phút). Departure khỏi PRD slice 9 nhưng đơn giản hơn cho multi-VPS / nhanh rollback.

## Dev vs Prod — phân biệt rõ

| | Dev (máy local Windows) | Prod (VPS Linux) |
|---|---|---|
| OS | Windows + PowerShell | Ubuntu/Xubuntu + bash |
| Khởi động service | `scripts\worker.ps1`, `scripts\web.ps1` (xem [scripts.md](./scripts.md)) | systemd: `tradingbot-web.service` + `tradingbot-worker.service` |
| DB stack | Docker Compose | Docker Compose (giống dev) |
| Mạng | localhost | Tailscale tailnet only — không public |
| Code source | thư mục dev | `git clone` vào `/opt/tradingbot` |
| Log | `logs/*.log` | `journalctl -u tradingbot-*` |

**KHÔNG** dùng `scripts/worker.ps1` / `web.ps1` trên VPS — đó là PowerShell + chỉ cho dev. VPS dùng systemd quản lý service.

Quy ước icon trong doc này: 💻 = chạy ở máy local, 🖥️ = SSH vào VPS, 🌐 = browser.

---

## Phase A — Chuẩn bị (trước khi đụng VPS)

### A.1 💻 Commit + push code lên GitHub/GitLab

VPS sẽ `git clone` nên phải có remote sẵn. Đẩy hết work hiện tại:

```powershell
cd D:\Projects\Crypto\TradingBot
git status
git add -A
git commit -m "Phase 6: full ship — auth, telegram, scripts, deploy"
git push origin main
```

Chưa có remote? Tạo private repo bằng GitHub CLI:

```powershell
gh repo create tradingbot --private --source=. --remote=origin --push
```

(`gh auth login` 1 lần đầu nếu cần.)

### A.2 🌐 Tạo Tailscale account (miễn phí, ~5 phút)

1. Vào https://login.tailscale.com → Sign up bằng Google / Microsoft / GitHub.
2. Admin console hiện ra với 0 device — đó là tailnet trống của bạn.
3. **Settings → DNS → bật MagicDNS**. VPS sau khi join sẽ có hostname dạng `tradingbot.tailXXXX.ts.net` thay vì IP `100.x.x.x` thô.
4. Free tier cover 100 device → dư cho 5 user × vài thiết bị.

### A.3 💻 Cài Tailscale client lên máy local

Download installer: https://tailscale.com/download/windows → cài → login cùng account A.2. Đây là device đầu tiên trong tailnet. Sau khi VPS join, máy này truy cập web qua tailnet.

Các collaborator (4 user khác) cũng cài Tailscale + login tailnet của bạn + bạn approve qua admin console.

---

## Phase B — Chuẩn bị VPS

### B.1 🖥️ SSH + tạo user dedicated

```bash
ssh youruser@<vps-public-ip>

# Trên VPS — tạo user 'tradingbot', không dùng root cho service
sudo adduser tradingbot
sudo usermod -aG sudo tradingbot
su - tradingbot
```

### B.2 🖥️ Cài Docker + Docker Compose

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker                                 # apply group ngay không cần logout
docker compose version                        # verify, không lỗi
```

### B.3 🖥️ Cài Python 3.10+ và git

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
python3 --version                             # phải >= 3.10
```

---

## Phase C — Clone + Docker DB stack

### C.1 🖥️ Clone repo vào `/opt/tradingbot`

```bash
sudo mkdir -p /opt/tradingbot
sudo chown tradingbot:tradingbot /opt/tradingbot
git clone https://github.com/<youruser>/tradingbot.git /opt/tradingbot
cd /opt/tradingbot
```

Nếu repo **private**: cần SSH key (`ssh-keygen -t ed25519` → copy `~/.ssh/id_ed25519.pub` vào GitHub Settings → SSH keys) hoặc HTTPS với Personal Access Token.

### C.2 🖥️ Khởi động Postgres + Redis qua Docker Compose

```bash
docker compose -f docker/docker-compose.yml up -d
docker ps                                     # tradingbot_timescaledb + tradingbot_redis phải healthy
```

### C.3 🖥️ Tạo DB `tradingbot_app` + role tách bạch

Adapt từ [`deploy/POSTGRES.md`](../deploy/POSTGRES.md) cho docker:

```bash
docker exec -i tradingbot_timescaledb psql -U postgres <<SQL
CREATE DATABASE tradingbot_app;
CREATE ROLE tradingbot_app_user WITH LOGIN PASSWORD 'CHANGE_THIS_TO_A_STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE tradingbot_app TO tradingbot_app_user;
SQL

docker exec -i tradingbot_timescaledb psql -U postgres -d tradingbot_app <<SQL
GRANT ALL ON SCHEMA public TO tradingbot_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO tradingbot_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO tradingbot_app_user;
SQL
```

> **Ghi nhớ password** `CHANGE_THIS_TO_A_STRONG_PASSWORD` — paste vào `.env` ở D.2.

Tại sao tách role: nếu vulnerability nào đó cho phép SQL injection, role `tradingbot_app_user` chỉ truy cập được `tradingbot_app` — KHÔNG động được DB OHLCV `tradingbot` hay bất kỳ DB nào khác trên cùng instance.

---

## Phase D — venv + migrations + config

### D.1 🖥️ Tạo venv + install deps

```bash
cd /opt/tradingbot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### D.2 🖥️ Tạo `.env` từ template

```bash
cp .env.production.example .env
nano .env
```

Phải set 6 biến (template có comment giải thích từng cái):

| Biến | Giá trị |
|---|---|
| `DATABASE_URL` | giữ nguyên `postgresql://postgres:postgres@localhost:5432/tradingbot` |
| `APP_DATABASE_URL` | `postgresql://tradingbot_app_user:CHANGE_THIS_TO_A_STRONG_PASSWORD@localhost:5432/tradingbot_app` (dùng password ở C.3) |
| `REDIS_URL` | giữ nguyên `redis://localhost:6379/0` |
| `SESSION_SECRET_KEY` | generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `TELEGRAM_BOT_TOKEN` | token thật từ BotFather |
| `COINMARKETCAP_API_KEY` | key từ https://coinmarketcap.com/api/ |
| `WORKER_SLEEP_SECONDS` | mặc định 10 — giữ nếu không có lý do đổi |

### D.3 🖥️ Apply migrations cả 2 DB

```bash
source venv/bin/activate
alembic upgrade head                          # OHLCV DB — tới 004 (head)
alembic -c alembic_app.ini upgrade head       # app DB — tới 002 (head)
```

Verify cả 2 lên đúng:

```bash
alembic current                               # 004 (head)
alembic -c alembic_app.ini current            # 002 (head)
```

### D.4 🖥️ Bootstrap admin đầu tiên

```bash
python scripts/create_admin.py
# nhập username + password (qua getpass, không lưu shell history)
# user này là login đầu tiên trên web
```

---

## Phase E — Tailscale + systemd + firewall

### E.1 🖥️ Cài + join Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                             # in ra URL — paste vào browser, login + approve VPS
tailscale ip -4                               # ghi lại IP dạng 100.x.x.x
```

Nếu enable MagicDNS ở A.2, admin console giờ thấy VPS với hostname `<vpsname>.tailXXXX.ts.net` — dùng được thay cho IP.

### E.2 🖥️ Cập nhật tailnet IP vào systemd unit

```bash
nano deploy/systemd/tradingbot-web.service
```

Tìm dòng `ExecStart=... --host 100.x.x.x ...`, thay `100.x.x.x` bằng IP ở E.1. Đây là bind quan trọng: nếu để `0.0.0.0` thì uvicorn lắng nghe public — không an toàn (dù UFW chặn). Tailnet IP đảm bảo defense-in-depth.

### E.3 🖥️ Cài + enable systemd services

```bash
sudo cp deploy/systemd/tradingbot-web.service /etc/systemd/system/
sudo cp deploy/systemd/tradingbot-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tradingbot-web tradingbot-worker
sudo systemctl status tradingbot-web tradingbot-worker     # cả 2 phải "active (running)"
```

`Restart=always` trong unit → service tự khởi động lại nếu crash. `WantedBy=multi-user.target` → auto-start sau reboot VPS.

### E.4 🖥️ Firewall — defense-in-depth

```bash
sudo bash deploy/ufw-setup.sh
sudo ufw status verbose
```

Script chạy: `default deny incoming` + `allow 22/tcp` (SSH) + `allow in on tailscale0` (mọi traffic qua tailnet). Public internet hoàn toàn bị chặn cổng 8000 dù uvicorn có bị misconfig.

---

## Phase F — Verify

### F.1 🌐 Truy cập web từ máy local (đã join tailnet ở A.3)

Mở browser:
```
http://<tailnet-ip>:8000
# hoặc nếu MagicDNS bật:
http://<vpsname>.tailXXXX.ts.net:8000
```

Login với admin tạo ở D.4 → trang `/processes` rỗng. Tạo Process EMARSI1 (Top 100, binance, 60m) → set Telegram chat ID (Settings) → Start → click "Quét ngay". Confirm trong vài giây:

- 🔍 Telegram nhận `Đã yêu cầu quét — EMARSI1`.
- Badge `idle → running → OK` qua HTMX polling 3s.
- ✅ Telegram nhận `Quét xong — EMARSI1 / Tín hiệu mới: N`.

### F.2 🖥️ Xem log live

```bash
journalctl -u tradingbot-web -f               # uvicorn access log
journalctl -u tradingbot-worker -f            # worker tick + scan + telegram
```

`Ctrl+C` để thoát mà không ảnh hưởng service.

### F.3 🌐 Public-access isolation check (quan trọng)

Từ máy **không trên tailnet** (data 4G điện thoại / VPS khác):

```bash
curl --max-time 5 http://<vps-public-ip>:8000
# Phải: "Connection refused" hoặc timeout
# Nếu trả về HTML login page → SAI, đang expose public — kiểm tra E.2 (host bind) + E.4 (UFW)
```

---

## Operate hằng ngày

```bash
# Logs
journalctl -u tradingbot-web -f
journalctl -u tradingbot-worker -f

# Restart sau khi pull code
sudo systemctl restart tradingbot-web tradingbot-worker

# Status
sudo systemctl status tradingbot-web tradingbot-worker

# Stop/start riêng từng cái
sudo systemctl stop tradingbot-worker
sudo systemctl start tradingbot-worker

# DB stack
docker ps                                     # confirm timescaledb + redis healthy
docker compose -f docker/docker-compose.yml restart   # restart DB stack
```

---

## Cập nhật code sau khi deploy

```bash
cd /opt/tradingbot
git pull
source venv/bin/activate
pip install -r requirements.txt               # nếu requirements.txt đổi
alembic upgrade head                          # nếu có migration mới (OHLCV DB)
alembic -c alembic_app.ini upgrade head       # nếu có migration mới (app DB)
sudo systemctl restart tradingbot-web tradingbot-worker
journalctl -u tradingbot-worker -f            # verify worker tick lại OK
```

---

## Gotcha cần biết

- **Collaborator tailnet access**: 4 user kia phải có account Tailscale → login cùng tailnet → bạn approve qua admin console. Free tier 100 device.
- **Backup DB**: docker volume `timescaledb_data` persist sau restart container. Backup periodic:
  ```bash
  docker exec tradingbot_timescaledb pg_dump -U postgres tradingbot_app > backup_$(date +%F).sql
  ```
- **Reboot test**: sau Phase E, chạy `sudo reboot`. Đợi ~2 phút rồi truy cập web — cả 2 service phải tự lên (docker restart unless-stopped + systemd `Restart=always` + `WantedBy=multi-user.target`).
- **Secret rotation**: `SESSION_SECRET_KEY` đổi không ảnh hưởng session (session là opaque UUID trong Redis, không signed). `TELEGRAM_BOT_TOKEN` đổi → mọi user phải `/start` lại bot mới — báo trước trên Slack/Telegram.
- **Disk space**: log Postgres + logs journald có thể phình. Thiết lập:
  ```bash
  sudo journalctl --vacuum-time=14d           # giữ 14 ngày journald
  ```
- **Free tier giới hạn**: CMC API 10,000 call/tháng (Phase 6 cache 1h → ~720 call/tháng, dư xa). Tailscale 100 device. Telegram bot không giới hạn message thường.
- **Out of scope v1**: monitoring (Prometheus/Grafana), backup tự động, alerting khi service down, multi-instance load balancing. Nếu cần, thêm sau khi production stable.

---

## Liên quan

- [`deploy/DEPLOY.md`](../deploy/DEPLOY.md) — runbook ngắn gọn 10 bước (khi đã quen).
- [`deploy/POSTGRES.md`](../deploy/POSTGRES.md) — chi tiết Postgres + role permissions.
- [`deploy/TAILSCALE.md`](../deploy/TAILSCALE.md) — chi tiết Tailscale setup + Magic DNS.
- [`deploy/systemd/`](../deploy/systemd/) — 2 unit file (web + worker).
- [`deploy/ufw-setup.sh`](../deploy/ufw-setup.sh) — script firewall.
- [`scripts.md`](./scripts.md) — quản lý service ở **dev** (Windows + PowerShell), không dùng trên VPS.
- [`getting-started.md`](./getting-started.md) — overview kiến trúc + dev environment.
- [`.env.production.example`](../.env.production.example) — template `.env` cho production.
