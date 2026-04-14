#!/usr/bin/env bash
# Install and bring up Tailscale on the Ubuntu server.
set -euo pipefail

echo "==> Installing Tailscale"
curl -fsSL https://tailscale.com/install.sh | sh

echo "==> Starting Tailscale (you will be prompted to authenticate)"
tailscale up --advertise-routes=10.0.0.0/24

echo "==> Tailscale IP:"
tailscale ip -4
