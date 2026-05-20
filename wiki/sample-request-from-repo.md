# Sample request — `POST /sandboxes/from-repo`

Run code from a **public GitHub repo** inside a Kata microVM, with the cloned
directory shared into the guest over **virtio-fs**. On `DELETE`, the per-sandbox
host directory is removed before the API returns 204.

Auth, base URL, and ingress behavior are identical to `POST /sandboxes` — see
[sample-request.md](sample-request.md) for the login flow.

---

## Lifecycle

```
POST /sandboxes/from-repo
  1. Clone Job (alpine/git, hostPath) -> /var/lib/sandboxkit/repos/<id>/repo
  2. Sandbox Job (kata-qemu) mounts that dir read-only at /sandbox/repo via virtio-fs
  3. Container command runs the user-specified entrypoint
     (logs "virtio-fs mount probe" output first so you can see the mount type)

DELETE /sandboxes/<id>
  1. Delete sandbox Job  -> Pod terminates  -> virtio-fs unmounts as VM shuts down
  2. Delete clone Job    (best-effort)
  3. Cleanup Job (busybox, hostPath /var/lib/sandboxkit/repos)
        runs: rm -rf /host/<id>
  4. API waits for cleanup Job to complete, THEN returns 204
```

---

## Request body

| Field | Required | Notes |
|-------|----------|-------|
| `sandbox_template` | yes | `sandboxkit-py-template` or `sandbox-js-template` |
| `github_repo_url` | yes | `https://github.com/<owner>/<repo>(.git)?` only — non-GitHub hosts rejected |
| `entrypoint` | yes | Relative path inside the repo (e.g. `main.py`, `src/index.ts`). No leading `/`, no `..` |
| `git_ref` | no | Branch / tag / commit. Default: repo HEAD |
| `vm_choice` | no | `kata-qemu` (default; virtio-fs reliable) or `kata-fc` (response header `X-VirtioFS-Mode: experimental-fc`) |
| `is_polling` | no | Same semantics as `POST /sandboxes` |
| `secret_names` | no | Same vault-backed env injection |
| `cpu_limit`, `memory_limit` | no | Same K8s quantity strings |

---

## Sync example (Python)

```bash
curl -s -b /tmp/sbx-cookie.txt -X POST http://127.0.0.1/sandboxes/from-repo \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandboxkit-py-template",
    "github_repo_url": "https://github.com/deepjyotk/sandboxkit-demo-hello",
    "entrypoint": "main.py",
    "vm_choice": "kata-qemu",
    "is_polling": false
  }' | jq
```

Response:

```json
{
  "sandbox_id": "sandbox-7c1d4e9a",
  "status": "completed",
  "stdout": "--- virtio-fs mount probe ---\nkataShared on /sandbox/repo type virtiofs (ro,relatime)\n--- entrypoint ---\nhello from github\n",
  "stderr": "",
  "exit_code": 0
}
```

The `virtio-fs mount probe` line proves the share is going through virtio-fs;
on `kata-qemu` you'll typically see something like `kataShared on /sandbox/repo
type virtiofs (...)`.

---

## TypeScript example

```bash
curl -s -b /tmp/sbx-cookie.txt -X POST http://127.0.0.1/sandboxes/from-repo \
  -H "Content-Type: application/json" \
  -d '{
    "sandbox_template": "sandbox-js-template",
    "github_repo_url": "https://github.com/deepjyotk/sandboxkit-demo-hello-ts",
    "entrypoint": "src/index.ts",
    "is_polling": false
  }' | jq
```

---

## Polling example

```bash
sandbox_id=$(curl -s -b /tmp/sbx-cookie.txt -X POST http://127.0.0.1/sandboxes/from-repo \
  -H "Content-Type: application/json" \
  -d '{"sandbox_template":"sandboxkit-py-template","github_repo_url":"https://github.com/deepjyotk/sandboxkit-demo-hello","entrypoint":"main.py","is_polling":true}' \
  | jq -r .sandbox_id)

# Poll until done
while :; do
  r=$(curl -s -b /tmp/sbx-cookie.txt http://127.0.0.1/sandboxes/$sandbox_id)
  s=$(jq -r .status <<<"$r")
  echo "status=$s"
  [[ "$s" == "completed" || "$s" == "failed" ]] && { echo "$r" | jq; break; }
  sleep 1
done
```

---

## Cleanup

```bash
curl -s -b /tmp/sbx-cookie.txt -X DELETE http://127.0.0.1/sandboxes/$sandbox_id -w "%{http_code}\n"
# 204
# The host directory /var/lib/sandboxkit/repos/<id> is gone before the 204 returns.
```

Verify on the droplet:

```bash
ssh root@<droplet> 'ls /var/lib/sandboxkit/repos/<id>'
# -> No such file or directory
```

---

## Validation errors

| Body | Response |
|------|----------|
| `github_repo_url: https://gitlab.com/foo/bar` | `422` — only `github.com` accepted (SSRF guard) |
| `entrypoint: ../escape.py` | `422` — `..` segments rejected |
| `entrypoint: /etc/passwd` | `422` — leading `/` rejected |
| `git_ref` contains `;` | `422` — only `[A-Za-z0-9_./-]` accepted |
| `sandbox_template` not in registry | `400` — `Unknown sandbox_template` |

---

## Caveats

- **Single-node assumption:** hostPath is per-node. On a multi-node cluster
  the clone Job, sandbox Job, and cleanup Job all need to land on the same
  node — pin with a `nodeSelector` (out of scope for this slice).
- **`kata-fc`:** allowed but virtio-fs support on Firecracker has lagged
  QEMU historically. Header `X-VirtioFS-Mode: experimental-fc` is returned
  so callers know.
- **Auto-cleanup on Job TTL:** if the control plane never sees `DELETE` (e.g.
  process crash), the host directory is **not** automatically reclaimed by
  K8s TTL. A reconciler that lists orphan host dirs vs Jobs would close that
  gap — not implemented in this slice.
