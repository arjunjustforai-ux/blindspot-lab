"""Adaptive question selection with novelty control.

For each requested slot the selector:
  * allocates concepts (diagnostic: one per concept in prerequisite order; adaptive:
    weighted towards low mastery, active misconceptions and due reviews);
  * targets a difficulty from the current mastery estimate;
  * excludes questions the learner has already seen, and down-ranks unseen questions
    from a question *family* the learner has already practised (paraphrase control);
  * prefers questions carrying signatures for an active misconception hypothesis,
    capped at medium difficulty (focused conceptual practice, not harder questions);
  * tops up from parametric templates (fresh, verified) when the pool runs dry.
Every choice is logged with a human-readable reason.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Concept, Question, QuestionAttempt, QuestionExposure
from app.services.assessment import templates as T
from app.services.assessment.supply import generate_template_question
from app.services.knowledge import graph
from app.services.learner import mastery
from app.services.learner.recommender import active_hypotheses, prerequisite_map, target_difficulty

ALL_TYPES = ("mcq", "short_answer", "numerical")


@dataclass
class Pick:
    question: Question
    reason: str


def _seen(db: Session, user_id: uuid.UUID) -> tuple[set[uuid.UUID], dict[str, int]]:
    seen_ids = {r[0] for r in db.execute(select(QuestionExposure.question_id)
                                         .where(QuestionExposure.user_id == user_id)).all()}
    fam_counts: dict[str, int] = {}
    rows = db.execute(select(Question).join(QuestionAttempt, QuestionAttempt.question_id == Question.id)
                      .where(QuestionAttempt.user_id == user_id)).scalars().all()
    for q in rows:
        f = mastery.family_of(q)
        fam_counts[f] = fam_counts.get(f, 0) + 1
    return seen_ids, fam_counts


def select_questions(
    db: Session, user_id: uuid.UUID, course_id: uuid.UUID, *, kind: str, concept_ids: list[uuid.UUID] | None,
    count: int, difficulty: int | None, question_types: list[str] | None, rng: random.Random | None = None,
) -> tuple[list[Pick], list[dict[str, Any]]]:
    rng = rng or random.Random()
    types = [t for t in (question_types or ALL_TYPES) if t in ALL_TYPES] or list(ALL_TYPES)
    concepts = list(db.scalars(select(Concept).where(Concept.course_id == course_id, Concept.kind == "concept",
                                                     Concept.review_status != "rejected")))
    if concept_ids:
        wanted = set(concept_ids)
        concepts = [c for c in concepts if c.id in wanted]
    if not concepts:
        return [], [{"note": "no concepts in scope"}]
    prereqs = prerequisite_map(db, course_id)
    edges = [(p, c) for c, ps in prereqs.items() for p in ps]
    order = graph.topological_order([c.id for c in concepts], edges)
    by_id = {c.id: c for c in concepts}
    concepts = [by_id[i] for i in order]
    states = mastery.states_for(db, user_id, course_id)
    hyps = [h for h in active_hypotheses(db, user_id, course_id) if h["status"] in ("suspected", "supported",
                                                                                     "unresolved")]
    hyp_by_concept: dict[str, list[str]] = {}
    for h in hyps:
        if h["concept_id"]:
            hyp_by_concept.setdefault(h["concept_id"], []).append(h["misconception_key"])
    seen_ids, fam_counts = _seen(db, user_id)

    # ---- allocate slots to concepts --------------------------------------------
    slots: list[Concept] = []
    if kind == "diagnostic":
        slots = concepts[:count] if count < len(concepts) else list(concepts)
        while len(slots) < count:
            slots += concepts[: count - len(slots)]
    else:
        weights = []
        for c in concepts:
            st = states.get(c.id)
            p = st.p_mastery if st and st.n_observations else 0.5
            w = 1.0 + (1 - p) * 2
            if str(c.id) in hyp_by_concept:
                w += 2.0
            if st and st.next_review_at and kind == "review":
                w += 1.0
            weights.append(w)
        slots = list(concepts) if count >= len(concepts) else []
        while len(slots) < count:
            slots.append(rng.choices(concepts, weights=weights, k=1)[0])
        if count < len(concepts):
            slots = slots[:count]
        slots.sort(key=lambda c: order.index(c.id))

    picks: list[Pick] = []
    log: list[dict[str, Any]] = []
    used: set[uuid.UUID] = set()
    used_fams: set[str] = set()
    type_cycle = list(types)
    rng.shuffle(type_cycle)
    for i, c in enumerate(slots):
        st = states.get(c.id)
        p = st.p_mastery if st and st.n_observations else None
        target = difficulty or (2 if kind == "diagnostic" else target_difficulty(p))
        mkeys = hyp_by_concept.get(str(c.id), [])
        if mkeys and kind != "mock_exam":
            target = min(target, 2)
        preferred_type = type_cycle[i % len(type_cycle)]
        purposes = ["assessment", "practice", "transfer"] if kind != "diagnostic" else ["assessment"]
        pool = list(db.scalars(select(Question).where(
            Question.concept_id == c.id, Question.verification_status == "verified",
            Question.purpose.in_(purposes), Question.question_type.in_(types))))
        allow_seen = kind == "review"
        cands = [q for q in pool if q.id not in used and (allow_seen or q.id not in seen_ids)]

        def score(q: Question) -> float:
            s = -abs(q.difficulty - target) * 2.0
            f = mastery.family_of(q)
            s -= 1.5 * fam_counts.get(f, 0)
            s -= 3.0 if f in used_fams else 0.0
            s += 1.0 if q.question_type == preferred_type else 0.0
            if mkeys and any(sig.get("misconception_key") in mkeys for sig in q.misconception_signatures):
                s += 2.5
            if q.id in seen_ids:
                s -= 4.0
            return s + rng.random() * 0.1

        chosen = max(cands, key=score) if cands else None
        reason_bits = [f"{c.name}: mastery {'unassessed' if p is None else f'{p:.2f}'} → target difficulty {target}"]
        if chosen is None or abs(chosen.difficulty - target) > 1 or fam_counts.get(mastery.family_of(chosen), 0) > 1:
            tpls = [t for t in T.templates_for_concept(c.catalog_key or "") if t.question_type in types]
            tpls.sort(key=lambda t: (abs(t.difficulty - target), fam_counts.get(t.family, 0), rng.random()))
            for t in tpls[:3]:
                fresh = generate_template_question(db, course_id, t.key, purpose="assessment",
                                                   seed=rng.randint(1, 10**9))
                if fresh is not None and fresh.id not in seen_ids:
                    chosen = fresh
                    reason_bits.append(f"fresh verified template question ({t.key})")
                    break
        if chosen is None:
            log.append({"concept_id": str(c.id), "note": "no unseen verified question available"})
            continue
        if mkeys and any(sig.get("misconception_key") in mkeys for sig in chosen.misconception_signatures):
            reason_bits.append(f"targets active misconception hypothesis ({', '.join(mkeys)})")
        f = mastery.family_of(chosen)
        reason_bits.append("new question family" if fam_counts.get(f, 0) == 0 else
                           f"family seen {fam_counts[f]}x before (evidence will be down-weighted)")
        used.add(chosen.id)
        used_fams.add(f)
        picks.append(Pick(chosen, "; ".join(reason_bits)))
        log.append({"concept_id": str(c.id), "question_id": str(chosen.id), "reason": "; ".join(reason_bits)})
    return picks, log
