"""
Orchestration for repo-mode sandboxes (clone -> Kata sandbox via virtio-fs).

Mirrors :class:`SandboxService` but for the ``POST /sandboxes/from-repo``
endpoint. Cleanup is **synchronous**: ``delete_repo_sandbox`` waits for the
cleanup Job to finish so the API only returns 204 after the per-sandbox host
directory has been removed from the k3s node.
"""

from __future__ import annotations

import logging

from sandboxkit.k8s.jobs import delete_job, wait_for_job
from sandboxkit.k8s.pods import get_pod_logs
from sandboxkit.k8s.repo_jobs import (
    create_cleanup_job,
    create_clone_job,
    create_repo_sandbox_job,
    repo_host_dir,
    wait_for_job_done,
    wait_for_job_done_sync,
)
from sandboxkit.k8s.secrets import create_sandbox_secret, delete_secret
from sandboxkit.k8s.templates import get_sandbox_templates
from sandboxkit.schemas import (
    ExecuteResponse,
    RepoExecuteRequest,
    SandboxRecord,
    SandboxStatus,
)
from sandboxkit.services.simulate_vault_service import resolve_secret_names
from sandboxkit.utils.config import settings
from sandboxkit.utils.exceptions import (
    SandboxResourceError,
    UnknownSecretError,
    UnknownTemplateError,
)

logger = logging.getLogger(__name__)


class RepoSandboxOrchestrator:
    """Stateless helpers; sandbox records are stored on :class:`SandboxService`."""

    @staticmethod
    def _validate_template(template_name: str) -> dict:
        templates = get_sandbox_templates()
        if template_name not in templates:
            raise UnknownTemplateError(template_name, list(templates.keys()))
        return templates[template_name]

    async def provision(
        self, sandbox_id: str, req: RepoExecuteRequest
    ) -> SandboxRecord:
        """
        Run clone Job synchronously, then create the sandbox Job (does not wait
        for sandbox completion — caller drives that via wait/collect).
        Returns a populated :class:`SandboxRecord`.
        """
        template_name = req.sandbox_template.value
        self._validate_template(template_name)

        secret_data = resolve_secret_names(req.secret_names or [])
        secret_name: str | None = None
        secret_keys: list[str] = []
        if secret_data:
            secret_name = create_sandbox_secret(sandbox_id, secret_data)
            secret_keys = list(secret_data.keys())

        # 1. Clone Job: pulls repo into hostPath on the node.
        clone_job_name = create_clone_job(sandbox_id, req.github_repo_url, req.git_ref)
        clone_status = await wait_for_job_done(
            clone_job_name, timeout=settings.clone_timeout_seconds
        )
        if clone_status != SandboxStatus.COMPLETED:
            logs = self._best_effort_clone_logs(clone_job_name)
            # Best-effort cleanup: kill clone Job + remove any partial host dir.
            try:
                delete_job(clone_job_name)
            except Exception:  # noqa: BLE001
                pass
            self._fire_cleanup_and_wait(sandbox_id)
            raise SandboxResourceError(
                sandbox_id,
                f"git clone failed (status={clone_status}). Logs: {logs}",
            )

        # 2. Sandbox Job: Kata + virtio-fs (read-only) mount of /sandbox/repo.
        sandbox_job_name = create_repo_sandbox_job(
            sandbox_id=sandbox_id,
            template_name=template_name,
            entrypoint=req.entrypoint,
            secret_name=secret_name,
            secret_keys=secret_keys or None,
            cpu_limit=req.cpu_limit,
            memory_limit=req.memory_limit,
            runtime_class_override=req.vm_choice.value,
        )

        record = SandboxRecord(
            sandbox_id=sandbox_id,
            job_name=sandbox_job_name,
            configmap_name=None,
            secret_name=secret_name,
            cpu_limit=req.cpu_limit,
            memory_limit=req.memory_limit,
            status=SandboxStatus.PENDING,
            is_repo=True,
            host_repo_path=repo_host_dir(sandbox_id),
            clone_job_name=clone_job_name,
        )
        return record

    async def wait_and_collect(self, record: SandboxRecord) -> None:
        """Wait for the sandbox Job and populate stdout/stderr/exit_code."""
        record.status = SandboxStatus.RUNNING
        final_status = await wait_for_job(
            record.job_name, timeout=settings.job_timeout_seconds
        )
        stdout, stderr, exit_code = get_pod_logs(record.sandbox_id)
        record.status = final_status
        record.stdout = stdout
        record.stderr = stderr
        record.exit_code = exit_code
        logger.info(
            "Repo sandbox %s finished: status=%s exit_code=%s",
            record.sandbox_id,
            final_status,
            exit_code,
        )

    def delete(self, record: SandboxRecord) -> None:
        """
        Synchronously tear down a repo sandbox:

        1. Delete sandbox Job (Pod terminates -> virtio-fs unmounts as the
           microVM shuts down).
        2. Best-effort delete the clone Job (often already GC'd).
        3. Create cleanup Job and **wait** for it to finish removing the host dir.
        4. Delete cleanup Job and any per-sandbox Secret.
        """
        try:
            delete_job(record.job_name)
        except Exception:  # noqa: BLE001
            logger.exception("delete sandbox Job %s failed", record.job_name)
        if record.clone_job_name:
            try:
                delete_job(record.clone_job_name)
            except Exception:  # noqa: BLE001
                logger.warning("delete clone Job %s failed (may be GC'd)", record.clone_job_name)

        self._fire_cleanup_and_wait(record.sandbox_id)

        if record.secret_name:
            try:
                delete_secret(record.secret_name)
            except Exception:  # noqa: BLE001
                logger.warning("delete secret %s failed", record.secret_name)

    @staticmethod
    def _fire_cleanup_and_wait(sandbox_id: str) -> None:
        cleanup_name = create_cleanup_job(sandbox_id)
        status = wait_for_job_done_sync(
            cleanup_name, timeout=settings.cleanup_timeout_seconds
        )
        if status != SandboxStatus.COMPLETED:
            logger.error(
                "Cleanup Job %s for %s did not complete (status=%s); host dir may be stale",
                cleanup_name,
                sandbox_id,
                status,
            )
        try:
            delete_job(cleanup_name)
        except Exception:  # noqa: BLE001
            logger.warning("delete cleanup Job %s failed", cleanup_name)

    @staticmethod
    def _best_effort_clone_logs(clone_job_name: str) -> str:
        """Try to fetch clone Pod logs for an error message (best effort)."""
        try:
            from sandboxkit.k8s.client import get_core_v1

            core = get_core_v1()
            sandbox_id = clone_job_name.removeprefix("clone-")
            pods = core.list_namespaced_pod(
                namespace=settings.sandbox_namespace,
                label_selector=f"sandbox-id={sandbox_id},sandbox-role=clone",
            )
            if not pods.items:
                return "(no clone pod found)"
            pod_name = pods.items[0].metadata.name
            log = core.read_namespaced_pod_log(
                name=pod_name,
                namespace=settings.sandbox_namespace,
                container="clone",
            )
            return (log or "")[-500:]
        except Exception:  # noqa: BLE001
            return "(no logs available)"


repo_sandbox_service = RepoSandboxOrchestrator()


__all__ = [
    "RepoSandboxOrchestrator",
    "repo_sandbox_service",
    "UnknownSecretError",
    "UnknownTemplateError",
]
