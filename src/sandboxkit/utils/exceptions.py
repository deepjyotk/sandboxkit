"""Domain exceptions raised by sandbox orchestration."""

from __future__ import annotations


class UnknownTemplateError(ValueError):
    def __init__(self, template_name: str, available: list[str]) -> None:
        self.template_name = template_name
        self.available = available
        super().__init__(f"Unknown sandbox_template '{template_name}'")


class SandboxNotFoundError(LookupError):
    def __init__(self, sandbox_id: str) -> None:
        self.sandbox_id = sandbox_id
        super().__init__(f"Sandbox '{sandbox_id}' not found")


class SandboxResourceError(RuntimeError):
    def __init__(self, sandbox_id: str, message: str, cause: Exception | None = None) -> None:
        self.sandbox_id = sandbox_id
        super().__init__(message)
        self.__cause__ = cause


class ResourceLimitError(ValueError):
    def __init__(self, field: str, value: str, hint: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"Invalid {field} '{value}': {hint}")


class UnknownSecretError(LookupError):
    """Raised when one or more requested secret names are not in the vault."""

    def __init__(self, missing: list[str], available: list[str]) -> None:
        self.missing = missing
        self.available = available
        super().__init__(f"Unknown secret name(s): {missing}. Available: {available}")
