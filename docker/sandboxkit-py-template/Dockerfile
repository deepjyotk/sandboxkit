# syntax=docker/dockerfile:1
# Prebuilt sandbox runtime: Python 3.13 + FastAPI stack for user snippets.
FROM python:3.13-slim

RUN pip install --no-cache-dir \
    "fastapi>=0.121.0" \
    "uvicorn[standard]>=0.38.0" \
    "pydantic>=2.0" \
    "httpx>=0.28.0"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# User code is mounted at /sandbox/code.py via ConfigMap
WORKDIR /sandbox

USER nobody

ENTRYPOINT ["/entrypoint.sh"]
