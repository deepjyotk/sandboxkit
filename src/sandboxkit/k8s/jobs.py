"""Kubernetes Job lifecycle for sandbox executions."""

from __future__ import annotations

import asyncio
import logging

from kubernetes import client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

from sandboxkit.utils.config import settings
from sandboxkit.k8s.client import get_batch_v1
from sandboxkit.k8s.configmaps import delete_configmap
from sandboxkit.k8s.resource_quantities import cap_request_at_limit
from sandboxkit.k8s.secrets import delete_secret
from sandboxkit.k8s.templates import get_sandbox_templates
from sandboxkit.schemas import SandboxStatus

logger = logging.getLogger(__name__)


def resolve_runtime_class(runtime_class_override: str | None = None) -> str | None:
    """Pick RuntimeClass for a sandbox Job (global use_kata + per-request override)."""
    if not settings.use_kata:
        return settings.sandbox_runtime_class or None
    if runtime_class_override:
        return runtime_class_override
    return settings.kata_runtime_class


def _secret_env_vars(secret_name: str, secret_keys: list[str]) -> list[client.V1EnvVar]:
    return [
        client.V1EnvVar(
            name=key,
            value_from=client.V1EnvVarSource(
                secret_key_ref=client.V1SecretKeySelector(
                    name=secret_name,
                    key=key,
                )
            ),
        )
        for key in secret_keys
    ]


def create_job(
    sandbox_id: str,
    template_name: str,
    configmap_name: str,
    secret_name: str | None = None,
    secret_keys: list[str] | None = None,
    cpu_limit: str | None = None,
    memory_limit: str | None = None,
    runtime_class_override: str | None = None,
) -> str:
    """Create a Kubernetes Job for the given sandbox; returns the Job name."""
    templates = get_sandbox_templates()
    tmpl = templates[template_name]
    job_name = sandbox_id
    file_ext = tmpl["file_extension"]

    # Caller-supplied limits override settings defaults; template-level memory_limit
    # is a legacy fallback kept for backwards compat if neither caller nor settings set it.
    effective_cpu_limit = cpu_limit or settings.sandbox_cpu_limit
    effective_memory_limit = memory_limit or tmpl.get("memory_limit", settings.sandbox_memory_limit)

    # K8s rejects pods when requests exceed limits (e.g. default 64Mi request + 32Mi limit).
    effective_cpu_request = cap_request_at_limit(settings.sandbox_cpu_request, effective_cpu_limit)
    effective_memory_request = cap_request_at_limit(
        settings.sandbox_memory_request, effective_memory_limit
    )

    

    container_kwargs: dict = {
        "name": "sandbox",
        "image": tmpl["image"],
        "image_pull_policy": settings.sandbox_image_pull_policy,
        "resources": client.V1ResourceRequirements(
            requests={
                "cpu": effective_cpu_request,
                "memory": effective_memory_request,
            },
            limits={
                "cpu": effective_cpu_limit,
                "memory": effective_memory_limit,
            },
        ),
        "volume_mounts": [
            client.V1VolumeMount(
                name="code-volume",
                mount_path="/sandbox",
                read_only=True,
            ),
            client.V1VolumeMount(
                name="tmp-volume",
                mount_path="/tmp",
            ),
        ],
        "security_context": client.V1SecurityContext(
            allow_privilege_escalation=False,
            read_only_root_filesystem=True,
            capabilities=client.V1Capabilities(drop=["ALL"]),
        ),
    }
    if tmpl.get("command") is not None:
        container_kwargs["command"] = tmpl["command"]

    if secret_name and secret_keys:
        container_kwargs["env"] = _secret_env_vars(secret_name, secret_keys)

    runtime_class = resolve_runtime_class(runtime_class_override)

    pod_spec_kwargs: dict = {
        "restart_policy": "Never",
        "security_context": client.V1PodSecurityContext(
            run_as_non_root=True,
            run_as_user=65534,
            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
        ),
        "containers": [client.V1Container(**container_kwargs)],
        "volumes": [
            client.V1Volume(
                name="code-volume",
                config_map=client.V1ConfigMapVolumeSource(
                    name=configmap_name,
                    items=[
                        client.V1KeyToPath(
                            key=f"code.{file_ext}",
                            path=f"code.{file_ext}",
                        )
                    ],
                ),
            ),
            client.V1Volume(
                name="tmp-volume",
                empty_dir=client.V1EmptyDirVolumeSource(),
            ),
        ],
    }
    if runtime_class:
        pod_spec_kwargs["runtime_class_name"] = runtime_class
        logger.info(
            "Sandbox Job %s using runtimeClassName=%s (use_kata=%s)",
            job_name,
            runtime_class,
            settings.use_kata,
        )

    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=settings.sandbox_namespace,
            labels={"app": "sandboxkit", "sandbox-id": sandbox_id, "sandbox-role": "sandbox"},
        ),
        spec=client.V1JobSpec(
            ttl_seconds_after_finished=settings.job_ttl_seconds,
            backoff_limit=0,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={
                        "app": "sandboxkit",
                        "sandbox-id": sandbox_id,
                        "sandbox-role": "sandbox",
                    }
                ),
                spec=client.V1PodSpec(**pod_spec_kwargs),
            ),
        ),
    )

    get_batch_v1().create_namespaced_job(namespace=settings.sandbox_namespace, body=job)
    logger.info("Created Job %s", job_name)
    return job_name


async def wait_for_job(job_name: str, timeout: int = 60) -> SandboxStatus:
    """Asynchronously poll until the Job succeeds/fails or timeout expires."""
    deadline = asyncio.get_event_loop().time() + timeout
    batch = get_batch_v1()

    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            logger.warning("Job %s timed out after %ds", job_name, timeout)
            return SandboxStatus.FAILED

        try:
            job = batch.read_namespaced_job(name=job_name, namespace=settings.sandbox_namespace)
            cond = job.status
            if cond.succeeded and cond.succeeded > 0:
                return SandboxStatus.COMPLETED
            if cond.failed and cond.failed > 0:
                return SandboxStatus.FAILED
        except ApiException as exc:
            logger.error("Error reading Job %s: %s", job_name, exc)
            return SandboxStatus.UNKNOWN

        await asyncio.sleep(settings.job_poll_interval_seconds)


def delete_job(job_name: str) -> None:
    """Delete a Job and its dependent pods (foreground cascade)."""
    try:
        get_batch_v1().delete_namespaced_job(
            name=job_name,
            namespace=settings.sandbox_namespace,
            body=client.V1DeleteOptions(propagation_policy="Foreground"),
        )
        logger.info("Deleted Job %s", job_name)
    except ApiException as exc:
        if exc.status != 404:
            logger.warning("Could not delete Job %s: %s", job_name, exc)


def delete_sandbox_resources(
    job_name: str,
    configmap_name: str,
    secret_name: str | None = None,
) -> None:
    """Delete Job, ConfigMap, and optional Secret together."""
    delete_job(job_name)
    delete_configmap(configmap_name)
    if secret_name:
        delete_secret(secret_name)
