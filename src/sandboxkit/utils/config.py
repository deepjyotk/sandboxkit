"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Kata / MicroVM feature flag (hardcoded; flip for DO demo vs kind/local) ---
# False: sandbox pods use cluster default runtime (runc) — kind/Mac dev.
# True:  sandbox Jobs set runtimeClassName (Kata microVM on KVM nodes).
USE_KATA: bool = True
KATA_RUNTIME_CLASS: str = "kata-qemu"  # matches kata-deploy default install on DO droplet


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
    # Empty = cluster default runtime (runc). Set to "kata" / "kata-qemu" / "kata-fc" on Kata nodes.
    sandbox_runtime_class: str = ""
    # JWT cookie auth (validated at nginx via /auth/validate subrequest).
    jwt_secret: str = "dev-secret-change-me"
    jwt_cookie_name: str = "auth_token"
    jwt_ttl_seconds: int = 24 * 3600


settings = Settings()
