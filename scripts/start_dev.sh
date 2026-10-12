#!/usr/bin/env bash
# Start the API (with the worker in-process) on :8000 and the web app on :3000. Ctrl-C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a; . "$ROOT/.env"; set +a

(cd "$ROOT/services/api" && RUN_WORKER_IN_PROCESS="${RUN_WORKER_IN_PROCESS:-true}" \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) &
API_PID=$!
(cd "$ROOT/apps/web" && npm run dev -- --port 3000) &
WEB_PID=$!
trap 'kill $API_PID $WEB_PID 2>/dev/null' EXIT INT TERM
echo "API http://localhost:8000/api/health   Web http://localhost:3000"
wait
