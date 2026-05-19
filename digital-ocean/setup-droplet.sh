#!/usr/bin/env bash
# Run on the DigitalOcean droplet as root (or via: ssh root@IP 'bash -s' < setup-droplet.sh)
# Installs k3s + Kata Containers (kata-qemu) and proves it with a smoke test.
set -euo pipefail

KATA_RC="${KATA_RC:-kata-qemu}"

echo "==> KVM check"
if [[ ! -e /dev/kvm ]]; then
  echo "ERROR: /dev/kvm missing — Kata/Firecracker will not work on this VM."
  exit 1
fi
ls -l /dev/kvm
egrep -c '(vmx|svm)' /proc/cpuinfo || true

echo "==> k3s"
if ! command -v k3s &>/dev/null; then
  curl -sfL https://get.k3s.io | sh -
fi
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl get nodes

echo "==> helm"
if ! command -v helm &>/dev/null; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

echo "==> Mirror k3s containerd config to /etc/containerd/config.toml (kata-deploy expects it there)"
mkdir -p /etc/containerd
rm -f /etc/containerd/config.toml
if [[ -f /var/lib/rancher/k3s/agent/etc/containerd/config.toml ]]; then
  cp /var/lib/rancher/k3s/agent/etc/containerd/config.toml /etc/containerd/config.toml
fi

echo "==> kata-deploy (official Helm chart — installs binaries to /opt/kata and RuntimeClass CRDs)"
# https://kata-containers.github.io/kata-containers/installation/#helm-chart
VERSION="$(curl -sSL https://api.github.com/repos/kata-containers/kata-containers/releases/latest | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)"
export VERSION
export CHART="oci://ghcr.io/kata-containers/kata-deploy-charts/kata-deploy"
helm upgrade --install kata-deploy "${CHART}" --version "${VERSION}" -n kube-system --create-namespace

echo "==> wait for kata-deploy pod Ready"
kubectl -n kube-system rollout status daemonset/kata-deploy --timeout=600s

echo "==> RuntimeClasses"
kubectl get runtimeclass | grep -E 'NAME|kata'

if ! kubectl get runtimeclass "${KATA_RC}" &>/dev/null; then
  echo "ERROR: RuntimeClass ${KATA_RC} not found."
  exit 1
fi

# kata-deploy on k3s does not wire the runtime into k3s's managed containerd
# (k3s regenerates config.toml on every restart and ignores /etc/containerd/).
# Fix: write a v3 drop-in into k3s's import directory pointing at the kata shim.
echo "==> Write k3s containerd drop-in for kata runtimes"
DROPIN_DIR=/var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.d
mkdir -p "$DROPIN_DIR"
cat > "$DROPIN_DIR/kata.toml" <<'EOF'
[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.kata-qemu]
  runtime_type = "io.containerd.kata-qemu.v2"
  runtime_path = "/opt/kata/bin/containerd-shim-kata-v2"
  privileged_without_host_devices = true
  pod_annotations = ["io.katacontainers.*"]

[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.kata-fc]
  runtime_type = "io.containerd.kata-fc.v2"
  runtime_path = "/opt/kata/bin/containerd-shim-kata-v2"
  privileged_without_host_devices = true
  pod_annotations = ["io.katacontainers.*"]

[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.kata-clh]
  runtime_type = "io.containerd.kata-clh.v2"
  runtime_path = "/opt/kata/bin/containerd-shim-kata-v2"
  privileged_without_host_devices = true
  pod_annotations = ["io.katacontainers.*"]
EOF

echo "==> Restart k3s so containerd reloads with kata drop-in"
systemctl restart k3s
sleep 10
kubectl wait --for=condition=ready node --all --timeout=120s

echo "==> kata smoke test (runtimeClassName=${KATA_RC})"
kubectl delete pod kata-smoke --ignore-not-found --force --grace-period=0 2>/dev/null || true
sleep 3
kubectl run kata-smoke --image=busybox --restart=Never \
  --overrides="{\"spec\":{\"runtimeClassName\":\"${KATA_RC}\"}}" \
  --command -- sh -c 'uname -a; sleep 60'
kubectl wait --for=condition=ready pod/kata-smoke --timeout=180s
echo "==> kata-smoke logs (should show microVM kernel)"
kubectl logs kata-smoke | head -5

echo "==> done — RuntimeClass: ${KATA_RC}"
