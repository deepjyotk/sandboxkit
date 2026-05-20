import {
  ModuleRegistry,
  AllCommunityModule,
  createGrid,
  type ColDef,
  type GridApi,
  type ICellRendererParams,
} from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import "./style.css";

import {
  runSandbox,
  deleteSandbox,
  pollSandboxUntilDone,
  parseSandboxIdFromOutput,
  checkHealth,
  setUnauthorizedHandler,
} from "./api";
import { logout, me, showLoginModal, type Identity } from "./auth";
import { createCopyableCell } from "./cellChrome";
import { renderPlayground } from "./playground";
import { currentRoute, navigate, onRouteChange, type Route } from "./router";
import { initialRows, type TestCaseRow } from "./testCases";

ModuleRegistry.registerModules([AllCommunityModule]);

// Test-runner state is module-level so re-rendering the route preserves rows + grid identity.
const rowData = initialRows();
let gridApi: GridApi<TestCaseRow> | null = null;

// =============================================================================
// Test runner: cell renderers + column defs (unchanged from previous main.ts)
// =============================================================================

function textCellRenderer(
  params: ICellRendererParams<TestCaseRow>,
  getText: (row: TestCaseRow) => string
) {
  const row = params.data;
  if (!row) return document.createElement("span");
  return createCopyableCell({
    getContent: () => getText(row),
    bodyClassName: "cell-plain",
    preformatted: false,
  });
}

function codeCellRenderer(params: ICellRendererParams<TestCaseRow>) {
  const row = params.data;
  if (!row) return document.createElement("span");
  return createCopyableCell({
    getContent: () => row.code,
    bodyClassName: "cell-code",
  });
}

function requestJsonCellRenderer(params: ICellRendererParams<TestCaseRow>) {
  const row = params.data;
  if (!row) return document.createElement("span");
  return createCopyableCell({
    getContent: () => JSON.stringify(row.request, null, 2),
    bodyClassName: "cell-json",
  });
}

function expectedOutputCellRenderer(params: ICellRendererParams<TestCaseRow>) {
  const row = params.data;
  if (!row) return document.createElement("span");
  return createCopyableCell({
    getContent: () => row.expectedOutput,
    bodyClassName: "cell-expected",
  });
}

function actualOutputCellRenderer(params: ICellRendererParams<TestCaseRow>) {
  const row = params.data;
  if (!row) return document.createElement("span");
  return createCopyableCell({
    getContent: () => row.actualOutput,
    bodyClassName: "cell-output",
    clearable: true,
    onClear: () => {
      row.actualOutput = "";
      gridApi?.applyTransaction({ update: [row] });
    },
  });
}

function getActionsCopyText(row: TestCaseRow): string {
  const lines = row.request.is_polling
    ? ["Create Sandbox", "PollForStatus", "Delete Sandbox"]
    : ["Run&Create Sandbox", "Delete Sandbox"];
  const id = row.sandboxId ?? parseSandboxIdFromOutput(row.actualOutput);
  if (id) lines.push(`sandbox_id: ${id}`);
  return lines.join("\n");
}

function buildActionsBody(params: ICellRendererParams<TestCaseRow>): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = "cell-actions";

  const isPollingMode = !!params.data?.request.is_polling;

  const runBtn = document.createElement("button");
  runBtn.className = "run-btn";
  runBtn.textContent = params.data?.running
    ? "Running…"
    : isPollingMode
      ? "Create Sandbox"
      : "Run&Create Sandbox";
  runBtn.disabled =
    !!params.data?.running || !!params.data?.deleting || !!params.data?.polling;

  let pollBtn: HTMLButtonElement | null = null;
  if (isPollingMode) {
    pollBtn = document.createElement("button");
    pollBtn.className = "poll-btn";
    pollBtn.textContent = params.data?.polling ? "Polling…" : "PollForStatus";
    pollBtn.disabled =
      !!params.data?.running || !!params.data?.deleting || !!params.data?.polling;
  }

  const deleteBtn = document.createElement("button");
  deleteBtn.className = "delete-btn";
  deleteBtn.textContent = params.data?.deleting ? "Deleting…" : "Delete Sandbox";
  deleteBtn.disabled =
    !!params.data?.running || !!params.data?.deleting || !!params.data?.polling;

  const refreshActionState = () => {
    const row = params.data;
    if (!row) return;
    const id = row.sandboxId ?? parseSandboxIdFromOutput(row.actualOutput);
    const busy = !!row.running || !!row.deleting || !!row.polling;
    runBtn.disabled = busy;
    if (pollBtn) {
      pollBtn.disabled = busy || !id;
      pollBtn.textContent = row.polling ? "Polling…" : "PollForStatus";
    }
    deleteBtn.disabled = busy || !id;
  };
  refreshActionState();

  runBtn.onclick = async () => {
    const row = params.data;
    if (!row || row.running || row.polling) return;

    row.running = true;
    row.actualOutput = isPollingMode ? "Creating sandbox…" : "Running…";
    gridApi?.applyTransaction({ update: [row] });

    try {
      const result = await runSandbox(row.request);
      row.actualOutput = result.text;
      row.sandboxId = result.sandboxId;
    } catch (err) {
      row.actualOutput = `Error: ${err instanceof Error ? err.message : String(err)}`;
      row.sandboxId = null;
    } finally {
      row.running = false;
      gridApi?.applyTransaction({ update: [row] });
      refreshActionState();
    }
  };

  pollBtn?.addEventListener("click", async () => {
    const row = params.data;
    if (!row || row.running || row.deleting || row.polling) return;

    const sandboxId = row.sandboxId ?? parseSandboxIdFromOutput(row.actualOutput);
    if (!sandboxId) {
      row.actualOutput = `${row.actualOutput}\n\n(No sandbox_id — create sandbox first)`;
      gridApi?.applyTransaction({ update: [row] });
      return;
    }

    const createPart = row.actualOutput.split("\n\n--- polling ---")[0];
    row.polling = true;
    row.actualOutput = `${createPart}\n\n--- polling ---\nStarting status polls…`;
    gridApi?.applyTransaction({ update: [row] });
    refreshActionState();

    try {
      const pollLog = await pollSandboxUntilDone(sandboxId, (attempt, result) => {
        row.actualOutput = `${createPart}\n\n--- polling ---\n(latest: attempt ${attempt}, status ${result.status ?? "—"})`;
        gridApi?.applyTransaction({ update: [row] });
      });
      row.actualOutput = `${createPart}\n\n--- polling ---\n${pollLog}`;
      row.sandboxId = sandboxId;
    } catch (err) {
      row.actualOutput = `${row.actualOutput}\n\nPoll error: ${
        err instanceof Error ? err.message : String(err)
      }`;
    } finally {
      row.polling = false;
      gridApi?.applyTransaction({ update: [row] });
      refreshActionState();
    }
  });

  deleteBtn.onclick = async () => {
    const row = params.data;
    if (!row || row.running || row.deleting || row.polling) return;

    const sandboxId = row.sandboxId ?? parseSandboxIdFromOutput(row.actualOutput);
    if (!sandboxId) {
      row.actualOutput = `${row.actualOutput}\n\n(No sandbox_id — run first)`;
      gridApi?.applyTransaction({ update: [row] });
      return;
    }

    row.deleting = true;
    deleteBtn.textContent = "Deleting…";
    deleteBtn.disabled = true;
    gridApi?.applyTransaction({ update: [row] });

    try {
      const msg = await deleteSandbox(sandboxId);
      row.actualOutput = `${row.actualOutput}\n\n--- delete ---\n${msg}`;
      row.sandboxId = null;
    } catch (err) {
      row.actualOutput = `${row.actualOutput}\n\n--- delete ---\nError: ${
        err instanceof Error ? err.message : String(err)
      }`;
    } finally {
      row.deleting = false;
      gridApi?.applyTransaction({ update: [row] });
      refreshActionState();
    }
  };

  wrap.appendChild(runBtn);
  if (pollBtn) wrap.appendChild(pollBtn);
  wrap.appendChild(deleteBtn);
  return wrap;
}

function runCellRenderer(params: ICellRendererParams<TestCaseRow>) {
  const row = params.data;
  if (!row) return document.createElement("span");
  return createCopyableCell({
    getContent: () => getActionsCopyText(row),
    bodyClassName: "cell-actions-wrap",
    preformatted: false,
    bodyContent: buildActionsBody(params),
  });
}

function categoryCellRenderer(params: ICellRendererParams<TestCaseRow>) {
  const row = params.data;
  if (!row) return document.createElement("span");
  const badgeWrap = document.createElement("div");
  badgeWrap.className = "cell-badge-wrap";
  const span = document.createElement("span");
  const cat = row.category;
  span.className = `badge badge-${cat}`;
  span.textContent = cat;
  badgeWrap.appendChild(span);
  return createCopyableCell({
    getContent: () => row.category,
    bodyClassName: "cell-plain",
    preformatted: false,
    bodyContent: badgeWrap,
  });
}

const columnDefs: ColDef<TestCaseRow>[] = [
  {
    field: "name",
    headerName: "Test case",
    width: 200,
    pinned: "left",
    cellRenderer: (p: ICellRendererParams<TestCaseRow>) =>
      textCellRenderer(p, (row) => row.name),
    autoHeight: true,
    wrapText: true,
  },
  {
    field: "description",
    headerName: "Description",
    width: 260,
    wrapText: true,
    autoHeight: true,
    cellRenderer: (p: ICellRendererParams<TestCaseRow>) =>
      textCellRenderer(p, (row) => row.description),
  },
  {
    field: "category",
    headerName: "Category",
    width: 100,
    cellRenderer: categoryCellRenderer,
  },
  {
    headerName: "request-json",
    width: 300,
    cellRenderer: requestJsonCellRenderer,
    autoHeight: true,
    sortable: false,
    filter: false,
  },
  {
    field: "code",
    headerName: "Code",
    width: 320,
    cellRenderer: codeCellRenderer,
    autoHeight: true,
  },
  {
    headerName: "Actions",
    width: 168,
    pinned: "right",
    cellRenderer: runCellRenderer,
    autoHeight: true,
    sortable: false,
    filter: false,
  },
  {
    field: "actualOutput",
    headerName: "Actual output",
    flex: 1,
    minWidth: 280,
    cellRenderer: actualOutputCellRenderer,
    autoHeight: true,
  },
  {
    field: "expectedOutput",
    headerName: "Expected output",
    width: 280,
    cellRenderer: expectedOutputCellRenderer,
    autoHeight: true,
  },
];

function renderTestRunner(page: HTMLElement): void {
  page.innerHTML = "";

  const wrap = document.createElement("section");
  wrap.className = "test-runner";

  const intro = document.createElement("div");
  intro.className = "test-runner-intro";
  intro.innerHTML = `
    <div class="status-bar">
      <span id="health-status">Checking API…</span>
      <button type="button" class="run-btn" id="run-all">Run all</button>
    </div>
  `;
  wrap.appendChild(intro);

  const gridEl = document.createElement("div");
  gridEl.id = "grid";
  gridEl.className = "ag-theme-quartz";
  wrap.appendChild(gridEl);

  page.appendChild(wrap);

  const healthEl = intro.querySelector("#health-status") as HTMLElement;
  void refreshHealth(healthEl);

  gridApi = createGrid(gridEl, {
    rowData,
    columnDefs,
    defaultColDef: { resizable: true, sortable: true, filter: true },
    animateRows: true,
    getRowId: (p) => p.data.id,
  });

  intro.querySelector("#run-all")?.addEventListener("click", async () => {
    for (const row of rowData) {
      if (row.running || row.deleting) continue;
      row.running = true;
      row.actualOutput = "Running…";
      gridApi?.applyTransaction({ update: [row] });
      try {
        const result = await runSandbox(row.request);
        row.actualOutput = result.text;
        row.sandboxId = result.sandboxId;
      } catch (err) {
        row.actualOutput = `Error: ${err instanceof Error ? err.message : String(err)}`;
        row.sandboxId = null;
      }
      row.running = false;
      gridApi?.applyTransaction({ update: [row] });
    }
  });
}

// =============================================================================
// Shared chrome (header + nav tabs + identity + logout) used by both routes
// =============================================================================

type ChromeHandle = {
  page: HTMLElement;
  setIdentity: (id: Identity) => void;
  highlightRoute: (r: Route) => void;
};

function mountChrome(root: HTMLElement, identity: Identity): ChromeHandle {
  const header = document.createElement("header");
  header.innerHTML = `
    <h1>SandboxKit</h1>
    <p>Calls ingress via Vite proxy (cookie auth flows through nginx).</p>
    <div class="status-bar">
      <nav class="nav-tabs">
        <button type="button" class="nav-tab" data-route="test-runner">Test Runner</button>
        <button type="button" class="nav-tab" data-route="playground">Playground</button>
      </nav>
      <span class="auth-user">Signed in as <strong>${identity.user_id}</strong> (${identity.role})</span>
      <button type="button" class="delete-btn" id="logout-btn">Logout</button>
    </div>
  `;
  root.appendChild(header);

  const page = document.createElement("main");
  page.id = "page";
  page.className = "page";
  root.appendChild(page);

  header.querySelectorAll<HTMLButtonElement>(".nav-tab").forEach((btn) => {
    btn.addEventListener("click", () => navigate(btn.dataset.route as Route));
  });

  header.querySelector("#logout-btn")?.addEventListener("click", async () => {
    await logout();
    const next = await showLoginModal();
    setIdentity(next);
  });

  const setIdentity = (id: Identity) => {
    const userEl = header.querySelector(".auth-user");
    if (userEl) {
      userEl.innerHTML = `Signed in as <strong>${id.user_id}</strong> (${id.role})`;
    }
  };

  const highlightRoute = (r: Route) => {
    header.querySelectorAll<HTMLButtonElement>(".nav-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.route === r);
    });
  };

  return { page, setIdentity, highlightRoute };
}

async function refreshHealth(el: HTMLElement) {
  const ok = await checkHealth();
  el.textContent = ok ? "API: healthy (/health)" : "API: unreachable — run make infra";
  el.className = ok ? "ok" : "bad";
}

async function ensureSignedIn(): Promise<Identity> {
  const existing = await me();
  if (existing) return existing;
  return showLoginModal();
}

// =============================================================================
// Boot
// =============================================================================

async function main() {
  const root = document.getElementById("app");
  if (!root) return;

  const identity = await ensureSignedIn();

  root.innerHTML = "";
  const chrome = mountChrome(root, identity);

  setUnauthorizedHandler(() => {
    void showLoginModal().then((id) => chrome.setIdentity(id));
  });

  const renderRoute = () => {
    const r = currentRoute();
    chrome.highlightRoute(r);
    if (r === "playground") {
      gridApi = null;
      renderPlayground(chrome.page);
    } else {
      renderTestRunner(chrome.page);
    }
  };

  onRouteChange(renderRoute);
  renderRoute();
}

void main();
