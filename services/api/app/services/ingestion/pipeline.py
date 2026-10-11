"""Ingestion job execution: extract -> persist units -> embed -> ready -> rebuild knowledge."""

from __future__ import annotations

import logging
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ContentUnit, Course, IngestionJob, SourceFile
from app.services.ai.embeddings import get_embedder
from app.services.ai.text import content_hash, word_count
from app.services.ingestion.pdf import extract_pdf
from app.services.ingestion.pptx import extract_pptx
from app.services.ingestion.types import ExtractionError, ExtractionResult
from app.services.ingestion.video import extract_video
from app.services.storage import get_storage

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue_ingest(db: Session, source: SourceFile) -> IngestionJob:
    job = IngestionJob(course_id=source.course_id, source_file_id=source.id, kind="ingest_source", status="queued",
                       stage="queued")
    db.add(job)
    return job


def enqueue_rebuild(db: Session, course_id: uuid.UUID) -> IngestionJob | None:
    existing = db.scalar(
        select(IngestionJob).where(
            IngestionJob.course_id == course_id, IngestionJob.kind == "rebuild_knowledge",
            IngestionJob.status == "queued",
        )
    )
    if existing:
        return existing
    job = IngestionJob(course_id=course_id, kind="rebuild_knowledge", status="queued", stage="queued")
    db.add(job)
    return job


class JobContext:
    def __init__(self, job_id: uuid.UUID) -> None:
        self.job_id = job_id

    def progress(self, stage: str, frac: float, *, source_status: str | None = None) -> None:
        with SessionLocal() as db:
            job = db.get(IngestionJob, self.job_id)
            if job is None:
                return
            job.stage = stage[:60]
            job.progress = max(0.0, min(1.0, frac))
            job.log = [*job.log[-49:], {"t": _now().isoformat(), "stage": stage, "progress": round(frac, 3)}]
            if job.source_file_id:
                values: dict = {"status_detail": stage}
                if source_status:
                    values["status"] = source_status
                db.execute(update(SourceFile).where(SourceFile.id == job.source_file_id).values(**values))
            db.commit()


def run_ingest(job: IngestionJob) -> None:
    ctx = JobContext(job.id)
    with SessionLocal() as db:
        source = db.get(SourceFile, job.source_file_id)
        if source is None:
            raise ExtractionError("Source file no longer exists")
        modality, key, course_id, source_id = source.modality, source.storage_key, source.course_id, source.id
        filename = source.filename

    storage = get_storage()
    path: Path = storage.local_path(key)
    ctx.progress("Extracting content", 0.02, source_status="extracting")

    def prog(msg: str, frac: float) -> None:
        ctx.progress(msg, 0.02 + 0.68 * frac, source_status="extracting")

    if modality == "pdf":
        result = extract_pdf(path, course_id=course_id, progress=prog)
    elif modality == "pptx":
        result = extract_pptx(path, course_id=course_id, progress=prog)
    elif modality == "video":
        result = extract_video(path, course_id=course_id, progress=prog)
    else:
        raise ExtractionError(f"Unsupported modality {modality}")

    ctx.progress(f"Indexing {len(result.units)} units", 0.72, source_status="indexing")
    _persist(result, course_id=course_id, source_id=source_id, ctx=ctx)

    with SessionLocal() as db:
        src = db.get(SourceFile, source_id)
        assert src is not None
        src.status = "ready"
        src.error = None
        counts: dict[str, int] = {}
        for u in result.units:
            counts[u.modality] = counts.get(u.modality, 0) + 1
        src.status_detail = f"Ready: {len(result.units)} units extracted from {filename}"
        src.page_count = result.page_count
        src.slide_count = result.slide_count
        src.duration_seconds = result.duration_seconds
        src.metadata_json = {**(src.metadata_json or {}), **result.metadata, "unit_counts": counts,
                             "warnings": result.warnings}
        course = db.get(Course, course_id)
        if course is not None:
            course.knowledge_status = "stale"
        enqueue_rebuild(db, course_id)
        db.commit()


def _persist(result: ExtractionResult, *, course_id: uuid.UUID, source_id: uuid.UUID, ctx: JobContext) -> None:
    storage = get_storage()
    embedder = get_embedder()
    # Previews (slides)
    for n, png in result.previews.items():
        storage.put_bytes(f"courses/{course_id}/sources/{source_id}/previews/slide-{n:03d}.png", png, "image/png")

    texts = [((u.heading + "\n") if u.heading and u.modality not in ("slide_notes",) else "") + u.content
             for u in result.units]
    vectors: list[list[float]] = []
    batch = 32
    for i in range(0, len(texts), batch):
        vectors.extend(embedder.embed_documents(texts[i : i + batch]))
        ctx.progress(f"Embedding units {min(i + batch, len(texts))}/{len(texts)}",
                     0.72 + 0.23 * min(i + batch, len(texts)) / max(len(texts), 1), source_status="indexing")

    with SessionLocal() as db:
        # Reindex semantics: replace all units of this source atomically.
        db.execute(delete(ContentUnit).where(ContentUnit.source_file_id == source_id))
        for idx, (u, vec) in enumerate(zip(result.units, vectors)):
            image_key = None
            if u.image_png:
                image_key = f"courses/{course_id}/sources/{source_id}/images/unit-{idx:04d}.png"
                storage.put_bytes(image_key, u.image_png, "image/png")
            db.add(
                ContentUnit(
                    course_id=course_id, source_file_id=source_id, modality=u.modality, order_index=idx,
                    heading=(u.heading or None) and u.heading[:300], section_path=u.section_path, content=u.content,
                    content_hash=content_hash(u.content), page_number=u.page_number, slide_number=u.slide_number,
                    start_seconds=u.start_seconds, end_seconds=u.end_seconds, bbox=u.bbox,
                    image_storage_key=image_key, is_generated=u.is_generated, generation_meta=u.generation_meta,
                    extraction_meta=u.extraction_meta, embedding=vec, embedding_model=embedder.name,
                    token_count=word_count(u.content),
                )
            )
        db.commit()


def fail_job(job_id: uuid.UUID, err: BaseException) -> None:
    msg = str(err) if isinstance(err, ExtractionError) else f"Unexpected processing error: {err.__class__.__name__}: {err}"
    with SessionLocal() as db:
        job = db.get(IngestionJob, job_id)
        if job is None:
            return
        job.attempts = job.attempts or 0
        retryable = not isinstance(err, ExtractionError) and job.attempts < job.max_attempts
        job.error = msg[:4000]
        job.log = [*job.log[-49:], {"t": _now().isoformat(), "error": msg[:500],
                                    "trace": traceback.format_exc()[-1500:]}]
        job.status = "queued" if retryable else "failed"
        job.finished_at = None if retryable else _now()
        job.locked_by = None
        if job.source_file_id and not retryable:
            db.execute(
                update(SourceFile).where(SourceFile.id == job.source_file_id).values(
                    status="failed", error=msg[:4000], status_detail="Failed"
                )
            )
        db.commit()
