"""Sandbox and health HTTP endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response, status

from sandboxkit import __version__
from sandboxkit.schemas import (
    ExecuteRequest,
    ExecuteResponse,
    RepoExecuteRequest,
    SandboxListResponse,
    SandboxSummary,
    VmChoice,
)
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
    logger.info(
        "create_sandbox user_id=%s role=%s vm_choice=%s",
        x_user_id,
        x_user_role,
        req.vm_choice.value,
    )
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


@router.post(
    "/sandboxes/from-repo",
    response_model=ExecuteResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Execute code from a public GitHub repo (virtio-fs hostPath share)",
)
async def create_sandbox_from_repo(
    req: RepoExecuteRequest,
    response: Response,
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> ExecuteResponse:
    """
    Clone a public GitHub repo onto the node's host filesystem and execute
    the user-specified entrypoint inside a Kata sandbox. The cloned directory
    is shared into the microVM via **virtio-fs** (transparent on `kata-qemu`
    when the Pod uses a hostPath volume).

    Lifecycle: `DELETE /sandboxes/{id}` waits for a cleanup Job to remove the
    per-sandbox host directory before returning 204 — guaranteeing that the
    code is gone from the node.

    `kata-fc` is accepted but flagged as experimental for repo mode via the
    `X-VirtioFS-Mode` response header.
    """
    logger.info(
        "create_sandbox_from_repo user_id=%s role=%s vm_choice=%s repo=%s ref=%s entry=%s",
        x_user_id,
        x_user_role,
        req.vm_choice.value,
        req.github_repo_url,
        req.git_ref,
        req.entrypoint,
    )
    if req.vm_choice == VmChoice.KATA_FC:
        response.headers["X-VirtioFS-Mode"] = "experimental-fc"
    else:
        response.headers["X-VirtioFS-Mode"] = "kata-qemu"

    try:
        return await sandbox_service.execute_from_repo(req)
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
    "/sandboxes",
    response_model=SandboxListResponse,
    summary="List all active sandboxes (in-memory store)",
)
async def list_sandboxes(
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> SandboxListResponse:
    """
    Return all sandboxes currently tracked in memory (created and not yet deleted).

    Note: the store is process-local — a control-plane restart clears it even if
    Kubernetes Jobs still exist. Entries are removed either by `DELETE /sandboxes/{id}`
    or when the pod restarts.
    """
    logger.info("list_sandboxes user_id=%s role=%s", x_user_id, x_user_role)
    records = sandbox_service.list_all()
    return SandboxListResponse(
        sandboxes=[
            SandboxSummary(
                sandbox_id=r.sandbox_id,
                status=r.status,
                cpu_limit=r.cpu_limit,
                memory_limit=r.memory_limit,
            )
            for r in records
        ],
        total=len(records),
    )


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
    Tear down the sandbox.

    - ``actual_code`` sandboxes: deletes the Kubernetes Job (cascade-deletes
      pods), the ConfigMap holding the code, and any per-run Secret.
    - ``from-repo`` sandboxes: deletes the Kubernetes Job, runs a synchronous
      cleanup Job that ``rm -rf``'s the per-sandbox host directory on the
      node, and only returns 204 after the host bytes are gone.

    In both cases the in-memory record is removed.
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
