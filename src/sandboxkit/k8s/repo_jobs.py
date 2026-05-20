"""
Kubernetes Job helpers for repo-mode sandboxes (virtio-fs via hostPath).

Three Job types per repo sandbox:

1. Clone Job (``clone-<sandbox_id>``): a tiny ``alpine/git`` pod with a
   ``hostPath`` mount that ``git clone``s the repo onto the node at
   ``{repo_host_base_path}/<sandbox_id>/repo``. Runs under the default
   container runtime (runc) — no Kata, no virtio-fs needed for this step.

2. Repo sandbox Job (``sandbox-<sandbox_id>``): runs the template image with
   ``runtimeClassName: kata-qemu`` (or ``kata-fc``). The same host directory
   is mounted **read-only** at ``/sandbox/repo`` — Kata transparently shares
   it into the microVM over **virtio-fs** (see
   https://virtio-fs.gitlab.io/ and the Kata virtio-fs how-to). The
   container ``command`` is overridden to print the in-guest mount table
   (so we can demo virtio-fs) and then exec the user-specified entrypoint.

3. Cleanup Job (``cleanup-<sandbox_id>``): a ``busybox`` pod that mounts the
   **parent** host directory and ``rm -rf``'s the per-sandbox sub-dir. Run
   on ``DELETE`` and awaited synchronously so the API only returns 204 after
   the bytes are gone from the host.
"""

from __future__ import annotations

import asyncio
import logging
import time

from kubernetes import client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

from sandboxkit.k8s.client import get_batch_v1
from sandboxkit.k8s.jobs import _secret_env_vars, resolve_runtime_class
from sandboxkit.k8s.resource_quantities import cap_request_at_limit
from sandboxkit.k8s.templates import get_sandbox_templates
from sandboxkit.schemas import SandboxStatus
from sandboxkit.utils.config import settings

logger = logging.getLogger(__name__)


def repo_host_dir(sandbox_id: str) -> str:
    """Per-sandbox host directory on the k3s node."""
    return f"{settings.repo_host_base_path}/{sandbox_id}"


def _labels(sandbox_id: str, role: str) -> dict[str, str]:
    return {"app": "sandboxkit", "sandbox-id": sandbox_id, "sandbox-role": role}


def create_clone_job(sandbox_id: str, repo_url: str, git_ref: str | None) -> str:
    """
    Create the clone Job. Uses ``alpine/git`` + hostPath under runc (no Kata)
    because (a) it's faster, (b) git needs to write to the shared dir.
    Returns the Job name.
    """
    job_name = f"clone-{sandbox_id}"
    host_dir = repo_host_dir(sandbox_id)

    ref_args = f"--branch {git_ref!s} " if git_ref else ""
    # Clone into /host/repo (subPath mounted into the sandbox as /sandbox/repo).
    clone_cmd = (
        "set -eu; "
        "mkdir -p /host; "
        "rm -rf /host/repo; "
        f"git clone --depth 1 {ref_args}'{repo_url}' /host/repo; "
        "echo '--- clone complete ---'; ls -la /host/repo | head -20"
    )

    container = client.V1Container(
        name="clone",
        image=settings.clone_image,
        image_pull_policy="IfNotPresent",
        command=["sh", "-c", clone_cmd],
        volume_mounts=[
            client.V1VolumeMount(name="repo-host", mount_path="/host"),
        ],
        security_context=client.V1SecurityContext(
            run_as_user=0,
            allow_privilege_escalation=False,
            capabilities=client.V1Capabilities(drop=["ALL"]),
        ),
        resources=client.V1ResourceRequirements(
            requests={"cpu": "50m", "memory": "64Mi"},
            limits={"cpu": "500m", "memory": "256Mi"},
        ),
    )

    pod_spec = client.V1PodSpec(
        restart_policy="Never",
        containers=[container],
        volumes=[
            client.V1Volume(
                name="repo-host",
                host_path=client.V1HostPathVolumeSource(
                    path=host_dir, type="DirectoryOrCreate"
                ),
            ),
        ],
    )

    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=settings.sandbox_namespace,
            labels=_labels(sandbox_id, "clone"),
        ),
        spec=client.V1JobSpec(
            ttl_seconds_after_finished=settings.job_ttl_seconds,
            backoff_limit=0,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=_labels(sandbox_id, "clone")),
                spec=pod_spec,
            ),
        ),
    )

    get_batch_v1().create_namespaced_job(namespace=settings.sandbox_namespace, body=job)
    logger.info("Created clone Job %s (host_dir=%s ref=%s)", job_name, host_dir, git_ref)
    return job_name


def _entrypoint_command(template_name: str, entrypoint: str) -> list[str]:
    """
    Build the in-guest command for the repo sandbox.

    Prefix logs the active mount table (filtered to virtio-fs) so the demo
    can prove that ``/sandbox/repo`` arrived via virtio-fs, then execs the
    user-specified entrypoint.
    """
    mount_probe = (
        "echo '--- virtio-fs mount probe ---'; "
        "mount | grep -E 'virtiofs|/sandbox/repo' || echo '(no virtiofs line)'; "
        "echo '--- entrypoint ---';"
    )
    safe_entry = entrypoint.replace("'", "")  # very light shell guard
    if template_name == "sandboxkit-py-template":
        return [
            "sh",
            "-c",
            f"{mount_probe} exec python /sandbox/repo/{safe_entry}",
        ]
    if template_name == "sandbox-js-template":
        return [
            "sh",
            "-c",
            f"{mount_probe} exec /app/node_modules/.bin/tsx /sandbox/repo/{safe_entry}",
        ]
    # Fallback: just exec the file
    return ["sh", "-c", f"{mount_probe} exec /sandbox/repo/{safe_entry}"]


def create_repo_sandbox_job(
    sandbox_id: str,
    template_name: str,
    entrypoint: str,
    secret_name: str | None = None,
    secret_keys: list[str] | None = None,
    cpu_limit: str | None = None,
    memory_limit: str | None = None,
    runtime_class_override: str | None = None,
) -> str:
    """
    Create the sandbox Job that mounts the cloned repo into the guest via
    virtio-fs (transparent on Kata + hostPath). Returns the Job name.
    """
    templates = get_sandbox_templates()
    tmpl = templates[template_name]
    job_name = sandbox_id
    host_dir = repo_host_dir(sandbox_id)

    effective_cpu_limit = cpu_limit or settings.sandbox_cpu_limit
    effective_memory_limit = memory_limit or tmpl.get(
        "memory_limit", settings.sandbox_memory_limit
    )
    effective_cpu_request = cap_request_at_limit(
        settings.sandbox_cpu_request, effective_cpu_limit
    )
    effective_memory_request = cap_request_at_limit(
        settings.sandbox_memory_request, effective_memory_limit
    )

    container_kwargs: dict = {
        "name": "sandbox",
        "image": tmpl["image"],
        "image_pull_policy": settings.sandbox_image_pull_policy,
        "command": _entrypoint_command(template_name, entrypoint),
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
                name="repo-volume",
                mount_path="/sandbox/repo",
                read_only=True,
                sub_path="repo",
            ),
            client.V1VolumeMount(name="tmp-volume", mount_path="/tmp"),
        ],
        "security_context": client.V1SecurityContext(
            allow_privilege_escalation=False,
            read_only_root_filesystem=True,
            capabilities=client.V1Capabilities(drop=["ALL"]),
        ),
    }

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
                name="repo-volume",
                host_path=client.V1HostPathVolumeSource(
                    path=host_dir, type="Directory"
                ),
            ),
            client.V1Volume(
                name="tmp-volume", empty_dir=client.V1EmptyDirVolumeSource()
            ),
        ],
    }
    if runtime_class:
        pod_spec_kwargs["runtime_class_name"] = runtime_class
        logger.info(
            "Repo sandbox Job %s using runtimeClassName=%s (virtio-fs hostPath share)",
            job_name,
            runtime_class,
        )

    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=settings.sandbox_namespace,
            labels=_labels(sandbox_id, "sandbox"),
        ),
        spec=client.V1JobSpec(
            ttl_seconds_after_finished=settings.job_ttl_seconds,
            backoff_limit=0,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=_labels(sandbox_id, "sandbox")),
                spec=client.V1PodSpec(**pod_spec_kwargs),
            ),
        ),
    )

    get_batch_v1().create_namespaced_job(namespace=settings.sandbox_namespace, body=job)
    logger.info("Created repo sandbox Job %s (entrypoint=%s)", job_name, entrypoint)
    return job_name


def create_cleanup_job(sandbox_id: str) -> str:
    """
    Create the cleanup Job: mount the **parent** host base path and
    ``rm -rf`` the per-sandbox sub-directory. Returns the Job name.
    """
    job_name = f"cleanup-{sandbox_id}"
    base = settings.repo_host_base_path
    cleanup_cmd = (
        "set -eu; "
        f"if [ -d /host/{sandbox_id} ]; then rm -rf /host/{sandbox_id}; fi; "
        f"echo 'cleaned /host/{sandbox_id} (parent={base})'"
    )

    container = client.V1Container(
        name="cleanup",
        image=settings.cleanup_image,
        image_pull_policy="IfNotPresent",
        command=["sh", "-c", cleanup_cmd],
        volume_mounts=[
            client.V1VolumeMount(name="repo-base", mount_path="/host"),
        ],
        security_context=client.V1SecurityContext(
            run_as_user=0,
            allow_privilege_escalation=False,
            capabilities=client.V1Capabilities(drop=["ALL"]),
        ),
        resources=client.V1ResourceRequirements(
            requests={"cpu": "20m", "memory": "32Mi"},
            limits={"cpu": "200m", "memory": "128Mi"},
        ),
    )

    pod_spec = client.V1PodSpec(
        restart_policy="Never",
        containers=[container],
        volumes=[
            client.V1Volume(
                name="repo-base",
                host_path=client.V1HostPathVolumeSource(
                    path=base, type="DirectoryOrCreate"
                ),
            ),
        ],
    )

    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=settings.sandbox_namespace,
            labels=_labels(sandbox_id, "cleanup"),
        ),
        spec=client.V1JobSpec(
            ttl_seconds_after_finished=settings.cleanup_timeout_seconds,
            backoff_limit=0,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=_labels(sandbox_id, "cleanup")),
                spec=pod_spec,
            ),
        ),
    )

    get_batch_v1().create_namespaced_job(namespace=settings.sandbox_namespace, body=job)
    logger.info("Created cleanup Job %s (rm -rf %s/%s)", job_name, base, sandbox_id)
    return job_name


async def wait_for_job_done(job_name: str, timeout: int) -> SandboxStatus:
    """Async-poll a Job to terminal state (succeeded / failed / timeout)."""
    deadline = asyncio.get_event_loop().time() + timeout
    batch = get_batch_v1()
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            logger.warning("Job %s did not finish within %ds", job_name, timeout)
            return SandboxStatus.FAILED
        try:
            job = batch.read_namespaced_job(
                name=job_name, namespace=settings.sandbox_namespace
            )
            status = job.status
            if status.succeeded and status.succeeded > 0:
                return SandboxStatus.COMPLETED
            if status.failed and status.failed > 0:
                return SandboxStatus.FAILED
        except ApiException as exc:
            logger.error("Error reading Job %s: %s", job_name, exc)
            return SandboxStatus.UNKNOWN
        await asyncio.sleep(settings.job_poll_interval_seconds)


def wait_for_job_done_sync(job_name: str, timeout: int) -> SandboxStatus:
    """Sync version (for use from synchronous delete paths)."""
    deadline = time.monotonic() + timeout
    batch = get_batch_v1()
    while True:
        if time.monotonic() >= deadline:
            logger.warning("Job %s did not finish within %ds", job_name, timeout)
            return SandboxStatus.FAILED
        try:
            job = batch.read_namespaced_job(
                name=job_name, namespace=settings.sandbox_namespace
            )
            status = job.status
            if status.succeeded and status.succeeded > 0:
                return SandboxStatus.COMPLETED
            if status.failed and status.failed > 0:
                return SandboxStatus.FAILED
        except ApiException as exc:
            logger.error("Error reading Job %s: %s", job_name, exc)
            return SandboxStatus.UNKNOWN
        time.sleep(max(0.25, settings.job_poll_interval_seconds))
