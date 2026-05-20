#!/usr/bin/env bash
# Compare Kata RuntimeClasses (vm_choice) on a live SandboxKit cluster.
#
# Measures per runtime:
#   - API wall time (POST polling → GET completed) — end-user perceived startup+run
#   - K8s schedule→Running, container start→Job complete (from pod/job timestamps)
#   - Guest-visible RAM (/proc/meminfo MemTotal) vs configured limit
#   - Short CPU micro-benchmark inside the guest
#   - Peak pod CPU/memory from metrics-server (if installed)
#
# Usage (from sandboxkit/):
#   ./digital-ocean/comparison-tests.sh
#   VM_CHOICES=kata-qemu,kata-fc ITERATIONS=5 ./digital-ocean/comparison-tests.sh
#   KUBECONFIG=digital-ocean/do-k3s.yaml BASE=http://137.184.4.45:30080 ./digital-ocean/comparison-tests.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${BASE:-http://137.184.4.45:30080}"
SBX_USER="${SBX_USER:-deepjyot}"
SBX_PASS="${SBX_PASS:-Abcd}"
COOKIE_JAR="${COOKIE_JAR:-/tmp/sbx-comparison-cookie.txt}"
export KUBECONFIG="${KUBECONFIG:-${ROOT}/digital-ocean/do-k3s.yaml}"
NS="${SANDBOX_NS:-sandboxes}"
VM_CHOICES="${VM_CHOICES:-kata-qemu,kata-fc}"
ITERATIONS="${ITERATIONS:-5}"
WARMUP="${WARMUP:-1}"
POLL_INTERVAL="${POLL_INTERVAL:-0.25}"
MEMORY_LIMIT="${MEMORY_LIMIT:-256Mi}"
CPU_LIMIT="${CPU_LIMIT:-500m}"
RESULTS_CSV="${RESULTS_CSV:-/tmp/sandboxkit-vm-comparison.csv}"

NEED_AUTH=1
[[ "$BASE" == *":8000"* ]] && NEED_AUTH=0

echo "================================================================"
echo "SandboxKit VM runtime comparison"
echo "  BASE=$BASE  NS=$NS  VMs=$VM_CHOICES  iterations=$ITERATIONS"
echo "  limits: cpu=$CPU_LIMIT mem=$MEMORY_LIMIT"
echo "================================================================"

# --- Python engine: login, POST, poll, kubectl timings, probes, stats ---
export BASE COOKIE_JAR NS VM_CHOICES ITERATIONS WARMUP POLL_INTERVAL MEMORY_LIMIT CPU_LIMIT RESULTS_CSV
export NEED_AUTH SBX_USER SBX_PASS

python3 << 'PY'
from __future__ import annotations

import csv
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

BASE = os.environ["BASE"]
COOKIE = os.environ["COOKIE_JAR"]
NS = os.environ["NS"]
VM_CHOICES = [v.strip() for v in os.environ["VM_CHOICES"].split(",") if v.strip()]
ITERATIONS = int(os.environ["ITERATIONS"])
WARMUP = int(os.environ["WARMUP"])
POLL_INTERVAL = float(os.environ["POLL_INTERVAL"])
MEMORY_LIMIT = os.environ["MEMORY_LIMIT"]
CPU_LIMIT = os.environ["CPU_LIMIT"]
RESULTS_CSV = os.environ["RESULTS_CSV"]
NEED_AUTH = os.environ.get("NEED_AUTH", "1") == "1"
SBX_USER = os.environ.get("SBX_USER", "deepjyot")
SBX_PASS = os.environ.get("SBX_PASS", "Abcd")


def login() -> None:
    if not NEED_AUTH:
        return
    if os.path.isfile(COOKIE):
        os.remove(COOKIE)
    http, body = curl_json(
        "POST",
        f"{BASE}/auth/login",
        {"username": SBX_USER, "password": SBX_PASS},
        save_cookie=True,
    )
    if http != 200:
        raise SystemExit(f"FAIL: login HTTP {http} body={body!r}")
    print("==> Login ok")


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def ms_between(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return (b - a).total_seconds() * 1000.0


def curl_json(
    method: str, url: str, body: dict | None = None, *, save_cookie: bool = False
) -> tuple[int, dict | str]:
    """HTTP via curl (cookie auth) or urllib (port-forward / no auth)."""
    if NEED_AUTH:
        cmd = ["curl", "-s", "-b", COOKIE]
        if save_cookie:
            cmd += ["-c", COOKIE]
        cmd += ["-w", "\n__HTTP__%{http_code}", "-X", method, url]
        if body is not None:
            cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
        out = subprocess.check_output(cmd, text=True)
        if "__HTTP__" not in out:
            return 0, out
        resp, http = out.rsplit("__HTTP__", 1)
        http_code = int(http.strip())
        try:
            return http_code, json.loads(resp)
        except json.JSONDecodeError:
            return http_code, resp
    headers = {"Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode()
        try:
            return r.status, json.loads(raw)
        except json.JSONDecodeError:
            return r.status, raw


def kubectl_json(args: list[str]) -> dict | list | None:
    env = os.environ.copy()
    try:
        out = subprocess.check_output(
            ["kubectl", *args], text=True, stderr=subprocess.DEVNULL, env=env
        )
        return json.loads(out) if out.strip() else None
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def kubectl_get(kind: str, name: str) -> dict | None:
    return kubectl_json(["get", kind, "-n", NS, name, "-o", "json"])


def metrics_server_available() -> bool:
    try:
        subprocess.check_output(
            ["kubectl", "get", "--raw", "/apis/metrics.k8s.io/v1beta1"],
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _parse_cpu_quantity(cpu: str) -> float | None:
    """Return millicores from metrics-server quantity (e.g. 279303n, 5m, 1)."""
    if not cpu:
        return None
    if cpu.endswith("n"):
        return int(cpu[:-1]) / 1_000_000
    if cpu.endswith("m"):
        return float(cpu[:-1])
    try:
        return float(cpu) * 1000
    except ValueError:
        return None


def _parse_mem_quantity(mem: str) -> int | None:
    if not mem:
        return None
    if mem.endswith("Ki"):
        return int(float(mem[:-2]) * 1024)
    if mem.endswith("Mi"):
        return int(float(mem[:-2]) * 1024 * 1024)
    if mem.endswith("Gi"):
        return int(float(mem[:-2]) * 1024 * 1024 * 1024)
    return None


def sample_pod_metrics(
    sandbox_id: str, peak_cpu: float | None, peak_mem: int | None
) -> tuple[float | None, int | None]:
    if not metrics_server_available():
        return peak_cpu, peak_mem
    m = kubectl_json(
        ["get", "--raw", f"/apis/metrics.k8s.io/v1beta1/namespaces/{NS}/pods/{sandbox_id}"]
    )
    if not isinstance(m, dict):
        return peak_cpu, peak_mem
    for c in m.get("containers", []):
        cpu = _parse_cpu_quantity(c.get("usage", {}).get("cpu", ""))
        mem = _parse_mem_quantity(c.get("usage", {}).get("memory", ""))
        if cpu is not None:
            peak_cpu = cpu if peak_cpu is None else max(peak_cpu, cpu)
        if mem is not None:
            peak_mem = mem if peak_mem is None else max(peak_mem, mem)
    return peak_cpu, peak_mem


def k8s_timings(sandbox_id: str) -> dict[str, float | None]:
    """Job start→complete from Batch Job status (pods may be GC'd already)."""
    job: dict = {}
    for _ in range(12):
        job = kubectl_get("job", sandbox_id) or {}
        if (job.get("status") or {}).get("completionTime"):
            break
        time.sleep(0.25)

    jmeta = job.get("metadata") or {}
    jstatus = job.get("status") or {}
    job_created = parse_ts(jmeta.get("creationTimestamp"))
    job_start = parse_ts(jstatus.get("startTime"))
    completion = parse_ts(jstatus.get("completionTime"))

    return {
        "k8s_job_created_to_start_ms": ms_between(job_created, job_start),
        "k8s_job_run_ms": ms_between(job_start, completion),
        "k8s_job_created_to_complete_ms": ms_between(job_created, completion),
    }


STARTUP_CODE = 'print("ping")'

OVERHEAD_CODE = r'''
import os, time, platform
# Guest RAM
memtotal_kb = None
with open("/proc/meminfo") as f:
    for line in f:
        if line.startswith("MemTotal:"):
            memtotal_kb = int(line.split()[1])
            break
# CPU micro-benchmark (fixed work)
t0 = time.perf_counter()
_ = sum(i * i for i in range(2_000_000))
bench_ms = (time.perf_counter() - t0) * 1000
cpus = os.cpu_count() or 0
print(f"MEMTOTAL_KB={memtotal_kb}")
print(f"BENCH_MS={bench_ms:.2f}")
print(f"CPUS={cpus}")
print(f"UNAME={platform.machine()}")
'''.strip()


@dataclass
class RunRow:
    vm: str
    iteration: int
    warmup: bool
    api_wall_ms: float
    status: str
    exit_code: int | None
    k8s_job_created_to_start_ms: float | None = None
    k8s_job_run_ms: float | None = None
    k8s_job_created_to_complete_ms: float | None = None
    metrics_cpu_peak_m: float | None = None
    metrics_mem_peak_bytes: int | None = None


@dataclass
class OverheadRow:
    vm: str
    memtotal_kb: int | None
    bench_ms: float | None
    cpus: int | None


rows: list[RunRow] = []
overheads: list[OverheadRow] = []


def post_poll(vm: str, code: str, *, iteration: int, warmup: bool) -> RunRow:
    body = {
        "sandbox_template": "sandboxkit-py-template",
        "actual_code": code,
        "vm_choice": vm,
        "is_polling": True,
        "cpu_limit": CPU_LIMIT,
        "memory_limit": MEMORY_LIMIT,
    }
    t0 = time.perf_counter()
    http, data = curl_json("POST", f"{BASE}/sandboxes", body)
    if http not in (200, 202) or not isinstance(data, dict):
        raise RuntimeError(f"POST failed http={http} body={data!r}")
    sid = data.get("sandbox_id", "")
    if not sid:
        raise RuntimeError(f"no sandbox_id in {data}")

    peak_cpu, peak_mem = None, None
    status = data.get("status", "")
    poll: dict | str = data
    while status not in ("completed", "failed"):
        peak_cpu, peak_mem = sample_pod_metrics(sid, peak_cpu, peak_mem)
        time.sleep(POLL_INTERVAL)
        _, poll = curl_json("GET", f"{BASE}/sandboxes/{sid}")
        if isinstance(poll, dict):
            status = poll.get("status", status)
        if time.perf_counter() - t0 > 120:
            break

    api_wall_ms = (time.perf_counter() - t0) * 1000
    time.sleep(0.3)
    kt = k8s_timings(sid)
    exit_code = poll.get("exit_code") if isinstance(poll, dict) else None

    return RunRow(
        vm=vm,
        iteration=iteration,
        warmup=warmup,
        api_wall_ms=api_wall_ms,
        status=status,
        exit_code=exit_code,
        k8s_job_created_to_start_ms=kt.get("k8s_job_created_to_start_ms"),
        k8s_job_run_ms=kt.get("k8s_job_run_ms"),
        k8s_job_created_to_complete_ms=kt.get("k8s_job_created_to_complete_ms"),
        metrics_cpu_peak_m=peak_cpu,
        metrics_mem_peak_bytes=peak_mem,
    )


def run_overhead_probe(vm: str) -> OverheadRow:
    http, data = curl_json(
        "POST",
        f"{BASE}/sandboxes",
        {
            "sandbox_template": "sandboxkit-py-template",
            "actual_code": OVERHEAD_CODE,
            "vm_choice": vm,
            "is_polling": False,
            "cpu_limit": CPU_LIMIT,
            "memory_limit": MEMORY_LIMIT,
        },
    )
    if http not in (200, 202) or not isinstance(data, dict):
        raise RuntimeError(f"overhead POST {vm}: http={http} {data!r}")
    stdout = data.get("stdout") or ""
    mem_kb = bench = cpus = None
    for line in stdout.splitlines():
        if line.startswith("MEMTOTAL_KB="):
            mem_kb = int(line.split("=", 1)[1])
        elif line.startswith("BENCH_MS="):
            bench = float(line.split("=", 1)[1])
        elif line.startswith("CPUS="):
            cpus = int(line.split("=", 1)[1])
    return OverheadRow(vm=vm, memtotal_kb=mem_kb, bench_ms=bench, cpus=cpus)


login()

print("\n==> Startup benchmark (minimal code, polling mode)")
for vm in VM_CHOICES:
    print(f"\n--- {vm} ---")
    total = WARMUP + ITERATIONS
    for i in range(total):
        is_warmup = i < WARMUP
        label = "warmup" if is_warmup else f"run {i - WARMUP + 1}/{ITERATIONS}"
        try:
            row = post_poll(vm, STARTUP_CODE, iteration=i, warmup=is_warmup)
            rows.append(row)
            print(
                f"  {label}: api={row.api_wall_ms:.0f}ms "
                f"k8s_job={row.k8s_job_created_to_complete_ms}ms "
                f"status={row.status} exit={row.exit_code}"
            )
        except Exception as e:
            print(f"  {label}: ERROR {e}", file=sys.stderr)
        time.sleep(0.5)

print("\n==> Guest overhead probe (meminfo + CPU bench, sync)")
for vm in VM_CHOICES:
    try:
        oh = run_overhead_probe(vm)
        overheads.append(oh)
        print(
            f"  {vm}: MemTotal={oh.memtotal_kb} KiB bench={oh.bench_ms}ms cpus={oh.cpus}"
        )
    except Exception as e:
        print(f"  {vm}: ERROR {e}", file=sys.stderr)
    time.sleep(0.5)


# --- Stats ---
def stat_vals(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {}
    return {
        "min": min(vals),
        "p50": statistics.median(vals),
        "max": max(vals),
        "mean": statistics.mean(vals),
    }


measured = [r for r in rows if not r.warmup and r.status == "completed"]
with open(RESULTS_CSV, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(
        [
            "vm",
            "iteration",
            "api_wall_ms",
            "k8s_job_created_to_start_ms",
            "k8s_job_run_ms",
            "k8s_job_created_to_complete_ms",
            "metrics_cpu_peak_m",
            "metrics_mem_peak_bytes",
            "status",
            "exit_code",
        ]
    )
    for r in measured:
        w.writerow(
            [
                r.vm,
                r.iteration,
                f"{r.api_wall_ms:.1f}",
                r.k8s_job_created_to_start_ms,
                r.k8s_job_run_ms,
                r.k8s_job_created_to_complete_ms,
                r.metrics_cpu_peak_m,
                r.metrics_mem_peak_bytes,
                r.status,
                r.exit_code,
            ]
        )

print(f"\n==> Raw CSV: {RESULTS_CSV}")

print("\n================================================================")
print("SUMMARY (completed runs only, excluding warmup)")
print("================================================================")
print(
    f"{'VM':<14} {'API p50':>10} {'K8s job p50':>12} {'K8s run p50':>12} "
    f"{'CPU peak p50':>12} {'Mem peak p50':>12}"
)
print("-" * 78)

summary: dict[str, dict] = {}
for vm in VM_CHOICES:
    subset = [r for r in measured if r.vm == vm]
    api = [r.api_wall_ms for r in subset]
    kjob = [r.k8s_job_created_to_complete_ms for r in subset if r.k8s_job_created_to_complete_ms is not None]
    krun = [r.k8s_job_run_ms for r in subset if r.k8s_job_run_ms is not None]
    cpu = [r.metrics_cpu_peak_m for r in subset if r.metrics_cpu_peak_m is not None]
    mem = [r.metrics_mem_peak_bytes for r in subset if r.metrics_mem_peak_bytes is not None]
    sa, sk, srun = stat_vals(api), stat_vals(kjob), stat_vals(krun)
    sc, sm = stat_vals(cpu), stat_vals(mem)
    summary[vm] = {"api": sa, "kjob": sk, "krun": srun, "cpu": sc, "mem": sm}
    mem_mib = f"{sm.get('p50', 0) / (1024 * 1024):.1f}Mi" if sm else "n/a"
    print(
        f"{vm:<14} "
        f"{sa.get('p50', 0):>9.0f}ms "
        f"{sk.get('p50', 0) if sk else 0:>11.0f}ms "
        f"{srun.get('p50', 0) if srun else 0:>11.0f}ms "
        f"{sc.get('p50', 0) if sc else 0:>11.0f}m "
        f"{mem_mib:>12}"
    )

print("\n==> Guest overhead (single sync run per VM)")
print(f"{'VM':<14} {'MemTotal (KiB)':>16} {'CPU bench (ms)':>16} {'vCPUs seen':>12}")
print("-" * 60)
for oh in overheads:
    print(f"{oh.vm:<14} {oh.memtotal_kb or 0:>16} {oh.bench_ms or 0:>16.1f} {oh.cpus or 0:>12}")

# Rankings for conclusion
if len(VM_CHOICES) >= 2 and all(summary.get(v, {}).get("api") for v in VM_CHOICES):
    fastest_api = min(VM_CHOICES, key=lambda v: summary[v]["api"].get("p50", 1e9))
    slowest_api = max(VM_CHOICES, key=lambda v: summary[v]["api"].get("p50", 0))
    print("\n================================================================")
    print("CONCLUSIONS")
    print("================================================================")
    print(
        f"• Fastest end-to-end (API p50): {fastest_api} "
        f"({summary[fastest_api]['api']['p50']:.0f}ms) vs "
        f"{slowest_api} ({summary[slowest_api]['api']['p50']:.0f}ms)."
    )
    if overheads:
        by_mem = sorted(overheads, key=lambda o: o.memtotal_kb or 0)
        by_bench = sorted(overheads, key=lambda o: o.bench_ms or 1e9)
        print(
            f"• Lowest guest MemTotal: {by_mem[0].vm} ({by_mem[0].memtotal_kb} KiB); "
            f"highest: {by_mem[-1].vm} ({by_mem[-1].memtotal_kb} KiB)."
        )
        print(
            f"• Fastest in-guest CPU bench: {by_bench[0].vm} ({by_bench[0].bench_ms:.1f}ms); "
            f"slowest: {by_bench[-1].vm} ({by_bench[-1].bench_ms:.1f}ms)."
        )
    print(
        "• API wall time includes control-plane polling + Job scheduling + microVM boot + code run."
    )
    print(
        "• K8s job duration = Batch Job startTime→completionTime (schedule + microVM boot + run)."
    )
    print(
        "• Guest MemTotal is microVM RAM seen inside the guest (~2Gi here), not the K8s limit field."
    )
    if not metrics_server_available():
        print("• metrics-server not available — CPU/RAM peak columns are n/a.")
    print(
        f"• All runs used limits cpu={CPU_LIMIT} mem={MEMORY_LIMIT}. "
        "Compare at equal limits for fair overhead."
    )
else:
    print("\n(Warning: insufficient completed runs for full conclusions)")

PY

echo ""
echo "Done."
