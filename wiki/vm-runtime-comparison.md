# Kata runtime comparison (`kata-qemu` vs `kata-fc`)

Benchmark results from the DigitalOcean Kata droplet (`137.184.4.45:30080`) using SandboxKit’s `vm_choice` field. Reproduce with:

```bash
cd sandboxkit
./digital-ocean/comparison-tests.sh
```

Optional env: `VM_CHOICES`, `ITERATIONS`, `WARMUP`, `BASE`, `KUBECONFIG`, `CPU_LIMIT`, `MEMORY_LIMIT`. Raw CSV: `/tmp/sandboxkit-vm-comparison.csv`.

**Test config:** `sandboxkit-py-template`, `cpu_limit=500m`, `memory_limit=256Mi`, minimal startup code `print("ping")` (polling mode), 1 warmup + 5 measured iterations per VM.

**Date:** 2026-05-20

---

## Summary table

| VM | API p50 | API mean | K8s job p50 | Guest MemTotal | CPU bench (in-guest) |
|----|---------|----------|-------------|----------------|----------------------|
| **kata-qemu** | 10,107 ms | 10,697 ms | ~8,000 ms | 2,232,544 KiB (~2.1 GiB) | **726 ms** |
| **kata-fc** | **9,673 ms** | **10,042 ms** | ~8,000 ms | 2,232,544 KiB (~2.1 GiB) | 829 ms |

Follow-up run (3 iterations, K8s timing fix verified):

| VM | API p50 | K8s job p50 | K8s run p50 | CPU bench |
|----|---------|-------------|-------------|-----------|
| kata-qemu | 9,156 ms | 8,000 ms | 8,000 ms | 604 ms |
| kata-fc | 8,670 ms | 8,000 ms | 8,000 ms | 792 ms |

---

## What was measured

| Metric | Method |
|--------|--------|
| **Startup (end-to-end)** | API wall time: polling `POST /sandboxes` → `GET /sandboxes/{id}` until `completed` |
| **Startup (Kubernetes)** | Batch Job `startTime` → `completionTime` (and creation → completion) |
| **RAM** | Guest `MemTotal` from `/proc/meminfo` inside the microVM (overhead probe) |
| **CPU** | Fixed in-guest bench: `sum(i*i for i in range(2_000_000))` |
| **Pod CPU/RAM peak** | metrics-server samples during poll (often **n/a** — pods GC’d before scrape) |

---

## Conclusions

### Startup (user-visible)

**kata-fc is slightly faster** end-to-end (~4–5% lower API p50 in the main run). Differences are modest and vary with image cache and node load — treat as **roughly similar**, with a small edge to Firecracker on cold-ish runs on this cluster.

### Startup (Kubernetes Job)

Both runtimes spend about **7–9 seconds** from Job start to completion for trivial `print("ping")`. Most of that is **schedule + microVM boot + teardown**, not user Python.

### RAM

**No meaningful difference** — both guests report the same **~2.1 GiB MemTotal**. That reflects **microVM guest RAM sizing**, not the Kubernetes `256Mi` limit (Kata guests often see a larger VM memory map than the cgroup limit alone suggests).

### CPU (in-guest compute)

**kata-qemu is faster** on the fixed micro-benchmark (~**14–25%** quicker than kata-fc). Prefer QEMU for CPU-heavy sandbox workloads on this node.

### metrics-server

Pod-level CPU/memory peaks were **not captured reliably** (pods removed quickly after Jobs finish). For host-level VMM RSS (QEMU vs Firecracker processes), use node tooling on the droplet during a run.

---

## Practical recommendation

| Use case | Prefer |
|----------|--------|
| Default / compatibility | **kata-qemu** |
| Slightly snappier cold start (this cluster) | **kata-fc** (marginal) |
| CPU-heavy user code | **kata-qemu** |
| Same memory footprint | Either (tie) |

To compare additional RuntimeClasses (e.g. `kata-clh`), extend `VmChoice` in `schemas.py` and the API, then:

```bash
VM_CHOICES=kata-qemu,kata-fc,kata-clh ./digital-ocean/comparison-tests.sh
```

---

## Related

- Script: [`digital-ocean/comparison-tests.sh`](../digital-ocean/comparison-tests.sh)
- `vm_choice` on `POST /sandboxes`: see [sample-request.md](sample-request.md) and `schemas.py`
- DO deploy notes: [`digital-ocean/digital-ocean.md`](../digital-ocean/digital-ocean.md)
