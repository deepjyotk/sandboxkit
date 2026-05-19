"""FastAPI application entrypoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from sandboxkit import __version__
from sandboxkit.apis.sandbox_apis import router as sandbox_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SandboxKit",
    description=(
        "Sandbox-as-a-service control plane. "
        "Creates isolated Kubernetes Jobs to execute code snippets."
    ),
    version=__version__,
)

app.include_router(sandbox_router)


def run() -> None:
    import uvicorn

    uvicorn.run(
        "sandboxkit.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    run()
