from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.courses import unit_out
from app.core.deps import DB, CurrentUser, require_course
from app.core.errors import conflict, not_found
from app.models import (
    Concept,
    ConceptPrerequisite,
    ConceptSource,
    ContentUnit,
    CourseMisconception,
    MisconceptionDefinition,
    Question,
    QuestionSource,
    SourceFile,
)
from app.schemas import ConceptPatch, PrerequisiteIn, PrerequisitePatch
from app.services.diagnosis.store import catalog_by_key
from app.services.knowledge import graph
from app.services.learner import mastery

router = APIRouter(prefix="/api", tags=["knowledge"])


def _edge(e: ConceptPrerequisite) -> dict[str, Any]:
    return {"id": str(e.id), "concept_id": str(e.concept_id), "prerequisite_id": str(e.prerequisite_id),
            "origin": e.origin, "confidence": e.confidence, "rationale": e.rationale, "review_status": e.review_status}


@router.get("/courses/{course_id}/graph")
def course_graph(course_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    course = require_course(db, course_id, user)
    concepts = list(db.scalars(select(Concept).where(Concept.course_id == course_id)
                               .order_by(Concept.order_index, Concept.name)))
    edges = list(db.scalars(select(ConceptPrerequisite).where(ConceptPrerequisite.course_id == course_id)))
    counts = dict(db.execute(select(ConceptSource.concept_id, func.count()).join(
        Concept, Concept.id == ConceptSource.concept_id).where(Concept.course_id == course_id)
        .group_by(ConceptSource.concept_id)).all())
    qcounts = dict(db.execute(select(Question.concept_id, func.count()).where(
        Question.course_id == course_id, Question.verification_status == "verified")
        .group_by(Question.concept_id)).all())
    states = mastery.states_for(db, user.id, course_id)
    nodes = []
    for c in concepts:
        v = mastery.concept_view(c, states.get(c.id))
        nodes.append({**v, "description": c.description, "origin": c.origin, "review_status": c.review_status,
                      "catalog_key": c.catalog_key, "units": counts.get(c.id, 0), "questions": qcounts.get(c.id, 0),
                      "order_index": c.order_index})
    total_units = db.scalar(select(func.count(ContentUnit.id)).where(ContentUnit.course_id == course_id)) or 0
    tagged = db.scalar(select(func.count(func.distinct(ConceptSource.content_unit_id))).join(
        ContentUnit, ContentUnit.id == ConceptSource.content_unit_id).where(ContentUnit.course_id == course_id)) or 0
    return {"course_id": str(course_id), "knowledge_status": course.knowledge_status, "nodes": nodes,
            "edges": [_edge(e) for e in edges], "coverage": {"units": total_units, "tagged_units": tagged}}


@router.get("/concepts/{concept_id}")
def concept_detail(concept_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    c = db.get(Concept, concept_id)
    if c is None:
        raise not_found("Concept")
    require_course(db, c.course_id, user)
    rows = db.execute(
        select(ConceptSource, ContentUnit, SourceFile)
        .join(ContentUnit, ContentUnit.id == ConceptSource.content_unit_id)
        .join(SourceFile, SourceFile.id == ContentUnit.source_file_id)
        .where(ConceptSource.concept_id == concept_id)
        .order_by(ConceptSource.is_primary.desc(), ConceptSource.relevance.desc()).limit(12)
    ).all()
    sources = [{**unit_out(u, sf, user.id), "relevance": cs.relevance, "primary": cs.is_primary,
                "method": cs.method} for cs, u, sf in rows]
    pre_edges = list(db.scalars(select(ConceptPrerequisite).where(ConceptPrerequisite.concept_id == concept_id)))
    post_edges = list(db.scalars(select(ConceptPrerequisite).where(ConceptPrerequisite.prerequisite_id == concept_id)))
    names = {x.id: x.name for x in db.scalars(select(Concept).where(Concept.course_id == c.course_id))}
    target_ids = [concept_id] + [x.id for x in db.scalars(select(Concept).where(Concept.parent_id == concept_id))]
    qs = list(db.scalars(select(Question).where(Question.concept_id.in_(target_ids),
                                                Question.verification_status == "verified")
                         .order_by(Question.difficulty, Question.created_at).limit(40)))
    qsrc = dict(db.execute(select(QuestionSource.question_id, func.count()).where(
        QuestionSource.question_id.in_([q.id for q in qs])).group_by(QuestionSource.question_id)).all()) if qs else {}
    st = mastery.states_for(db, user.id, c.course_id).get(concept_id)
    act = db.execute(select(MisconceptionDefinition, CourseMisconception).join(
        CourseMisconception, CourseMisconception.misconception_id == MisconceptionDefinition.id)
        .where(CourseMisconception.course_id == c.course_id, CourseMisconception.concept_id == concept_id)).all()
    children = [{"id": str(x.id), "name": x.name, "kind": x.kind} for x in
                db.scalars(select(Concept).where(Concept.parent_id == concept_id))]
    return {
        "id": str(c.id), "name": c.name, "kind": c.kind, "description": c.description, "origin": c.origin,
        "review_status": c.review_status, "aliases": c.aliases, "catalog_key": c.catalog_key,
        "parent": {"id": str(c.parent_id), "name": names.get(c.parent_id)} if c.parent_id else None,
        "children": children, "mastery": mastery.concept_view(c, st),
        "prerequisites": [{**_edge(e), "name": names.get(e.prerequisite_id)} for e in pre_edges],
        "unlocks": [{**_edge(e), "name": names.get(e.concept_id)} for e in post_edges],
        "sources": sources,
        "questions": [{"id": str(q.id), "stem": q.stem, "question_type": q.question_type, "difficulty": q.difficulty,
                       "origin": q.origin, "template_key": q.template_key, "purpose": q.purpose,
                       "sources": qsrc.get(q.id, 0)} for q in qs],
        "misconceptions": [{"key": d.key, "title": d.title, "active": cm.active, "reason": cm.reason}
                           for d, cm in act],
    }


@router.patch("/concepts/{concept_id}")
def patch_concept(concept_id: uuid.UUID, body: ConceptPatch, db: DB, user: CurrentUser) -> dict[str, Any]:
    c = db.get(Concept, concept_id)
    if c is None:
        raise not_found("Concept")
    require_course(db, c.course_id, user, manage=True)
    if body.name is not None:
        c.name = body.name.strip()
        c.origin = "instructor"
    if body.description is not None:
        c.description = body.description
    if body.review_status is not None:
        c.review_status = body.review_status
    c.updated_at = datetime.now(UTC)
    db.commit()
    return {"id": str(c.id), "name": c.name, "description": c.description, "review_status": c.review_status}


@router.post("/courses/{course_id}/prerequisites", status_code=201)
def add_prerequisite(course_id: uuid.UUID, body: PrerequisiteIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    require_course(db, course_id, user, manage=True)
    a, b = db.get(Concept, body.prerequisite_id), db.get(Concept, body.concept_id)
    if a is None or b is None or a.course_id != course_id or b.course_id != course_id:
        raise not_found("Concept")
    existing = list(db.scalars(select(ConceptPrerequisite).where(ConceptPrerequisite.course_id == course_id,
                                                                 ConceptPrerequisite.review_status != "rejected")))
    pair = (a.id, b.id)
    if any((e.prerequisite_id, e.concept_id) == pair for e in existing):
        raise conflict("This prerequisite already exists", code="duplicate_edge")
    if graph.would_create_cycle([(e.prerequisite_id, e.concept_id) for e in existing], pair):
        raise conflict(f"Adding '{a.name}' as a prerequisite of '{b.name}' would create a circular dependency",
                       code="cycle")
    e = db.scalar(select(ConceptPrerequisite).where(ConceptPrerequisite.concept_id == b.id,
                                                    ConceptPrerequisite.prerequisite_id == a.id))
    if e is None:
        e = ConceptPrerequisite(course_id=course_id, concept_id=b.id, prerequisite_id=a.id)
        db.add(e)
    e.origin, e.review_status, e.confidence, e.rationale = "instructor", "approved", 1.0, body.rationale
    db.commit()
    return _edge(e)


@router.patch("/prerequisites/{edge_id}")
def patch_prerequisite(edge_id: uuid.UUID, body: PrerequisitePatch, db: DB, user: CurrentUser) -> dict[str, Any]:
    e = db.get(ConceptPrerequisite, edge_id)
    if e is None:
        raise not_found("Prerequisite")
    require_course(db, e.course_id, user, manage=True)
    if body.review_status != "rejected" and e.review_status == "rejected":
        others = [(x.prerequisite_id, x.concept_id) for x in db.scalars(select(ConceptPrerequisite).where(
            ConceptPrerequisite.course_id == e.course_id, ConceptPrerequisite.review_status != "rejected",
            ConceptPrerequisite.id != e.id))]
        if graph.would_create_cycle(others, (e.prerequisite_id, e.concept_id)):
            raise conflict("Restoring this edge would create a circular dependency", code="cycle")
    e.review_status = body.review_status
    db.commit()
    return _edge(e)


@router.get("/courses/{course_id}/misconceptions")
def course_misconceptions(course_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    require_course(db, course_id, user)
    cat = catalog_by_key()
    rows = db.execute(select(MisconceptionDefinition, CourseMisconception).join(
        CourseMisconception, CourseMisconception.misconception_id == MisconceptionDefinition.id)
        .where(CourseMisconception.course_id == course_id)).all()
    names = {x.id: x.name for x in db.scalars(select(Concept).where(Concept.course_id == course_id))}
    out = []
    for d, cm in rows:
        e = cat.get(d.key, {})
        out.append({"key": d.key, "title": d.title, "description": d.description, "active": cm.active,
                    "reason": cm.reason, "support_score": cm.support_score,
                    "concept": names.get(cm.concept_id) if cm.concept_id else None,
                    "concept_id": str(cm.concept_id) if cm.concept_id else None,
                    "competing_interpretations": e.get("competing_interpretations", []),
                    "probes": [{"key": p["key"], "type": p["type"], "prompt": p["prompt"]}
                               for p in e.get("diagnostic_probes", [])],
                    "repair": e.get("repair", {}), "review_status": d.review_status})
    from app.services.knowledge.catalog import misconception_catalog

    return {"catalogue_status": misconception_catalog()["status"], "entries": out}
