#!/bin/sh
# Run user code with tsx (TypeScript + JavaScript). Prefer code.ts; fall back to code.js.
set -e
TSX=/app/node_modules/.bin/tsx
if [ -f /sandbox/code.ts ]; then
  exec "$TSX" /sandbox/code.ts
fi
if [ -f /sandbox/code.js ]; then
  exec "$TSX" /sandbox/code.js
fi
echo "No code file found at /sandbox/code.ts or /sandbox/code.js" >&2
exit 1
