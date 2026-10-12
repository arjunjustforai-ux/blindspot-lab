# Deployment and operations

Nothing in this repository has been deployed to a public URL by the team yet. The configurations below are prepared and the container entrypoints are exercised by the same commands used locally; the Docker images themselves have not been built in the development environment (no Docker daemon there), so treat the first image build as the first test of the Dockerfiles.

## Requirements

| Component | Minimum | Notes |
|---|---|---|
| PostgreSQL | 16 with the `vector` extension (pgvector ≥ 0.5) | Supabase, Render, Railway and Neon all offer pgvector. |
| API + worker | Python 3.12+ (3.13 tested), ~2 GB RAM, 2 vCPU | Tesseract, FFmpeg; LibreOffice only for slide previews. Local models: ~350 MB on disk. |
| Web | Node 20+ (22 tested) | Static + server-rendered Next.js; any Node host or Vercel. |
| AI provider | none required | Optional OpenAI-compatible API for generative answers, question verification, figure descriptions and RAGAS LLM-judge metrics. |

## Configuration

All configuration is environment variables; `.env.example` documents each one. The important ones:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://…`; `postgres://` and `postgresql://` URLs from hosting providers are accepted and converted. |
| `JWT_SECRET` | ≥ 32 random characters. With `ENVIRONMENT=production` the API refuses to start with the development default or a short secret. |
| `CORS_ORIGINS` | Comma-separated web origins allowed to call the API (e.g. `https://blindspot.vercel.app`). |
| `NEXT_PUBLIC_API_URL` | Public URL of the API, baked into the web build. |
| `STORAGE_BACKEND` | `local` (default; `LOCAL_STORAGE_DIR` must be a persistent volume) or `supabase` (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET`; implemented but not yet tested against a live project). |
| `RUN_WORKER_IN_PROCESS` | `true` runs the job worker inside the API process (one service); `false` when a separate worker runs. |
| `MODEL_CACHE_DIR` | Where local models are cached; the API image pre-downloads them at build time. |
| `LLM_PROVIDER`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`, `VERIFIER_MODEL`, `VISION_MODEL` | Optional generative mode. `LLM_PROVIDER=local` (default) never sends content to an external provider. |
| `MAX_DOCUMENT_MB`, `MAX_VIDEO_MB`, `MAX_VIDEO_MINUTES`, `MAX_VISION_CALLS_PER_SOURCE`, `MAX_LLM_CALLS_PER_USER_PER_DAY` | Bounds that keep a demo deployment affordable. Defaults: 60 MB, 400 MB, 90 min, 24 vision calls per file, 400 model calls per user per day. |
| `DEMO_ENABLED` | Enables one-click synthetic demo learners. |

## Local, without Docker

```bash
cp .env.example .env            # set JWT_SECRET; DATABASE_URL points at your Postgres
scripts/setup.sh                # venv, deps, migrations, model download, demo course ingestion, npm ci
scripts/start_dev.sh            # API :8000 (worker in-process) + web :3000
```

Database migrations at any time: `cd services/api && .venv/bin/alembic upgrade head`. The first migration runs `CREATE EXTENSION IF NOT EXISTS vector`; if the application's database role is not allowed to create extensions, run that statement once as a superuser (or enable *vector* in the provider's dashboard) before migrating.

## Docker Compose

```bash
cp .env.example .env            # set JWT_SECRET
docker compose up --build       # db (pgvector), api, worker, web
```

The API container runs `alembic upgrade head`, queues the demo pack (`SEED_DEMO=true`) and serves on :8000; the worker ingests the demo course on first start (a few minutes on CPU). Uploads persist in the `storage` volume and the database in `pgdata`.

## Production build commands

```bash
docker build -f services/api/Dockerfile -t blindspot-api .                 # API and worker image
docker build --build-arg NEXT_PUBLIC_API_URL=https://api.example.com -t blindspot-web apps/web
cd apps/web && npm ci && npm run build && npm run start                     # without Docker
```

The API image entrypoint accepts `api` (default), `worker`, or any CLI command (`seed-demo`, `drain`, `reset-demo`, `warm-models`). Health checks: `GET /api/health` (process up) and `GET /api/ready` (database, pgvector, migration revision, storage, AI mode).

## Hosted options

**Recommended bounded demo: Render blueprint** (`render.yaml`). One Postgres database, one API web service with the worker in-process and a 5 GB persistent disk for uploads, and the web app. Steps: *New → Blueprint* on the repository, then set `CORS_ORIGINS` (the web service URL) and `NEXT_PUBLIC_API_URL` (the API service URL) and redeploy the web service. Render generates `JWT_SECRET`. The API plan needs about 2 GB RAM for Whisper and the embedding models.

**Vercel (web) + Railway (API, worker) + Supabase (Postgres, storage).**
1. Supabase: create a project, enable the `vector` extension (Database → Extensions), create a private storage bucket `course-materials` (the default `SUPABASE_STORAGE_BUCKET`), and copy the connection string and service-role key.
2. Railway: create a service from this repository with config file `deploy/railway/api.json`, and a second with `deploy/railway/worker.json`. Set `DATABASE_URL`, `JWT_SECRET`, `ENVIRONMENT=production`, `STORAGE_BACKEND=supabase`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET`, `CORS_ORIGINS`, `RUN_WORKER_IN_PROCESS=false`, and `SEED_DEMO=true` on the API. (Alternatively run only the API service with `RUN_WORKER_IN_PROCESS=true` and a Railway volume mounted at `/data/storage` with `STORAGE_BACKEND=local`.)
3. Vercel: import the repository with root directory `apps/web` (`apps/web/vercel.json`), set `NEXT_PUBLIC_API_URL` to the Railway API URL, deploy.

The Supabase storage path is implemented (`services/storage.py`) but has not been tested against a live Supabase project; the local-disk path is the one exercised by every test and by the recorded evaluation.

## Operations

* **Jobs**: `ingestion_jobs` and `evaluation_runs` are the queue. Multiple workers are safe (`FOR UPDATE SKIP LOCKED`). Stale running jobs are re-queued after 45 min (up to the retry limit); evaluation runs stuck for 4 h are marked failed.
* **Logs**: structured JSON (structlog) with request id, path, status and latency; every model call is recorded in `ai_operation_logs`.
* **Demo data**: `python -m app.cli reset-demo` (or `scripts/reset_demo.sh`) deletes all synthetic demo learners; demo learners can also reset their own progress from the dashboard.
* **Backups**: standard PostgreSQL backups cover all learner evidence; uploaded files live in the storage volume or bucket.
