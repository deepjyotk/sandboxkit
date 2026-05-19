"""ConfigMap helpers for sandbox user code."""

from __future__ import annotations

import logging

from kubernetes import client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

from sandboxkit.utils.config import settings
from sandboxkit.k8s.client import get_core_v1

logger = logging.getLogger(__name__)


def create_code_configmap(sandbox_id: str, code: str, file_extension: str) -> str:
    """Create a ConfigMap containing the code file; returns the ConfigMap name."""
    cm_name = f"code-{sandbox_id}"
    filename = f"code.{file_extension}"

    cm = client.V1ConfigMap(
        api_version="v1",
        kind="ConfigMap",
        metadata=client.V1ObjectMeta(
            name=cm_name,
            namespace=settings.sandbox_namespace,
            labels={"app": "sandboxkit", "sandbox-id": sandbox_id},
        ),
        data={filename: code},
    )
    get_core_v1().create_namespaced_config_map(namespace=settings.sandbox_namespace, body=cm)
    logger.info("Created ConfigMap %s", cm_name)
    return cm_name


def delete_configmap(cm_name: str) -> None:
    try:
        get_core_v1().delete_namespaced_config_map(
            name=cm_name, namespace=settings.sandbox_namespace
        )
        logger.info("Deleted ConfigMap %s", cm_name)
    except ApiException as exc:
        if exc.status != 404:
            logger.warning("Could not delete ConfigMap %s: %s", cm_name, exc)
