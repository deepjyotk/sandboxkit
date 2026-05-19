"""Helpers for comparing Kubernetes resource quantities."""

from __future__ import annotations

from kubernetes.utils.quantity import parse_quantity  # type: ignore[import-untyped]


def cap_request_at_limit(request: str, limit: str) -> str:
    """Return the smaller of request and limit (K8s requires request <= limit)."""
    if parse_quantity(request) <= parse_quantity(limit):
        return request
    return limit
