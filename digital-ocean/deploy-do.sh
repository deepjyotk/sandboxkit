#!/usr/bin/env bash
# Run from sandboxkit/ on your Mac after the droplet exists.
# Bootstraps Kata on the droplet, builds + pushes images, deploys Sandboxkit to k3s.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DROPLET_IP="${DROPLET_IP:-137.184.4.45}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519_do}"
DOCKERHUB_USER="${DOCKERHUB_USER:-deepjyot}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

IMG_SANDBOXKIT="${DOCKERHUB_USER}/sandboxkit:${IMAGE_TAG}"
IMG_PY="${DOCKERHUB_USER}/sandboxkit-py-template:${IMAGE_TAG}"
IMG_JS="${DOCKERHUB_USER}/sandbox-js-template:${IMAGE_TAG}"

echo "==> 1) Bootstrap droplet (k3s + kata-deploy + smoke)"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "root@${DROPLET_IP}" 'bash -s' < "${ROOT}/digital-ocean/setup-droplet.sh"

echo "==> 2) Push images to Docker Hub (from Mac) — bakes USE_KATA=True into control plane image"
cd "$ROOT"
make push

echo "==> 3) Fetch kubeconfig from droplet"
scp -i "$SSH_KEY" "root@${DROPLET_IP}:/etc/rancher/k3s/k3s.yaml" "${ROOT}/digital-ocean/do-k3s.yaml"
sed -i.bak "s/127.0.0.1/${DROPLET_IP}/" "${ROOT}/digital-ocean/do-k3s.yaml"
export KUBECONFIG="${ROOT}/digital-ocean/do-k3s.yaml"

echo "==> 4a) Install ingress-nginx (NodePort 30080/30443) if missing"
if ! kubectl get ns ingress-nginx >/dev/null 2>&1; then
  kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.3/deploy/static/provider/baremetal/deploy.yaml
  kubectl wait --namespace ingress-nginx --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller --timeout=300s
  kubectl patch svc ingress-nginx-controller -n ingress-nginx --type=json -p='[
    {"op":"replace","path":"/spec/ports/0/nodePort","value":30080},
    {"op":"replace","path":"/spec/ports/1/nodePort","value":30443}
  ]'
else
  echo "    ingress-nginx already installed; skipping"
fi

echo "==> 4b) Deploy Sandboxkit"
kubectl apply -k "${ROOT}/infra/kustomize/base"
kubectl set image deployment/sandboxkit sandboxkit="${IMG_SANDBOXKIT}" -n sandboxes
# USE_KATA=True is compile-time; we do NOT set SANDBOX_RUNTIME_CLASS here.
# Use Always so :latest re-pulls the newly pushed image.
kubectl set env deployment/sandboxkit -n sandboxes \
  TEMPLATE_PY_IMAGE="${IMG_PY}" \
  TEMPLATE_JS_IMAGE="${IMG_JS}" \
  SANDBOX_IMAGE_PULL_POLICY=Always
# Control-plane Deployment itself should also Always pull on rollout
kubectl patch deployment sandboxkit -n sandboxes --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Always"}]' || true
kubectl rollout restart deployment/sandboxkit -n sandboxes
kubectl rollout status deployment/sandboxkit -n sandboxes --timeout=300s

echo "==> 5) Verify via public nginx Ingress URL"
INGRESS_URL="http://${DROPLET_IP}:30080"
echo "    ${INGRESS_URL}/health"
echo "    ${INGRESS_URL}/docs"
echo "    curl -s -X POST ${INGRESS_URL}/sandboxes -H 'Content-Type: application/json' \\"
echo "      -d '{\"sandbox_template\":\"sandboxkit-py-template\",\"actual_code\":\"import platform; print(platform.uname())\",\"is_polling\":false}'"
echo
echo "    kubectl get pods -n sandboxes -o custom-columns=NAME:.metadata.name,RUNTIME:.spec.runtimeClassName"
