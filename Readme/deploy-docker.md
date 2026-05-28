# Deploy lên VPS bằng Docker (pull & compose up)

Path deploy ngắn hơn — chỉ cần `docker compose up -d` trên VPS, không cần `git clone`, không cần venv, không cần systemd. Target **~10 phút** sau khi VPS có Docker.

Đây là **alternative** cho [deploy.md](./deploy.md) (venv + systemd). Cả hai cùng tồn tại; chọn 1 path. So sánh nhanh:

| | Docker (file này) | venv + systemd ([deploy.md](./deploy.md)) |
|---|---|---|
| Thời gian deploy | ~10 phút | ~30–45 phút |
| Cần `git clone` trên VPS | ❌ Không | ✅ Có |
| Python trên VPS | Image-pinned (3.13) | system Python |
| Update code | `docker compose pull && up -d` | `git pull && pip install && systemctl restart` |
| Image size overhead | ~400MB app + ~200MB DB | ~50MB venv |
| Multi-VPS / rollback | Dễ (tag image) | Khó (git checkout SHA) |
| Phù hợp PRD slice 9 | ❌ Departure | ✅ Đúng |

> Quy ước icon: 💻 = máy local Windows, 🖥️ = SSH vào VPS, 🌐 = browser.

---

## Phase A — Setup CI publish image (1 lần / repo)

### A.1 💻 Push code + workflow lên GitHub

Workflow `.github/workflows/docker-publish.yml` đã sẵn — push code là tự build + publish image lên **GHCR** (GitHub Container Registry, free cho private repo).

```powershell
cd D:\Projects\Crypto\TradingBot
git add -A
git commit -m "Add Docker deploy path"
git push origin main
```

### A.2 🌐 Verify image đã publish

Vào GitHub repo → tab **Actions** → check workflow "Build & publish Docker image" pass. Sau đó tab **Packages** (cột phải) → thấy `tradingbot` package với tag `latest` + `sha-<short>`.

Image URL: `ghcr.io/<owner>/tradingbot:latest`.

### A.3 🌐 (Nếu repo private) Make image pullable on VPS

GHCR theo mặc định image của private repo cũng private — pull cần auth. 2 options:

- **A. Make image public**: vào package settings → Change package visibility → Public. Image vẫn không expose code (chỉ artifact built). Đơn giản nhất.
- **B. Keep private + PAT**: tạo Personal Access Token (Settings → Developer settings → Personal access tokens → `read:packages`). Trên VPS: `echo <PAT> | docker login ghcr.io -u <username> --password-stdin`.

Khuyến nghị A trừ khi image chứa secret hardcoded (KHÔNG NÊN có — secret đi qua .env).

---

## Phase B — Chuẩn bị VPS (giống deploy.md)

Xem [deploy.md Phase A.2, A.3, B.1, B.2](./deploy.md#phase-a--chuẩn-bị-trước-khi-đụng-vps) cho:
- Tạo Tailscale account.
- Cài Tailscale client máy local.
- SSH vào VPS, tạo user `tradingbot`.
- Cài Docker + Docker Compose.

Khác biệt với deploy.md: **KHÔNG cần** cài Python, không cần venv, không cần `git clone` source.

---

## Phase C — Deploy

### C.1 🖥️ Cài Tailscale trên VPS

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                             # paste URL → login → approve VPS
tailscale ip -4                               # ghi lại IP 100.x.x.x
```

### C.2 🖥️ Tạo thư mục deploy + lấy 2 file cấu hình

```bash
sudo mkdir -p /opt/tradingbot && sudo chown $USER /opt/tradingbot
cd /opt/tradingbot

# Lấy compose file + env template từ repo (raw GitHub URL)
curl -O https://raw.githubusercontent.com/<owner>/tradingbot/main/docker/docker-compose.prod.yml
curl -O https://raw.githubusercontent.com/<owner>/tradingbot/main/.env.production.example
mv .env.production.example .env
```

> Replace `<owner>` bằng GitHub username/org của bạn.

### C.3 🖥️ Sửa compose + điền `.env`

```bash
nano docker-compose.prod.yml
# Tìm 2 dòng `image: ghcr.io/CHANGE_ME/tradingbot:latest`
# Thay CHANGE_ME thành GitHub username của bạn.

nano .env
```

Trong `.env`, **chỉ điền 3 secret** (DB/Redis URL được hardcode trong compose, đừng động):

| Biến | Giá trị |
|---|---|
| `SESSION_SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` từ máy local |
| `TELEGRAM_BOT_TOKEN` | từ BotFather |
| `COINMARKETCAP_API_KEY` | từ https://coinmarketcap.com/api/ |
| `WORKER_SLEEP_SECONDS` | giữ `10` |

Các biến `DATABASE_URL` / `APP_DATABASE_URL` / `REDIS_URL` trong `.env` sẽ bị **compose override** (point tới docker service name), nên có hay không không quan trọng — nhưng nên xoá để không gây nhầm lẫn.

### C.4 🖥️ Pull image + bring up stack

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps          # 4 container, web phải "healthy"
```

Lần đầu sẽ mất ~30s vì timescaledb cần init data dir và web đợi DB healthy.

### C.5 🖥️ Migrations cả 2 DB + bootstrap admin

```bash
docker compose -f docker-compose.prod.yml exec web alembic upgrade head
docker compose -f docker-compose.prod.yml exec web alembic -c alembic_app.ini upgrade head
docker compose -f docker-compose.prod.yml exec web python scripts/create_admin.py
```

`create_admin.py` interactive prompt cho username + password.

### C.6 🖥️ Expose web qua Tailscale (KHÔNG bind public)

Web container chỉ bind `127.0.0.1:8000` trên host (loopback). Để truy cập từ tailnet:

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
```

Giờ truy cập `https://<vpsname>.tailXXXX.ts.net` (MagicDNS) hoặc `https://<tailnet-ip>` từ device tailnet → HTTPS tự động bởi Tailscale (cert miễn phí cho mọi tailnet device).

> Tại sao không bind `0.0.0.0:8000`? → expose public, không an toàn. Tại sao không bind `100.x.x.x:8000`? → tailnet IP có thể đổi (DHCP-style); tailscale serve trừu tượng hoá việc đó + tự cấp HTTPS.

### C.7 🖥️ UFW (defense-in-depth, optional nhưng khuyến nghị)

Docker tự thêm iptables rule có thể bypass UFW. Cách an toàn:

```bash
sudo bash -c 'echo "{\"iptables\": false}" > /etc/docker/daemon.json'
sudo systemctl restart docker
sudo ufw default deny incoming
sudo ufw allow 22/tcp
sudo ufw allow in on tailscale0
sudo ufw --force enable
```

> Nếu set `iptables: false`, container-to-container communication vẫn OK (Docker dùng internal bridge), nhưng container bind to host port phải đi qua proxy. Stack hiện tại CHỈ bind 127.0.0.1 → không ảnh hưởng.

---

## Phase D — Verify

### D.1 🌐 Truy cập web

Mở browser trên máy local (đã join tailnet):
```
https://<vpsname>.tailXXXX.ts.net
# hoặc IP: https://<tailnet-ip>
```

Login với admin tạo ở C.5 → tạo Process EMARSI1 → click "Quét ngay" → confirm Telegram nhận 🔍 → ✅.

### D.2 🖥️ Xem log container

```bash
docker compose -f docker-compose.prod.yml logs -f web        # uvicorn access
docker compose -f docker-compose.prod.yml logs -f worker     # worker tick + scan
docker compose -f docker-compose.prod.yml logs -f --tail=50  # tất cả service
```

### D.3 🌐 Public-access isolation check

Từ máy ngoài tailnet:
```bash
curl --max-time 5 http://<vps-public-ip>:8000
# Phải: connection refused / timeout
curl --max-time 5 https://<vps-public-ip>
# Phải: connection refused / timeout (tailscale serve không expose public)
```

---

## Operate hằng ngày

```bash
cd /opt/tradingbot

# Logs
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs -f worker

# Restart 1 service
docker compose -f docker-compose.prod.yml restart web
docker compose -f docker-compose.prod.yml restart worker

# Restart tất cả
docker compose -f docker-compose.prod.yml restart

# Status
docker compose -f docker-compose.prod.yml ps

# Stop all
docker compose -f docker-compose.prod.yml stop

# Tear down (giữ volume DB data)
docker compose -f docker-compose.prod.yml down

# Nuke everything (XÓA DB volume! cẩn thận)
docker compose -f docker-compose.prod.yml down -v
```

---

## Cập nhật code

Mỗi lần code push lên `main`, CI tự build image mới. Trên VPS chỉ:

```bash
cd /opt/tradingbot
docker compose -f docker-compose.prod.yml pull       # tải image latest mới
docker compose -f docker-compose.prod.yml up -d      # recreate container web + worker
docker image prune -f                                # dọn image cũ
```

Nếu có migration mới:
```bash
docker compose -f docker-compose.prod.yml exec web alembic upgrade head
docker compose -f docker-compose.prod.yml exec web alembic -c alembic_app.ini upgrade head
```

Image với git SHA cũng được tag (vd `sha-a1b2c3d`) → muốn rollback:
```bash
# Sửa compose: image: ghcr.io/<owner>/tradingbot:sha-a1b2c3d
docker compose -f docker-compose.prod.yml up -d
```

---

## Backup

```bash
# Postgres dump (cả 2 DB)
docker exec tradingbot_timescaledb pg_dump -U postgres tradingbot     > backup-ohlcv-$(date +%F).sql
docker exec tradingbot_timescaledb pg_dump -U postgres tradingbot_app > backup-app-$(date +%F).sql

# Restore (DB phải tồn tại trước)
docker exec -i tradingbot_timescaledb psql -U postgres tradingbot_app < backup-app-2026-05-30.sql
```

Cron daily backup (trên VPS):
```bash
0 3 * * * cd /opt/tradingbot && docker exec tradingbot_timescaledb pg_dump -U postgres tradingbot_app > /backup/app-$(date +\%F).sql
```

---

## Gotcha

- **Image private + VPS không login GHCR**: `docker compose pull` báo `unauthorized` → quay lại Phase A.3.
- **Bind 0.0.0.0 nhầm**: nếu sửa `ports:` trong compose thành `"0.0.0.0:8000:8000"` (hoặc bỏ host prefix → mặc định 0.0.0.0) → web expose public. UFW + Docker iptables = 1 rule conflict thường gặp.
- **Tailscale serve sau reboot**: `tailscale serve` config tự khôi phục sau reboot (Tailscale lưu state). Nếu mất, chạy lại C.6.
- **Migration cần image có code mới**: nếu `alembic upgrade head` thấy không có revision mới → check image tag có đúng `latest` không (`docker compose images`).
- **Worker không có HTTP healthcheck**: chỉ web có. Worker alive check qua `docker compose ps` + log.
- **DB connection refused lần đầu**: timescaledb cần ~15s init. Compose `depends_on: condition: service_healthy` đã handle, nhưng nếu manually start service riêng (`docker compose up web` không kèm timescaledb), có thể fail. Luôn `up -d` cả stack.
- **Image lớn hơn dev**: ~600MB nén vì có pandas, numpy, ccxt. Bình thường. Nếu cần nhỏ hơn, multi-stage build với `--no-deps` + strip test deps.

---

## Liên quan

- [`Dockerfile`](../Dockerfile) — build definition (multi-stage, non-root).
- [`docker/docker-compose.prod.yml`](../docker/docker-compose.prod.yml) — 4-service stack.
- [`.github/workflows/docker-publish.yml`](../.github/workflows/docker-publish.yml) — CI build + push GHCR.
- [`.dockerignore`](../.dockerignore) — file blacklist cho `COPY .`.
- [`deploy.md`](./deploy.md) — path venv + systemd (alternative).
- [`scripts.md`](./scripts.md) — quản lý service ở dev (PowerShell).
