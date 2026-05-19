# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Build stage — install dependencies with uv
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Hatchling needs README.md (pyproject readme) and src/ to build the local package
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN uv sync --no-dev --frozen

# ---------------------------------------------------------------------------
# Runtime stage — lean final image
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

WORKDIR /app

# Non-root user for the service itself
RUN adduser --system --no-create-home --uid 1000 sandboxkit

# Bring over the virtualenv and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

# Put the venv's bin on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER sandboxkit

EXPOSE 8000

CMD ["python", "-m", "sandboxkit.main"]
