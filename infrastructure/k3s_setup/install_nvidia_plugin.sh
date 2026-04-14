#!/usr/bin/env bash
# Install the NVIDIA device plugin so k3s pods can request GPU resources.
# Requires: NVIDIA drivers + nvidia-container-toolkit already installed on host.
set -euo pipefail

echo "==> Installing NVIDIA Container Toolkit (if not present)"
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/libnvidia-container/gpgkey | apt-key add -
curl -s -L "https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list" \
  | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update && apt-get install -y nvidia-container-toolkit

echo "==> Configuring containerd runtime for NVIDIA"
nvidia-ctk runtime configure --runtime=containerd
systemctl restart containerd

echo "==> Deploying NVIDIA device plugin DaemonSet"
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml

echo "==> Verifying GPU is visible to the cluster"
sleep 15
kubectl get nodes -o json | python3 -c "
import sys, json
nodes = json.load(sys.stdin)['items']
for n in nodes:
    cap = n['status'].get('capacity', {})
    gpu = cap.get('nvidia.com/gpu', '0')
    print(f\"Node {n['metadata']['name']}: {gpu} GPU(s)\")
"
