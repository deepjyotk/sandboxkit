#!/usr/bin/env bash
# Prove that the sandbox is a real Kata microVM, not a runc container.
# Compares observations *inside* a sandbox pod against the host (DO droplet).
set -uo pipefail
BASE="${BASE:-http://127.0.0.1:8000}"
DROPLET="${DROPLET:-137.184.4.45}"
SSH="ssh -i $HOME/.ssh/id_ed25519_do -o StrictHostKeyChecking=accept-new root@${DROPLET}"

post() {
  local code="$1"
  # Embed code via printf %q so newlines/quotes are safe inside the JSON string.
  local payload
  payload=$(python3 -c '
import json,sys
print(json.dumps({"sandbox_template":"sandboxkit-py-template",
                  "actual_code":sys.argv[1],"is_polling":False}))
' "$code")
  curl -s --max-time 90 -X POST "${BASE}/sandboxes" \
    -H "Content-Type: application/json" -d "$payload"
}

run() {
  local label="$1" code="$2"
  echo "================================================================"
  echo "PROBE: $label"
  echo "----------------------------------------------------------------"
  local resp stdout
  resp=$(post "$code")
  stdout=$(python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("stdout",""))' <<<"$resp")
  echo "$stdout"
}

echo "================================================================"
echo "HOST (DO droplet)"
echo "----------------------------------------------------------------"
echo "kernel:    $($SSH 'uname -r')"
echo "uname:     $($SSH 'uname -a')"
echo "host /proc/version:"
$SSH 'cat /proc/version'
echo "host CPU model:"
$SSH 'grep "model name" /proc/cpuinfo | head -1'
echo "host pid 1:"
$SSH 'cat /proc/1/comm'
echo "host /dev count:"
$SSH 'ls /dev | wc -l'
echo "host /dev/kvm:"
$SSH 'ls -la /dev/kvm 2>&1'
echo "host total RAM (kB):"
$SSH 'grep MemTotal /proc/meminfo'

run "Probe 1 — kernel uname (must differ from host kernel 6.8.0-71-generic)" '
import platform, subprocess
print("uname:", platform.uname())
print("/proc/version:", open("/proc/version").read().strip())
'

run "Probe 2 — pid 1 inside sandbox (Kata: kata-agent or systemd; runc: your app)" '
print("pid 1 comm:", open("/proc/1/comm").read().strip())
print("pid count visible:", sum(1 for x in __import__("os").listdir("/proc") if x.isdigit()))
'

run "Probe 3 — /dev contents (Kata microVM: very small, no host devices)" '
import os
devs = sorted(os.listdir("/dev"))
print("total /dev entries:", len(devs))
print("entries:", devs)
print("has /dev/kvm?:", os.path.exists("/dev/kvm"))
print("has /dev/sda?:", os.path.exists("/dev/sda"))
print("has /dev/vda?:", os.path.exists("/dev/vda"))
print("has /dev/pmem0?:", os.path.exists("/dev/pmem0"))
'

run "Probe 4 — CPU model (microVM exposes host CPU via -cpu host but topology limited)" '
with open("/proc/cpuinfo") as f:
    txt = f.read()
print(txt[:600])
'

run "Probe 5 — memory (capped at sandbox memory_limit not host RAM)" '
with open("/proc/meminfo") as f:
    for line in f:
        if line.startswith(("MemTotal","MemFree","MemAvailable")):
            print(line.strip())
'

run "Probe 6 — kernel modules (microVM has its own kernel, separate module list)" '
try:
    with open("/proc/modules") as f:
        mods = f.read().splitlines()
    print("module count:", len(mods))
    print("first 10:")
    for m in mods[:10]: print(" ", m.split()[0])
except Exception as e:
    print("error:", e)
'

run "Probe 7 — try to dmesg (kernel ring buffer is the guest kernel, not host)" '
import subprocess
try:
    out = subprocess.run(["dmesg"], capture_output=True, text=True, timeout=5)
    print("rc:", out.returncode)
    print("stderr:", out.stderr[:200])
    print("stdout head:")
    print("\n".join(out.stdout.splitlines()[:10]))
except FileNotFoundError:
    print("no dmesg")
'

run "Probe 8 — try to read host kernel commandline" '
print("/proc/cmdline:", open("/proc/cmdline").read().strip())
'

run "Probe 9 — try to escape via /proc/sys (kernel params we change here must NOT affect host)" '
import os
try:
    val = open("/proc/sys/kernel/hostname").read().strip()
    print("guest hostname:", val)
except Exception as e:
    print("err:", e)
# Try writing a sysctl — should fail or only affect microVM kernel
try:
    open("/proc/sys/kernel/panic","w").write("60\n")
    print("wrote /proc/sys/kernel/panic (this only affects guest)")
except Exception as e:
    print("write blocked:", e)
'

run "Probe 10 — host filesystem accessible? (no — only kataShared mount)" '
import os
mounts = open("/proc/mounts").read()
print(mounts[:1000])
print()
print("Can see /var/lib/rancher (k3s host dir)?", os.path.exists("/var/lib/rancher"))
print("Can see host /etc/k3s files?", os.path.exists("/etc/rancher"))
'

run "Probe 11 — Capabilities & seccomp (defense in depth ON TOP of microVM)" '
caps = {}
with open("/proc/self/status") as f:
    for line in f:
        if line.startswith(("CapEff","Seccomp","NoNewPrivs","Uid")):
            caps[line.split(":")[0]] = line.split(":",1)[1].strip()
for k,v in caps.items(): print(f"{k:12} {v}")
'

run "Probe 12 — virtualization hint (CPUID flags / dmesg-style)" '
with open("/proc/cpuinfo") as f:
    flags = ""
    for line in f:
        if line.startswith("flags"): flags = line.strip(); break
print("hypervisor flag present?:", "hypervisor" in flags)
print("flags head:", flags[:300])
'

echo
echo "================================================================"
echo "Now from the HOST: list QEMU processes (one per running sandbox)"
echo "----------------------------------------------------------------"
$SSH 'ps -eo pid,comm,args --sort=start | grep "[q]emu-system" | head -3' || echo "(no live qemu — sandboxes already exited; that is normal for short jobs)"

echo
echo "================================================================"
echo "Compare: most recent sandbox pod's runtimeClass"
echo "----------------------------------------------------------------"
$SSH 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; kubectl get pods -n sandboxes -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,RUNTIME:.spec.runtimeClassName | head -20'
