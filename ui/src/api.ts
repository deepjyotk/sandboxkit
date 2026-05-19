import type { SandboxRequest } from "./testCases";

export type ExecuteResponse = {
  sandbox_id?: string;
  status?: string;
  stdout?: string | null;
  stderr?: string | null;
  exit_code?: number | null;
  detail?: string | unknown;
};

export type RunSandboxResult = {
  text: string;
  sandboxId: string | null;
  status: string | null;
};

const TERMINAL_STATUSES = new Set(["completed", "failed"]);

function formatExecuteResponse(httpStatus: number, body: ExecuteResponse): string {
  const lines = [
    `HTTP ${httpStatus}`,
    `status: ${body.status ?? "—"}`,
    `sandbox_id: ${body.sandbox_id ?? "—"}`,
    `exit_code: ${body.exit_code ?? "—"}`,
  ];
  if (body.stdout) lines.push(`--- stdout ---\n${body.stdout}`);
  if (body.stderr) lines.push(`--- stderr ---\n${body.stderr}`);
  return lines.join("\n");
}

function toRunResult(httpStatus: number, body: ExecuteResponse): RunSandboxResult {
  const formatted = formatExecuteResponse(httpStatus, body);
  return {
    text: formatted,
    sandboxId: body.sandbox_id ?? parseSandboxIdFromOutput(formatted),
    status: body.status ?? null,
  };
}

/** Parse sandbox_id from formatted actual-output text. */
export function parseSandboxIdFromOutput(output: string): string | null {
  const lineMatch = output.match(/^sandbox_id:\s*(\S+)/m);
  if (lineMatch?.[1] && lineMatch[1] !== "—") return lineMatch[1];
  const jsonMatch = output.match(/"sandbox_id"\s*:\s*"(sandbox-[^"]+)"/);
  return jsonMatch?.[1] ?? null;
}

export function isTerminalStatus(status: string | null | undefined): boolean {
  return !!status && TERMINAL_STATUSES.has(status);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function runSandbox(req: SandboxRequest): Promise<RunSandboxResult> {
  const res = await fetch("/sandboxes", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(req),
  });

  const text = await res.text();
  let body: ExecuteResponse;
  try {
    body = JSON.parse(text) as ExecuteResponse;
  } catch {
    return { text: `HTTP ${res.status}\n${text}`, sandboxId: null, status: null };
  }

  if (!res.ok) {
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail ?? body, null, 2);
    return { text: `HTTP ${res.status}\n${detail}`, sandboxId: null, status: null };
  }

  return toRunResult(res.status, body);
}

export async function getSandboxStatus(sandboxId: string): Promise<RunSandboxResult> {
  const res = await fetch(`/sandboxes/${encodeURIComponent(sandboxId)}`, {
    headers: { Accept: "application/json" },
  });

  const text = await res.text();
  let body: ExecuteResponse;
  try {
    body = JSON.parse(text) as ExecuteResponse;
  } catch {
    return { text: `HTTP ${res.status}\n${text}`, sandboxId, status: null };
  }

  if (!res.ok) {
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail ?? body, null, 2);
    return { text: `HTTP ${res.status}\n${detail}`, sandboxId, status: null };
  }

  return toRunResult(res.status, body);
}

/** Poll GET /sandboxes/{id} with 2s base delay, exponential backoff, max 8 attempts. */
export async function pollSandboxUntilDone(
  sandboxId: string,
  onAttempt?: (attempt: number, result: RunSandboxResult) => void
): Promise<string> {
  const maxAttempts = 8;
  const baseDelayMs = 2000;
  const chunks: string[] = [];

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const result = await getSandboxStatus(sandboxId);
    onAttempt?.(attempt, result);
    chunks.push(`--- poll ${attempt}/${maxAttempts} ---\n${result.text}`);

    if (isTerminalStatus(result.status)) {
      chunks.push(`\nFinished: ${result.status}`);
      return chunks.join("\n\n");
    }

    if (attempt < maxAttempts) {
      const delayMs = baseDelayMs * 2 ** (attempt - 1);
      chunks.push(`(waiting ${delayMs}ms before next poll…)`);
      await sleep(delayMs);
    }
  }

  chunks.push(`\nStopped after ${maxAttempts} polls (still not completed/failed).`);
  return chunks.join("\n\n");
}

export async function deleteSandbox(sandboxId: string): Promise<string> {
  const res = await fetch(`/sandboxes/${encodeURIComponent(sandboxId)}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });

  if (res.status === 204) {
    return `HTTP 204 — deleted ${sandboxId}`;
  }

  const text = await res.text();
  try {
    const body = JSON.parse(text) as { detail?: string };
    return `HTTP ${res.status}\n${body.detail ?? text}`;
  } catch {
    return `HTTP ${res.status}\n${text || "(empty body)"}`;
  }
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch("/health");
    return res.ok;
  } catch {
    return false;
  }
}
