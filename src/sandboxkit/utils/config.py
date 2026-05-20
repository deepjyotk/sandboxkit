"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    sandbox_namespace: str = "sandboxes"
    job_timeout_seconds: int = 60
    job_poll_interval_seconds: float = 1.0
    # Path to kubeconfig file; empty string means auto-detect (in-cluster → local)
    kubeconfig: str = ""
    # Resource limits for sandbox pods
    sandbox_cpu_limit: str = "500m"
    sandbox_memory_limit: str = "256Mi"
    sandbox_cpu_request: str = "100m"
    sandbox_memory_request: str = "64Mi"
    # Seconds before the completed/failed Job is auto-deleted by K8s GC
    job_ttl_seconds: int = 300
    # Prebuilt sandbox template images (override via env; full ref from registry)
    template_py_image: str = "sandboxkit-py-template:latest"
    template_js_image: str = "sandbox-js-template:latest"
    sandbox_image_pull_policy: str = "IfNotPresent"
    # Kata / MicroVM: False = cluster default (runc) on kind/local; True = microVM on KVM nodes.
    use_kata: bool = True
    # RuntimeClass when use_kata=True (e.g. kata-qemu, kata-fc, kata-dragonball).
    kata_runtime_class: str = "kata-qemu"
    # When use_kata=False, optional override; empty = cluster default runtime (runc).
    sandbox_runtime_class: str = ""
    # JWT cookie auth (validated at nginx via /auth/validate subrequest).
    jwt_secret: str = "dev-secret-change-me"
    jwt_cookie_name: str = "auth_token"
    jwt_ttl_seconds: int = 24 * 3600


settings = Settings()
