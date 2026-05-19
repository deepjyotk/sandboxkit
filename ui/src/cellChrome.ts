export async function copyText(text: string): Promise<boolean> {
  const value = text || "";
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = value;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

function flashButtonLabel(btn: HTMLButtonElement, label: string, ms = 1200): void {
  const prev = btn.textContent;
  btn.textContent = label;
  window.setTimeout(() => {
    btn.textContent = prev;
  }, ms);
}

export type CopyableCellOptions = {
  getContent: () => string;
  bodyClassName?: string;
  preformatted?: boolean;
  clearable?: boolean;
  onClear?: () => void;
  /** Extra nodes placed in the body area (e.g. action buttons). */
  bodyContent?: HTMLElement;
};

export function createCopyableCell(options: CopyableCellOptions): HTMLElement {
  const {
    getContent,
    bodyClassName = "cell-text",
    preformatted = true,
    clearable,
    onClear,
    bodyContent,
  } = options;

  const wrap = document.createElement("div");
  wrap.className = "cell-chrome";

  const toolbar = document.createElement("div");
  toolbar.className = "cell-chrome-toolbar";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "cell-icon-btn";
  copyBtn.title = "Copy cell content";
  copyBtn.textContent = "Copy";

  const runCopy = () => {
    void copyText(getContent()).then((ok) => {
      if (ok) flashButtonLabel(copyBtn, "Copied!");
    });
  };

  copyBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    runCopy();
  });

  toolbar.appendChild(copyBtn);

  if (clearable && onClear) {
    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "cell-icon-btn cell-clear-btn";
    clearBtn.title = "Clear cell content";
    clearBtn.textContent = "Clear";
    clearBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      onClear();
    });
    toolbar.appendChild(clearBtn);
  }

  const body = document.createElement("div");
  body.className = `cell-chrome-body ${bodyClassName}`;

  if (bodyContent) {
    body.appendChild(bodyContent);
  } else {
    const text = getContent() || "—";
    if (preformatted) {
      const pre = document.createElement("pre");
      pre.textContent = text;
      body.appendChild(pre);
    } else {
      const span = document.createElement("span");
      span.className = "cell-plain-text";
      span.textContent = text;
      body.appendChild(span);
    }
  }

  wrap.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    e.stopPropagation();
    runCopy();
  });

  wrap.appendChild(toolbar);
  wrap.appendChild(body);
  return wrap;
}
