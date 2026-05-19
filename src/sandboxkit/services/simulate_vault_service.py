"""Simulated secret vault (stand-in for HashiCorp Vault / cloud secret manager)."""

from __future__ import annotations

from sandboxkit.utils.exceptions import UnknownSecretError

# In-memory vault: callers reference keys by name only; values never appear in POST bodies.
VAULT: dict[str, str] = {
    "SECRET_KEY1": "secret-value1",
    "SECRET_KEY2": "secret-value2",
}


def list_secret_names() -> list[str]:
    """Return all secret names defined in the simulated vault."""
    return sorted(VAULT.keys())


def resolve_secret_names(names: list[str]) -> dict[str, str]:
    """Resolve secret names to values. Empty list returns empty dict."""
    if not names:
        return {}

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_names: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique_names.append(name)

    missing = [n for n in unique_names if n not in VAULT]
    if missing:
        raise UnknownSecretError(missing=missing, available=list_secret_names())

    return {name: VAULT[name] for name in unique_names}
