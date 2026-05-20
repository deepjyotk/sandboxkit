/** Hardcoded wiki test cases — mirrors sample-request*.md */

export type SandboxRequest = {
  sandbox_template: string;
  actual_code: string;
  is_polling: boolean;
  /** Kata RuntimeClass: kata-qemu (default) or kata-fc */
  vm_choice?: "kata-qemu" | "kata-fc";
  secret_names?: string[];
  cpu_limit?: string;
  memory_limit?: string;
};

export type TestCaseRow = {
  id: string;
  name: string;
  description: string;
  category: string;
  code: string;
  request: SandboxRequest;
  expectedOutput: string;
  actualOutput: string;
  sandboxId: string | null;
  running: boolean;
  deleting: boolean;
  polling: boolean;
};

export const TEST_CASES: Omit<
  TestCaseRow,
  "actualOutput" | "sandboxId" | "running" | "deleting" | "polling"
>[] = [
  {
    id: "py-fastapi-httpx",
    name: "PY — FastAPI + httpx",
    description: "sample-request.md: import fastapi and httpx, print versions",
    category: "basic",
    code: `from fastapi import FastAPI
import httpx

app = FastAPI()
print("fastapi", FastAPI.__name__)
print("httpx", httpx.__version__)`,
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: `from fastapi import FastAPI
import httpx

app = FastAPI()
print("fastapi", FastAPI.__name__)
print("httpx", httpx.__version__)`,
      is_polling: false,
    },
    expectedOutput: `status: completed
exit_code: 0
stdout contains: fastapi FastAPI
stdout contains: httpx`,
  },
  {
    id: "py-hello",
    name: "PY — minimal hello",
    description: "sample-request.md: simple print",
    category: "basic",
    code: 'print("hello from fastapi template")',
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: 'print("hello from fastapi template")',
      is_polling: false,
    },
    expectedOutput: `status: completed
exit_code: 0
stdout: hello from fastapi template`,
  },
  {
    id: "js-axios",
    name: "JS — axios hello",
    description: "sample-request.md: axios VERSION + hello",
    category: "basic",
    code: `const axios = require("axios");
console.log("axios version:", axios.VERSION);
console.log("hello from node template");`,
    request: {
      sandbox_template: "sandbox-js-template",
      actual_code: `const axios = require("axios");
console.log("axios version:", axios.VERSION);
console.log("hello from node template");`,
      is_polling: false,
    },
    expectedOutput: `status: completed
exit_code: 0
stdout contains: axios version
stdout contains: hello from node template`,
  },
  {
    id: "js-hello",
    name: "JS — minimal hello",
    description: "sample-request.md: node hello",
    category: "basic",
    code: 'console.log("hello from node template");',
    request: {
      sandbox_template: "sandbox-js-template",
      actual_code: 'console.log("hello from node template");',
      is_polling: false,
    },
    expectedOutput: `status: completed
exit_code: 0
stdout: hello from node template`,
  },
  {
    id: "secret-py-key1",
    name: "PY — SECRET_KEY1 masked",
    description: "sample-request2.md: os.environ.get SECRET_KEY1",
    category: "secrets",
    code: `import os
key = os.environ.get("SECRET_KEY1")
print("SECRET_KEY1 present:", key is not None)
print("masked:", (key[:2] + "***") if key else None)`,
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: `import os
key = os.environ.get("SECRET_KEY1")
print("SECRET_KEY1 present:", key is not None)
print("masked:", (key[:2] + "***") if key else None)`,
      secret_names: ["SECRET_KEY1"],
      is_polling: false,
    },
    expectedOutput: `status: completed
exit_code: 0
stdout contains: SECRET_KEY1 present: True
stdout contains: masked: se***`,
  },
  {
    id: "secret-py-both-keys",
    name: "PY — both secrets + httpx",
    description: "sample-request2.md: SECRET_KEY1 and SECRET_KEY2",
    category: "secrets",
    code: `import os
import httpx
k1 = os.environ["SECRET_KEY1"]
k2 = os.environ["SECRET_KEY2"]
print("keys loaded", len(k1), len(k2))
print("httpx", httpx.__version__)`,
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: `import os
import httpx
k1 = os.environ["SECRET_KEY1"]
k2 = os.environ["SECRET_KEY2"]
print("keys loaded", len(k1), len(k2))
print("httpx", httpx.__version__)`,
      secret_names: ["SECRET_KEY1", "SECRET_KEY2"],
      is_polling: false,
    },
    expectedOutput: `status: completed
exit_code: 0
stdout contains: keys loaded`,
  },
  {
    id: "secret-js-key2",
    name: "JS — SECRET_KEY2",
    description: "sample-request2.md: process.env.SECRET_KEY2",
    category: "secrets",
    code: `const v = process.env.SECRET_KEY2;
console.log("SECRET_KEY2 set:", typeof v === "string");
console.log("length:", v ? v.length : 0);`,
    request: {
      sandbox_template: "sandbox-js-template",
      actual_code: `const v = process.env.SECRET_KEY2;
console.log("SECRET_KEY2 set:", typeof v === "string");
console.log("length:", v ? v.length : 0);`,
      secret_names: ["SECRET_KEY2"],
      is_polling: false,
    },
    expectedOutput: `status: completed
exit_code: 0
stdout contains: SECRET_KEY2 set: true`,
  },
  {
    id: "secret-unknown",
    name: "PY — unknown secret (400)",
    description: "sample-request2.md: invalid secret name before pod runs",
    category: "secrets",
    code: 'print("hi")',
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: 'print("hi")',
      secret_names: ["SECRET_KEY_DOES_NOT_EXIST"],
      is_polling: false,
    },
    expectedOutput: `HTTP 400
detail contains: Unknown secret name`,
  },
  {
    id: "limit-mem-pass",
    name: "PY — memory within 128Mi",
    description: "sample-request3.md scenario 1",
    category: "limits",
    code: `data = bytearray(1024 * 1024)
print(f"allocated {len(data)} bytes — OK")`,
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: `data = bytearray(1024 * 1024)
print(f"allocated {len(data)} bytes — OK")`,
      memory_limit: "128Mi",
      is_polling: false,
    },
    expectedOutput: `status: completed
exit_code: 0
stdout: allocated 1048576 bytes — OK`,
  },
  {
    id: "limit-mem-oom",
    name: "PY — OOM 32Mi",
    description: "sample-request3.md scenario 2 — OOMKilled",
    category: "limits",
    code: `data = bytearray(200 * 1024 * 1024)
print("never reached")`,
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: `data = bytearray(200 * 1024 * 1024)
print("never reached")`,
      memory_limit: "32Mi",
      is_polling: false,
    },
    expectedOutput: `status: failed
exit_code: 137
stderr contains: OOMKilled`,
  },
  {
    id: "limit-cpu-pass",
    name: "PY — CPU 250m pass",
    description: "sample-request3.md scenario 3",
    category: "limits",
    code: `result = sum(range(100_000))
print("sum:", result)`,
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: `result = sum(range(100_000))
print("sum:", result)`,
      cpu_limit: "250m",
      is_polling: false,
    },
    expectedOutput: `status: completed
exit_code: 0
stdout contains: sum: 4999950000`,
  },
  {
    id: "limit-invalid-mem",
    name: "PY — invalid memory_limit (400)",
    description: "sample-request3.md scenario 5",
    category: "limits",
    code: 'print("hi")',
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: 'print("hi")',
      memory_limit: "two-hundred-megabytes",
      is_polling: false,
    },
    expectedOutput: `HTTP 400
detail contains: Invalid memory_limit`,
  },
  {
    id: "combo-secrets-limits",
    name: "PY — secrets + limits",
    description: "sample-request3.md: SECRET_KEY1 with cpu/memory limits",
    category: "combo",
    code: `import os
print(os.environ["SECRET_KEY1"])`,
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: `import os
print(os.environ["SECRET_KEY1"])`,
      secret_names: ["SECRET_KEY1"],
      memory_limit: "128Mi",
      cpu_limit: "250m",
      is_polling: false,
    },
    expectedOutput: `status: completed
exit_code: 0
stdout contains: secret-value1 (value not echoed in API; check stdout non-empty)`,
  },
  {
    id: "poll-py-sleep",
    name: "PY — polling (sleep 2s)",
    description: "sample-request.md: is_polling true, poll until completed",
    category: "polling",
    code: `import time
time.sleep(2)
print("done after sleep")`,
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: `import time
time.sleep(2)
print("done after sleep")`,
      is_polling: true,
    },
    expectedOutput: `POST: status running + sandbox_id
after PollForStatus: status completed
stdout: done after sleep`,
  },
  {
    id: "poll-js-async",
    name: "JS — polling (async wait)",
    description: "sample-request.md: node polling with axios delay",
    category: "polling",
    code: `const axios = require("axios");
(async () => {
  await new Promise((r) => setTimeout(r, 2000));
  console.log("done", axios.VERSION);
})();`,
    request: {
      sandbox_template: "sandbox-js-template",
      actual_code: `const axios = require("axios");
(async () => {
  await new Promise((r) => setTimeout(r, 2000));
  console.log("done", axios.VERSION);
})();`,
      is_polling: true,
    },
    expectedOutput: `POST: status running
after PollForStatus: status completed
stdout contains: done`,
  },
  {
    id: "poll-secret-py",
    name: "PY — polling + SECRET_KEY1",
    description: "sample-request2.md: async create then poll",
    category: "polling",
    code: `import os
print(os.environ.get("SECRET_KEY1", "missing"))`,
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: `import os
print(os.environ.get("SECRET_KEY1", "missing"))`,
      secret_names: ["SECRET_KEY1"],
      is_polling: true,
    },
    expectedOutput: `POST: status running
after PollForStatus: status completed
stdout contains: secret-value1 or non-empty`,
  },
  {
    id: "poll-py-hello",
    name: "PY — polling (fast hello)",
    description: "Minimal async job; quick poll success",
    category: "polling",
    code: 'print("hello polling")',
    request: {
      sandbox_template: "sandboxkit-py-template",
      actual_code: 'print("hello polling")',
      is_polling: true,
    },
    expectedOutput: `POST: status running
after PollForStatus: status completed
stdout: hello polling`,
  },
];

export function initialRows(): TestCaseRow[] {
  return TEST_CASES.map((tc) => ({
    ...tc,
    actualOutput: "",
    sandboxId: null,
    running: false,
    deleting: false,
    polling: false,
  }));
}
