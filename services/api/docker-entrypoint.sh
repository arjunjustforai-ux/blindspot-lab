#!/bin/sh
# Entry point for the API/worker image.
#   api        run migrations, optionally queue the demo course, then serve on $PORT (default 8000)
#   worker     process ingestion jobs and evaluation runs
#   <other>    passed to the CLI, e.g. `seed-demo`, `drain`, `reset-demo`
set -e
cmd="${1:-api}"
shift || true
case "$cmd" in
  api)
    alembic upgrade head
    if [ "${SEED_DEMO:-false}" = "true" ]; then
      # Queue the demo pack; a worker (separate service, or RUN_WORKER_IN_PROCESS=true) ingests it.
      python -m app.cli seed-demo --no-process
    fi
    exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
    ;;
  worker)
    exec python -m app.cli worker
    ;;
  *)
    exec python -m app.cli "$cmd" "$@"
    ;;
esac
