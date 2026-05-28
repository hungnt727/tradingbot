# Tailscale setup — private access, no public exposure

The web app is reachable only over the Tailscale tailnet. There is no public
port, no domain, and no HTTPS in code (Tailscale encrypts the tunnel).

## 1. VPS

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Approve the VPS in the Tailscale admin console (https://login.tailscale.com).
Get its tailnet IP:

```bash
tailscale ip -4        # e.g. 100.101.102.103
```

Put that IP into `deploy/systemd/tradingbot-web.service` (`--host 100.x.x.x`).

## 2. Magic DNS (optional but nicer)

Enable **MagicDNS** in the admin console → the VPS gets a hostname like
`tradingbot.tailXXXX.ts.net`. You can then use the hostname instead of the raw
`100.x.x.x` in the unit file and in the browser.

## 3. Each user device

Every collaborator installs the Tailscale client (laptop/phone), logs into the
**same tailnet**, and gets approved. They then open:

```
http://100.x.x.x:8000          # or http://tradingbot.tailXXXX.ts.net:8000
```

Free tier covers 100 devices — ample for 5 users × a few devices.

## Verify isolation

From a machine **not** on the tailnet, `curl http://<vps-public-ip>:8000`
should time out / be refused. From a tailnet device it should return the login
page.
