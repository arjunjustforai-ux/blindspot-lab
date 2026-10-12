"""Persistence of per-learner, per-concept mastery estimates and their history."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Concept, MasteryHistory, MasteryState, Question, QuestionAttempt
from app.services.learner import bkt

REPEAT_DECAY = 0.5           # weight multiplier per earlier attempt in the same question family
SAME_QUESTION_WEIGHT = 0.3   # deliberate review of an identical question
QUESTIONABLE_REASONING_WEIGHT = 0.4
SCAFFOLDED_PRACTICE_WEIGHT = 0.6  # practice right after a worked example of the same structure


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Observation:
    correct: bool
    weight: float
    reasons: list[str]


def family_of(q: Question) -> str:
    return q.family_key or q.template_key or (q.generation_meta or {}).get("bank_key") or str(q.id)


def evidence_weight(db: Session, user_id: uuid.UUID, q: Question, *, classification: str | None,
                    needs_review: bool, exclude_attempt: uuid.UUID | None = None,
                    scaffolded: bool = False) -> tuple[float, list[str]]:
    """How much an observation should move the estimate (see bkt module docstring)."""
    if needs_review:
        return 0.0, ["grading flagged for review: not used as mastery evidence"]
    reasons: list[str] = []
    w = 1.0
    prev = db.execute(
        select(QuestionAttempt.question_id, Question.family_key, Question.template_key, Question.generation_meta)
        .join(Question, Question.id == QuestionAttempt.question_id)
        .where(QuestionAttempt.user_id == user_id, Question.concept_id == q.concept_id,
               QuestionAttempt.is_correct.is_not(None),
               QuestionAttempt.id != (exclude_attempt or uuid.uuid4()))
    ).all()
    same_q = sum(1 for r in prev if r[0] == q.id)
    fam = family_of(q)
    same_family = sum(1 for r in prev if (r[1] or r[2] or (r[3] or {}).get("bank_key") or str(r[0])) == fam)
    if same_q:
        w *= SAME_QUESTION_WEIGHT
        reasons.append(f"identical question seen before (x{SAME_QUESTION_WEIGHT})")
    elif same_family:
        f = REPEAT_DECAY ** same_family
        w *= f
        reasons.append(f"{same_family} earlier attempt(s) in the same question family (x{f:.2f})")
    if scaffolded:
        w *= SCAFFOLDED_PRACTICE_WEIGHT
        reasons.append(f"scaffolded practice right after a worked example (x{SCAFFOLDED_PRACTICE_WEIGHT})")
    if classification == "correct_questionable_reasoning":
        w *= QUESTIONABLE_REASONING_WEIGHT
        reasons.append(f"correct answer with questionable reasoning (x{QUESTIONABLE_REASONING_WEIGHT})")
    if not reasons:
        reasons.append("new question family: full weight")
    return round(w, 4), reasons


def next_review(p: float, now: datetime) -> datetime:
    if p >= 0.95:
        return now + timedelta(days=7)
    if p >= 0.8:
        return now + timedelta(days=3)
    if p >= 0.6:
        return now + timedelta(days=1)
    return now + timedelta(hours=12)


def get_state(db: Session, user_id: uuid.UUID, concept_id: uuid.UUID, course_id: uuid.UUID) -> MasteryState:
    st = db.scalar(select(MasteryState).where(MasteryState.user_id == user_id, MasteryState.concept_id == concept_id))
    if st is None:
        st = MasteryState(user_id=user_id, course_id=course_id, concept_id=concept_id, p_mastery=bkt.P_INIT,
                          params={"p_init": bkt.P_INIT, "p_transit": bkt.P_TRANSIT}, n_observations=0, n_correct=0,
                          effective_evidence=0.0, distinct_questions=0, updated_at=_now())
        db.add(st)
        db.flush()
    return st


def record(
    db: Session, *, user_id: uuid.UUID, course_id: uuid.UUID, question: Question, attempt: QuestionAttempt | None,
    correct: bool, weight: float, source: str, session_key: str | None = None, reasons: list[str] | None = None,
) -> MasteryHistory | None:
    if weight <= 0:
        return None
    st = get_state(db, user_id, question.concept_id, course_id)
    params = bkt.params_for(question.question_type, question.difficulty, len(question.options) or None)
    before = st.p_mastery
    after = bkt.update(before, correct, params, weight)
    now = _now()
    st.p_mastery = after
    st.n_observations += 1
    st.n_correct += int(correct)
    st.effective_evidence = round(st.effective_evidence + weight, 4)
    st.last_observation_at = now
    if correct:
        st.last_correct_at = now
    st.next_review_at = next_review(after, now)
    st.updated_at = now
    st.params = {"p_init": bkt.P_INIT, "p_transit": bkt.P_TRANSIT, "last_guess": params.guess,
                 "last_slip": params.slip}
    st.distinct_questions = db.scalar(
        select(func.count(func.distinct(QuestionAttempt.question_id)))
        .join(Question, Question.id == QuestionAttempt.question_id)
        .where(QuestionAttempt.user_id == user_id, Question.concept_id == question.concept_id)
    ) or 0
    h = MasteryHistory(
        user_id=user_id, course_id=course_id, concept_id=question.concept_id,
        attempt_id=attempt.id if attempt else None, p_before=before, p_after=after, observed_correct=correct,
        evidence_weight=weight, source=source, session_key=session_key,
        detail={"guess": params.guess, "slip": params.slip, "transit": bkt.P_TRANSIT, "reasons": reasons or [],
                "question_type": question.question_type, "difficulty": question.difficulty},
    )
    db.add(h)
    db.flush()
    return h


def states_for(db: Session, user_id: uuid.UUID, course_id: uuid.UUID) -> dict[uuid.UUID, MasteryState]:
    return {s.concept_id: s for s in db.scalars(select(MasteryState).where(MasteryState.user_id == user_id,
                                                                           MasteryState.course_id == course_id))}


def concept_view(c: Concept, st: MasteryState | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()
    n = st.n_observations if st else 0
    p = st.p_mastery if st and n else None
    stale = bool(st and st.last_observation_at and now - st.last_observation_at > timedelta(days=14))
    due = bool(st and st.next_review_at and st.next_review_at <= now)
    return {
        "concept_id": str(c.id), "name": c.name, "kind": c.kind, "parent_id": str(c.parent_id) if c.parent_id else None,
        "p_mastery": None if p is None else round(p, 4),
        "label": bkt.label(p, n, st.distinct_questions if st else 0),
        "n_observations": n, "n_correct": st.n_correct if st else 0,
        "effective_evidence": st.effective_evidence if st else 0.0,
        "evidence_quality": bkt.evidence_quality(st.effective_evidence if st else 0.0),
        "distinct_questions": st.distinct_questions if st else 0,
        "last_observation_at": st.last_observation_at.isoformat() if st and st.last_observation_at else None,
        "next_review_at": st.next_review_at.isoformat() if st and st.next_review_at else None,
        "review_due": due, "stale": stale,
    }


def topic_rollup(concepts: list[Concept], views: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    topics = [c for c in concepts if c.kind == "topic"]
    out = []
    for t in topics:
        kids = [views[str(c.id)] for c in concepts if c.parent_id == t.id and c.kind == "concept" and str(c.id) in views]
        assessed = [k for k in kids if k["p_mastery"] is not None]
        if assessed:
            wsum = sum(max(k["effective_evidence"], 0.5) for k in assessed)
            p = sum(k["p_mastery"] * max(k["effective_evidence"], 0.5) for k in assessed) / wsum
        else:
            p = None
        out.append({"topic_id": str(t.id), "name": t.name, "p_mastery": None if p is None else round(p, 4),
                    "concepts": len(kids), "assessed_concepts": len(assessed)})
    return out
