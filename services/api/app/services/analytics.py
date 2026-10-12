"""Learning analytics built only from persisted evidence (no synthetic numbers)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Assessment,
    Concept,
    DiagnosticSession,
    MasteryHistory,
    MisconceptionDefinition,
    MisconceptionEvidence,
    MisconceptionHypothesis,
    Question,
    QuestionAttempt,
)
from app.services.learner import bkt, mastery
from app.services.learner.recommender import recommend

METHOD = {
    "model": "Bayesian Knowledge Tracing (Corbett & Anderson, 1995) per concept, with evidence weighting",
    "parameters": {"p_init": bkt.P_INIT, "p_transit": bkt.P_TRANSIT, "guess_by_type": bkt.GUESS,
                   "slip_by_difficulty": bkt.SLIP},
    "evidence_weighting": {
        "same_question_family_repeat": f"x{mastery.REPEAT_DECAY} per earlier attempt in the family",
        "identical_question_review": f"x{mastery.SAME_QUESTION_WEIGHT}",
        "scaffolded_practice": f"x{mastery.SCAFFOLDED_PRACTICE_WEIGHT}",
        "correct_with_questionable_reasoning": f"x{mastery.QUESTIONABLE_REASONING_WEIGHT}",
        "grading_flagged_for_review": "not used",
        "diagnostic_probes": "not used as mastery evidence (they test explanations, not mastery)",
    },
    "labels": {"unassessed": "no scored evidence", "emerging": "< 0.40", "developing": "0.40-0.70",
               "proficient": ">= 0.70", "mastered": ">= 0.90 with >= 3 distinct questions"},
    "caveats": [
        "Estimates come from a simple model with hand-set parameters; they are not validated measures of what a "
        "person knows.",
        "BKT does not model forgetting; spaced-review reminders are scheduled separately from the estimate.",
        "Tutor conversations only update mastery through explicitly scored knowledge-check questions.",
    ],
}


def _now() -> datetime:
    return datetime.now(UTC)


def course_analytics(db: Session, user_id: uuid.UUID, course_id: uuid.UUID) -> dict[str, Any]:
    now = _now()
    all_concepts = list(db.scalars(select(Concept).where(Concept.course_id == course_id)
                                   .order_by(Concept.order_index, Concept.name)))
    concepts = [c for c in all_concepts if c.kind == "concept" and c.review_status != "rejected"]
    states = mastery.states_for(db, user_id, course_id)
    views = {str(c.id): mastery.concept_view(c, states.get(c.id), now) for c in concepts}

    hist = list(db.scalars(select(MasteryHistory).where(MasteryHistory.user_id == user_id,
                                                        MasteryHistory.course_id == course_id)
                           .order_by(MasteryHistory.created_at)))
    series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for h in hist:
        series[str(h.concept_id)].append({"t": h.created_at.isoformat(), "p_before": round(h.p_before, 4),
                                          "p_after": round(h.p_after, 4), "correct": h.observed_correct,
                                          "weight": h.evidence_weight, "source": h.source})

    attempts = list(db.execute(
        select(QuestionAttempt, Question).join(Question, Question.id == QuestionAttempt.question_id)
        .where(QuestionAttempt.user_id == user_id, QuestionAttempt.course_id == course_id)
        .order_by(QuestionAttempt.created_at)).all())
    acc: dict[str, dict[str, Any]] = {}
    last_seen: dict[uuid.UUID, datetime] = {}
    revisit = {"attempts": 0, "correct": 0}
    for at, q in attempts:
        d = acc.setdefault(str(q.concept_id), {"answered": 0, "correct": 0, "by_type": {}})
        if at.is_correct is None:
            continue
        d["answered"] += 1
        d["correct"] += int(at.is_correct)
        bt = d["by_type"].setdefault(q.question_type, {"answered": 0, "correct": 0})
        bt["answered"] += 1
        bt["correct"] += int(at.is_correct)
        prev = last_seen.get(q.concept_id)
        if prev is not None and at.created_at - prev >= timedelta(hours=20):
            revisit["attempts"] += 1
            revisit["correct"] += int(at.is_correct)
        last_seen[q.concept_id] = at.created_at
    accuracy = [{"concept_id": cid, "name": views[cid]["name"] if cid in views else cid,
                 "answered": d["answered"], "correct": d["correct"],
                 "accuracy": round(d["correct"] / d["answered"], 3) if d["answered"] else None,
                 "by_type": d["by_type"]} for cid, d in acc.items() if cid in views]

    # Sessions: assessments, diagnostic sessions, tutor checks, in time order, with a mastery snapshot.
    sessions = []
    snap: dict[str, float] = {}
    by_session: dict[str, list[MasteryHistory]] = defaultdict(list)
    for h in hist:
        by_session[h.session_key or str(h.id)].append(h)
    labels: dict[str, tuple[str, str]] = {}
    for a in db.scalars(select(Assessment).where(Assessment.user_id == user_id, Assessment.course_id == course_id)):
        labels[str(a.id)] = (a.kind.replace("_", " ").title() + " assessment", a.kind)
    for s in db.scalars(select(DiagnosticSession).where(DiagnosticSession.user_id == user_id,
                                                        DiagnosticSession.course_id == course_id)):
        labels[str(s.id)] = ("Blindspot investigation" + (" (scripted demo)" if s.is_demo_script else ""), "diagnostic")
    ordered = sorted(by_session.items(), key=lambda kv: kv[1][0].created_at)
    for key, hs in ordered:
        for h in hs:
            snap[str(h.concept_id)] = h.p_after
        lab, kind = labels.get(key, ("Knowledge check", "tutor_check"))
        assessed = [v for k, v in snap.items() if k in views]
        sessions.append({
            "session_key": key, "label": lab, "kind": kind, "at": hs[0].created_at.isoformat(),
            "observations": len(hs), "correct": sum(1 for h in hs if h.observed_correct),
            "mean_mastery_assessed": round(sum(assessed) / len(assessed), 4) if assessed else None,
            "concepts_assessed": len(assessed),
            "delta": {str(h.concept_id): round(h.p_after - h.p_before, 4) for h in hs},
        })

    hyps = []
    rows = db.execute(select(MisconceptionHypothesis, MisconceptionDefinition)
                      .join(MisconceptionDefinition, MisconceptionDefinition.id == MisconceptionHypothesis.misconception_id)
                      .where(MisconceptionHypothesis.user_id == user_id,
                             MisconceptionHypothesis.course_id == course_id)).all()
    for h, d in rows:
        ev = list(db.scalars(select(MisconceptionEvidence).where(MisconceptionEvidence.hypothesis_id == h.id)
                             .order_by(MisconceptionEvidence.created_at)))
        hyps.append({
            "id": str(h.id), "misconception_key": d.key, "title": d.title, "description": d.description,
            "status": h.status, "posterior": h.posterior, "evidence_count": h.evidence_count,
            "concept_id": str(h.concept_id) if h.concept_id else None,
            "revisit_at": h.revisit_at.isoformat() if h.revisit_at else None, "updated_at": h.updated_at.isoformat(),
            "evidence": [{"kind": e.kind, "summary": e.summary, "likelihood_ratio": e.likelihood_ratio,
                          "posterior_before": e.posterior_before, "posterior_after": e.posterior_after,
                          "at": e.created_at.isoformat(), "session_id": str(e.session_id) if e.session_id else None}
                         for e in ev],
        })

    recent = [{"at": at.created_at.isoformat(), "question": q.stem[:160], "concept_id": str(q.concept_id),
               "concept": views.get(str(q.concept_id), {}).get("name"), "context": at.context,
               "is_correct": at.is_correct, "classification": at.classification, "question_type": q.question_type}
              for at, q in attempts[-12:][::-1]]
    topics = mastery.topic_rollup(all_concepts, views)
    return {
        "concepts": list(views.values()), "topics": topics, "history": series, "accuracy": accuracy,
        "sessions": sessions, "hypotheses": hyps, "recent": recent,
        "retention": {"revisit_attempts": revisit["attempts"], "revisit_correct": revisit["correct"],
                      "revisit_accuracy": round(revisit["correct"] / revisit["attempts"], 3)
                      if revisit["attempts"] else None,
                      "definition": "Attempts on a concept at least 20 hours after the previous attempt on it.",
                      "due_reviews": [v["name"] for v in views.values() if v["review_due"]]},
        "recommendations": recommend(db, user_id, course_id),
        "method": METHOD,
        "totals": {"attempts": sum(1 for at, _ in attempts if at.is_correct is not None),
                   "correct": sum(1 for at, _ in attempts if at.is_correct),
                   "assessed_concepts": sum(1 for v in views.values() if v["p_mastery"] is not None),
                   "concepts": len(views)},
    }
