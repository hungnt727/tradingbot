# Deploy web tín hiệu lên VPS — Quickstart (hungnt727 · Docker · Tailscale)

Runbook copy-paste cho **đúng** cấu hình của bạn:

- Repo: `github.com/hungnt727/tradingbot` (**public** → image GHCR pull không cần auth)
- Image: `ghcr.io/hungnt727/tradingbot:latest` (đã điền sẵn trong `docker/docker-compose.prod.yml`)
- VPS: **Ubuntu, 4GB RAM, 2 CPU**
- Truy cập web: **Tailscale** (web bind `127.0.0.1`, không expose public)

> Icon: 💻 = máy local Windows · 🖥️ = SSH vào VPS · 🌐 = browser.
> Chi tiết/biến thể xem [`deploy-docker.md`](./deploy-docker.md). File này là path tối giản 1 chiều.

---

## ⚠️ Trước khi bắt đầu — commit & push code mới nhất

CI **chỉ build image từ những gì đã có trên nhánh `main`**. Working tree hiện đang có nhiều file chưa commit (`web/`, `worker/`, `strategies/`, ...). Nếu không push, image trên VPS sẽ **thiếu** các thay đổi mới.

### 0. 💻 Trên máy local (PowerShell)

```powershell
cd D:\Projects\Crypto\TradingBot
git status                      # xem lại thứ sắp commit
git add -A
git commit -m "Deploy: set GHCR owner + latest web control changes"
git push origin main
```

> Lưu ý đừng vô tình commit `.env` thật (đã gitignore). Kiểm tra `git status` trước khi `add -A`.

---

## Phase A — Build & publish image (tự động, ~3–5 phút)

### A.1 🌐 Verify CI build pass

Sau khi push, vào `https://github.com/hungnt727/tradingbot/actions` → workflow **"Build & publish Docker image"** phải xanh ✅.

### A.2 🌐 Đặt package image thành Public

Vào `https://github.com/hungnt727/tradingbot/pkgs/container/tradingbot` → **Package settings** → **Change visibility** → **Public**.

> Bước này giúp VPS `docker pull` không cần đăng nhập. (Repo public không tự động làm package public — phải set riêng.)

Xác nhận image tồn tại: tag `latest` + `sha-<short>`.

---

## Phase B — Chuẩn bị VPS

### B.1 🖥️ SSH vào VPS, tạo user riêng (không chạy bằng root)

```bash
adduser tradingbot
usermod -aG sudo tradingbot
su - tradingbot
```

### B.2 🖥️ Tạo swap 2GB (an toàn cho 4GB RAM)

Worker quét Top 300 bằng pandas có thể ngốn RAM theo đợt. Swap giúp tránh OOM-kill.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h                                   # xác nhận Swap: 2.0Gi
```

### B.3 🖥️ Cài Docker + Compose plugin

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Đăng xuất rồi SSH lại để nhóm docker có hiệu lực
exit
```

SSH lại, kiểm tra:

```bash
docker --version && docker compose version
docker run --rm hello-world               # xác nhận chạy không cần sudo
```

---

## Phase C — Deploy stack

### C.1 🖥️ Cài Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                         # mở URL in ra → login → approve VPS
tailscale ip -4                           # ghi lại IP 100.x.x.x
tailscale status                          # xác nhận VPS online trong tailnet
```

> Máy bạn (laptop/PC) cũng phải cài Tailscale và join cùng tailnet để truy cập web.

### C.2 🖥️ Lấy compose file + env template

```bash
sudo mkdir -p /opt/tradingbot && sudo chown $USER /opt/tradingbot
cd /opt/tradingbot

curl -O https://raw.githubusercontent.com/hungnt727/tradingbot/main/docker/docker-compose.prod.yml
curl -O https://raw.githubusercontent.com/hungnt727/tradingbot/main/.env.production.example
mv .env.production.example .env
```

> `image:` trong compose đã trỏ sẵn `ghcr.io/hungnt727/tradingbot:latest` — **không cần sửa**.

### C.3 🖥️ Điền `.env` (chỉ 4 biến)

`DATABASE_URL` / `APP_DATABASE_URL` / `REDIS_URL` bị compose override (trỏ tới service trong docker network) → **xoá hoặc bỏ qua**, đừng điền. Chỉ cần:

```bash
# Tạo session key (chạy ngay trên VPS cũng được):
python3 -c "import secrets; print(secrets.token_hex(32))"

nano .env
```

| Biến | Giá trị |
|---|---|
| `SESSION_SECRET_KEY` | dán chuỗi 64 hex vừa tạo |
| `TELEGRAM_BOT_TOKEN` | token từ BotFather (cùng bot bạn đang dùng) |
| `COINMARKETCAP_API_KEY` | key từ coinmarketcap.com/api |
| `WORKER_SLEEP_SECONDS` | để `10` |

### C.4 🖥️ Pull image + bring up

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps      # 4 container; web phải "healthy" sau ~30s
```

### C.5 🖥️ Migrations (cả 2 DB) + tạo admin

```bash
docker compose -f docker-compose.prod.yml exec web alembic upgrade head
docker compose -f docker-compose.prod.yml exec web alembic -c alembic_app.ini upgrade head
docker compose -f docker-compose.prod.yml exec web python scripts/create_admin.py
```

`create_admin.py` hỏi username + password (interactive) → đây là tài khoản đăng nhập web.

### C.6 🖥️ Expose web qua Tailscale (HTTPS tự động)

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
sudo tailscale serve status               # xác nhận đang serve
```

---

## Phase D — Verify

### D.1 🌐 Truy cập web

Trên máy local (đã join tailnet), mở:

```
https://<tên-vps>.tailXXXX.ts.net        # MagicDNS
# hoặc: https://100.x.x.x
```

Login bằng admin ở C.5 → tạo lại các process (VolumeBreakout1, EmaRsi_DH, ...) → bấm **"Quét ngay"** → xác nhận Telegram nhận tín hiệu 🔍.

### D.2 🖥️ Xem log

```bash
docker compose -f docker-compose.prod.yml logs -f web       # uvicorn
docker compose -f docker-compose.prod.yml logs -f worker    # tick + scan
```

### D.3 🌐 Kiểm tra KHÔNG lộ public

Từ một mạng ngoài tailnet (vd điện thoại 4G):

```bash
curl --max-time 5 http://<public-ip-vps>:8000     # phải: refused / timeout
```

---

## Vận hành hằng ngày

```bash
cd /opt/tradingbot
COMPOSE="docker compose -f docker-compose.prod.yml"

$COMPOSE ps                      # trạng thái
$COMPOSE logs -f worker          # theo dõi worker
$COMPOSE restart web             # restart 1 service
$COMPOSE stop                    # dừng
$COMPOSE down                    # tear down (GIỮ data)
```

### Cập nhật code sau khi push mới

```bash
cd /opt/tradingbot
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker image prune -f
# Nếu có migration mới:
docker compose -f docker-compose.prod.yml exec web alembic upgrade head
docker compose -f docker-compose.prod.yml exec web alembic -c alembic_app.ini upgrade head
```

### Backup DB (khuyến nghị cron 3h sáng)

```bash
docker exec tradingbot_timescaledb pg_dump -U postgres tradingbot_app > app-$(date +%F).sql
```

---

## Ghi chú RAM 4GB

- 4 container + pandas/ccxt khi quét Top 300 là điểm nóng RAM. Swap 2GB ở B.2 là lưới an toàn.
- Nếu thấy worker bị OOM-kill (`docker compose logs worker` thấy chết đột ngột, `dmesg | grep -i oom`): cân nhắc giảm số process chạy song song, hoặc giảm số symbol (Top 150 thay vì Top 300), hoặc nâng VPS lên 8GB.
- Theo dõi RAM: `docker stats` (xem cột MEM USAGE từng container).
- *Chưa* đặt mem-limit trong compose (giữ nguyên file gốc). Nếu muốn giới hạn cứng cho từng service, báo tôi — sẽ thêm `deploy.resources.limits` (cần xác nhận vì đụng file đã backtest/chuẩn).

---

## Khi kẹt — dán lại cho tôi

Nếu bước nào lỗi, dán output của lệnh đó + `docker compose -f docker-compose.prod.yml logs --tail=50` vào chat, tôi debug tiếp.
