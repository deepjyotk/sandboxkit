"""Kubernetes API client initialization and accessors."""

from __future__ import annotations

import logging

from kubernetes import client, config as k8s_config  # type: ignore[import-untyped]

from sandboxkit.utils.config import settings

logger = logging.getLogger(__name__)


def _load_k8s_config() -> None:
    """Load kubeconfig: in-cluster first, then local kubeconfig file."""
    try:
        k8s_config.load_incluster_config()
        logger.info("Using in-cluster Kubernetes config")
    except k8s_config.ConfigException:
        kubeconfig = settings.kubeconfig or None
        k8s_config.load_kube_config(config_file=kubeconfig)
        logger.info("Using local kubeconfig")


def get_batch_v1() -> client.BatchV1Api:
    return client.BatchV1Api()


def get_core_v1() -> client.CoreV1Api:
    return client.CoreV1Api()
