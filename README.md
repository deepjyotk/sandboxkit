# SandboxKit

**Sandbox-as-a-service control plane** (Python 3.13+, FastAPI, Kubernetes).

Accepts a code snippet, spins up a short-lived Kubernetes Job to execute it in isolation, and returns `stdout`, `stderr`, and `exit_code`. Supports both **synchronous** (wait for result) and **polling** (fire-and-forget + poll) execution modes.

---

## Architecture

```
External Caller
      │
      ▼
POST /sandboxes  ──►  FastAPI (agent-sandbox-service)
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
              ConfigMap              K8s Job
             (code file)          (sandbox pod)
                    │                    │
                    └─────────┬──────────┘
                              ▼
                         Pod Logs
                       (stdout/stderr/exit_code)
```

---

## Prerequisites

| Tool | Version |
|------|---------|
| [Docker](https://docs.docker.com/get-docker/) | 24+ |
| [kind](https://kind.sigs.k8s.io/docs/user/quick-start/) | 0.23+ |
| [kubectl](https://kubernetes.io/docs/tasks/tools/) | 1.29+ |
| [uv](https://docs.astral.sh/uv/) | 0.4+ |

```bash
# macOS install via Homebrew
brew install kind kubectl
```

---

## Quick Start

### One command (recommended)

Requires Docker, kind, kubectl, make, and a **public Docker Hub** account.

```bash
cp .env.example .env          # set DOCKERHUB_USER=your-dockerhub-username
docker login                  # once, for make push
make push                     # build + push images to Docker Hub (required first)
make setup                    # kind + deploy (cluster pulls from registry)
make infra                    # redeploy only (after code: make push, then make infra)
make kind                     # create kind cluster only
make clean                    # delete kind cluster + volumes only
make clean-docker-hub-template-images   # remove local Docker Hub image copies
make build-and-run-ui                   # wiki test cases grid → http://127.0.0.1:5173
```

**Flow:** `make push` publishes images to `docker.io/$(DOCKERHUB_USER)/…`. `make infra` only deploys to kind; nodes **pull** those images (`imagePullPolicy: IfNotPresent`). Push is not part of infra.

| Image on Docker Hub | Purpose |
|---------------------|---------|
| `$(DOCKERHUB_USER)/sandboxkit:latest` | Control-plane API |
| `$(DOCKERHUB_USER)/sandboxkit-py-template:latest` | Python + FastAPI template |
| `$(DOCKERHUB_USER)/sandbox-js-template:latest` | Node + axios template |

Health check uses ingress-nginx on port 80:

- `http://127.0.0.1/health` (works in the browser after deploy)
- `http://sandboxkit.local/health` if you add `127.0.0.1 sandboxkit.local` to `/etc/hosts`

A plain `404` from **nginx** (not “connection refused”) means ingress is running but the request did not match a route — usually missing `Host: sandboxkit.local` before the catch-all rule was added.

If you already created a `sandbox` cluster **before** ingress-ready labels and port 80/443 were added to [`infra/kind/cluster.yaml`](infra/kind/cluster.yaml), run `make clean` then `make setup` again.

### Manual setup

### 1. Create the kind cluster

```bash
kind create cluster --config infra/kind/cluster.yaml --name sandbox
```

Verify the cluster is running:

```bash
kubectl cluster-info --context kind-sandbox
kubectl get nodes
```

### 2. Push images, then deploy

```bash
export DOCKERHUB_USER=your-dockerhub-username
docker login
make push    # build + push to Docker Hub
make infra   # deploy; cluster pulls from registry
```

Template images include runtime dependencies (FastAPI stack, axios). Jobs **pull** them from the registry; user code is injected per request via ConfigMap.

### 3. Verify deployment

```bash
kubectl apply -k infra/kustomize/base   # applied by make infra
```

Verify the pod is running:

```bash
kubectl -n sandboxes get pods
kubectl -n sandboxes get svc
```

### 4. Port-forward the service

```bash
kubectl port-forward -n sandboxes svc/sandboxkit 8000:8000
```

The API is now reachable at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

---

## API Reference

### `POST /sandboxes` — Execute code

**Sync mode** (wait for result):

```bash
curl -s -X POST http://localhost:8000/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "from fastapi import FastAPI\nprint(FastAPI.__name__)",
    "is_polling": false
  }' | jq
```

Response:

```json
{
  "sandbox_id": "sandbox-abc12345",
  "status": "completed",
  "stdout": "FastAPI\n",
  "stderr": "",
  "exit_code": 0
}
```

**Polling mode** (fire-and-forget):

```bash
curl -s -X POST http://localhost:8000/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "import time; time.sleep(2); print(\"done\")",
    "is_polling": true
  }' | jq
```

Response:

```json
{
  "sandbox_id": "sandbox-def67890",
  "status": "running"
}
```

**Node sandbox** (prebuilt axios):

```bash
curl -s -X POST http://localhost:8000/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandbox-js-template",
    "actual_code": "const axios = require(\"axios\"); console.log(\"axios\", axios.VERSION);",
    "is_polling": false
  }' | jq
```

---

### `GET /sandboxes/{id}` — Poll execution status

```bash
curl -s http://localhost:8000/sandboxes/sandbox-def67890 | jq
```

Response once complete:

```json
{
  "sandbox_id": "sandbox-def67890",
  "status": "completed",
  "stdout": "done\n",
  "stderr": "",
  "exit_code": 0
}
```

---

### `DELETE /sandboxes/{id}` — Cleanup

Deletes the Kubernetes Job, the code ConfigMap, and removes in-memory state:

```bash
curl -s -X DELETE http://localhost:8000/sandboxes/sandbox-abc12345
# → 204 No Content
```

---

## Available Sandbox Templates

Templates are **prebuilt Docker images** (see `docker/`). Each Job mounts your `actual_code` at `/sandbox/code.py` or `/sandbox/code.js`.

| `sandbox_template` | Prebuilt image (registry) | Pre-installed packages |
|--------------------|---------------------------|------------------------|
| `sandboxkit-py-template` | `$(DOCKERHUB_USER)/sandboxkit-py-template:latest` | fastapi, uvicorn, pydantic, httpx |
| `sandbox-js-template` | `$(DOCKERHUB_USER)/sandbox-js-template:latest` | axios |

Template images are **not** in Kustomize manifests — only the control-plane Deployment is. Jobs pull template images from the registry via env vars set by `make infra` (`TEMPLATE_PY_IMAGE`, `TEMPLATE_JS_IMAGE`).

---

## Local Development (without Kubernetes)

```bash
# Install dependencies
uv sync --dev

# Run the API server locally (K8s calls will fail without a cluster)
uv run sandboxkit

# Lint & format
uv run flake8 src
uv run black src
```

---

## Repository Layout

```
sandboxkit/
├── src/sandboxkit/           # control-plane API
├── docker/
│   ├── sandboxkit-py-template/  # prebuilt Python+FastAPI sandbox image
│   └── sandbox-js-template/          # prebuilt Node+axios sandbox image
├── scripts/
│   └── build-template-images.sh
├── infra/kind/               # kind cluster config
├── infra/kustomize/          # control-plane Deployment only
├── Dockerfile                # control-plane image
└── pyproject.toml
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SANDBOX_NAMESPACE` | `sandboxes` | K8s namespace for sandbox Jobs |
| `JOB_TIMEOUT_SECONDS` | `60` | Max seconds to wait for a Job to finish |
| `JOB_POLL_INTERVAL_SECONDS` | `1.0` | How often to poll Job status |
| `KUBECONFIG` | `` (auto) | Path to kubeconfig; empty = in-cluster |
| `SANDBOX_CPU_LIMIT` | `500m` | CPU limit for sandbox pods |
| `SANDBOX_MEMORY_LIMIT` | `256Mi` | Default memory limit (templates may override) |
| `JOB_TTL_SECONDS` | `300` | K8s TTL before completed Jobs are auto-deleted |
| `TEMPLATE_PY_IMAGE` | (set by `make infra`) | Full registry ref for FastAPI template |
| `TEMPLATE_JS_IMAGE` | (set by `make infra`) | Full registry ref for Node template |
| `SANDBOX_IMAGE_PULL_POLICY` | `IfNotPresent` | Pull policy for sandbox Job pods (pull from registry) |

---

## Teardown

```bash
# Delete the kind cluster and all resources
kind delete cluster --name sandbox
```
