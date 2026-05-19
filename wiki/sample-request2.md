# Sample API requests — secrets via simulated vault

Base URL (local kind + ingress): `http://127.0.0.1`  
See also: [sample-request.md](sample-request.md) for templates without secrets.

Use `sandbox_template`: **`sandboxkit-py-template`** (Python) or **`sandbox-js-template`** (Node). Examples below use Python unless noted.

## Vault keys (names only in requests)

| Name | Injected as env var | Example value (in vault, not in API) |
|------|---------------------|--------------------------------------|
| `SECRET_KEY1` | `SECRET_KEY1` | `secret-value1` |
| `SECRET_KEY2` | `SECRET_KEY2` | `secret-value2` |

Send **`secret_names`** in the POST body — never secret values. The control plane resolves names at provision time and creates a per-run Kubernetes Secret; the Job pod receives them as environment variables.

---

## `sandboxkit-py-template` — read `SECRET_KEY1` (sync)

### JSON body

```json
{
  "sandbox_template": "sandboxkit-py-template",
  "actual_code": "import os\nkey = os.environ.get(\"SECRET_KEY1\")\nprint(\"SECRET_KEY1 present:\", key is not None)\nprint(\"masked:\", (key[:2] + \"***\") if key else None)",
  "secret_names": ["SECRET_KEY1"],
  "is_polling": false
}
```

### curl

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "import os\nkey = os.environ.get(\"SECRET_KEY1\")\nprint(\"SECRET_KEY1 present:\", key is not None)\nprint(\"masked:\", (key[:2] + \"***\") if key else None)",
    "secret_names": ["SECRET_KEY1"],
    "is_polling": false
  }' | jq
```

---

## Python — both keys + httpx (sync)

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "import os\nimport httpx\nk1 = os.environ[\"SECRET_KEY1\"]\nk2 = os.environ[\"SECRET_KEY2\"]\nprint(\"keys loaded\", len(k1), len(k2))\nprint(\"httpx\", httpx.__version__)",
    "secret_names": ["SECRET_KEY1", "SECRET_KEY2"],
    "is_polling": false
  }' | jq
```

---

## `sandbox-js-template` — `process.env.SECRET_KEY2` (sync)

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandbox-js-template",
    "actual_code": "const v = process.env.SECRET_KEY2;\nconsole.log(\"SECRET_KEY2 set:\", typeof v === \"string\");\nconsole.log(\"length:\", v ? v.length : 0);",
    "secret_names": ["SECRET_KEY2"],
    "is_polling": false
  }' | jq
```

---

## Polling with secrets

Submit async, then poll until complete:

```bash
RESP=$(curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "import os\nprint(os.environ.get(\"SECRET_KEY1\", \"missing\"))",
    "secret_names": ["SECRET_KEY1"],
    "is_polling": true
  }')
echo "$RESP" | jq
SID=$(echo "$RESP" | jq -r .sandbox_id)

until [ "$(curl -s "http://127.0.0.1/sandboxes/$SID" | jq -r .status)" = "completed" ]; do
  sleep 1
done
curl -s "http://127.0.0.1/sandboxes/$SID" | jq
```

---

## Unknown secret name (expected HTTP 400)

```bash
curl -s -X POST http://127.0.0.1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "actual_code": "print(\"hi\")",
    "secret_names": ["SECRET_KEY_DOES_NOT_EXIST"],
    "is_polling": false
  }' | jq
```

Example response:

```json
{
  "detail": "Unknown secret name(s): ['SECRET_KEY_DOES_NOT_EXIST']. Available: ['SECRET_KEY1', 'SECRET_KEY2']"
}
```

---

## Cleanup

```bash
curl -s -X DELETE "http://127.0.0.1/sandboxes/$SID"
```

Deletes the Job, ConfigMap, and per-run Secret (if any).
