# Deploy runbook — TradingBot Web Control Panel (Phase 6)

End-to-end, fresh VPS → web reachable over Tailscale. **HITL**: needs SSH +
sudo + Tailscale admin access. Target ~30 minutes.

> Pre-flight: Postgres and Redis must already be running (the existing
> `docker/` compose stack or system services). Verify before starting.

## Steps

1. **Clone + venv**
   ```bash
   sudo mkdir -p /opt/tradingbot && sudo chown $USER /opt/tradingbot
   git clone <repo> /opt/tradingbot && cd /opt/tradingbot
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Postgres** — create DB + role, see [POSTGRES.md](./POSTGRES.md).

3. **Tailscale** — install + `tailscale up`, get the tailnet IP, see
   [TAILSCALE.md](./TAILSCALE.md).

4. **Config**
   ```bash
   cp .env.production.example .env
   # edit .env: APP_DATABASE_URL password, SESSION_SECRET_KEY, TELEGRAM_BOT_TOKEN,
   # COINMARKETCAP_API_KEY
   ```

5. **Migrations** (both DBs)
   ```bash
   alembic upgrade head
   alembic -c alembic_app.ini upgrade head
   ```

6. **Bootstrap the first admin**
   ```bash
   python scripts/create_admin.py
   ```

7. **systemd units** — set the tailnet IP in
   `deploy/systemd/tradingbot-web.service`, then:
   ```bash
   sudo cp deploy/systemd/tradingbot-web.service /etc/systemd/system/
   sudo cp deploy/systemd/tradingbot-worker.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now tradingbot-web tradingbot-worker
   ```

8. **Firewall**
   ```bash
   sudo bash deploy/ufw-setup.sh
   ```

9. **Disable the legacy scheduler** — the worker replaces
   `cli/start_scheduler.py`; make sure no unit runs it:
   ```bash
   systemctl list-units | grep -i tradingbot   # expect only web + worker
   ```

10. **Verify from a phone** on the tailnet: open
    `http://<tailnet-ip-or-magicdns>:8000`, log in, create a process, click
    "Quét ngay", confirm the status badge goes running → OK within ~30s.

## Operate

```bash
journalctl -u tradingbot-web -f       # request logs
journalctl -u tradingbot-worker -f    # scan logs
sudo systemctl restart tradingbot-web tradingbot-worker
```

## Notes

- **Reboot test**: `sudo reboot`; both services should auto-start
  (`WantedBy=multi-user.target` + `Restart=always`).
- **Public-access check**: from off-tailnet, `curl http://<public-ip>:8000`
  must fail (timeout/refused).
- **Secret rotation**: changing `SESSION_SECRET_KEY` is harmless to sessions
  (they are opaque Redis keys, not signed) but a `TELEGRAM_BOT_TOKEN` change
  means every user must `/start` the new bot — communicate first.
- **Backups / monitoring**: out of scope for v1. Periodic
  `pg_dump tradingbot_app` is enough; `journalctl` is the only log source.
