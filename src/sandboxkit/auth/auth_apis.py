"""Auth endpoints: /auth/login, /auth/logout, /auth/me, /auth/validate (for nginx)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel

from sandboxkit.auth.jwt_utils import decode_token, encode_token
from sandboxkit.auth.users import verify_credentials
from sandboxkit.utils.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class IdentityResponse(BaseModel):
    user_id: str
    role: str


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.jwt_cookie_name,
        value=token,
        max_age=settings.jwt_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=False,  # set True behind HTTPS in prod
        path="/",
    )


@router.post(
    "/login",
    response_model=IdentityResponse,
    summary="Exchange username+password for an auth_token cookie",
)
async def login(req: LoginRequest, response: Response) -> IdentityResponse:
    identity = verify_credentials(req.username, req.password)
    if identity is None:
        logger.info("login failed username=%s", req.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = encode_token(identity["user_id"], identity["role"])
    _set_cookie(response, token)
    logger.info("login ok user_id=%s role=%s", identity["user_id"], identity["role"])
    return IdentityResponse(**identity)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear the auth_token cookie",
)
async def logout(response: Response) -> Response:
    response.delete_cookie(key=settings.jwt_cookie_name, path="/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=IdentityResponse,
    summary="Return current user from auth_token cookie (UI helper)",
)
async def me(auth_token: str | None = Cookie(default=None)) -> IdentityResponse:
    if not auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No auth cookie")
    identity = decode_token(auth_token)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return IdentityResponse(**identity)


@router.get(
    "/validate",
    summary="Subrequest endpoint for nginx auth-url; returns 200 + X-User-* headers",
)
async def validate(auth_token: str | None = Cookie(default=None)) -> Response:
    """Called by ingress-nginx via auth-url. On 200 nginx forwards the X-User-* headers
    to the protected backend (per auth-response-headers annotation)."""
    if not auth_token:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    identity = decode_token(auth_token)
    if identity is None:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    resp = Response(status_code=status.HTTP_200_OK)
    resp.headers["X-User-Id"] = identity["user_id"]
    resp.headers["X-User-Role"] = identity["role"]
    return resp
