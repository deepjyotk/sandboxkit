# DigitalOcean — Kata + k3s demo host

Plan: one **Droplet** (not App Platform) running **k3s + Kata** for MicroVM sandbox demos.  
Specs: **Regular SSD · 2 vCPU · 4 GB RAM** (`s-2vcpu-4gb`, ~$24/mo).

Local **kind** stays for everyday dev (runc). This droplet is for proving **Kubernetes + Kata** ([Kata docs](https://katacontainers.io/docs/)).

---

## Part 1 — Create Droplet in the UI

### Region

| Field | Value |
|--------|--------|
| Datacenter (UI) | **San Francisco** — pick any **available** SF datacenter (SFO1 is often full) |
| Region slug (CLI) | **`sfo3`** preferred (`sfo2` also OK). Avoid `sfo1` if API says unavailable. |

Check availability:

```bash
doctl compute region list
# use a row where Available = true, e.g. sfo3
```

### Image & size (already chosen)

| Field | Value |
|--------|--------|
| Image | **Ubuntu 24.04 (LTS) x64** |
| Plan | **Basic → Regular** → **$24/mo** — 2 vCPU, 4 GB RAM, 80 GB SSD |
| Slug | `s-2vcpu-4gb` |

4 GB is the minimum worth trying for k3s + Kata + a few sandbox pods. If Kata smoke tests OOM, bump to **8 GB** (`s-2vcpu-8gb`).

### Authentication — **SSH key (Option A — dedicated key)**

We use a **dedicated key** for this droplet: `~/.ssh/id_ed25519_do` (private) and `~/.ssh/id_ed25519_do.pub` (public).

**Step 1 — Generate the key on your Mac (do this first):**

```bash
ssh-keygen -t ed25519 -C "sandbox-kata-do" -f ~/.ssh/id_ed25519_do -N ""

# Verify both files exist
ls -l ~/.ssh/id_ed25519_do ~/.ssh/id_ed25519_do.pub
```

**Step 2 — Add the public key in the UI:**

| Option | What to do |
|--------|------------|
| **SSH Keys** ✓ | Click **Add an SSH Key**, paste output of `cat ~/.ssh/id_ed25519_do.pub`. |
| **Password** | Leave unused. |

```bash
cat ~/.ssh/id_ed25519_do.pub   # copy entire line into DigitalOcean
```

**Step 3 — SSH after the droplet exists:**

```bash
ssh -i ~/.ssh/id_ed25519_do root@DROPLET_IP
```

The UI blocks **Create Droplet** until at least one SSH key is selected — that’s expected.

### Networking

| Option | Recommendation |
|--------|----------------|
| **VPC** | Default VPC is fine (single droplet). |
| **Enable IPv6** | Optional — not required for this demo. |
| **Private IPv4** | Always on — ignore unless you add more droplets. |

No extra networking setup needed.

### Monitoring

| Option | Recommendation |
|--------|----------------|
| **Improved metrics and monitoring (free)** | ✓ **Check it** — useful to see CPU/RAM while testing Kata. Harmless. |

### Additional options

| Option | Recommendation |
|--------|----------------|
| **Startup scripts** | **Leave unchecked** for the first create — run k3s/Kata manually so failures are easier to debug. |
| **Backups / volumes** | Skip for a short-lived demo. |

### Final

- **Quantity:** `1`
- **Hostname:** `sandbox-kata` (or any name)
- Click **Add Payment Method and Create Droplet** (after SSH key is added)

---

## Part 2 — Create the same Droplet with `doctl` (CLI)

Faster repeats and matches the UI plan exactly. Uses the same **Option A** SSH key as Part 1.

### Step 0 — Generate SSH key (required before `doctl` or UI)

Skip only if `~/.ssh/id_ed25519_do.pub` already exists.

```bash
ssh-keygen -t ed25519 -C "sandbox-kata-do" -f ~/.ssh/id_ed25519_do -N ""
ls -l ~/.ssh/id_ed25519_do.pub   # must exist — if "No such file", rerun ssh-keygen
```

### One-time: install and auth `doctl`

```bash
# macOS
brew install doctl

# API token: https://cloud.digitalocean.com/account/api/tokens (Read + Write)
doctl auth init
# paste token when prompted (input is hidden)

doctl account get   # sanity check
```

### Register the public key with DigitalOcean (once)

```bash
# doctl uses --public-key (file contents), NOT --public-key-file
doctl compute ssh-key create sandbox-kata-key \
  --public-key "$(cat ~/.ssh/id_ed25519_do.pub)"

# List key IDs — copy the ID for the next step
doctl compute ssh-key list
```

If you already added this key in the **UI**, skip `ssh-key create` and only run `doctl compute ssh-key list` to get the ID.

### Create droplet

```bash
export DO_REGION=sfo3          # San Francisco 3 (sfo1 often unavailable — see: doctl compute region list)
export DO_SSH_KEY_ID=12345678  # replace: doctl compute ssh-key list → ID column

doctl compute droplet create sandbox-kata \
  --region "$DO_REGION" \
  --image ubuntu-24-04-x64 \
  --size s-2vcpu-4gb \
  --ssh-keys "$DO_SSH_KEY_ID" \
  --enable-monitoring \
  --tag-names sandboxkit,kata \
  --wait

# Get IP
doctl compute droplet list --format Name,PublicIPv4,Status
export DROPLET_IP=$(doctl compute droplet list --format Name,PublicIPv4 --no-header | awk '/sandbox-kata/{print $2}')
echo "SSH: ssh -i ~/.ssh/id_ed25519_do root@$DROPLET_IP"
```

### Optional: user-data script at create (advanced)

Only if you want unattended **k3s** install (Kata still manual). Save as `user-data.sh` and pass `--user-data-file user-data.sh`:

```bash
#!/bin/bash
set -euo pipefail
curl -sfL https://get.k3s.io | sh -
```

```bash
doctl compute droplet create sandbox-kata \
  ... \
  --user-data-file ./user-data.sh \
  --wait
```

For tomorrow’s deadline, **manual SSH steps below are safer**.

### Delete droplet when done (stop billing)

```bash
doctl compute droplet delete sandbox-kata --force
```

---

## Part 3 — After the droplet is up (~30 min path)

**Automated (from Mac, in `sandboxkit/`):**

```bash
export DROPLET_IP=137.184.4.45   # your droplet public IP
chmod +x digital-ocean/setup-droplet.sh digital-ocean/deploy-do.sh
./digital-ocean/deploy-do.sh
```

**Kata on sandbox Jobs** (pick one):

| Method | When |
|--------|------|
| `USE_KATA = True` in [src/sandboxkit/utils/config.py](../src/sandboxkit/utils/config.py) | **Current default** — hardcodes `runtimeClassName: kata-qemu`. Rebuild/push image (`make push`), then redeploy. |
| `SANDBOX_RUNTIME_CLASS=<name>` env on Deployment | Override only when `USE_KATA=False` (e.g. test `kata-fc`). |

SSH in manually, or use the steps below.

### 1. KVM check (required for Kata)

```bash
ssh -i ~/.ssh/id_ed25519_do root@"$DROPLET_IP"

ls -l /dev/kvm
egrep -c '(vmx|svm)' /proc/cpuinfo
```

- If **`/dev/kvm` missing** → Kata/Firecracker will not work reliably on this VM; try another provider or larger/bare-metal plan. Stop here and use **kind + runc** for API demo + architecture doc.

### 2. k3s

```bash
curl -sfL https://get.k3s.io | sh -
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl get nodes
```

### 3. Kata ([install / Kubernetes guides](https://katacontainers.io/docs/))

```bash
# Use the official kata-deploy Helm chart (see katacontainers.io/docs)
VERSION="$(curl -sSL https://api.github.com/repos/kata-containers/kata-containers/releases/latest | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)"
helm upgrade --install kata-deploy oci://ghcr.io/kata-containers/kata-deploy-charts/kata-deploy \
  --version "$VERSION" -n kube-system --create-namespace

# k3s renders containerd config under /var/lib/rancher/k3s/... — copy it where kata-deploy expects it
cp /var/lib/rancher/k3s/agent/etc/containerd/config.toml /etc/containerd/config.toml

kubectl -n kube-system rollout status daemonset/kata-deploy --timeout=600s
# Restart k3s so containerd picks up kata shim drop-ins
systemctl restart k3s
kubectl wait --for=condition=ready node --all --timeout=120s
kubectl get runtimeclass
```

Smoke pod:

```bash
kubectl run kata-smoke --image=busybox --restart=Never \
  --overrides='{"spec":{"runtimeClassName":"kata-qemu"}}' \
  --command -- sh -c 'uname -a; sleep 60'

kubectl wait --for=condition=ready pod/kata-smoke --timeout=180s
kubectl logs kata-smoke | head -1   # microVM kernel (different from host uname)
```

The Helm chart installs `kata-qemu`, `kata-fc`, `kata-clh`, etc. — there is **no** plain `kata` RuntimeClass. Pick one that matches `kubectl get runtimeclass`. We default to **`kata-qemu`** (QEMU+KVM microVM, most reliable).

### 4. Sandboxkit (from your laptop)

```bash
# Mac, in sandboxkit/
make push   # needs DOCKERHUB_USER in .env

# Copy kubeconfig from droplet (replace IP)
scp -i ~/.ssh/id_ed25519_do root@"$DROPLET_IP":/etc/rancher/k3s/k3s.yaml ./do-k3s.yaml
# Edit server: https://127.0.0.1:6443 → https://DROPLET_IP:6443

export KUBECONFIG=$(pwd)/do-k3s.yaml
kubectl apply -k infra/kustomize/base
# Set images/env like make infra (TEMPLATE_PY_IMAGE, TEMPLATE_JS_IMAGE, SANDBOX_RUNTIME_CLASS when added)

kubectl port-forward -n sandboxes svc/sandboxkit 8000:8000
```

Or install manifests directly on the droplet with `kubectl` as root.

---

## Part 4 — What to tell Nick

| Piece | Choice |
|--------|--------|
| Orchestrator | **Kubernetes** (k3s on demo droplet; customer’s K8s in prod) |
| Isolation | **Kata microVMs** via `runtimeClassName` on sandbox Jobs |
| Hypervisor | **KVM** on host; Kata may use **Firecracker** (`kata-fc`) or QEMU |
| Local dev | **kind + runc** (no KVM on Mac) |
| Demo host | **DO Droplet `s-2vcpu-4gb` in `sfo3`** (or other available region) |

---

## Quick reference — UI vs CLI

| UI field | CLI / note |
|----------|------------|
| San Francisco (available) | `--region sfo3` (not `sfo1` if unavailable) |
| 2 vCPU, 4 GB, Regular SSD | `--size s-2vcpu-4gb` |
| Ubuntu 24.04 LTS | `--image ubuntu-24-04-x64` |
| SSH key | `--ssh-keys <ID>` |
| Monitoring on | `--enable-monitoring` |
| Startup script | `--user-data-file` (optional) |
| IPv6 | not needed |
| Password auth | avoid; use SSH |

---

## Troubleshooting

| Problem | Action |
|---------|--------|
| `sfo1 is unavailable` (422) | `doctl compute region list` → use `sfo3`, `sfo2`, or `nyc1` where **Available = true** |
| `cat: id_ed25519_do.pub: No such file` | Run **Step 0** `ssh-keygen` first |
| `unknown flag: --public-key-file` | Use `--public-key "$(cat ~/.ssh/id_ed25519_do.pub)"` |
| Create button disabled | Add/select an **SSH key** |
| `no runtime for kata` on k3s | See [kata-deploy k3s issues](https://github.com/kata-containers/kata-containers/issues/10809); try `kata-qemu` RuntimeClass |
| Pod Pending / OOM | Resize to **8 GB** or reduce concurrent sandboxes |
| Can’t pull images | `docker login` on laptop; ensure `make push` succeeded; check image names in deployment env |

---

## Cost

`s-2vcpu-4gb` ≈ **$0.036/hour** — destroy the droplet when finished:

```bash
doctl compute droplet delete sandbox-kata --force
```
