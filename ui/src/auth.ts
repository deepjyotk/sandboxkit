/** Cookie-based JWT auth: login/logout API + a TS-rendered login modal. */

export type Identity = { user_id: string; role: string };

const FETCH_OPTS: RequestInit = { credentials: "include" };

export async function me(): Promise<Identity | null> {
  try {
    const res = await fetch("/auth/me", FETCH_OPTS);
    if (!res.ok) return null;
    return (await res.json()) as Identity;
  } catch {
    return null;
  }
}

export async function login(username: string, password: string): Promise<Identity> {
  const res = await fetch("/auth/login", {
    ...FETCH_OPTS,
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Login failed (HTTP ${res.status})`);
  }
  return (await res.json()) as Identity;
}

export async function logout(): Promise<void> {
  await fetch("/auth/logout", { ...FETCH_OPTS, method: "POST" });
}

/** Modal lifecycle: returns the resolved Identity on successful login. */
export function showLoginModal(): Promise<Identity> {
  return new Promise((resolve) => {
    document.querySelectorAll(".auth-modal-backdrop").forEach((n) => n.remove());

    const backdrop = document.createElement("div");
    backdrop.className = "auth-modal-backdrop";

    const card = document.createElement("div");
    card.className = "auth-modal-card";

    const title = document.createElement("h2");
    title.textContent = "Sign in to SandboxKit";
    card.appendChild(title);

    const form = document.createElement("form");
    form.className = "auth-modal-form";

    const userInput = document.createElement("input");
    userInput.type = "text";
    userInput.name = "username";
    userInput.placeholder = "username";
    userInput.required = true;
    userInput.autocomplete = "username";
    form.appendChild(userInput);

    const passInput = document.createElement("input");
    passInput.type = "password";
    passInput.name = "password";
    passInput.placeholder = "password";
    passInput.required = true;
    passInput.autocomplete = "current-password";
    form.appendChild(passInput);

    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "run-btn";
    submit.textContent = "Sign in";
    form.appendChild(submit);

    const errorEl = document.createElement("div");
    errorEl.className = "auth-modal-error";
    form.appendChild(errorEl);

    form.onsubmit = async (e) => {
      e.preventDefault();
      errorEl.textContent = "";
      submit.disabled = true;
      submit.textContent = "Signing in…";
      try {
        const id = await login(userInput.value.trim(), passInput.value);
        backdrop.remove();
        resolve(id);
      } catch (err) {
        errorEl.textContent = err instanceof Error ? err.message : String(err);
        submit.disabled = false;
        submit.textContent = "Sign in";
      }
    };

    card.appendChild(form);
    backdrop.appendChild(card);
    document.body.appendChild(backdrop);
    userInput.focus();
  });
}
