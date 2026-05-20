"""Sandbox and health HTTP endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response, status

from sandboxkit import __version__
from sandboxkit.schemas import ExecuteRequest, ExecuteResponse
from sandboxkit.services import sandbox_service
from sandboxkit.utils.exceptions import (
    ResourceLimitError,
    SandboxNotFoundError,
    SandboxResourceError,
    UnknownSecretError,
    UnknownTemplateError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
async def root() -> dict[str, Any]:
    return {
        "message": "Welcome to SandboxKit",
        "version": __version__,
        "docs": "/docs",
    }


@router.post(
    "/sandboxes",
    response_model=ExecuteResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Execute code in an isolated sandbox",
)
async def create_sandbox(
    req: ExecuteRequest,
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> ExecuteResponse:
    """
    Submit code for execution.

    - `is_polling=false` (default): wait for the Job to finish and return full results.
    - `is_polling=true`: return immediately with `status=running`; poll `GET /sandboxes/{id}`.

    `X-User-Id` / `X-User-Role` are injected by nginx after validating the auth cookie
    (auth-subrequest pattern); we log them for audit but do not enforce role policy yet.
    """
    logger.info("create_sandbox user_id=%s role=%s", x_user_id, x_user_role)
    try:
        return await sandbox_service.execute(req)
    except UnknownTemplateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown sandbox_template '{exc.template_name}'. "
            f"Available: {exc.available}",
        ) from exc
    except UnknownSecretError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown secret name(s): {exc.missing}. Available: {exc.available}",
        ) from exc
    except ResourceLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except SandboxResourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.get(
    "/sandboxes/{sandbox_id}",
    response_model=ExecuteResponse,
    summary="Get sandbox execution status and results",
)
async def get_sandbox(
    sandbox_id: str,
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> ExecuteResponse:
    """
    Retrieve the current status and results of a previously submitted sandbox.
    Use this to poll after submitting with `is_polling=true`.
    """
    logger.info("get_sandbox %s user_id=%s role=%s", sandbox_id, x_user_id, x_user_role)
    try:
        return sandbox_service.get_status(sandbox_id)
    except SandboxNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.delete(
    "/sandboxes/{sandbox_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a sandbox and clean up all associated Kubernetes resources",
)
async def delete_sandbox(
    sandbox_id: str,
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> Response:
    """
    Tear down the sandbox: deletes the Kubernetes Job (cascade-deletes pods),
    the ConfigMap holding the code, any per-run Secret, and removes in-memory state.
    """
    logger.info("delete_sandbox %s user_id=%s role=%s", sandbox_id, x_user_id, x_user_role)
    try:
        sandbox_service.delete(sandbox_id)
    except SandboxNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SandboxResourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
