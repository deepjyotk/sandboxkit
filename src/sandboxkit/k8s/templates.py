"""Sandbox runtime template registry."""

from __future__ import annotations

from sandboxkit.utils.config import settings


def get_sandbox_templates() -> dict[str, dict]:
    """Return template registry with image refs from settings."""
    return {
        "sandboxkit-py-template": {
            "image": settings.template_py_image,
            "command": None,  # image ENTRYPOINT runs /sandbox/code.py
            "file_extension": "py",
            "memory_limit": "384Mi",
        },
        "sandbox-js-template": {
            "image": settings.template_js_image,
            "command": None,  # image ENTRYPOINT runs /sandbox/code.js
            "file_extension": "js",
            "memory_limit": "256Mi",
        },
    }


def list_sandbox_template_names() -> list[str]:
    return list(get_sandbox_templates().keys())
