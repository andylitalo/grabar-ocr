#!/usr/bin/env bash
# Bootstrap k3s on the Ubuntu compute server.
# Run as root or with sudo on the server.
set -euo pipefail

echo "==> Installing k3s (single-node cluster, no Traefik — we use Nginx)"
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik" sh -

echo "==> Waiting for k3s to become ready..."
sleep 10
k3s kubectl get nodes

echo "==> Copying kubeconfig to ~/.kube/config"
mkdir -p ~/.kube
cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
chmod 600 ~/.kube/config

echo "==> Done. Run 'kubectl get nodes' to verify."
