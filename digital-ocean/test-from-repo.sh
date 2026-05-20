#!/usr/bin/env bash
# Smoke test for POST /sandboxes/from-repo (virtio-fs hostPath share).
#
# Verifies:
#   1. Clone Job populates the host directory on the droplet
#   2. Kata sandbox runs the user-specified entrypoint
#   3. The mount probe inside the guest shows a virtio-fs mount line
#      (or '/sandbox/repo' present in the mount table)
#   4. DELETE returns 204 only AFTER the host directory has been removed
#
# Usage (from sandboxkit/):
#   ./digital-ocean/test-from-repo.sh
#   REPO_URL=https://github.com/your/repo ENTRYPOINT=main.py \
#     ./digital-ocean/test-from-repo.sh
#
# Env knobs:
#   BASE                  control plane URL (default: DO ingress)
#   SBX_USER / SBX_PASS   login creds
#   REPO_URL              public GitHub URL (default: a tiny hello-world repo)
#   GIT_REF               optional branch/tag
#   ENTRYPOINT            relative path to run inside the repo
#   TEMPLATE              sandboxkit-py-template (default) or sandbox-js-template
#   VM_CHOICE             kata-qemu (default) or kata-fc
#   DROPLET               droplet IP for SSH cleanup verification (default: 137.184.4.45)
#   SSH_KEY               SSH key for droplet (default: ~/.ssh/id_ed25519_do)
#
set -uo pipefail

BASE="${BASE:-http://137.184.4.45:30080}"
SBX_USER="${SBX_USER:-deepjyot}"
SBX_PASS="${SBX_PASS:-Abcd}"
COOKIE_JAR="${COOKIE_JAR:-/tmp/sbx-fromrepo-cookie.txt}"

REPO_URL="${REPO_URL:-https://github.com/deepjyotk/sandboxkit-demo-hello}"
GIT_REF="${GIT_REF:-}"
ENTRYPOINT="${ENTRYPOINT:-main.py}"
TEMPLATE="${TEMPLATE:-sandboxkit-py-template}"
VM_CHOICE="${VM_CHOICE:-kata-qemu}"

DROPLET="${DROPLET:-137.184.4.45}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519_do}"
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=5"
REPO_HOST_BASE="${REPO_HOST_BASE:-/var/lib/sandboxkit/repos}"

pass=0
fail=0

_section() {
  echo
  echo "================================================================"
  echo "  $*"
  echo "================================================================"
}

_check() {
  local label="$1" ok="$2"
  if [[ "$ok" == "1" ]]; then
    printf "  PASS  %s\n" "$label"
    pass=$((pass + 1))
  else
    printf "  FAIL  %s\n" "$label"
    fail=$((fail + 1))
  fi
}

_section "Login"
rm -f "$COOKIE_JAR"
login_http=$(curl -s -o /dev/null -w "%{http_code}" \
  -c "$COOKIE_JAR" -X POST "$BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$SBX_USER\",\"password\":\"$SBX_PASS\"}")
if [[ "$login_http" != "200" ]]; then
  echo "FAIL: login HTTP $login_http"
  exit 1
fi
echo "  ok (cookie -> $COOKIE_JAR)"

_section "POST /sandboxes/from-repo (sync)"
body=$(cat <<JSON
{
  "sandbox_template": "$TEMPLATE",
  "github_repo_url": "$REPO_URL",
  ${GIT_REF:+\"git_ref\": \"$GIT_REF\",}
  "entrypoint": "$ENTRYPOINT",
  "vm_choice": "$VM_CHOICE",
  "is_polling": false
}
JSON
)
resp=$(curl -s -b "$COOKIE_JAR" --max-time 180 -w "\n__HTTP__%{http_code}" \
  -X POST "$BASE/sandboxes/from-repo" \
  -H "Content-Type: application/json" \
  -d "$body")
http="${resp##*__HTTP__}"
resp_body="${resp%__HTTP__*}"
echo "HTTP: $http"
echo "Body: $resp_body"

sandbox_id=$(echo "$resp_body" | python3 -c \
  "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('sandbox_id',''))" 2>/dev/null || echo "")
status=$(echo "$resp_body" | python3 -c \
  "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('status',''))" 2>/dev/null || echo "")
stdout=$(echo "$resp_body" | python3 -c \
  "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('stdout','') or '')" 2>/dev/null || echo "")

_check "HTTP 202 from from-repo"                "$([[ "$http" == "202" ]] && echo 1 || echo 0)"
_check "non-empty sandbox_id"                   "$([[ -n "$sandbox_id" ]] && echo 1 || echo 0)"
_check "status == completed"                    "$([[ "$status" == "completed" ]] && echo 1 || echo 0)"
_check "stdout mentions virtio-fs mount probe"  "$(grep -q 'virtio-fs mount probe' <<<"$stdout" && echo 1 || echo 0)"

# virtio-fs check: prefer 'virtiofs' on the mount line, fall back to /sandbox/repo presence
if grep -qE 'virtiofs' <<<"$stdout"; then
  vfs_ok=1
elif grep -qE '/sandbox/repo' <<<"$stdout"; then
  vfs_ok=1
else
  vfs_ok=0
fi
_check "guest mount table shows virtio-fs or /sandbox/repo" "$vfs_ok"

echo
echo "--- stdout (first 40 lines) ---"
echo "$stdout" | head -40
echo "--- end stdout ---"

if [[ -z "$sandbox_id" ]]; then
  echo
  echo "No sandbox_id; aborting cleanup checks."
  exit 1
fi

_section "Host directory exists BEFORE delete (via SSH)"
if [[ -f "$SSH_KEY" ]]; then
  host_before=$(ssh -i "$SSH_KEY" $SSH_OPTS "root@${DROPLET}" \
    "test -d ${REPO_HOST_BASE}/${sandbox_id} && echo PRESENT || echo MISSING" 2>/dev/null || echo "SSH-FAIL")
  echo "  ${REPO_HOST_BASE}/${sandbox_id} -> $host_before"
  _check "host dir present pre-delete" "$([[ "$host_before" == "PRESENT" ]] && echo 1 || echo 0)"
else
  echo "  (SSH key $SSH_KEY missing; skipping host-dir check)"
fi

_section "DELETE /sandboxes/{id} (synchronous cleanup)"
t0=$(date +%s)
del_http=$(curl -s -b "$COOKIE_JAR" --max-time 90 -o /dev/null -w "%{http_code}" \
  -X DELETE "$BASE/sandboxes/$sandbox_id")
t1=$(date +%s)
elapsed=$((t1 - t0))
echo "DELETE HTTP: $del_http (elapsed=${elapsed}s)"
_check "DELETE returned 204" "$([[ "$del_http" == "204" ]] && echo 1 || echo 0)"

_section "Host directory removed AFTER delete (via SSH)"
if [[ -f "$SSH_KEY" ]]; then
  host_after=$(ssh -i "$SSH_KEY" $SSH_OPTS "root@${DROPLET}" \
    "test -d ${REPO_HOST_BASE}/${sandbox_id} && echo PRESENT || echo MISSING" 2>/dev/null || echo "SSH-FAIL")
  echo "  ${REPO_HOST_BASE}/${sandbox_id} -> $host_after"
  _check "host dir removed post-delete" "$([[ "$host_after" == "MISSING" ]] && echo 1 || echo 0)"
else
  echo "  (SSH key $SSH_KEY missing; skipping host-dir check)"
fi

_section "Summary"
printf "  %d PASS / %d FAIL (of %d)\n" "$pass" "$fail" "$((pass + fail))"
[[ "$fail" -eq 0 ]] && exit 0 || exit 1
