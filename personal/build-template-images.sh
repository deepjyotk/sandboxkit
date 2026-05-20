#!/usr/bin/env bash
# Build sandboxkit control-plane + template images and push to a registry.
# Requires DOCKERHUB_USER (e.g. from .env). Used by: make push
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="${IMAGE_TAG:-latest}"
PUSH="${PUSH:-1}"

cd "$ROOT"

if [ -z "${DOCKERHUB_USER:-}" ]; then
  echo "ERROR: DOCKERHUB_USER is required (set in .env or export it)" >&2
  exit 1
fi

IMG_SANDBOXKIT="${DOCKERHUB_USER}/sandboxkit:${IMAGE_TAG}"
IMG_PY="${DOCKERHUB_USER}/sandboxkit-py-template:${IMAGE_TAG}"
IMG_JS="${DOCKERHUB_USER}/sandbox-js-template:${IMAGE_TAG}"

# Multi-arch by default so Apple Silicon Macs can push images that run on
# linux/amd64 nodes (e.g. DigitalOcean droplets). Override with PLATFORMS=.
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"

if [ "${PUSH}" = "1" ]; then
  # buildx requires --push (registry-only) for multi-arch.
  if ! docker buildx inspect sandboxkit-builder >/dev/null 2>&1; then
    docker buildx create --name sandboxkit-builder --use >/dev/null
  else
    docker buildx use sandboxkit-builder >/dev/null
  fi
  docker buildx inspect --bootstrap >/dev/null

  echo "==> buildx push ${IMG_PY} [${PLATFORMS}]"
  docker buildx build --platform "${PLATFORMS}" -t "${IMG_PY}" --push docker/sandboxkit-py-template

  echo "==> buildx push ${IMG_JS} [${PLATFORMS}]"
  docker buildx build --platform "${PLATFORMS}" -t "${IMG_JS}" --push docker/sandbox-js-template

  echo "==> buildx push ${IMG_SANDBOXKIT} [${PLATFORMS}]"
  docker buildx build --platform "${PLATFORMS}" -t "${IMG_SANDBOXKIT}" --push .
else
  echo "==> PUSH=0; single-arch local build (native)"
  docker build -t "${IMG_PY}" docker/sandboxkit-py-template
  docker build -t "${IMG_JS}" docker/sandbox-js-template
  docker build -t "${IMG_SANDBOXKIT}" .
fi

echo "Built (cluster will pull these from the registry):"
echo "  ${IMG_SANDBOXKIT}"
echo "  ${IMG_PY}"
echo "  ${IMG_JS}"
