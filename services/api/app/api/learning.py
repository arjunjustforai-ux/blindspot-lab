"""Assessments, Blindspot Lab diagnostic sessions, analytics and recommendations."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import delete, select

from app.core.deps import DB, CurrentUser, require_course
from app.core.errors import APIError, bad_request
from app.models import Assessment, DiagnosticSession, QuestionAttempt
from app.schemas import AnswerIn, AssessmentIn, DiagnosticIn, ProbeAnswerIn
from app.services import analytics
from app.services.assessment import sessions as A
from app.services.diagnosis import engine as E
from app.services.learner.recommender import recommend

router = APIRouter(prefix="/api", tags=["learning"])


# ---- assessments -------------------------------------------------------------------------------
@router.post("/courses/{course_id}/assessments", status_code=201)
def create_assessment(course_id: uuid.UUID, body: AssessmentIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    require_course(db, course_id, user)
    a = A.create(db, user, course_id, kind=body.kind, concept_ids=body.concept_ids, count=body.count,
                 difficulty=body.difficulty, question_types=body.question_types)
    db.commit()
    return A.view(db, a)


@router.get("/courses/{course_id}/assessments")
def list_assessments(course_id: uuid.UUID, db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    require_course(db, course_id, user)
    rows = db.scalars(select(Assessment).where(Assessment.course_id == course_id, Assessment.user_id == user.id)
                      .order_by(Assessment.created_at.desc()).limit(50))
    out = []
    for a in rows:
        n = db.scalar(select(QuestionAttempt.id).where(QuestionAttempt.assessment_id == a.id).limit(1))
        out.append({"id": str(a.id), "kind": a.kind, "status": a.status, "created_at": a.created_at.isoformat(),
                    "completed_at": a.completed_at.isoformat() if a.completed_at else None,
                    "score": (a.report or {}).get("score"), "started": n is not None})
    return out


@router.get("/assessments/{assessment_id}")
def get_assessment(assessment_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    return A.view(db, A.get(db, user, assessment_id))


@router.post("/assessments/{assessment_id}/answers", status_code=201)
def answer_assessment(assessment_id: uuid.UUID, body: AnswerIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    a = A.get(db, user, assessment_id)
    if body.question_id is None:
        raise bad_request("question_id is required")
    out = A.answer(db, user, a, body.question_id, body.response, body.reasoning, body.confidence, body.time_spent_ms)
    db.commit()
    return out


@router.post("/assessments/{assessment_id}/complete")
def complete_assessment(assessment_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    a = A.get(db, user, assessment_id)
    report = A.complete(db, user, a)
    db.commit()
    return {"id": str(a.id), "report": report}


# ---- Blindspot Lab ---------------------------------------------------------------------------------
@router.post("/courses/{course_id}/diagnostics", status_code=201)
def start_diagnostic(course_id: uuid.UUID, body: DiagnosticIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    require_course(db, course_id, user)
    s = E.start_session(db, user, course_id, concept_id=body.concept_id, misconception_key=body.misconception_key,
                        scenario=body.scenario)
    db.commit()
    return E.view(db, s)


@router.get("/courses/{course_id}/diagnostics")
def list_diagnostics(course_id: uuid.UUID, db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    require_course(db, course_id, user)
    rows = db.scalars(select(DiagnosticSession).where(DiagnosticSession.course_id == course_id,
                                                      DiagnosticSession.user_id == user.id)
                      .order_by(DiagnosticSession.created_at.desc()).limit(50))
    return [{"id": str(s.id), "stage": s.stage, "outcome": s.outcome, "is_demo_script": s.is_demo_script,
             "concept_id": str(s.concept_id), "created_at": s.created_at.isoformat(),
             "misconception_key": s.hypotheses[0]["misconception_key"] if s.hypotheses else None} for s in rows]


@router.get("/diagnostics/{session_id}")
def get_diagnostic(session_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    return E.view(db, E.get_session(db, user, session_id))


@router.post("/diagnostics/{session_id}/answer")
def diagnostic_answer(session_id: uuid.UUID, body: AnswerIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    s = E.get_session(db, user, session_id)
    if s.stage == "answer":
        E.answer_question(db, user, s, body.response, body.reasoning, body.confidence)
    elif s.stage == "practice":
        E.answer_practice(db, user, s, body.response, body.reasoning, body.confidence)
    elif s.stage == "transfer":
        E.answer_transfer(db, user, s, body.response, body.reasoning, body.confidence)
    else:
        raise APIError(409, "wrong_stage", f"Nothing to answer in the '{s.stage}' stage")
    db.commit()
    return E.view(db, s)


@router.post("/diagnostics/{session_id}/probe")
def diagnostic_probe(session_id: uuid.UUID, body: ProbeAnswerIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    s = E.get_session(db, user, session_id)
    E.answer_probe(db, user, s, body.probe_id, body.response)
    db.commit()
    return E.view(db, s)


@router.post("/diagnostics/{session_id}/continue")
def diagnostic_continue(session_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    s = E.get_session(db, user, session_id)
    E.continue_after_repair(db, user, s)
    db.commit()
    return E.view(db, s)


# ---- analytics ----------------------------------------------------------------------------------------
@router.get("/courses/{course_id}/analytics")
def course_analytics(course_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    require_course(db, course_id, user)
    return analytics.course_analytics(db, user.id, course_id)


@router.get("/courses/{course_id}/recommendations")
def recommendations(course_id: uuid.UUID, db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    require_course(db, course_id, user)
    return recommend(db, user.id, course_id)


@router.post("/demo/reset", status_code=200)
def reset_my_demo_progress(db: DB, user: CurrentUser) -> dict[str, Any]:
    """Demo learners can wipe their own activity to replay the scripted walkthrough."""
    if not user.is_demo:
        raise APIError(403, "forbidden", "Only demo accounts can be reset")
    from app.models import (
        Conversation,
        MasteryHistory,
        MasteryState,
        MisconceptionHypothesis,
        QuestionExposure,
    )

    for model in (QuestionAttempt, MasteryHistory, MasteryState, MisconceptionHypothesis, QuestionExposure,
                  DiagnosticSession, Assessment, Conversation):
        db.execute(delete(model).where(model.user_id == user.id))
    db.commit()
    return {"reset": True}
