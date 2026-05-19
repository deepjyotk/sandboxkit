#!/usr/bin/env bash
# Run UI test cases (mirrors ui/src/testCases.ts) against the deployed sandboxkit.
# Assumes:
#   - KUBECONFIG already exports to the DO cluster
#   - kubectl port-forward -n sandboxes svc/sandboxkit 8000:8000 is running
set -uo pipefail
BASE="${BASE:-http://127.0.0.1:8000}"

pass=0; fail=0
declare -a results

_check_resp() {
  # $1 = response body, then a list of substrings (all must match); prefix "!" to negate.
  local body="$1"; shift
  local needle ok=1
  for needle in "$@"; do
    if [[ "$needle" == !* ]]; then
      if grep -qF -- "${needle#!}" <<<"$body"; then ok=0; fi
    else
      if ! grep -qF -- "$needle" <<<"$body"; then ok=0; fi
    fi
  done
  return $((1-ok))
}

run_case() {
  local name="$1" body="$2"; shift 2
  local resp http
  resp=$(curl -s --max-time 90 -w "\n__HTTP__%{http_code}" -X POST "${BASE}/sandboxes" \
    -H "Content-Type: application/json" -d "$body")
  http="${resp##*__HTTP__}"
  resp="${resp%__HTTP__*}"
  if _check_resp "$resp" "$@"; then
    printf "PASS  %-32s  http=%s  %s\n" "$name" "$http" "$(echo "$resp" | head -c 120)"
    pass=$((pass+1))
  else
    printf "FAIL  %-32s  http=%s  body=%s\n" "$name" "$http" "$(echo "$resp" | head -c 200)"
    fail=$((fail+1))
  fi
}

echo "== Test cases =="

# 1) py fastapi + httpx
run_case "py-fastapi-httpx" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"from fastapi import FastAPI\nimport httpx\napp=FastAPI()\nprint(\"fastapi\",FastAPI.__name__)\nprint(\"httpx\",httpx.__version__)",
  "is_polling":false}' \
  '"status":"completed"' 'fastapi FastAPI' 'httpx'

# 2) py hello
run_case "py-hello" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"print(\"hello from fastapi template\")",
  "is_polling":false}' \
  '"status":"completed"' 'hello from fastapi template'

# 3) js axios
run_case "js-axios" '{
  "sandbox_template":"sandbox-js-template",
  "actual_code":"const axios=require(\"axios\");console.log(\"axios version:\",axios.VERSION);console.log(\"hello from node template\");",
  "is_polling":false}' \
  '"status":"completed"' 'axios version' 'hello from node template'

# 4) js hello
run_case "js-hello" '{
  "sandbox_template":"sandbox-js-template",
  "actual_code":"console.log(\"hello from node template\");",
  "is_polling":false}' \
  '"status":"completed"' 'hello from node template'

# 5) secret py key1 (uses vault SECRET_KEY1)
run_case "secret-py-key1" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"import os\nk=os.environ.get(\"SECRET_KEY1\")\nprint(\"SECRET_KEY1 present:\",k is not None)\nprint(\"masked:\",(k[:2]+\"***\") if k else None)",
  "secret_names":["SECRET_KEY1"],
  "is_polling":false}' \
  '"status":"completed"' 'SECRET_KEY1 present: True'

# 6) secret both keys
run_case "secret-py-both" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"import os,httpx\nk1=os.environ[\"SECRET_KEY1\"]\nk2=os.environ[\"SECRET_KEY2\"]\nprint(\"keys loaded\",len(k1),len(k2))\nprint(\"httpx\",httpx.__version__)",
  "secret_names":["SECRET_KEY1","SECRET_KEY2"],
  "is_polling":false}' \
  '"status":"completed"' 'keys loaded' 'httpx'

# 7) secret js
run_case "secret-js-key2" '{
  "sandbox_template":"sandbox-js-template",
  "actual_code":"const v=process.env.SECRET_KEY2;console.log(\"SECRET_KEY2 set:\",typeof v===\"string\");console.log(\"length:\",v?v.length:0);",
  "secret_names":["SECRET_KEY2"],
  "is_polling":false}' \
  '"status":"completed"' 'SECRET_KEY2 set: true'

# 8) unknown secret -> 400
run_case "secret-unknown-400" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"print(\"hi\")",
  "secret_names":["SECRET_KEY_DOES_NOT_EXIST"],
  "is_polling":false}' \
  'Unknown secret'

# 9) memory pass
run_case "limit-mem-pass" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"data=bytearray(1024*1024)\nprint(f\"allocated {len(data)} bytes — OK\")",
  "memory_limit":"128Mi",
  "is_polling":false}' \
  '"status":"completed"' 'allocated 1048576'

# 10) memory OOM (Kata reports SIGKILL exit_code=9; runc reports 137)
run_case "limit-mem-oom" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"data=bytearray(200*1024*1024)\nprint(\"never reached\")",
  "memory_limit":"32Mi",
  "is_polling":false}' \
  '"status":"failed"'

# 11) cpu pass
run_case "limit-cpu-pass" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"r=sum(range(100000))\nprint(\"sum:\",r)",
  "cpu_limit":"250m",
  "is_polling":false}' \
  '"status":"completed"' 'sum: 4999950000'

# 12) invalid memory -> 400
run_case "limit-invalid-mem-400" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"print(\"hi\")",
  "memory_limit":"two-hundred-megabytes",
  "is_polling":false}' \
  'Invalid memory_limit'

# 13) combo: secrets + limits
run_case "combo-secrets-limits" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"import os\nprint(os.environ[\"SECRET_KEY1\"])",
  "secret_names":["SECRET_KEY1"],
  "memory_limit":"128Mi",
  "cpu_limit":"250m",
  "is_polling":false}' \
  '"status":"completed"' '"exit_code":0'

# Polling cases — POST returns running; we then poll
poll_case() {
  local name="$1" body="$2"; shift 2
  local resp http sid status tries
  resp=$(curl -s --max-time 30 -w "\n__HTTP__%{http_code}" -X POST "${BASE}/sandboxes" \
    -H "Content-Type: application/json" -d "$body")
  http="${resp##*__HTTP__}"; resp="${resp%__HTTP__*}"
  sid=$(echo "$resp" | grep -oE '"sandbox_id":"[^"]*"' | cut -d'"' -f4)
  status=$(echo "$resp" | grep -oE '"status":"[^"]*"' | cut -d'"' -f4)
  if [[ "$status" != "running" || -z "$sid" ]]; then
    printf "FAIL  %-32s  POST did not return running: %s\n" "$name" "$resp"
    fail=$((fail+1)); return
  fi
  for tries in $(seq 1 30); do
    sleep 2
    resp=$(curl -s --max-time 10 "${BASE}/sandboxes/${sid}")
    status=$(echo "$resp" | grep -oE '"status":"[^"]*"' | cut -d'"' -f4)
    if [[ "$status" == "completed" || "$status" == "failed" ]]; then break; fi
  done
  if [[ "$status" == "completed" ]] && _check_resp "$resp" "$@"; then
    printf "PASS  %-32s  polled %s (sid=%s)\n" "$name" "$status" "$sid"
    pass=$((pass+1))
  else
    printf "FAIL  %-32s  status=%s body=%s\n" "$name" "$status" "$(echo "$resp" | head -c 200)"
    fail=$((fail+1))
  fi
}

# 14) py polling sleep
poll_case "poll-py-sleep" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"import time\ntime.sleep(2)\nprint(\"done after sleep\")",
  "is_polling":true}' \
  'done after sleep'

# 15) js polling
poll_case "poll-js-async" '{
  "sandbox_template":"sandbox-js-template",
  "actual_code":"const axios=require(\"axios\");(async()=>{await new Promise(r=>setTimeout(r,2000));console.log(\"done\",axios.VERSION);})();",
  "is_polling":true}' \
  '"stdout":"done '

# 16) poll secret
poll_case "poll-secret-py" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"import os\nprint(os.environ.get(\"SECRET_KEY1\",\"missing\"))",
  "secret_names":["SECRET_KEY1"],
  "is_polling":true}' \
  '!"stdout":"missing'

# 17) poll hello
poll_case "poll-py-hello" '{
  "sandbox_template":"sandboxkit-py-template",
  "actual_code":"print(\"hello polling\")",
  "is_polling":true}' \
  'hello polling'

echo
echo "================================================"
printf "Summary: %d PASS / %d FAIL (of %d)\n" "$pass" "$fail" "$((pass+fail))"
echo "================================================"
