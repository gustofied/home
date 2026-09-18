#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8000}"
SERVER_PID=""
READY=false
DEMO_DATA_DIR="$(mktemp -d "${TMPDIR:-/tmp}/databank-demo.XXXXXX")"

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$DEMO_DATA_DIR"
}
trap cleanup EXIT

cd "$PROJECT_DIR"

uv sync --locked
uv run --locked backend run --from-snapshot data/bronze/example --data-dir "$DEMO_DATA_DIR"
uv run --locked pytest -q

# Refuse an occupied port instead of accidentally checking another local app.
.venv/bin/python - "$PORT" <<'PY'
import socket
import sys

with socket.socket() as listener:
    listener.bind(("127.0.0.1", int(sys.argv[1])))
PY

BACKEND_DATA_DIR="$DEMO_DATA_DIR" BACKEND_HOST=127.0.0.1 BACKEND_PORT="$PORT" BACKEND_RELOAD=false .venv/bin/backend serve &
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
curl --silent --show-error --fail --max-time 5 "http://127.0.0.1:$PORT/api/overview" | .venv/bin/python -c 'import json, sys; r=json.load(sys.stdin); assert r["summary"]["facility_count"] == 4; assert r["source"]["data_kind"] == "synthetic"; print(json.dumps(r["summary"], indent=2))'
curl --silent --show-error --fail --max-time 5 "http://127.0.0.1:$PORT/api/facilities?market=chicago&min_capacity_mw=5" | .venv/bin/python -c 'import json, sys; r=json.load(sys.stdin); assert r["count"] == 1; assert r["facilities"][0]["facility_code"] == "ORD4"'
printf '\n'
