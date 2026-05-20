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

    Repo-mode also creates clone/cleanup pods with the same ``sandbox-id``
    label; we must not pick those when reading the user sandbox — prefer
    ``sandbox-role=sandbox`` when present, else the pod whose spec defines a
    ``sandbox`` container.
    """
    core = get_core_v1()
    ns = settings.sandbox_namespace

    pods = core.list_namespaced_pod(
        namespace=ns,
        label_selector=f"sandbox-id={sandbox_id},sandbox-role=sandbox",
    )
    if not pods.items:
        pods = core.list_namespaced_pod(
            namespace=ns,
            label_selector=f"sandbox-id={sandbox_id}",
        )

    if not pods.items:
        logger.warning("No pods found for sandbox %s", sandbox_id)
        return "", "No pods found for this sandbox", 1

    pod = None
    for p in pods.items:
        names = [c.name for c in (p.spec.containers or [])]
        if "sandbox" in names:
            pod = p
            break
    if pod is None:
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
            namespace=ns,
            container="sandbox",
        )
    except ApiException as exc:
        logger.error("Failed to read logs for pod %s: %s", pod_name, exc)
        stdout_text = ""
        stderr_text = str(exc)

    return stdout_text, stderr_text, exit_code
