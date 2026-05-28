---
id: "0010"
title: Tailscale + systemd deployment
status: artifacts-ready-for-human
type: HITL
blocked_by: ["0009"]
covers_user_stories: ["#44", "#45", "#46", "#47", "#50"]
prd: ../PRD.md
plan: ../../../docs/WEB_CONTROL_PANEL_PLAN.md
---

# 0010 — Tailscale + systemd deployment

## What to build

Production deploy lên VPS qua Tailscale. **HITL** vì cần operator có quyền SSH + admin Tailscale console + sudo trên VPS.

- 2 systemd unit files trong repo (vd `deploy/systemd/`):
  - `tradingbot-web.service` (theo PRD section 8.1).
  - `tradingbot-worker.service` (theo PRD section 8.1).
- UFW config script `deploy/ufw-setup.sh`:
  ```
  ufw default deny incoming
  ufw allow 22/tcp
  ufw allow in on tailscale0
  ufw enable
  ```
- `.env.production.example` — template với placeholder cho VPS:
  - `APP_DATABASE_URL=postgresql://tradingbot_app_user:CHANGE_ME@localhost:5432/tradingbot_app`
  - `SESSION_SECRET_KEY=CHANGE_ME_TO_RANDOM_64_CHAR`
  - `TELEGRAM_BOT_TOKEN=...`
  - `COINMARKETCAP_API_KEY=...`
- Tailscale setup doc `deploy/TAILSCALE.md`:
  - Install Tailscale daemon trên VPS (`curl ... | sh`).
  - `tailscale up` → admin approve VPS trong console.
  - Mỗi user device: install Tailscale client, login cùng tailnet.
  - Magic DNS: enable trong Tailscale admin console → VPS có hostname `<vps-name>.tailxxx.ts.net`.
  - Update `tradingbot-web.service` ExecStart với hostname hoặc tailnet IP.
- Postgres setup doc `deploy/POSTGRES.md`:
  - `CREATE DATABASE tradingbot_app;`
  - `CREATE ROLE tradingbot_app_user WITH LOGIN PASSWORD '...';`
  - `GRANT ALL ON DATABASE tradingbot_app TO tradingbot_app_user;` (hoặc grant tách bạch hơn).
  - `alembic -c alembic_app.ini upgrade head`.
- Deploy runbook `deploy/DEPLOY.md` — step-by-step từ git clone đến web accessible:
  1. SSH vào VPS, clone repo, `python -m venv venv`, `pip install -r requirements.txt`.
  2. Setup Postgres role + DB (POSTGRES.md).
  3. Setup Tailscale (TAILSCALE.md).
  4. Copy `.env.production.example` → `.env`, điền secret.
  5. Run alembic migrations cho cả 2 DB.
  6. Run `python scripts/create_admin.py`.
  7. Copy systemd unit files vào `/etc/systemd/system/`.
  8. `systemctl enable --now tradingbot-web tradingbot-worker`.
  9. Run UFW script.
  10. Verify từ phone qua Tailscale.

## Acceptance criteria

- [ ] Systemd unit files validate (`systemd-analyze verify *.service`).
- [ ] `tradingbot-web.service` start được, bind đúng tailnet IP (verify `ss -tlnp | grep 8000`).
- [ ] `tradingbot-worker.service` start được, log `worker started` trong journald.
- [ ] Reboot VPS → cả 2 service auto-up.
- [ ] Web truy cập được từ phone (Tailscale client active) qua Magic DNS hostname.
- [ ] Web KHÔNG truy cập được từ public IP của VPS (`curl http://<public-ip>:8000` từ máy ngoài tailnet → timeout / connection refused).
- [ ] UFW status: chỉ allow 22 + interface tailscale0.
- [ ] Existing `cli/start_scheduler.py` KHÔNG chạy (verify `systemctl list-units | grep tradingbot` — chỉ thấy web + worker, không có scheduler).
- [ ] Logs flow vào journald: `journalctl -u tradingbot-web -f` thấy request log; `journalctl -u tradingbot-worker -f` thấy scan log.
- [ ] Deploy runbook executable end-to-end bởi operator mới (test: fresh VPS, làm theo runbook → web up trong < 30 phút).

## Notes for the operator

- **Pre-flight check**: VPS phải có Postgres + Redis đang chạy (từ docker-compose stack existing). Verify trước khi deploy web/worker.
- **Backup strategy** out of scope cho v1 — manual `pg_dump tradingbot_app` định kỳ là đủ. v2 thêm cron + offsite.
- **Monitoring** out of scope — `journalctl` là log source duy nhất. v2 có thể thêm Grafana/Loki nếu cần.
- **Secret rotation**: `SESSION_SECRET_KEY` đổi → tất cả user phải login lại (Redis sessions invalidated). `TELEGRAM_BOT_TOKEN` đổi → mọi user phải /start lại với bot mới — communicate trước.

## Blocked by

- 0009 (feature complete — deploy production cần all features tested locally)
