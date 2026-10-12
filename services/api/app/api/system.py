"""Health/readiness and evaluation-run endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select, text

from app.config import get_settings
from app.core.deps import DB, CurrentUser, require_course
from app.core.errors import APIError, not_found
from app.db import SessionLocal
from app.models import Course, EvaluationResult, EvaluationRun
from app.schemas import EvaluationRunIn

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict[str, Any]:
    s = get_settings()
    checks: dict[str, Any] = {}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            checks["database"] = "ok"
            ext = db.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
            checks["pgvector"] = ext or "missing"
            checks["migrations"] = db.scalar(text("SELECT version_num FROM alembic_version")) or "none"
    except Exception as e:
        checks["database"] = f"error: {e.__class__.__name__}"
    checks["storage"] = s.storage_backend
    emb = s.embedding_model if s.embedding_provider == "local" else s.openai_embedding_model
    stt = s.whisper_model if s.transcription_provider == "local" else s.openai_transcription_model
    checks["ai_mode"] = {"generation": "llm" if s.llm_enabled else "local-extractive",
                         "llm_model": s.llm_model if s.llm_enabled else None,
                         "embeddings": f"{s.embedding_provider}:{emb}",
                         "transcription": f"{s.transcription_provider}:{stt}",
                         "reranker": s.reranker_model if s.reranker_enabled else None,
                         "external_processing": s.llm_enabled or s.embedding_provider == "openai"
                         or s.transcription_provider == "openai"}
    ok = checks.get("database") == "ok" and checks.get("pgvector") not in (None, "missing")
    if not ok:
        raise APIError(503, "not_ready", "Service not ready", checks)
    return {"status": "ready", "checks": checks}


def _run(r: EvaluationRun, n_results: int | None = None) -> dict[str, Any]:
    return {"id": str(r.id), "kind": r.kind, "status": r.status, "course_id": str(r.course_id) if r.course_id else None,
            "dataset_name": r.dataset_name, "dataset_version": r.dataset_version, "config": r.config,
            "model_info": r.model_info, "prompt_version": r.prompt_version, "seed": r.seed, "summary": r.summary,
            "limitations": r.limitations, "progress": r.progress, "error": r.error,
            "created_at": r.created_at.isoformat(), "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None, "n_results": n_results}


@router.get("/evaluation/runs")
def list_runs(db: DB, user: CurrentUser, kind: str | None = None) -> list[dict[str, Any]]:
    q = select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(50)
    if kind:
        q = q.where(EvaluationRun.kind == kind)
    runs = list(db.scalars(q))
    counts = dict(db.execute(select(EvaluationResult.run_id, func.count()).where(
        EvaluationResult.run_id.in_([r.id for r in runs])).group_by(EvaluationResult.run_id)).all()) if runs else {}
    return [_run(r, counts.get(r.id, 0)) for r in runs]


@router.get("/evaluation/runs/{run_id}")
def get_run(run_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    r = db.get(EvaluationRun, run_id)
    if r is None:
        raise not_found("Evaluation run")
    n = db.scalar(select(func.count(EvaluationResult.id)).where(EvaluationResult.run_id == run_id))
    return _run(r, n)


@router.get("/evaluation/runs/{run_id}/results")
def run_results(run_id: uuid.UUID, db: DB, user: CurrentUser, category: str | None = None,
                passed: bool | None = None, limit: int = Query(200, le=1000), offset: int = 0) -> dict[str, Any]:
    if db.get(EvaluationRun, run_id) is None:
        raise not_found("Evaluation run")
    q = select(EvaluationResult).where(EvaluationResult.run_id == run_id)
    if category:
        q = q.where(EvaluationResult.category == category)
    if passed is not None:
        q = q.where(EvaluationResult.passed.is_(passed))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(EvaluationResult.case_key).offset(offset).limit(limit))
    return {"total": total, "results": [{"id": str(x.id), "case_key": x.case_key, "category": x.category,
                                         "metrics": x.metrics, "output": x.output, "passed": x.passed} for x in rows]}


@router.post("/evaluation/runs", status_code=202)
def queue_run(body: EvaluationRunIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    from app.cli import find_demo_course

    course = db.get(Course, body.course_id) if body.course_id else find_demo_course(db)
    if course is None:
        raise APIError(409, "no_course", "The demonstration course has not been seeded")
    require_course(db, course.id, user)
    busy = db.scalar(select(EvaluationRun).where(EvaluationRun.kind == body.kind,
                                                 EvaluationRun.status.in_(["queued", "running"])))
    if busy:
        raise APIError(409, "already_running", "An evaluation of this kind is already queued or running",
                       {"run_id": str(busy.id)})
    r = EvaluationRun(kind=body.kind, status="queued", course_id=course.id, requested_by=user.id)
    db.add(r)
    db.commit()
    return _run(r, 0)
