# syntax=docker/dockerfile:1
# Prebuilt sandbox runtime: Node 22 + axios + tsx (TypeScript/JavaScript user snippets).
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --omit=dev 2>/dev/null || npm install --omit=dev \
    && chmod -R a+rX /app/node_modules

ENV NODE_PATH=/app/node_modules

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# User code is mounted at /sandbox/code.ts (or legacy code.js) via ConfigMap
WORKDIR /sandbox

ENTRYPOINT ["/entrypoint.sh"]
