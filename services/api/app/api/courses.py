from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select

from app.core.deps import DB, CurrentUser, require_course
from app.core.errors import forbidden, not_found
from app.core.security import sign_media
from app.models import (
    Concept,
    ContentUnit,
    Course,
    CourseMembership,
    IngestionJob,
    Question,
    SourceFile,
)
from app.schemas import CourseIn, CourseOut, JobOut, SourceOut
from app.services import courses as course_svc
from app.services.learner import mastery
from app.services.learner.recommender import recommend
from app.services.tutor.citations import fmt_ts

router = APIRouter(prefix="/api", tags=["courses"])


def _course_dict(db: DB, c: Course, role: str, user_id: uuid.UUID) -> dict[str, Any]:
    out = CourseOut.model_validate(c).model_dump(mode="json")
    out["role"] = role
    out["sources"] = db.scalar(select(func.count(SourceFile.id)).where(SourceFile.course_id == c.id)) or 0
    out["concepts"] = db.scalar(select(func.count(Concept.id)).where(Concept.course_id == c.id,
                                                                     Concept.kind == "concept")) or 0
    out["verified_questions"] = db.scalar(select(func.count(Question.id)).where(
        Question.course_id == c.id, Question.verification_status == "verified")) or 0
    states = mastery.states_for(db, user_id, c.id)
    assessed = [s.p_mastery for s in states.values() if s.n_observations]
    out["mastery"] = {"assessed": len(assessed), "mean": round(sum(assessed) / len(assessed), 4) if assessed else None}
    return out


@router.get("/courses")
def list_courses(db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    rows = db.execute(select(Course, CourseMembership.role).join(CourseMembership, CourseMembership.course_id == Course.id)
                      .where(CourseMembership.user_id == user.id).order_by(Course.is_demo.desc(), Course.created_at)).all()
    return [_course_dict(db, c, role, user.id) for c, role in rows]


@router.post("/courses", status_code=201)
def create_course(body: CourseIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    c = course_svc.create_course(db, user, body.title, body.description, body.subject)
    db.commit()
    return _course_dict(db, c, "owner", user.id)


@router.get("/courses/{course_id}")
def get_course(course_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    c = require_course(db, course_id, user)
    role = db.scalar(select(CourseMembership.role).where(CourseMembership.course_id == course_id,
                                                         CourseMembership.user_id == user.id))
    return _course_dict(db, c, role or "student", user.id)


@router.delete("/courses/{course_id}", status_code=204, response_class=Response, response_model=None)
def delete_course(course_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    c = require_course(db, course_id, user, manage=True)
    role = db.scalar(select(CourseMembership.role).where(CourseMembership.course_id == course_id,
                                                         CourseMembership.user_id == user.id))
    if role != "owner" or c.is_demo:
        raise forbidden("Only the owner can delete a course (the demo course cannot be deleted)")
    from app.services.storage import get_storage

    get_storage().delete_prefix(f"courses/{course_id}")
    db.delete(c)
    db.commit()


@router.get("/dashboard")
def dashboard(db: DB, user: CurrentUser) -> dict[str, Any]:
    courses = list_courses(db, user)
    out = []
    for c in courses:
        recs = recommend(db, user.id, uuid.UUID(c["id"]), limit=3) if c["concepts"] else []
        out.append({**c, "recommendations": recs})
    return {"user": {"id": str(user.id), "display_name": user.display_name, "is_demo": user.is_demo},
            "courses": out}


# ---- sources -----------------------------------------------------------------------------------


@router.get("/courses/{course_id}/sources", response_model=list[SourceOut])
def list_sources(course_id: uuid.UUID, db: DB, user: CurrentUser) -> list[SourceFile]:
    require_course(db, course_id, user)
    return list(db.scalars(select(SourceFile).where(SourceFile.course_id == course_id).order_by(SourceFile.created_at)))


@router.post("/courses/{course_id}/sources", response_model=SourceOut, status_code=201)
def upload_source(course_id: uuid.UUID, db: DB, user: CurrentUser, file: UploadFile = File(...)) -> SourceFile:
    course = require_course(db, course_id, user, manage=True)
    src = course_svc.add_source_from_stream(db, course, user, file.filename or "upload", file.file, file.content_type)
    db.commit()
    return src


@router.get("/courses/{course_id}/jobs", response_model=list[JobOut])
def list_jobs(course_id: uuid.UUID, db: DB, user: CurrentUser) -> list[IngestionJob]:
    require_course(db, course_id, user)
    return list(db.scalars(select(IngestionJob).where(IngestionJob.course_id == course_id)
                           .order_by(IngestionJob.created_at.desc()).limit(50)))


def _source(db: DB, user: CurrentUser, source_id: uuid.UUID, manage: bool = False) -> SourceFile:
    src = db.get(SourceFile, source_id)
    if src is None:
        raise not_found("Source")
    require_course(db, src.course_id, user, manage=manage)
    return src


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: uuid.UUID, db: DB, user: CurrentUser) -> SourceFile:
    return _source(db, user, source_id)


@router.delete("/sources/{source_id}", status_code=204, response_class=Response, response_model=None)
def delete_source(source_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    src = _source(db, user, source_id, manage=True)
    course_svc.delete_source(db, src)
    db.commit()


@router.post("/sources/{source_id}/reindex", response_model=JobOut, status_code=202)
def reindex(source_id: uuid.UUID, db: DB, user: CurrentUser) -> IngestionJob:
    src = _source(db, user, source_id, manage=True)
    job = course_svc.reindex_source(db, src)
    db.commit()
    return job


def unit_out(u: ContentUnit, src: SourceFile, user_id: uuid.UUID) -> dict[str, Any]:
    image_url = None
    if u.image_storage_key:
        image_url = f"/api/media/{u.image_storage_key}?{sign_media(u.image_storage_key, user_id)}"
    anchor = (f"Page {u.page_number}" if u.page_number is not None else f"Slide {u.slide_number}"
              if u.slide_number is not None else fmt_ts(u.start_seconds))
    return {
        "id": str(u.id), "source_id": str(src.id), "filename": src.filename, "modality": u.modality,
        "order_index": u.order_index, "heading": u.heading, "section_path": u.section_path, "content": u.content,
        "page": u.page_number, "slide": u.slide_number, "start": u.start_seconds, "end": u.end_seconds,
        "anchor": anchor, "bbox": u.bbox, "is_generated": u.is_generated, "image_url": image_url,
        "extraction_meta": {k: v for k, v in (u.extraction_meta or {}).items() if k != "segments"},
        "segments": (u.extraction_meta or {}).get("segments"),
        "generation_meta": {k: v for k, v in (u.generation_meta or {}).items() if k in ("kind", "model", "status")},
    }


@router.get("/sources/{source_id}/units")
def source_units(source_id: uuid.UUID, db: DB, user: CurrentUser, page: int | None = None,
                 slide: int | None = None, limit: int = 500) -> dict[str, Any]:
    src = _source(db, user, source_id)
    q = select(ContentUnit).where(ContentUnit.source_file_id == source_id)
    if page is not None:
        q = q.where(ContentUnit.page_number == page)
    if slide is not None:
        q = q.where(ContentUnit.slide_number == slide)
    units = list(db.scalars(q.order_by(ContentUnit.order_index).limit(min(limit, 1000))))
    from app.models import ConceptSource

    tags: dict[uuid.UUID, list[dict[str, Any]]] = {}
    if units:
        for cs, c in db.execute(select(ConceptSource, Concept).join(Concept, Concept.id == ConceptSource.concept_id)
                                .where(ConceptSource.content_unit_id.in_([u.id for u in units]))).all():
            tags.setdefault(cs.content_unit_id, []).append({"concept_id": str(c.id), "name": c.name, "kind": c.kind,
                                                            "primary": cs.is_primary, "relevance": cs.relevance,
                                                            "method": cs.method})
    return {"source": SourceOut.model_validate(src).model_dump(mode="json"),
            "units": [{**unit_out(u, src, user.id), "concepts": tags.get(u.id, [])} for u in units]}


@router.get("/sources/{source_id}/view")
def source_view(source_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    """Everything the citation viewer needs: signed media URLs and per-anchor previews."""
    src = _source(db, user, source_id)
    file_url = f"/api/media/{src.storage_key}?{sign_media(src.storage_key, user.id)}"
    previews = {}
    if src.modality == "pptx" and src.slide_count:
        for n in range(1, src.slide_count + 1):
            key = f"courses/{src.course_id}/sources/{src.id}/previews/slide-{n:03d}.png"
            previews[n] = f"/api/media/{key}?{sign_media(key, user.id)}"
    return {"source": SourceOut.model_validate(src).model_dump(mode="json"), "file_url": file_url,
            "slide_previews": previews}
