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
} from "./api";
import { createCopyableCell } from "./cellChrome";
import { initialRows, type TestCaseRow } from "./testCases";

ModuleRegistry.registerModules([AllCommunityModule]);

const rowData = initialRows();
let gridApi: GridApi<TestCaseRow> | null = null;

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

function mountHeader(root: HTMLElement) {
  const header = document.createElement("header");
  header.innerHTML = `
    <h1>SandboxKit test runner</h1>
    <p>Calls ingress via Vite proxy → <code>http://127.0.0.1</code> (wiki hardcoded cases)</p>
    <div class="status-bar">
      <span id="health-status">Checking API…</span>
      <button type="button" class="run-btn" id="run-all">Run all</button>
    </div>
  `;
  root.appendChild(header);

  const gridEl = document.createElement("div");
  gridEl.id = "grid";
  gridEl.className = "ag-theme-quartz";
  root.appendChild(gridEl);

  return { gridEl, header };
}

async function refreshHealth(el: HTMLElement) {
  const ok = await checkHealth();
  el.textContent = ok ? "API: healthy (/health)" : "API: unreachable — run make infra";
  el.className = ok ? "ok" : "bad";
}

async function main() {
  const root = document.getElementById("app");
  if (!root) return;

  const { gridEl, header } = mountHeader(root);
  const healthEl = header.querySelector("#health-status") as HTMLElement;
  void refreshHealth(healthEl);

  gridApi = createGrid(gridEl, {
    rowData,
    columnDefs,
    defaultColDef: { resizable: true, sortable: true, filter: true },
    animateRows: true,
    getRowId: (p) => p.data.id,
  });

  header.querySelector("#run-all")?.addEventListener("click", async () => {
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

void main();
