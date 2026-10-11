"""Adaptive decision engine: what should this learner do next, and why.

Inputs: BKT mastery estimates, misconception hypotheses, prerequisite edges, recent
errors, question exposure and review timing. Output: a ranked list of activities,
each with a human-readable rationale. Rules (highest priority first):
  1. New learner with no evidence           -> diagnostic onboarding assessment
  2. Active misconception hypothesis         -> Blindspot investigation (focused repair)
  3. Weak concept whose prerequisite is weak -> practise the prerequisite first
  4. Weakest concept with ready prerequisites-> targeted practice at matched difficulty
  5. Review due / stale evidence             -> spaced review
  6. Unassessed concepts                     -> short assessment
  7. Everything proficient                   -> mixed mock exam
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Concept, ConceptPrerequisite, MisconceptionDefinition, MisconceptionHypothesis
from app.services.learner.mastery import concept_view, states_for

READY = 0.6


def target_difficulty(p: float | None) -> int:
    if p is None:
        return 2
    if p < 0.4:
        return 1
    if p < 0.75:
        return 2
    return 3


def prerequisite_map(db: Session, course_id: uuid.UUID) -> dict[uuid.UUID, list[uuid.UUID]]:
    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for e in db.scalars(select(ConceptPrerequisite).where(ConceptPrerequisite.course_id == course_id,
                                                          ConceptPrerequisite.review_status != "rejected")):
        out.setdefault(e.concept_id, []).append(e.prerequisite_id)
    return out


def active_hypotheses(db: Session, user_id: uuid.UUID, course_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        select(MisconceptionHypothesis, MisconceptionDefinition)
        .join(MisconceptionDefinition, MisconceptionDefinition.id == MisconceptionHypothesis.misconception_id)
        .where(MisconceptionHypothesis.user_id == user_id, MisconceptionHypothesis.course_id == course_id)
    ).all()
    out = []
    for h, d in rows:
        out.append({"hypothesis_id": str(h.id), "misconception_key": d.key, "title": d.title, "status": h.status,
                    "posterior": round(h.posterior, 3), "evidence_count": h.evidence_count,
                    "concept_id": str(h.concept_id) if h.concept_id else None,
                    "revisit_at": h.revisit_at.isoformat() if h.revisit_at else None,
                    "updated_at": h.updated_at.isoformat()})
    return out


def recommend(db: Session, user_id: uuid.UUID, course_id: uuid.UUID, limit: int = 5) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    concepts = list(db.scalars(select(Concept).where(Concept.course_id == course_id, Concept.kind == "concept",
                                                     Concept.review_status != "rejected").order_by(Concept.order_index)))
    if not concepts:
        return []
    states = states_for(db, user_id, course_id)
    views = {c.id: concept_view(c, states.get(c.id), now) for c in concepts}
    prereqs = prerequisite_map(db, course_id)
    name = {c.id: c.name for c in concepts}
    recs: list[dict[str, Any]] = []

    total_obs = sum(v["n_observations"] for v in views.values())
    if total_obs == 0:
        return [{
            "type": "diagnostic_assessment", "priority": 100, "title": "Take the diagnostic check-in",
            "rationale": "There is no evidence about your understanding yet, so every concept starts at an uncertain "
            "prior. A short diagnostic (one question per concept, prerequisites first) gives the learner model its "
            "first observations.", "concept_ids": [str(c.id) for c in concepts], "difficulty": 2,
        }]

    for h in active_hypotheses(db, user_id, course_id):
        if h["status"] in ("suspected", "supported", "unresolved") or (
                h["status"] == "resolving" and h["revisit_at"] and h["revisit_at"] <= now.isoformat()):
            pr = {"supported": 95, "suspected": 90, "unresolved": 80, "resolving": 70}[h["status"]]
            what = "revisit" if h["status"] == "resolving" else "investigate"
            recs.append({
                "type": "blindspot_session", "priority": pr, "title": f"{what.title()}: {h['title']}",
                "rationale": f"A '{h['title']}' hypothesis is {h['status']} (model posterior {h['posterior']:.2f} from "
                f"{h['evidence_count']} piece(s) of evidence). Focused conceptual practice is more useful than harder "
                "questions until it is resolved.",
                "concept_ids": [h["concept_id"]] if h["concept_id"] else [], "misconception_key": h["misconception_key"],
                "difficulty": 2,
            })

    for c in concepts:
        v = views[c.id]
        p = v["p_mastery"]
        if p is None or p >= READY:
            continue
        weak_pre = [pid for pid in prereqs.get(c.id, []) if pid in views and
                    (views[pid]["p_mastery"] is None or views[pid]["p_mastery"] < READY)]
        if weak_pre:
            for pid in weak_pre:
                pv = views[pid]
                pre_state = "unassessed" if pv["p_mastery"] is None else f"at {pv['p_mastery']:.2f}"
                recs.append({
                    "type": "practice", "priority": 75 - (pv["p_mastery"] or 0) * 10,
                    "title": f"Strengthen the prerequisite: {name[pid]}",
                    "rationale": f"'{c.name}' is at {p:.2f} and depends on '{name[pid]}', which is "
                    f"{pre_state}. Building the "
                    "prerequisite first should make later practice more effective.",
                    "concept_ids": [str(pid)], "difficulty": target_difficulty(pv["p_mastery"]),
                })
        else:
            recs.append({
                "type": "practice", "priority": 70 - p * 20, "title": f"Targeted practice: {c.name}",
                "rationale": f"Estimated mastery {p:.2f} ({v['label']}, {v['evidence_quality']} evidence). Its "
                "prerequisites look ready, so practice at a matched difficulty is the next step.",
                "concept_ids": [str(c.id)], "difficulty": target_difficulty(p),
            })

    for c in concepts:
        v = views[c.id]
        if v["p_mastery"] is not None and (v["review_due"] or v["stale"]) and v["p_mastery"] >= READY:
            recs.append({
                "type": "review", "priority": 50, "title": f"Spaced review: {c.name}",
                "rationale": "The last reliable demonstration is due for review "
                f"({'stale evidence' if v['stale'] else 'review interval reached'}); a quick retrieval check guards "
                "against forgetting, which BKT itself does not model.",
                "concept_ids": [str(c.id)], "difficulty": target_difficulty(v["p_mastery"]),
            })
        if v["p_mastery"] is None:
            recs.append({
                "type": "assessment", "priority": 45, "title": f"First check: {c.name}",
                "rationale": "No scored evidence yet for this concept.", "concept_ids": [str(c.id)], "difficulty": 2,
            })

    if not recs:
        recs.append({"type": "mock_exam", "priority": 10, "title": "Mixed mock exam",
                     "rationale": "All concepts are estimated proficient; a mixed exam with harder, unseen questions "
                     "tests transfer across topics.", "concept_ids": [str(c.id) for c in concepts], "difficulty": 3})
    recs.sort(key=lambda r: r["priority"], reverse=True)
    seen, out = set(), []
    for r in recs:
        key = (r["type"], tuple(r["concept_ids"]), r.get("misconception_key"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out[:limit]
