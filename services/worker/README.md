# Worker

The worker processes the durable job queue stored in PostgreSQL (`ingestion_jobs`, `evaluation_runs`):

* `ingest_source` — extract a PDF, PPTX or video (OCR, Whisper transcription, keyframes), chunk, embed and index it
* `rebuild_knowledge` — rebuild the course's concept graph, misconception activation and verified question pool
* queued evaluation runs started from the Evaluation Lab

Jobs are claimed with `SELECT … FOR UPDATE SKIP LOCKED`, so several workers can run safely. A job whose worker
dies is re-queued after 45 minutes (up to its retry limit); an evaluation run that never finishes is marked failed.

The code lives in `services/api/app/worker.py` and shares everything with the API, so the worker runs from the
same image:

```bash
docker run --env-file .env blindspot-api worker          # or: docker compose up worker
python -m app.cli worker                                  # local, from services/api
python -m app.cli drain                                   # process everything queued, then exit
```

For a single-process deployment (one small container), set `RUN_WORKER_IN_PROCESS=true` on the API instead and
skip this service.
