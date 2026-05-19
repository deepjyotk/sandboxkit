# Sample API requests — resource limits (CPU & memory)

Base URL (local kind + ingress): `http://127.0.0.1`  
See also: [sample-request.md](sample-request.md) | [sample-request2.md](sample-request2.md)

All examples use `"sandbox_template": "sandboxkit-py-template"` unless noted. For Node, use `"sandbox_template": "sandbox-js-template"` (same `cpu_limit` / `memory_limit` fields apply).

## Default limits (when not specified)

| Resource | Default request | Default limit |
|----------|-----------------|---------------|
| CPU | `100m` | `500m` |
| Memory | `64Mi` | `256Mi` |

Pass `cpu_limit` and/or `memory_limit` to override limits per request. Requests always stay at
the defaults. Formats follow the standard Kubernetes quantity syntax.

| Field | Examples |
|-------|----------|
| `cpu_limit` | `"250m"` (250 millicores), `"1"` (1 core), `"0.5"` |
| `memory_limit` | `"64Mi"`, `"128Mi"`, `"1Gi"` |

---

## Scenario 1 — Pass: within memory limit

Code allocates ~1 MB; limit is `128Mi` — well within bounds.

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "data = bytearray(1024 * 1024)\nprint(f\"allocated {len(data)} bytes — OK\")",
    "memory_limit": "128Mi",
    "is_polling": false
  }' | jq
```

Expected response:

```json
{
  "status": "completed",
  "stdout": "allocated 1048576 bytes — OK\n",
  "stderr": "",
  "exit_code": 0
}
```

---

## Scenario 2 — Fail: OOMKilled (exceeds memory limit)

Code allocates 200 MB; limit is `32Mi` — kubelet kills the container with OOMKilled (exit 137).

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "data = bytearray(200 * 1024 * 1024)\nprint(\"never reached\")",
    "memory_limit": "32Mi",
    "is_polling": false
  }' | jq
```

Expected response:

```json
{
  "status": "failed",
  "stdout": "",
  "stderr": "Container was OOMKilled (exit 137): the process exceeded the memory limit.",
  "exit_code": 137
}
```

---

## Scenario 3 — Pass: within CPU limit (`sandboxkit-py-template`)

Light arithmetic; limit is `250m` — finishes comfortably within the CPU budget.

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "result = sum(range(100_000))\nprint(\"sum:\", result)",
    "cpu_limit": "250m",
    "is_polling": false
  }' | jq
```

Expected response:

```json
{
  "status": "completed",
  "stdout": "sum: 4999950000\n",
  "stderr": "",
  "exit_code": 0
}
```

---

## Scenario 4 — Fail: CPU throttle causes timeout

Tight CPU-bound loop with a very low limit (`50m`); the kernel heavily throttles the process and
it cannot finish before the job timeout (default 60 s).

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "x = 0\nwhile True:\n    x += 1",
    "cpu_limit": "50m",
    "is_polling": false
  }' | jq
```

Expected response (after ~60 s):

```json
{
  "status": "failed",
  "stdout": "",
  "stderr": "",
  "exit_code": 1
}
```

> The job hits the `job_timeout_seconds` ceiling (60 s by default) and the control plane
> marks it as `failed`. The pod is still throttled/running in the cluster at that point;
> it will be cleaned up when you `DELETE /sandboxes/{id}` or by the K8s Job TTL.

---

## Scenario 5 — Fail: invalid format → HTTP 400

Bad format is rejected **before** any pod is created.

```bash
curl -s -w "\nHTTP:%{http_code}\n" -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "print(\"hi\")",
    "memory_limit": "two-hundred-megabytes",
    "is_polling": false
  }' | jq
```

Expected response (HTTP 400, no pod created):

```json
{
  "detail": "Invalid memory_limit 'two-hundred-megabytes': use a number with optional suffix (e.g. '64Mi', '256Mi', '1Gi')"
}
```

Same applies to a bad `cpu_limit`:

```bash
curl -s -w "\nHTTP:%{http_code}\n" -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "print(\"hi\")",
    "cpu_limit": "fast",
    "is_polling": false
  }' | jq
```

```json
{
  "detail": "Invalid cpu_limit 'fast': use millicores (e.g. '250m', '500m') or fractional cores (e.g. '0.5', '1')"
}
```

---

## Node example (`sandbox-js-template`)

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandbox-js-template",
    "actual_code": "const axios = require(\"axios\");\nconsole.log(\"axios\", axios.VERSION);",
    "memory_limit": "128Mi",
    "is_polling": false
  }' | jq
```

---

## Combine with secrets (`sandboxkit-py-template`)

Both features compose freely:

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "import os\nprint(os.environ[\"SECRET_KEY1\"])",
    "secret_names": ["SECRET_KEY1"],
    "memory_limit": "128Mi",
    "cpu_limit": "250m",
    "is_polling": false
  }' | jq
```
