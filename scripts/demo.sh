#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8000}"
SERVER_PID=""
READY=false

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

cd "$PROJECT_DIR"

uv sync --locked
uv run --locked pytest -q

# Refuse an occupied port instead of accidentally checking another local app.
.venv/bin/python - "$PORT" <<'PY'
import socket
import sys

with socket.socket() as listener:
    listener.bind(("127.0.0.1", int(sys.argv[1])))
PY

BACKEND_HOST=127.0.0.1 BACKEND_PORT="$PORT" BACKEND_RELOAD=false .venv/bin/backend serve &
SERVER_PID=$!

for _ in {1..50}; do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    wait "$SERVER_PID"
    exit 1
  fi

  if curl --silent --fail --max-time 1 "http://127.0.0.1:$PORT/api/health" >/dev/null; then
    READY=true
    break
  fi

  sleep 0.2
done

if [[ "$READY" != true ]]; then
  printf 'API did not become ready on port %s\n' "$PORT" >&2
  exit 1
fi

BACKEND_HOST=127.0.0.1 BACKEND_PORT="$PORT" .venv/bin/backend ping
curl --silent --show-error --fail --max-time 5 "http://127.0.0.1:$PORT/" >/dev/null
curl --silent --show-error --fail --max-time 5 "http://127.0.0.1:$PORT/api/health"
printf '\n'
