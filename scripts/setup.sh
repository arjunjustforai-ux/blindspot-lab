#!/usr/bin/env bash
# One-time local setup without Docker: Python env, web dependencies, database and demo course.
# Needs: Python 3.12+, Node 20+, PostgreSQL 16 with pgvector, tesseract-ocr, ffmpeg (LibreOffice optional),
# and `uv` (https://docs.astral.sh/uv/) or pip.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example; set JWT_SECRET before production use"; }

echo "==> Python environment (services/api/.venv)"
cd services/api
if command -v uv >/dev/null; then
  uv venv --allow-existing .venv
  uv pip install --python .venv/bin/python -e ".[dev,eval]"
else
  python3 -m venv .venv
  .venv/bin/pip install -e ".[dev,eval]"
fi

echo "==> Database migrations"
set -a; . "$ROOT/.env"; set +a
.venv/bin/alembic upgrade head

echo "==> Downloading local models (first run only)"
.venv/bin/python -m app.cli warm-models

echo "==> Ingesting the demo course pack (PDF, PPTX, narrated MP4)"
.venv/bin/python -m app.cli seed-demo

echo "==> Web dependencies"
cd "$ROOT/apps/web"
npm ci --no-audit --no-fund

echo "Done. Start everything with scripts/start_dev.sh"
