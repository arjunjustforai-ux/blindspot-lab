#!/usr/bin/env bash
# Backend unit + integration tests, frontend unit tests and type checks.
# Integration tests use the database in TEST_DATABASE_URL (default .../blindspot_test) and reset it.
# End-to-end tests (needs the app running): cd tests/e2e && npx playwright test
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/services/api"
.venv/bin/ruff check app tests
.venv/bin/python -m pytest tests -p no:logging
cd "$ROOT/apps/web"
npx tsc --noEmit
npx vitest run
