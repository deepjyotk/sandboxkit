# SandboxKit

A minimal **sandbox-as-a-service** for running untrusted agent code in isolation — a take-home slice of what providers like E2B, Modal, and Cloudflare Sandboxes do at scale.

---

## Context

Coding agents need somewhere safe to run untrusted code. Today many teams use hosted sandbox providers; for on-prem deployments you need the same capability in-house: **spin up an isolated environment fast, run code, tear it down**.

SandboxKit is a small, working version of that system:

- **Control plane** — HTTP API that provisions and manages sandboxes
- **Sandbox runtime** — isolated environments where code actually executes

It is intentionally a **thoughtful slice**, not a full platform: real sandboxes boot, run Python/TypeScript, and return results on both local kind and a Kata-enabled DigitalOcean droplet.

---

## The Task

Minimum capabilities implemented:


| Requirement                                    | Status | How                                                    |
| ---------------------------------------------- | ------ | ------------------------------------------------------ |
| `POST /sandboxes` → spin up sandbox, return ID | ✅      | Creates ConfigMap + K8s Job per request                |
| Run code inside sandbox                        | ✅      | Lambda-style: POST snippet → stdout/stderr/exit code   |
| `DELETE /sandboxes/{id}` → tear down           | ✅      | Deletes Job, ConfigMap, Secret; clears in-memory state |
| `GET /sandboxes/{id}`                          | ✅      | Poll status (polling mode)                             |
| `GET /sandboxes`                               | ✅      | List active sandboxes (in-memory)                      |


---

## Interaction Model

**Lambda-style** (chosen) — closer to what agent harnesses need:

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "print(\"hello\")",
    "is_polling": false
  }'
```

Returns `stdout`, `stderr`, `exit_code` when done. **Polling mode** (`is_polling: true`) returns immediately with `sandbox_id` + `running`; poll `GET /sandboxes/{id}` until `completed`.

SSH/exec-style interactive sandboxes are **not** implemented — would add long-lived pods + exec/WebSocket API.

More examples: `[wiki/sample-request.md](wiki/sample-request.md)`.

---

## Tech Direction & Architecture Decisions

### Why Kubernetes (not Nomad / raw Firecracker)

- **Pragmatic scheduler:** K8s Job + ConfigMap + Secret is enough for a day-one slice. Nomad would work similarly; I leaned on K8s because kata-deploy, RuntimeClass, and resource limits are well-trodden.
- **Did not** orchestrate Firecracker directly — Kata Containers bridges OCI images → microVMs without rewriting containerd integration.

### Why Kata microVMs (Firecracker / QEMU via RuntimeClass)

- **Isolation:** Firecracker is the gold standard (Lambda). On a KVM droplet, **Kata Containers** gives microVM isolation with the same Docker images used locally on kind (runc).
- **Per-request VMM:** `vm_choice` selects `kata-qemu` (default) or `kata-fc` via K8s `RuntimeClass`. See `[wiki/vm-runtime-comparison.md](wiki/vm-runtime-comparison.md)`.
- **Local dev:** `use_kata=False` on kind → plain runc containers; flip to `True` on the DO droplet.

### Why Python + FastAPI

- Fast iteration for the control plane; `kubernetes` client for Job lifecycle; `uv` + Python 3.13.

### Why prebuilt template images + ConfigMap code injection

- User code is **not** baked into an image per request. Prebuilt runtime images (Python + FastAPI stack, Node + axios/tsx) mount `actual_code` from a ConfigMap at `/sandbox/code.py` or `code.ts`. Keeps cold path simple and matches how many providers ship language runtimes.

### Hosting


| Target                   | Isolation           | Entry                                                      |
| ------------------------ | ------------------- | ---------------------------------------------------------- |
| **Local kind**           | runc (containers)   | `make push && make setup`                                  |
| **DigitalOcean droplet** | Kata microVMs (KVM) | `[digital-ocean/deploy-do.sh](digital-ocean/deploy-do.sh)` |


### Architecture (end-to-end)

Production path on the **DigitalOcean droplet** (k3s + Kata on KVM). Local **kind** uses the same control-plane code but skips Kata — kubelet → containerd → **runc** instead of a microVM.

```mermaid
flowchart TB
  subgraph client["Client (agent, UI, curl)"]
    C1["POST /sandboxes<br/>actual_code + vm_choice"]
    C2["POST /sandboxes/from-repo<br/>GitHub + entrypoint + vm_choice"]
  end

  subgraph droplet["DigitalOcean droplet — k3s single-node cluster"]
    subgraph edge["Edge"]
      NG["nginx Ingress :30080<br/>JWT cookie auth → /auth/validate"]
    end

    subgraph cp_ns["namespace: sandboxes — control plane"]
      API["sandboxkit FastAPI<br/>(Deployment, in-cluster)"]
    end

    subgraph code_paths["How user code reaches the guest (one path per request)"]
      subgraph path_a["Path A — ConfigMap"]
        CM["ConfigMap + sandbox Job<br/>snippet at /sandbox/code.py | code.ts"]
      end
      subgraph path_b["Path B — virtio-fs (public repo)"]
        CL["clone Job — git checkout<br/>→ hostPath on node"]
        SBX["sandbox Job — hostPath volume<br/>→ virtio-fs in guest<br/>read-only /sandbox/repo"]
      end
    end

    subgraph k8s_cp["Kubernetes control plane"]
      ETCD["etcd"]
      APIS["API server"]
      JC["Job controller"]
      SCH["Scheduler"]
    end

    subgraph worker["Worker node (same droplet in demo)"]
      KBL["kubelet"]
      CTR["containerd (CRI)"]
      subgraph kata_stack["Kata path — per sandbox Pod"]
        RC["runtimeClassName<br/>kata-qemu | kata-fc"]
        KRT["kata-runtime / kata-shim"]
        VMM["VMM<br/>QEMU (kata-qemu) or Firecracker (kata-fc)"]
        KVM["Linux KVM — /dev/kvm<br/>hardware-assisted virtualization"]
        GUEST["Guest microVM<br/>own kernel + minimal init"]
        OCI["OCI sandbox container<br/>template + user code:<br/>Path A: ConfigMap @ /sandbox<br/>Path B: virtio-fs @ /sandbox/repo"]
      end
    end
  end

  C1 --> NG
  C2 --> NG
  NG -->|"subrequest validates cookie"| API
  NG -->|"proxied POST"| API
  API -->|"Path A"| CM
  API -->|"Path B: clone"| CL
  API -->|"Path B: sandbox Job after clone OK"| SBX
  CM -->|"persist objects"| APIS
  CL -->|"persist clone Job"| APIS
  SBX -->|"persist sandbox Job"| APIS
  APIS --> ETCD
  JC -->|"watch Job → create Pod"| APIS
  SCH -->|"assign Pod → nodeName"| APIS
  KBL -->|"watch Pod on this node"| APIS
  KBL -->|"CRI RunPodSandbox + CreateContainer"| CTR
  CTR --> RC
  RC --> KRT
  KRT --> VMM
  VMM --> KVM
  KVM --> GUEST
  GUEST --> OCI
  KBL -->|"collect logs"| APIS
  API -->|"poll Job + get pod logs"| APIS
  API -->|"stdout / stderr / exit_code"| C1
  API -->|"stdout / stderr / exit_code"| C2
```

Path **B** runs a **clone Job** first (repo on disk under `REPO_HOST_BASE_PATH`), then a **sandbox Job** whose Pod mounts that directory; Kata exposes it inside the microVM as **virtio-fs** at `/sandbox/repo`. Examples: [`wiki/sample-request-from-repo.md`](wiki/sample-request-from-repo.md).

#### Request path (step by step)

**Common steps** (both paths share the same ingress, Kata stack, and log polling after the sandbox Pod exists):

| Step   | Component                     | What happens                                                                                                                                                          |
| ------ | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1**  | **Client**                    | `POST /sandboxes` **or** `POST /sandboxes/from-repo` with template, optional `vm_choice`, limits, secrets                                                            |
| **2**  | **nginx Ingress**             | Validates JWT via subrequest to FastAPI `/auth/validate`; forwards to control plane on success                                                                        |
| **3**  | **FastAPI control plane**     | **Path A:** creates **ConfigMap** (code file) + optional **Secret** + **sandbox Job**. **Path B:** creates **clone Job** → waits for success → creates **sandbox Job** (hostPath volume, no ConfigMap for code) + optional Secret |
| **4**  | **API server + etcd**         | Persists Job spec(s) (pod template, CPU/mem limits, volume mounts, `runtimeClassName`)                                                                                |
| **5**  | **Job controller**            | Sees Job(s) → creates **Pod(s)** from each `job.spec.template` (Path B may run clone Pod then sandbox Pod)                                                             |
| **6**  | **Scheduler**                 | Binds Pod to a worker node (the droplet itself in the demo)                                                                                                           |
| **7**  | **kubelet**                   | Sees Pod assigned to its node → calls **containerd** over CRI                                                                                                         |
| **8**  | **containerd + Kata**         | Reads `runtimeClassName: kata-`* → invokes **kata-runtime** instead of runc                                                                                           |
| **9**  | **VMM (QEMU or Firecracker)** | Kata asks the VMM to create a **microVM**: tiny guest kernel, virtio devices, sandbox rootfs                                                                          |
| **10** | **KVM**                       | Host Linux exposes `/dev/kvm`; VMM uses **hardware virtualization** (not slow software emulation) to run the guest CPU                                                |
| **11** | **Guest microVM**             | Isolated kernel boundary — user code never runs on the host kernel. **Path A:** ConfigMap mounted at `/sandbox/code.py` (or `.ts`). **Path B:** host repo shared by **virtio-fs** at `/sandbox/repo` (read-only) |
| **12** | **Control plane poll**        | FastAPI polls Job status, reads pod logs from kubelet/API, returns `stdout`, `stderr`, `exit_code` (sync or polling mode)                                             |
| **13** | **Cleanup**                   | Job `ttlSecondsAfterFinished` (5 min) GCs Pod/Job. **Path A:** `DELETE` removes Job + ConfigMap + Secret. **Path B:** `DELETE` is synchronous: cleanup Job + host dir + sandbox Job (no ConfigMap for code) |


#### Isolation stack (why KVM matters)

```
┌─────────────────────────────────────────────────────────────────┐
│  DigitalOcean droplet (Ubuntu host kernel)                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  k3s: API server · scheduler · kubelet · containerd       │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  sandboxkit control plane (normal container / runc) │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  KVM (/dev/kvm) — host CPU virtualization extension │  │  │
│  │  │    ┌──────────────────┐  ┌──────────────────┐     │  │  │
│  │  │    │ microVM A        │  │ microVM B        │     │  │  │
│  │  │    │ (kata-qemu/fc)   │  │ (next sandbox)   │     │  │  │
│  │  │    │ guest kernel     │  │ guest kernel     │     │  │  │
│  │  │    │ └ sandbox pod    │  │ └ sandbox pod    │     │  │  │
│  │  │    │   CM or virtio-fs│  │   CM or virtio-fs│     │  │  │
│  │  │    │   /sandbox | /repo│  │   /sandbox | /repo│     │  │  │
│  │  │    └──────────────────┘  └──────────────────┘     │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

- **Without Kata (local kind):** step 8 is `containerd → runc` — containers share the **host kernel** (faster, weaker isolation).
- **With Kata (DO droplet):** each sandbox Pod is a **real VM**; escape requires breaking out of the guest kernel *and* the VMM — Lambda-class boundary.
- **KVM** is the Linux kernel module that makes VM boot fast on cloud VMs (nested virt enabled on DO). Kata’s VMM (QEMU/Firecracker) is the process that actually creates and drives each microVM.

#### Per-request Kubernetes objects

```
POST /sandboxes
    │
    ├── ConfigMap  code-{sandbox_id}     ← actual_code as code.py / code.ts
    ├── Secret     (optional)            ← SECRET_KEY* env vars
    └── Job        {sandbox_id}          ← K8s Job name == sandbox_id
            └── Pod spec
                  ├── runtimeClassName: kata-qemu | kata-fc
                  ├── image: sandboxkit-py-template | sandbox-js-template
                  ├── resources: cpu_limit, memory_limit
                  └── volumes: ConfigMap → /sandbox, emptyDir → /tmp

POST /sandboxes/from-repo
    │
    ├── Job        clone-{sandbox_id}    ← git clone into REPO_HOST_BASE_PATH/{id}/…
    ├── (wait clone Job success)
    ├── Secret     (optional)
    └── Job        {sandbox_id}          ← K8s Job name == sandbox_id (after clone succeeds)
            └── Pod spec
                  ├── runtimeClassName: kata-qemu | kata-fc
                  ├── image: sandboxkit-py-template | sandbox-js-template
                  ├── resources: cpu_limit, memory_limit
                  └── volumes: hostPath (repo) → /sandbox/repo (virtio-fs in guest, ro), emptyDir → /tmp
    └── (on DELETE) cleanup Job + remove host dir — synchronous before 204
```


---

## Stretch Goals (implemented)


| Stretch                               | Status      | Notes                                                                    |
| ------------------------------------- | ----------- | ------------------------------------------------------------------------ |
| Resource limits (CPU/mem per sandbox) | ✅           | `cpu_limit`, `memory_limit` on POST; validated + applied to Job          |
| Basic auth on the API                 | ✅           | JWT cookie auth at nginx ingress (`/auth/login`); protected `/sandboxes` |
| Filesystem / code upload              | ✅ (minimal) | Code via JSON body → ConfigMap volume mount                              |
| Run code from GitHub repo (virtio-fs) | ✅           | `POST /sandboxes/from-repo` clones to host, shares to guest via virtio-fs; synchronous cleanup on DELETE |
| Secret injection                      | ✅           | `secret_names` resolved from vault → K8s Secret → env vars               |
| VM runtime choice                     | ✅           | `vm_choice`: `kata-qemu` | `kata-fc`                                     |
| Snapshot / warm sub-second starts     | ❌           | Not implemented           |
| Test UI + playground                  | ✅           | Vite UI: test runner grid + CodeMirror playground                        |


---

## How to Run It

### Prerequisites


| Tool                                                    | Version |
| ------------------------------------------------------- | ------- |
| [Docker](https://docs.docker.com/get-docker/)           | 24+     |
| [kind](https://kind.sigs.k8s.io/docs/user/quick-start/) | 0.23+   |
| [kubectl](https://kubernetes.io/docs/tasks/tools/)      | 1.29+   |
| [uv](https://docs.astral.sh/uv/)                        | 0.4+    |


### One command (local kind)

```bash
cp .env.example .env          # set DOCKERHUB_USER=your-dockerhub-username
docker login
make push                     # build + push images to Docker Hub
make setup                    # kind cluster + deploy + UI preview
```

- Health: `http://127.0.0.1/health`
- API docs: `http://127.0.0.1/docs`
- Test UI: `http://127.0.0.1:5173` (test runner + playground)

**Flow:** `make push` publishes to `docker.io/$(DOCKERHUB_USER)/…`. `make infra` deploys; nodes pull images.


| Image                                             | Purpose                 |
| ------------------------------------------------- | ----------------------- |
| `$(DOCKERHUB_USER)/sandboxkit:latest`             | Control-plane API       |
| `$(DOCKERHUB_USER)/sandboxkit-py-template:latest` | Python sandbox runtime  |
| `$(DOCKERHUB_USER)/sandbox-js-template:latest`    | Node/TS sandbox runtime |


### DigitalOcean (Kata microVMs)

```bash
./digital-ocean/deploy-do.sh
./digital-ocean/run-tests.sh
./digital-ocean/comparison-tests.sh   # kata-qemu vs kata-fc benchmarks
```

See `[digital-ocean/digital-ocean.md](digital-ocean/digital-ocean.md)`.

### Port-forward (without ingress)

```bash
kubectl port-forward -n sandboxes svc/sandboxkit 8000:8000
# → http://localhost:8000/docs
```

### Local dev (API only, no cluster)

```bash
uv sync --dev
uv run sandboxkit
```

---

## API Reference (summary)

### `POST /sandboxes`

Sync (`is_polling: false`) — wait for result:

```json
{
  "sandbox_id": "sandbox-abc12345",
  "status": "completed",
  "stdout": "hello\n",
  "stderr": "",
  "exit_code": 0
}
```

Key optional fields: `is_polling`, `cpu_limit`, `memory_limit`, `secret_names`, `vm_choice` (`kata-qemu` | `kata-fc`).

### `GET /sandboxes/{id}` — poll status

### `DELETE /sandboxes/{id}` — teardown → `204`

For repo sandboxes, `DELETE` is **synchronous**: it only returns 204 after a
cleanup Job has removed the per-sandbox host directory from the node.

### `POST /sandboxes/from-repo` — run code from a public GitHub repo (virtio-fs)

Clone a public GitHub repo onto the node and run a chosen entrypoint inside a
Kata sandbox. The repo directory is shared into the microVM via **virtio-fs**
(transparent on `kata-qemu` when a `hostPath` volume is attached). The
container logs a `virtio-fs mount probe` line before exec so the demo can show
the mount type.

```bash
curl -s -b /tmp/cookie -X POST http://127.0.0.1/sandboxes/from-repo \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "github_repo_url": "https://github.com/deepjyotk/sandboxkit-demo-hello",
    "entrypoint": "main.py",
    "vm_choice": "kata-qemu",
    "is_polling": false
  }' | jq
```

Lifecycle guarantees:

- **Provision:** clone Job (alpine/git, `hostPath`) → sandbox Job
  (`runtimeClassName: kata-qemu`, `hostPath` mounted read-only at
  `/sandbox/repo` over virtio-fs).
- **Delete:** sandbox Job removed → cleanup Job (`busybox` + `rm -rf`) runs and
  is **awaited synchronously**; 204 only returns after the per-sandbox host
  directory is gone.

`kata-fc` is allowed but flagged via header `X-VirtioFS-Mode: experimental-fc`
(Firecracker virtio-fs is less mature than QEMU).

Full examples + validation rules: `[wiki/sample-request-from-repo.md](wiki/sample-request-from-repo.md)`.
Smoke test: `[digital-ocean/test-from-repo.sh](digital-ocean/test-from-repo.sh)`.

### Templates


| `sandbox_template`       | Runtime     | Pre-installed                     |
| ------------------------ | ----------- | --------------------------------- |
| `sandboxkit-py-template` | Python 3.13 | fastapi, uvicorn, pydantic, httpx |
| `sandbox-js-template`    | Node 22     | axios, tsx (TypeScript)           |


Full curl examples: `[wiki/](wiki/)`.

---

## Repository Layout

```
sandboxkit/
├── src/sandboxkit/              # control-plane (FastAPI, K8s client, auth)
├── docker/
│   ├── sandboxkit-py-template/  # Python sandbox image
│   └── sandbox-js-template/     # Node/TS sandbox image
├── infra/kind/                  # local cluster config
├── infra/kustomize/             # Deployment, ingress, auth nginx
├── digital-ocean/               # Kata droplet deploy + benchmarks
├── ui/                          # test runner + playground
├── wiki/                        # sample requests, VM comparison results
└── doc.md                       # deeper architecture notes
```

---

## Environment Variables


| Variable                                  | Default         | Description                              |
| ----------------------------------------- | --------------- | ---------------------------------------- |
| `SANDBOX_NAMESPACE`                       | `sandboxes`     | K8s namespace for sandbox Jobs           |
| `JOB_TIMEOUT_SECONDS`                     | `60`            | Max wait for Job completion              |
| `JOB_TTL_SECONDS`                         | `300`           | Auto-delete completed Jobs after 5 min   |
| `SANDBOX_CPU_LIMIT`                       | `500m`          | Default CPU limit                        |
| `SANDBOX_MEMORY_LIMIT`                    | `256Mi`         | Default memory limit                     |
| `USE_KATA`                                | `True`          | MicroVM RuntimeClass vs runc             |
| `KATA_RUNTIME_CLASS`                      | `kata-qemu`     | Default RuntimeClass when no `vm_choice` |
| `TEMPLATE_PY_IMAGE` / `TEMPLATE_JS_IMAGE` | (set by deploy) | Sandbox runtime images                   |
| `REPO_HOST_BASE_PATH`                     | `/var/lib/sandboxkit/repos` | Node directory holding per-sandbox clones (hostPath / virtio-fs) |
| `CLONE_IMAGE`                             | `alpine/git:latest` | Image used for the per-sandbox clone Job             |
| `CLEANUP_IMAGE`                           | `busybox:1.36`  | Image used for the synchronous cleanup Job on DELETE |
| `CLONE_TIMEOUT_SECONDS` / `CLEANUP_TIMEOUT_SECONDS` | `90` / `60` | Wait deadlines for clone and cleanup Jobs |


---

## Teardown

```bash
make clean    # delete kind cluster
```

---

## Debrief Cheat Sheet

Quick pointers for a walkthrough call:

- **Demo path:** `make setup` → UI test runner → POST from playground with `vm_choice`
- **Isolation proof:** `[digital-ocean/kata-isolation-probe.sh](digital-ocean/kata-isolation-probe.sh)`
- **VM tradeoffs:** `[wiki/vm-runtime-comparison.md](wiki/vm-runtime-comparison.md)` — FC slightly faster cold start; QEMU faster in-guest CPU
- **virtio-fs demo:** `[digital-ocean/test-from-repo.sh](digital-ocean/test-from-repo.sh)` — clones a public GitHub repo, runs entrypoint in a Kata microVM with virtio-fs share, then proves the host dir is gone after DELETE
- **Surprises:** ConfigMap + Kata FC works on our cluster despite virtio-fs concerns; cold start dominated by microVM boot not user code

