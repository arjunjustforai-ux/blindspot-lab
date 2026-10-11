"""Database-backed background worker.

Claims queued jobs with `SELECT ... FOR UPDATE SKIP LOCKED` so several worker
processes can run safely. Handles ingestion jobs, knowledge rebuilds and queued
evaluation runs. Run standalone with `python -m app.worker`, or in-process (dev)
when RUN_WORKER_IN_PROCESS=true.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.config import get_settings
from app.db import SessionLocal
from app.models import EvaluationRun, IngestionJob

log = logging.getLogger("blindspot.worker")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
STALE_AFTER = timedelta(minutes=45)


def _now() -> datetime:
    return datetime.now(UTC)


def claim_job() -> uuid.UUID | None:
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                UPDATE ingestion_jobs SET status='running', locked_by=:w, locked_at=now(),
                       started_at=coalesce(started_at, now()), attempts=attempts+1
                WHERE id = (
                    SELECT id FROM ingestion_jobs WHERE status='queued'
                    ORDER BY (kind='rebuild_knowledge'), created_at
                    FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING id
                """
            ),
            {"w": WORKER_ID},
        ).first()
        db.commit()
        return row[0] if row else None


def claim_eval_run() -> uuid.UUID | None:
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                UPDATE evaluation_runs SET status='running', locked_by=:w, started_at=now()
                WHERE id = (SELECT id FROM evaluation_runs WHERE status='queued' ORDER BY created_at
                            FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING id
                """
            ),
            {"w": WORKER_ID},
        ).first()
        db.commit()
        return row[0] if row else None


def requeue_stale() -> None:
    cutoff = _now() - STALE_AFTER
    with SessionLocal() as db:
        db.execute(
            text(
                "UPDATE ingestion_jobs SET status=CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END, "
                "error=coalesce(error, 'Worker stopped before finishing'), locked_by=NULL "
                "WHERE status='running' AND locked_at < :c"
            ),
            {"c": cutoff},
        )
        db.commit()


def process_job(job_id: uuid.UUID) -> None:
    from app.services.ingestion.pipeline import fail_job, run_ingest
    from app.services.knowledge.build import rebuild_course_knowledge

    with SessionLocal() as db:
        job = db.get(IngestionJob, job_id)
        if job is None:
            return
        kind, course_id = job.kind, job.course_id
        db.expunge(job)
    try:
        if kind == "ingest_source":
            run_ingest(job)
        elif kind == "rebuild_knowledge":
            rebuild_course_knowledge(course_id, job_id=job_id)
        with SessionLocal() as db:
            j = db.get(IngestionJob, job_id)
            if j is not None:
                j.status = "succeeded"
                j.progress = 1.0
                j.stage = "done"
                j.finished_at = _now()
                j.locked_by = None
                db.commit()
    except Exception as e:
        log.exception("job %s failed", job_id)
        if kind == "rebuild_knowledge":
            from app.models import Course

            with SessionLocal() as db:
                c = db.get(Course, course_id)
                if c:
                    c.knowledge_status = "failed"
                    db.commit()
        fail_job(job_id, e)


def process_eval_run(run_id: uuid.UUID) -> None:
    from app.services.evaluation.runner import execute_run

    try:
        execute_run(run_id)
    except Exception as e:
        log.exception("evaluation run %s failed", run_id)
        with SessionLocal() as db:
            r = db.get(EvaluationRun, run_id)
            if r is not None:
                r.status = "failed"
                r.error = f"{e.__class__.__name__}: {e}"[:4000]
                r.finished_at = _now()
                db.commit()


def run_once() -> bool:
    """Process at most one unit of work. Returns True if something was processed."""
    job_id = claim_job()
    if job_id:
        process_job(job_id)
        return True
    run_id = claim_eval_run()
    if run_id:
        process_eval_run(run_id)
        return True
    return False


def drain(max_iterations: int = 1000) -> int:
    n = 0
    while n < max_iterations and run_once():
        n += 1
    return n


def run_forever(stop: threading.Event | None = None) -> None:
    s = get_settings()
    log.info("worker %s started", WORKER_ID)
    last_stale = 0.0
    while not (stop and stop.is_set()):
        try:
            if time.time() - last_stale > 300:
                requeue_stale()
                last_stale = time.time()
            if not run_once():
                time.sleep(s.worker_poll_seconds)
        except Exception:
            log.exception("worker loop error")
            time.sleep(5)


def pending_counts() -> dict[str, int]:
    with SessionLocal() as db:
        jobs = db.scalars(select(IngestionJob.status)).all()
    out: dict[str, int] = {}
    for st in jobs:
        out[st] = out.get(st, 0) + 1
    return out


if __name__ == "__main__":
    from app.logging_setup import configure_logging

    configure_logging()
    run_forever()
