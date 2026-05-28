#!/usr/bin/env bash
# Defense-in-depth firewall for the TradingBot VPS (Phase 6 slice 0010).
# Binding uvicorn to the tailnet IP already keeps port 8000 off the public
# internet; UFW is the backstop in case that bind config is ever wrong.
#
# Run as root:  sudo bash deploy/ufw-setup.sh
set -euo pipefail

ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp            # SSH
ufw allow in on tailscale0  # everything over the Tailscale interface
ufw --force enable
ufw status verbose
