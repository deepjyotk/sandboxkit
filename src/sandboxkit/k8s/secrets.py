"""Kubernetes Secret helpers for sandbox environment variables."""

from __future__ import annotations

import logging

from kubernetes import client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

from sandboxkit.utils.config import settings
from sandboxkit.k8s.client import get_core_v1

logger = logging.getLogger(__name__)


def create_sandbox_secret(sandbox_id: str, data: dict[str, str]) -> str:
    """Create a Secret for env injection; returns the Secret name."""
    secret_name = f"secrets-{sandbox_id}"

    secret = client.V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=client.V1ObjectMeta(
            name=secret_name,
            namespace=settings.sandbox_namespace,
            labels={"app": "sandboxkit", "sandbox-id": sandbox_id},
        ),
        type="Opaque",
        string_data=data,
    )
    get_core_v1().create_namespaced_secret(namespace=settings.sandbox_namespace, body=secret)
    logger.info("Created Secret %s with %d key(s)", secret_name, len(data))
    return secret_name


def delete_secret(secret_name: str) -> None:
    try:
        get_core_v1().delete_namespaced_secret(
            name=secret_name, namespace=settings.sandbox_namespace
        )
        logger.info("Deleted Secret %s", secret_name)
    except ApiException as exc:
        if exc.status != 404:
            logger.warning("Could not delete Secret %s: %s", secret_name, exc)
