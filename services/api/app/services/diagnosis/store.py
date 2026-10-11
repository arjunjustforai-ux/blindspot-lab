"""Persistence of learner-level misconception hypotheses and their evidence trail."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CourseMisconception, MisconceptionDefinition, MisconceptionEvidence, MisconceptionHypothesis
from app.services.diagnosis.hypotheses import status_for
from app.services.knowledge.catalog import misconception_catalog

BASE_RATE = 0.25  # prior that a learner holds a given catalogued misconception (assumption)


def _odds(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return p / (1 - p)


def _prob(o: float) -> float:
    return o / (1 + o)


def catalog_by_key() -> dict[str, dict[str, Any]]:
    return {e["key"]: e for e in misconception_catalog()["entries"]}


def active_keys(db: Session, course_id: uuid.UUID) -> set[str]:
    rows = db.execute(
        select(MisconceptionDefinition.key).join(CourseMisconception,
                                                 CourseMisconception.misconception_id == MisconceptionDefinition.id)
        .where(CourseMisconception.course_id == course_id, CourseMisconception.active.is_(True))
    ).all()
    return {r[0] for r in rows}


def definition(db: Session, key: str) -> MisconceptionDefinition | None:
    return db.scalar(select(MisconceptionDefinition).where(MisconceptionDefinition.key == key))


def get_hypothesis(db: Session, user_id: uuid.UUID, course_id: uuid.UUID, md: MisconceptionDefinition
                   ) -> MisconceptionHypothesis | None:
    return db.scalar(select(MisconceptionHypothesis).where(
        MisconceptionHypothesis.user_id == user_id, MisconceptionHypothesis.course_id == course_id,
        MisconceptionHypothesis.misconception_id == md.id))


def record_evidence(
    db: Session, *, user_id: uuid.UUID, course_id: uuid.UUID, md: MisconceptionDefinition,
    concept_id: uuid.UUID | None, kind: str, summary: str, likelihood_ratio: float | None = None,
    set_posterior: float | None = None, session_id: uuid.UUID | None = None, attempt_id: uuid.UUID | None = None,
    probe_id: uuid.UUID | None = None, detail: dict[str, Any] | None = None, status_override: str | None = None,
    create: bool = True,
) -> tuple[MisconceptionHypothesis | None, MisconceptionEvidence | None]:
    h = get_hypothesis(db, user_id, course_id, md)
    if h is None:
        if not create:
            return None, None
        h = MisconceptionHypothesis(user_id=user_id, course_id=course_id, misconception_id=md.id, concept_id=concept_id,
                                    status="unresolved", posterior=BASE_RATE, evidence_count=0, evidence_kinds=[])
        db.add(h)
        db.flush()
    before = h.posterior
    if set_posterior is not None:
        after = set_posterior
        lr = (_odds(after) / _odds(before)) if before > 0 else 1.0
    else:
        lr = likelihood_ratio or 1.0
        after = _prob(_odds(before) * lr)
    h.posterior = round(after, 4)
    h.evidence_count += 1
    h.evidence_kinds = sorted(set(h.evidence_kinds) | {kind})
    h.status = status_override or status_for(h.posterior, h.evidence_count)
    h.updated_at = datetime.now(UTC)
    if concept_id and not h.concept_id:
        h.concept_id = concept_id
    ev = MisconceptionEvidence(hypothesis_id=h.id, session_id=session_id, attempt_id=attempt_id, probe_id=probe_id,
                               kind=kind, likelihood_ratio=round(lr, 4), posterior_before=round(before, 4),
                               posterior_after=h.posterior, summary=summary[:2000], detail=detail or {})
    db.add(ev)
    db.flush()
    return h, ev
