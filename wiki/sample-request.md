# Sample API requests

Base URL (local kind + ingress): `http://127.0.0.1`  
Optional: `http://sandboxkit.local` if `127.0.0.1 sandboxkit.local` is in `/etc/hosts`.

Endpoint: `POST /sandboxes`

For requests that inject secrets by name, see [sample-request2.md](sample-request2.md).  
For requests with custom CPU/memory limits, see [sample-request3.md](sample-request3.md).

## `sandbox_template` values (required)

Pick **one** prebuilt runtime. The control plane maps it to a registry image (`TEMPLATE_PY_IMAGE` / `TEMPLATE_JS_IMAGE` on the cluster).

| `sandbox_template` | Runtime | Pre-installed | User code file |
|--------------------|---------|---------------|----------------|
| `sandboxkit-py-template` | Python 3.13 | fastapi, uvicorn, pydantic, httpx | `code.py` |
| `sandbox-js-template` | Node 22 | axios | `code.js` |

Any other value → HTTP **400** (`Unknown sandbox_template`).

---

## `sandboxkit-py-template` (sync — wait for result)

### JSON body

```json
{
  "sandbox_template": "sandboxkit-py-template",
  "actual_code": "from fastapi import FastAPI\nimport httpx\n\napp = FastAPI()\nprint(\"fastapi\", FastAPI.__name__)\nprint(\"httpx\", httpx.__version__)",
  "is_polling": false
}
```

### curl

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "from fastapi import FastAPI\nimport httpx\n\napp = FastAPI()\nprint(\"fastapi\", FastAPI.__name__)\nprint(\"httpx\", httpx.__version__)",
    "is_polling": false
  }' | jq
```

### Minimal hello

```json
{
  "sandbox_template": "sandboxkit-py-template",
  "actual_code": "print(\"hello from fastapi template\")",
  "is_polling": false
}
```

---

## `sandbox-js-template` (sync)

### JSON body

```json
{
  "sandbox_template": "sandbox-js-template",
  "actual_code": "const axios = require(\"axios\");\nconsole.log(\"axios version:\", axios.VERSION);\nconsole.log(\"hello from node template\");",
  "is_polling": false
}
```

### curl

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandbox-js-template",
    "actual_code": "const axios = require(\"axios\");\nconsole.log(\"axios version:\", axios.VERSION);\nconsole.log(\"hello from node template\");",
    "is_polling": false
  }' | jq
```

### Minimal hello

```json
{
  "sandbox_template": "sandbox-js-template",
  "actual_code": "console.log(\"hello from node template\");",
  "is_polling": false
}
```

---

## Polling mode (`is_polling: true`)

### `sandboxkit-py-template`

```json
{
  "sandbox_template": "sandboxkit-py-template",
  "actual_code": "import time\ntime.sleep(2)\nprint(\"done after sleep\")",
  "is_polling": true
}
```

Poll until complete:

```bash
curl -s http://127.0.0.1/sandboxes/sandbox-XXXXXXXX | jq
```

### `sandbox-js-template`

```json
{
  "sandbox_template": "sandbox-js-template",
  "actual_code": "const axios = require(\"axios\");\n(async () => {\n  await new Promise((r) => setTimeout(r, 2000));\n  console.log(\"done\", axios.VERSION);\n})();",
  "is_polling": true
}
```

---

## Expected sync response

```json
{
  "sandbox_id": "sandbox-a1b2c3d4",
  "status": "completed",
  "stdout": "...\n",
  "stderr": "",
  "exit_code": 0
}
```

Polling initial response:

```json
{
  "sandbox_id": "sandbox-a1b2c3d4",
  "status": "running"
}
```

---

## Other endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check (200) |
| `GET` | `/sandboxes/{sandbox_id}` | Poll status / results |
| `DELETE` | `/sandboxes/{sandbox_id}` | Delete Job + ConfigMap |

Interactive docs: `http://127.0.0.1/docs`
