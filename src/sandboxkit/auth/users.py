"""Hardcoded user directory. Take-home only — replace with a real store in prod."""

from __future__ import annotations

USER_DB: dict[str, dict[str, str]] = {
    "deepjyot": {"user_id": "u-1", "password": "Abcd", "role": "admin"},
    "Nick": {"user_id": "u-2", "password": "Abcd", "role": "admin"},
}


def verify_credentials(username: str, password: str) -> dict[str, str] | None:
    user = USER_DB.get(username)
    if not user or user["password"] != password:
        return None
    return {"user_id": user["user_id"], "role": user["role"]}
