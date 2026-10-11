"""Assessment lifecycle: create (adaptive selection) -> answer (cited feedback) -> complete (report)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import APIError, bad_request, conflict, not_found
from app.models import Assessment, AssessmentItem, Concept, Question, QuestionAttempt, User
from app.services.assessment.selection import select_questions
from app.services.diagnosis.engine import public_question
from app.services.learner import mastery
from app.services.learner.recommender import active_hypotheses, recommend
from app.services.learning.attempts import record_exposure, submit

KINDS = ("diagnostic", "practice", "follow_up", "review", "mock_exam", "tutor_check")


def create(db: Session, user: User, course_id: uuid.UUID, *, kind: str, concept_ids: list[uuid.UUID] | None,
           count: int, difficulty: int | None, question_types: list[str] | None) -> Assessment:
    if kind not in KINDS:
        raise bad_request(f"Unknown assessment kind '{kind}'")
    if kind == "diagnostic":
        n_concepts = len(list(db.scalars(select(Concept.id).where(Concept.course_id == course_id,
                                                                  Concept.kind == "concept"))))
        count = max(count, n_concepts)
    picks, log = select_questions(db, user.id, course_id, kind=kind, concept_ids=concept_ids, count=count,
                                  difficulty=difficulty, question_types=question_types)
    if not picks:
        raise conflict("No unseen verified questions are available for this selection. Try another scope or a "
                       "review assessment.", code="pool_exhausted", details=log)
    a = Assessment(course_id=course_id, user_id=user.id, kind=kind, status="in_progress",
                   config={"concept_ids": [str(c) for c in concept_ids or []], "count": count,
                           "difficulty": difficulty, "question_types": question_types},
                   selection_log=log)
    db.add(a)
    db.flush()
    for i, p in enumerate(picks):
        db.add(AssessmentItem(assessment_id=a.id, question_id=p.question.id, position=i, selection_reason=p.reason))
        record_exposure(db, user.id, p.question.id, deliberate=kind == "review")
    db.flush()
    return a


def get(db: Session, user: User, assessment_id: uuid.UUID) -> Assessment:
    a = db.get(Assessment, assessment_id)
    if a is None or a.user_id != user.id:
        raise not_found("Assessment")
    return a


def view(db: Session, a: Assessment) -> dict[str, Any]:
    items = list(db.execute(select(AssessmentItem, Question).join(Question, Question.id == AssessmentItem.question_id)
                            .where(AssessmentItem.assessment_id == a.id).order_by(AssessmentItem.position)).all())
    attempts = {at.question_id: at for at in db.scalars(select(QuestionAttempt).where(
        QuestionAttempt.assessment_id == a.id).order_by(QuestionAttempt.created_at))}
    concepts = {c.id: c.name for c in db.scalars(select(Concept).where(Concept.course_id == a.course_id))}
    out_items = []
    for it, q in items:
        at = attempts.get(q.id)
        out_items.append({
            "position": it.position, "selection_reason": it.selection_reason,
            "question": {**public_question(q), "concept_name": concepts.get(q.concept_id),
                         "source_labels": [c["label"] for c in (at.feedback.get("citations", []) if at else [])]},
            "attempt": None if at is None else {"id": str(at.id), "response": at.response, "reasoning": at.reasoning,
                                                "confidence": at.confidence, "is_correct": at.is_correct,
                                                "score": at.score, "feedback": at.feedback},
        })
    return {"id": str(a.id), "course_id": str(a.course_id), "kind": a.kind, "status": a.status, "config": a.config,
            "items": out_items, "report": a.report, "created_at": a.created_at.isoformat(),
            "completed_at": a.completed_at.isoformat() if a.completed_at else None}


def answer(db: Session, user: User, a: Assessment, question_id: uuid.UUID, response: dict[str, Any],
           reasoning: str | None, confidence: int | None, time_spent_ms: int | None) -> dict[str, Any]:
    if a.status != "in_progress":
        raise conflict("This assessment is already completed", code="completed")
    item = db.scalar(select(AssessmentItem).where(AssessmentItem.assessment_id == a.id,
                                                  AssessmentItem.question_id == question_id))
    if item is None:
        raise not_found("Question in this assessment")
    if db.scalar(select(QuestionAttempt.id).where(QuestionAttempt.assessment_id == a.id,
                                                  QuestionAttempt.question_id == question_id)):
        raise conflict("This question has already been answered", code="already_answered")
    q = db.get(Question, question_id)
    assert q is not None
    ctx = "tutor_check" if a.kind == "tutor_check" else "assessment"
    res = submit(db, user=user, course_id=a.course_id, question=q, response=response, reasoning=reasoning,
                 confidence=confidence, context=ctx, assessment_id=a.id, time_spent_ms=time_spent_ms,
                 mastery_source=ctx if ctx == "tutor_check" else a.kind)
    return {"attempt_id": str(res.attempt.id), "feedback": res.feedback}


def complete(db: Session, user: User, a: Assessment) -> dict[str, Any]:
    if a.status == "completed" and a.report:
        return a.report
    rows = list(db.execute(select(QuestionAttempt, Question).join(Question, Question.id == QuestionAttempt.question_id)
                           .where(QuestionAttempt.assessment_id == a.id)).all())
    if not rows:
        raise APIError(400, "nothing_answered", "Answer at least one question before finishing")
    concepts = {c.id: c for c in db.scalars(select(Concept).where(Concept.course_id == a.course_id))}
    per: dict[uuid.UUID, dict[str, Any]] = {}
    for at, q in rows:
        d = per.setdefault(q.concept_id, {"concept_id": str(q.concept_id), "name": concepts[q.concept_id].name,
                                          "answered": 0, "correct": 0, "needs_review": 0, "classifications": {}})
        d["answered"] += 1
        d["correct"] += int(bool(at.is_correct))
        d["needs_review"] += int(at.needs_review)
        d["classifications"][at.classification] = d["classifications"].get(at.classification, 0) + 1
    states = mastery.states_for(db, user.id, a.course_id)
    topics = []
    for cid, d in per.items():
        st = states.get(cid)
        d["accuracy"] = round(d["correct"] / d["answered"], 3)
        d["mastery_after"] = round(st.p_mastery, 4) if st else None
        d["weak"] = d["accuracy"] < 0.6 or (st is not None and st.p_mastery < 0.5)
        topics.append(d)
    topics.sort(key=lambda d: (not d["weak"], d["accuracy"]))
    hyps = [h for h in active_hypotheses(db, user.id, a.course_id) if h["status"] in ("suspected", "supported",
                                                                                       "unresolved")]
    attempt_ids = {at.id for at, _ in rows}
    from app.models import MisconceptionEvidence, MisconceptionHypothesis

    touched = {r[0] for r in db.execute(select(MisconceptionHypothesis.id).join(
        MisconceptionEvidence, MisconceptionEvidence.hypothesis_id == MisconceptionHypothesis.id)
        .where(MisconceptionEvidence.attempt_id.in_(attempt_ids))).all()}
    likely = [h for h in hyps if h["hypothesis_id"] in {str(t) for t in touched}]
    total = len(rows)
    correct = sum(1 for at, _ in rows if at.is_correct)
    report = {
        "score": {"answered": total, "correct": correct, "accuracy": round(correct / total, 3)},
        "topics": topics,
        "weak_topics": [t["name"] for t in topics if t["weak"]],
        "likely_misconceptions": likely,
        "recommendations": recommend(db, user.id, a.course_id, limit=3),
        "notes": [
            "Mastery values are Bayesian Knowledge Tracing estimates, not validated measures of knowledge.",
            "Misconceptions listed here are hypotheses supported by answer patterns; a Blindspot investigation "
            "tests them with follow-up probes before any repair.",
        ],
    }
    a.status = "completed"
    a.completed_at = datetime.now(UTC)
    a.report = report
    db.flush()
    return report
