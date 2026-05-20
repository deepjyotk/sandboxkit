"""JWT encode/decode helpers (HS256 with secret from settings)."""

from __future__ import annotations

import time

import jwt

from sandboxkit.utils.config import settings

ALGORITHM = "HS256"


def encode_token(user_id: str, role: str, ttl_seconds: int | None = None) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + (ttl_seconds or settings.jwt_ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, str] | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    role = payload.get("role")
    if not isinstance(sub, str) or not isinstance(role, str):
        return None
    return {"user_id": sub, "role": role}
