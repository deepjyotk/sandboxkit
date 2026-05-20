/** Playground page: template + code editor + secrets + polling + cpu/mem -> POST /sandboxes. */

import { pollSandboxUntilDone, runSandbox } from "./api";
import { createEditor, type EditorHandle } from "./codeEditor";
import {
  CPU_LIMITS,
  MEMORY_LIMITS,
  SECRETS,
  TEMPLATES,
  VM_CHOICES,
  type TemplateOption,
} from "./constants";
import type { SandboxRequest } from "./testCases";

/** Build a labelled <select> with given options. Returns the <select>. */
function buildSelect(
  options: { value: string; label: string }[],
  initial?: string,
): HTMLSelectElement {
  const sel = document.createElement("select");
  sel.className = "playground-input";
  for (const opt of options) {
    const o = document.createElement("option");
    o.value = opt.value;
    o.textContent = opt.label;
    if (initial !== undefined && opt.value === initial) o.selected = true;
    sel.appendChild(o);
  }
  return sel;
}

function buildRow(labelText: string, control: HTMLElement, hint?: string): HTMLElement {
  const row = document.createElement("div");
  row.className = "playground-row";
  const label = document.createElement("label");
  label.className = "playground-label";
  label.textContent = labelText;
  row.appendChild(label);
  row.appendChild(control);
  if (hint) {
    const h = document.createElement("div");
    h.className = "playground-hint";
    h.textContent = hint;
    row.appendChild(h);
  }
  return row;
}

export function renderPlayground(container: HTMLElement): void {
  container.innerHTML = "";

  const root = document.createElement("section");
  root.className = "playground";

  const title = document.createElement("h2");
  title.className = "playground-title";
  title.textContent = "Playground";
  root.appendChild(title);

  const subtitle = document.createElement("p");
  subtitle.className = "playground-subtitle";
  subtitle.textContent =
    "Pick a template, edit code, and submit. Polling is handled automatically.";
  root.appendChild(subtitle);

  const form = document.createElement("form");
  form.className = "playground-form";
  form.onsubmit = (e) => {
    e.preventDefault();
    void onSubmit();
  };

  // --- Template selector ---
  const templateSel = buildSelect(
    TEMPLATES.map((t) => ({ value: t.value, label: t.label })),
    TEMPLATES[0].value,
  );
  form.appendChild(buildRow("Template", templateSel));

  const vmSel = buildSelect(VM_CHOICES, VM_CHOICES[0].value);
  form.appendChild(
    buildRow(
      "MicroVM",
      vmSel,
      "Per-sandbox Kata runtime. kata-fc may not support ConfigMap mounts on all clusters.",
    ),
  );

  // --- Code editor (CodeMirror) ---
  const editorWrap = document.createElement("div");
  editorWrap.className = "playground-editor";
  form.appendChild(buildRow("Code", editorWrap));

  let currentTemplate: TemplateOption = TEMPLATES[0];
  const editor: EditorHandle = createEditor(
    editorWrap,
    currentTemplate.defaultCode,
    currentTemplate.lang,
  );

  // Replace default code on template switch only if the editor body still equals the previous default.
  templateSel.onchange = () => {
    const next = TEMPLATES.find((t) => t.value === templateSel.value);
    if (!next) return;
    editor.setLanguage(next.lang);
    if (editor.getValue().trim() === currentTemplate.defaultCode.trim()) {
      editor.setValue(next.defaultCode);
    }
    currentTemplate = next;
  };

  // --- Secrets multi-select ---
  const secretsSel = document.createElement("select");
  secretsSel.className = "playground-input playground-secrets";
  secretsSel.multiple = true;
  for (const s of SECRETS) {
    const o = document.createElement("option");
    o.value = s;
    o.textContent = s;
    secretsSel.appendChild(o);
  }
  form.appendChild(
    buildRow("Secrets", secretsSel, "Hold Cmd/Ctrl to select multiple. Leave empty for none."),
  );

  // --- is_polling ---
  const pollingWrap = document.createElement("label");
  pollingWrap.className = "playground-checkbox";
  const pollingCb = document.createElement("input");
  pollingCb.type = "checkbox";
  pollingCb.id = "pg-polling";
  const pollingLabel = document.createElement("span");
  pollingLabel.textContent = "is_polling (return immediately, then poll status)";
  pollingWrap.appendChild(pollingCb);
  pollingWrap.appendChild(pollingLabel);
  form.appendChild(buildRow("Mode", pollingWrap));

  // --- CPU limit ---
  const cpuSel = buildSelect(CPU_LIMITS);
  form.appendChild(buildRow("CPU limit", cpuSel));

  // --- Memory limit ---
  const memSel = buildSelect(MEMORY_LIMITS);
  form.appendChild(buildRow("Memory limit", memSel));

  // --- Submit + output ---
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "run-btn playground-submit";
  submit.textContent = "Submit & Run";
  form.appendChild(submit);

  const outputEl = document.createElement("pre");
  outputEl.className = "playground-output";
  outputEl.textContent = "(no output yet)";

  root.appendChild(form);
  root.appendChild(outputEl);
  container.appendChild(root);

  async function onSubmit(): Promise<void> {
    if (submit.disabled) return;

    const selectedSecrets: string[] = Array.from(secretsSel.selectedOptions).map((o) => o.value);

    const req: SandboxRequest = {
      sandbox_template: templateSel.value,
      actual_code: editor.getValue(),
      is_polling: pollingCb.checked,
      vm_choice: vmSel.value as "kata-qemu" | "kata-fc",
      ...(selectedSecrets.length ? { secret_names: selectedSecrets } : {}),
      ...(cpuSel.value ? { cpu_limit: cpuSel.value } : {}),
      ...(memSel.value ? { memory_limit: memSel.value } : {}),
    };

    submit.disabled = true;
    submit.textContent = req.is_polling ? "Submitting…" : "Running…";
    outputEl.textContent = req.is_polling ? "Creating sandbox…" : "Running…";

    try {
      const initial = await runSandbox(req);
      outputEl.textContent = initial.text;

      if (req.is_polling && initial.sandboxId) {
        submit.textContent = "Polling…";
        const createPart = initial.text;
        const pollLog = await pollSandboxUntilDone(initial.sandboxId, (attempt, result) => {
          outputEl.textContent =
            `${createPart}\n\n--- polling ---\n` +
            `attempt ${attempt}, status ${result.status ?? "—"}`;
        });
        outputEl.textContent = `${createPart}\n\n--- polling ---\n${pollLog}`;
      }
    } catch (err) {
      outputEl.textContent = `Error: ${err instanceof Error ? err.message : String(err)}`;
    } finally {
      submit.disabled = false;
      submit.textContent = "Submit & Run";
    }
  }
}
