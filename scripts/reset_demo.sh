#!/usr/bin/env bash
# Delete all synthetic demo learners and their activity (the demo course and its sources are kept).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a; . "$ROOT/.env"; set +a
cd "$ROOT/services/api" && .venv/bin/python -m app.cli reset-demo
