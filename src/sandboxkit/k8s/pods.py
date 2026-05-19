"""Pod log retrieval for completed sandboxes."""

from __future__ import annotations

import logging

from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

from sandboxkit.utils.config import settings
from sandboxkit.k8s.client import get_core_v1

logger = logging.getLogger(__name__)


def get_pod_logs(sandbox_id: str) -> tuple[str, str, int]:
    """Retrieve stdout, stderr, and exit code from the completed sandbox pod.

    The kubernetes API does not expose stderr separately from stdout for
    terminated containers; we return the combined log as stdout and derive
    exit code from the container termination state.
    """
    core = get_core_v1()
    pods = core.list_namespaced_pod(
        namespace=settings.sandbox_namespace,
        label_selector=f"sandbox-id={sandbox_id}",
    )

    if not pods.items:
        logger.warning("No pods found for sandbox %s", sandbox_id)
        return "", "No pods found for this sandbox", 1

    pod = pods.items[0]
    pod_name = pod.metadata.name

    exit_code = 1
    stderr_text = ""
    container_statuses = pod.status.container_statuses or []
    for cs in container_statuses:
        if cs.name == "sandbox" and cs.state and cs.state.terminated:
            term = cs.state.terminated
            exit_code = term.exit_code or 0
            if term.reason == "OOMKilled":
                stderr_text = (
                    "Container was OOMKilled (exit 137): " "the process exceeded the memory limit."
                )
            elif term.message:
                stderr_text = term.message
            break

    try:
        stdout_text = core.read_namespaced_pod_log(
            name=pod_name,
            namespace=settings.sandbox_namespace,
            container="sandbox",
        )
    except ApiException as exc:
        logger.error("Failed to read logs for pod %s: %s", pod_name, exc)
        stdout_text = ""
        stderr_text = str(exc)

    return stdout_text, stderr_text, exit_code
