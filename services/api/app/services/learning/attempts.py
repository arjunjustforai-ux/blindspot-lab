"""One code path for every scored answer: assessments, Blindspot Lab, tutor knowledge checks.

grade -> classify -> persist attempt -> evidence-weighted BKT update ->
misconception evidence -> cited feedback.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Concept,
    ContentUnit,
    Question,
    QuestionAttempt,
    QuestionExposure,
    QuestionSource,
    SourceFile,
    User,
)
from app.services.assessment.grading import Grade
from app.services.assessment.grading import grade as grade_answer
from app.services.diagnosis import classifier
from app.services.diagnosis.store import active_keys, catalog_by_key, definition, get_hypothesis, record_evidence
from app.services.learner import mastery
from app.services.learner.recommender import READY, prerequisite_map
from app.services.tutor.citations import build_citation

# Likelihood ratios for assessment-context evidence (no probing yet). An exact numeric match to the
# value a misconception predicts is far more specific than picking one of three wrong MCQ options.
SIGNATURE_LR_NUMERIC = 6.0
SIGNATURE_LR_MCQ = 2.5
CUE_ONLY_LR = 1.6
AVOIDED_TRAP_LR = 0.5    # correct answer on a question carrying a signature for an existing hypothesis


@dataclass
class AttemptResult:
    attempt: QuestionAttempt
    grade: Grade
    classification: classifier.Classification
    feedback: dict[str, Any]


def record_exposure(db: Session, user_id: uuid.UUID, question_id: uuid.UUID, *, deliberate: bool = False) -> None:
    ex = db.scalar(select(QuestionExposure).where(QuestionExposure.user_id == user_id,
                                                  QuestionExposure.question_id == question_id))
    now = datetime.now(UTC)
    if ex is None:
        db.add(QuestionExposure(user_id=user_id, question_id=question_id, first_shown_at=now, last_shown_at=now,
                                times_shown=1, deliberate_review=deliberate))
    else:
        ex.last_shown_at = now
        ex.times_shown += 1
        ex.deliberate_review = ex.deliberate_review or deliberate
    db.flush()


def question_citations(db: Session, q: Question) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ContentUnit, SourceFile, QuestionSource.support_score)
        .join(QuestionSource, QuestionSource.content_unit_id == ContentUnit.id)
        .join(SourceFile, SourceFile.id == ContentUnit.source_file_id)
        .where(QuestionSource.question_id == q.id)
    ).all()
    return [build_citation(f"S{i + 1}", u, sf, focus_text=q.explanation, support=sc) for i, (u, sf, sc) in enumerate(rows)]


def weak_prerequisites(db: Session, user_id: uuid.UUID, course_id: uuid.UUID, concept_id: uuid.UUID) -> list[str]:
    pre = prerequisite_map(db, course_id).get(concept_id, [])
    if not pre:
        return []
    states = mastery.states_for(db, user_id, course_id)
    out = []
    for pid in pre:
        st = states.get(pid)
        if st and st.n_observations >= 1 and st.p_mastery < READY - 0.2:
            c = db.get(Concept, pid)
            out.append(c.name if c else str(pid))
    return out


def correct_answer_view(q: Question) -> dict[str, Any]:
    if q.question_type == "mcq":
        opt = next((o for o in q.options if o["id"] == q.correct_option_id), None)
        return {"option_id": q.correct_option_id, "text": opt["text"] if opt else None}
    if q.question_type == "numerical":
        return {"value": q.numeric_answer, "unit": q.answer_unit, "tolerance": q.numeric_tolerance}
    return {"key_points": [kp["text"] for kp in (q.rubric or {}).get("key_points", [])]}


def submit(
    db: Session, *, user: User, course_id: uuid.UUID, question: Question, response: dict[str, Any],
    reasoning: str | None, confidence: int | None, context: str, assessment_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None, time_spent_ms: int | None = None, mastery_source: str | None = None,
    record_mastery: bool = True, hypothesis_evidence: bool = True,
) -> AttemptResult:
    concept = db.get(Concept, question.concept_id)
    srcs = [c["excerpt"] for c in question_citations(db, question)]
    g = grade_answer(question, response, sources=srcs, user_id=user.id, course_id=course_id)
    cat = catalog_by_key()
    act = active_keys(db, course_id)
    weak = weak_prerequisites(db, user.id, course_id, question.concept_id)
    cls = classifier.classify(question, response, g, reasoning, confidence, catalog=cat, active_keys=act,
                              weak_prereqs=weak, concept_key=concept.catalog_key if concept else None)
    attempt = QuestionAttempt(
        user_id=user.id, course_id=course_id, question_id=question.id, assessment_id=assessment_id,
        diagnostic_session_id=session_id, context=context, response=response, reasoning=reasoning,
        confidence=confidence, is_correct=g.is_correct, score=g.score, grading_method=g.method,
        grading_detail=g.detail, needs_review=g.needs_review, classification=cls.category,
        classification_detail=cls.as_dict(), time_spent_ms=time_spent_ms,
    )
    db.add(attempt)
    db.flush()
    record_exposure(db, user.id, question.id)

    mastery_view = None
    if record_mastery and g.is_correct is not None:
        w, reasons = mastery.evidence_weight(db, user.id, question, classification=cls.category,
                                             needs_review=g.needs_review, exclude_attempt=attempt.id,
                                             scaffolded=context == "practice")
        h = mastery.record(db, user_id=user.id, course_id=course_id, question=question, attempt=attempt,
                           correct=bool(g.is_correct), weight=w, source=mastery_source or context,
                           session_key=str(assessment_id or session_id or attempt.id), reasons=reasons)
        if h is not None:
            mastery_view = {"concept_id": str(question.concept_id), "name": concept.name if concept else None,
                            "before": round(h.p_before, 4), "after": round(h.p_after, 4), "weight": w,
                            "weight_reasons": reasons}
        else:
            mastery_view = {"concept_id": str(question.concept_id), "name": concept.name if concept else None,
                            "before": None, "after": None, "weight": 0.0, "weight_reasons": reasons}

    alert = None
    if hypothesis_evidence:
        alert = _hypothesis_evidence(db, user, course_id, question, cls, g, attempt, session_id)

    feedback = {
        "is_correct": g.is_correct, "score": g.score, "needs_review": g.needs_review,
        "correct_answer": correct_answer_view(question), "explanation": question.explanation,
        "worked_steps": (question.generation_meta or {}).get("worked_steps", []),
        "assumptions": question.assumptions, "citations": question_citations(db, question),
        "classification": cls.as_dict(), "misconception_alert": alert, "mastery": mastery_view,
        "grading": {"method": g.method, "detail": g.detail},
    }
    attempt.feedback = feedback
    db.flush()
    return AttemptResult(attempt, g, cls, feedback)


def _hypothesis_evidence(db: Session, user: User, course_id: uuid.UUID, q: Question, cls: classifier.Classification,
                         g: Grade, attempt: QuestionAttempt, session_id: uuid.UUID | None) -> dict[str, Any] | None:
    alert = None
    if cls.category == "likely_misconception" and cls.candidates:
        top = cls.candidates[0]
        md = definition(db, top["misconception_key"])
        if md is not None:
            if top["pattern"] == "signature":
                lr = SIGNATURE_LR_NUMERIC if q.question_type == "numerical" else SIGNATURE_LR_MCQ
            else:
                lr = CUE_ONLY_LR
            h, _ = record_evidence(
                db, user_id=user.id, course_id=course_id, md=md, concept_id=q.concept_id,
                kind="signature_match" if top["pattern"] == "signature" else "reasoning_cue",
                summary=f"Answer to '{q.stem[:120]}' matched the predicted pattern: "
                + "; ".join(e.get("summary") or "" for e in cls.evidence if e.get("misconception_key") == md.key),
                likelihood_ratio=lr, session_id=session_id, attempt_id=attempt.id,
                detail={"question_id": str(q.id), "distribution": top["distribution"]},
            )
            if h is not None:
                alert = {"misconception_key": md.key, "title": md.title, "status": h.status,
                         "posterior": h.posterior, "evidence_count": h.evidence_count,
                         "message": "This answer is consistent with a known misconception. It is a hypothesis, "
                         "not a diagnosis; a Blindspot investigation can test it with follow-up questions."}
    elif cls.category == "correct_questionable_reasoning":
        for k in cls.reasoning_cues:
            md = definition(db, k)
            if md is not None:
                h, _ = record_evidence(db, user_id=user.id, course_id=course_id, md=md, concept_id=q.concept_id,
                                       kind="reasoning_cue", summary="Correct answer, but reasoning used cues "
                                       f"{cls.reasoning_cues[k]}", likelihood_ratio=CUE_ONLY_LR, session_id=session_id,
                                       attempt_id=attempt.id)
                if h is not None:
                    alert = {"misconception_key": md.key, "title": md.title, "status": h.status,
                             "posterior": h.posterior, "evidence_count": h.evidence_count,
                             "message": "Your answer is right, but your explanation resembles a common misconception."}
    elif g.is_correct:
        for s in q.misconception_signatures:
            k = s.get("misconception_key")
            md = definition(db, k) if k else None
            if md is None:
                continue
            h = get_hypothesis(db, user.id, course_id, md)
            if h is not None and h.status not in ("rejected", "resolved"):
                record_evidence(db, user_id=user.id, course_id=course_id, md=md, concept_id=q.concept_id,
                                kind="avoided_trap", summary=f"Answered correctly a question where '{md.title}' "
                                "predicts a specific wrong answer.", likelihood_ratio=AVOIDED_TRAP_LR,
                                session_id=session_id, attempt_id=attempt.id,
                                status_override="resolved" if h.status == "resolving" else None)
    return alert
