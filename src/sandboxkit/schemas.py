"""Pydantic schemas for the sandbox API."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class SandboxTemplate(str, Enum):
    PY_TEMPLATE = "sandboxkit-py-template"
    JS_TEMPLATE = "sandbox-js-template"


# Accepted API values (includes legacy names for backward compatibility)
_LEGACY_TEMPLATE_ALIASES: dict[str, str] = {
    "template-fastapi-py": SandboxTemplate.PY_TEMPLATE.value,
    "node-latest": SandboxTemplate.JS_TEMPLATE.value,
}


class SandboxStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class VmChoice(str, Enum):
    """Kata RuntimeClass for the sandbox microVM (requires use_kata=True on the server)."""

    KATA_QEMU = "kata-qemu"
    KATA_FC = "kata-fc"


class ExecuteRequest(BaseModel):
    sandbox_template: SandboxTemplate = Field(
        ...,
        description=(
            "Runtime template: sandboxkit-py-template (Python) or "
            "sandbox-js-template (Node)"
        ),
    )
    actual_code: str = Field(..., description="Source code to execute inside the sandbox")

    @field_validator("sandbox_template", mode="before")
    @classmethod
    def _normalize_sandbox_template(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _LEGACY_TEMPLATE_ALIASES.get(v, v)
        return v

    is_polling: bool = Field(
        False,
        description="Return immediately with sandbox_id for polling instead of waiting for result",
    )
    secret_names: list[str] = Field(
        default_factory=list,
        description="Secret names only; values resolved from vault at provision time",
    )
    cpu_limit: str | None = Field(
        None,
        description="CPU limit e.g. '250m', '1'. Overrides default (500m).",
    )
    memory_limit: str | None = Field(
        None,
        description="Memory limit e.g. '64Mi', '1Gi'. Overrides default (256Mi).",
    )
    vm_choice: VmChoice = Field(
        default=VmChoice.KATA_QEMU,
        description=(
            "MicroVM runtime for this sandbox: kata-qemu (QEMU, default) or "
            "kata-fc (Firecracker). Ignored when the server has use_kata=False."
        ),
    )


class ExecuteResponse(BaseModel):
    sandbox_id: str
    status: SandboxStatus
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None


class SandboxSummary(BaseModel):
    """Public summary of a single sandbox (used in GET /sandboxes list)."""

    sandbox_id: str
    status: SandboxStatus
    cpu_limit: str | None = None
    memory_limit: str | None = None


class SandboxListResponse(BaseModel):
    """Response body for GET /sandboxes."""

    sandboxes: list[SandboxSummary]
    total: int


class SandboxRecord(BaseModel):
    """Internal in-memory state for a sandbox execution."""

    sandbox_id: str
    job_name: str
    configmap_name: str
    secret_name: str | None = None
    cpu_limit: str | None = None
    memory_limit: str | None = None
    status: SandboxStatus = SandboxStatus.PENDING
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
