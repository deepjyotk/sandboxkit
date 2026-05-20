"""Business logic for sandbox execution lifecycle."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid

from sandboxkit.utils.config import settings
from sandboxkit.k8s import (
    create_code_configmap,
    create_job,
    create_sandbox_secret,
    delete_sandbox_resources,
    get_pod_logs,
    get_sandbox_templates,
    wait_for_job,
)
from sandboxkit.schemas import ExecuteRequest, ExecuteResponse, SandboxRecord, SandboxStatus
from sandboxkit.services.simulate_vault_service import resolve_secret_names
from sandboxkit.utils.exceptions import (
    ResourceLimitError,
    SandboxNotFoundError,
    SandboxResourceError,
    UnknownSecretError,
    UnknownTemplateError,
)

logger = logging.getLogger(__name__)


class SandboxService:
    """Orchestrates K8s resources and in-memory sandbox state."""

    def __init__(self) -> None:
        self._store: dict[str, SandboxRecord] = {}

    @staticmethod
    def new_sandbox_id() -> str:
        return f"sandbox-{uuid.uuid4().hex[:8]}"

    def get_record(self, sandbox_id: str) -> SandboxRecord:
        record = self._store.get(sandbox_id)
        if record is None:
            raise SandboxNotFoundError(sandbox_id)
        return record

    def to_response(self, record: SandboxRecord) -> ExecuteResponse:
        return ExecuteResponse(
            sandbox_id=record.sandbox_id,
            status=record.status,
            stdout=record.stdout,
            stderr=record.stderr,
            exit_code=record.exit_code,
        )

    async def _wait_and_collect(self, record: SandboxRecord) -> None:
        record.status = SandboxStatus.RUNNING
        final_status = await wait_for_job(record.job_name, timeout=settings.job_timeout_seconds)
        stdout, stderr, exit_code = get_pod_logs(record.sandbox_id)
        record.status = final_status
        record.stdout = stdout
        record.stderr = stderr
        record.exit_code = exit_code

        logger.info(
            "Sandbox %s finished: status=%s exit_code=%s",
            record.sandbox_id,
            final_status,
            exit_code,
        )

    @staticmethod
    def _validate_cpu_limit(value: str) -> None:
        """Accept K8s CPU quantity: plain number (cores) or millicores e.g. '500m', '1', '0.5'."""
        if not re.fullmatch(r"\d+(\.\d+)?m?", value):
            raise ResourceLimitError(
                "cpu_limit",
                value,
                "use millicores (e.g. '250m', '500m') or fractional cores (e.g. '0.5', '1')",
            )

    @staticmethod
    def _validate_memory_limit(value: str) -> None:
        """Accept K8s memory quantity: plain bytes or with SI suffix."""
        if not re.fullmatch(r"\d+(\.\d+)?(Ki|Mi|Gi|Ti|K|M|G|T)?", value):
            raise ResourceLimitError(
                "memory_limit",
                value,
                "use a number with optional suffix (e.g. '64Mi', '256Mi', '1Gi')",
            )

    def _validate_template(self, template_name: str) -> dict:
        templates = get_sandbox_templates()
        if template_name not in templates:
            raise UnknownTemplateError(template_name, list(templates.keys()))
        return templates[template_name]

    def _provision_resources(
        self,
        sandbox_id: str,
        template_name: str,
        code: str,
        file_extension: str,
        secret_names: list[str] | None = None,
        cpu_limit: str | None = None,
        memory_limit: str | None = None,
        runtime_class_override: str | None = None,
    ) -> tuple[str, str, str | None]:
        """
        Provision resources for a sandbox execution.
        - Resolves secret names from vault and creates a K8s Secret when requested;
        - Uploads code as a ConfigMap and creates a Job in the chosen prebuilt image;
        - It does not wait for output—that happens in _wait_and_collect.
        """
        secret_data = resolve_secret_names(secret_names or [])
        secret_name: str | None = None
        secret_keys: list[str] = []

        if secret_data:
            secret_name = create_sandbox_secret(sandbox_id, secret_data)
            secret_keys = list(secret_data.keys())

        cm_name = create_code_configmap(sandbox_id, code, file_extension)
        job_name = create_job(
            sandbox_id,
            template_name,
            cm_name,
            secret_name=secret_name,
            secret_keys=secret_keys or None,
            cpu_limit=cpu_limit,
            memory_limit=memory_limit,
            runtime_class_override=runtime_class_override,
        )
        return cm_name, job_name, secret_name

    async def execute(self, req: ExecuteRequest) -> ExecuteResponse:
        """Create sandbox resources and run sync or async (polling) execution."""
        template_name = req.sandbox_template.value
        tmpl = self._validate_template(template_name)

        # Validate resource limits before any K8s calls
        if req.cpu_limit is not None:
            self._validate_cpu_limit(req.cpu_limit)
        if req.memory_limit is not None:
            self._validate_memory_limit(req.memory_limit)

        sandbox_id = self.new_sandbox_id()
        try:
            cm_name, job_name, secret_name = self._provision_resources(
                sandbox_id,
                template_name,
                req.actual_code,
                tmpl["file_extension"],
                secret_names=req.secret_names,
                cpu_limit=req.cpu_limit,
                memory_limit=req.memory_limit,
                runtime_class_override=req.vm_choice.value,
            )
        except (UnknownSecretError, ResourceLimitError):
            raise
        except Exception as exc:
            logger.exception("Failed to create sandbox resources for %s", sandbox_id)
            raise SandboxResourceError(
                sandbox_id, f"Could not create sandbox: {exc}", cause=exc
            ) from exc

        record = SandboxRecord(
            sandbox_id=sandbox_id,
            job_name=job_name,
            configmap_name=cm_name,
            secret_name=secret_name,
            cpu_limit=req.cpu_limit,
            memory_limit=req.memory_limit,
            status=SandboxStatus.PENDING,
        )
        self._store[sandbox_id] = record

        if req.is_polling:
            asyncio.create_task(self._wait_and_collect(record))
            return ExecuteResponse(sandbox_id=sandbox_id, status=SandboxStatus.RUNNING)

        await self._wait_and_collect(record)
        return self.to_response(record)

    def list_all(self) -> list[SandboxRecord]:
        return list(self._store.values())

    def get_status(self, sandbox_id: str) -> ExecuteResponse:
        return self.to_response(self.get_record(sandbox_id))

    def delete(self, sandbox_id: str) -> None:
        record = self.get_record(sandbox_id)
        try:
            delete_sandbox_resources(
                record.job_name, record.configmap_name, secret_name=record.secret_name
            )
        except Exception as exc:
            logger.exception("Error cleaning up sandbox %s", sandbox_id)
            raise SandboxResourceError(sandbox_id, f"Cleanup failed: {exc}", cause=exc) from exc
        del self._store[sandbox_id]


sandbox_service = SandboxService()
