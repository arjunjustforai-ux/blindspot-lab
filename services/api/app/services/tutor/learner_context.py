"""What the learner model says about the concepts a tutor answer covered.

Grounding never depends on the learner: the answer itself comes only from the course sources.
This context is attached beside the answer so the tutor responds to the learner's state:

  * the current mastery estimate of each concept the answer drew on,
  * any open misconception hypothesis on those concepts (with its status and posterior),
  * prerequisites of those concepts that the learner model rates as weak,
  * one suggested next step, chosen by a fixed priority:
      open misconception hypothesis  -> investigate it in the Blindspot Lab
      weak prerequisite              -> review the prerequisite first
      unassessed or low mastery      -> take the knowledge check on this answer
      otherwise                      -> none (the learner is on track)
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Concept, ConceptPrerequisite, MisconceptionDefinition, MisconceptionHypothesis
from app.services.learner import mastery

OPEN_STATUSES = ("suspected", "supported", "unresolved")
WEAK_P = 0.4
CHECK_BELOW_P = 0.7


def learner_context(db: Session, user_id: uuid.UUID, course_id: uuid.UUID, concept_ids: list[str]) -> dict[str, Any]:
    ids: list[uuid.UUID] = []
    for c in concept_ids:
        try:
            ids.append(uuid.UUID(str(c)))
        except ValueError:
            continue
    if not ids:
        return {}
    concepts = {c.id: c for c in db.scalars(select(Concept).where(Concept.course_id == course_id))}
    # Mastery is tracked per concept; a sub-concept reports its parent's estimate.
    focus: list[Concept] = []
    for i in ids:
        c = concepts.get(i)
        if c is not None and c.kind == "subconcept" and c.parent_id in concepts:
            c = concepts[c.parent_id]
        if c is not None and c.kind == "concept" and c not in focus:
            focus.append(c)
    if not focus:
        return {}
    states = mastery.states_for(db, user_id, course_id)
    views = {c.id: mastery.concept_view(c, states.get(c.id)) for c in concepts.values() if c.kind == "concept"}

    focus_ids = {c.id for c in focus}
    hyps = db.execute(
        select(MisconceptionHypothesis, MisconceptionDefinition)
        .join(MisconceptionDefinition, MisconceptionDefinition.id == MisconceptionHypothesis.misconception_id)
        .where(MisconceptionHypothesis.user_id == user_id, MisconceptionHypothesis.course_id == course_id,
               MisconceptionHypothesis.concept_id.in_(focus_ids), MisconceptionHypothesis.status.in_(OPEN_STATUSES))
        .order_by(MisconceptionHypothesis.posterior.desc())
    ).all()
    prereq_ids = {e.prerequisite_id for e in db.scalars(
        select(ConceptPrerequisite).where(ConceptPrerequisite.course_id == course_id,
                                          ConceptPrerequisite.concept_id.in_(focus_ids),
                                          ConceptPrerequisite.review_status != "rejected"))} - focus_ids
    weak_prereqs = [views[p] for p in prereq_ids
                    if p in views and views[p]["p_mastery"] is not None and views[p]["p_mastery"] < WEAK_P]

    out: dict[str, Any] = {
        "concepts": [{k: views[c.id][k] for k in ("concept_id", "name", "p_mastery", "label", "evidence_quality")}
                     for c in focus],
        "hypotheses": [{"misconception_key": d.key, "title": d.title, "status": h.status,
                        "posterior": round(h.posterior, 3), "concept_id": str(h.concept_id)} for h, d in hyps],
        "weak_prerequisites": [{"concept_id": v["concept_id"], "name": v["name"], "p_mastery": v["p_mastery"]}
                               for v in weak_prereqs],
    }
    if hyps:
        h, d = hyps[0]
        out["suggestion"] = {"type": "blindspot_session", "misconception_key": d.key,
                             "text": f"Your earlier answers left an open hypothesis, '{d.title}' ({h.status}). "
                                     "A short investigation in the Blindspot Lab can confirm or rule it out."}
    elif weak_prereqs:
        w = min(weak_prereqs, key=lambda v: v["p_mastery"])
        out["suggestion"] = {"type": "practice", "concept_id": w["concept_id"],
                             "text": f"This builds on '{w['name']}', which your learner model rates at "
                                     f"{w['p_mastery']:.0%}. Practising it first should make this easier."}
    elif any(views[c.id]["p_mastery"] is None or views[c.id]["p_mastery"] < CHECK_BELOW_P for c in focus):
        out["suggestion"] = {"type": "knowledge_check",
                             "text": "Use 'Check my understanding' below: one scored question on this answer "
                                     "that updates your mastery estimate."}
    return out
