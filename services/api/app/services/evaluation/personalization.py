"""Personalization evaluation with simulated learners.

Each simulated learner has a hidden ground-truth state: which concepts it knows and
which catalogued misconceptions it holds. It answers questions through a fixed,
explicit response model, and learns through explicit (assumed) learning rates. Two
strategies get the same interaction budget and both show feedback after every answer:

  adaptive  the real Blindspot Lab code paths: diagnostic onboarding, recommender,
            adaptive selection, Blindspot investigations (probes -> repair -> practice ->
            transfer), BKT updates
  baseline  a generic quiz: uniformly random verified questions each session (repeats across
            sessions allowed, as in a static quiz bank), no diagnosis or targeting

Everything runs against the real database inside a SAVEPOINT that is rolled back per learner.
These results describe the system's behaviour under the stated assumptions; they are NOT
evidence about real students' learning.
"""

from __future__ import annotations

import random
import statistics
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assessment, Concept, CourseMembership, Question, User
from app.services.assessment import sessions as A
from app.services.assessment import templates as T
from app.services.diagnosis import engine as E
from app.services.diagnosis.store import catalog_by_key
from app.services.learner import mastery
from app.services.learner.recommender import active_hypotheses, prerequisite_map, recommend
from app.services.learning.attempts import submit

# ---- explicit simulation assumptions ------------------------------------------------------------
ASSUMPTIONS = {
    "slip": 0.10, "slip_per_difficulty": 0.03, "mcq_guess": "uniform over options", "numeric_guess": 0.05,
    "p_signature_answer_if_misconception": 0.8,
    "p_learn_after_feedback": 0.12, "p_learn_without_prereqs": 0.03,
    "p_fix_misconception_generic_feedback": 0.08, "p_fix_misconception_targeted_repair": 0.6,
    "p_learn_from_worked_example": 0.3, "p_forget_per_session": 0.03,
    "probe_consistency": 0.8, "interactions_per_session": 8, "learning_sessions": 5,
    "question_types": ["mcq", "numerical"],
}

PROFILES: dict[str, dict[str, Any]] = {
    "A_strong": {
        "label": "Learner A: strong baseline knowledge",
        "p_known": {"revenue_conversion": 0.9, "contribution_margin": 0.85, "roas": 0.8, "cac_clv": 0.8,
                    "correlation_causation": 0.85, "decision_assumptions": 0.8},
        "p_misconception": {"default": 0.05},
    },
    "B_mixed": {
        "label": "Learner B: mixed understanding with selected misconceptions",
        "p_known": {"revenue_conversion": 0.8, "contribution_margin": 0.5, "roas": 0.4, "cac_clv": 0.5,
                    "correlation_causation": 0.6, "decision_assumptions": 0.5},
        "p_misconception": {"contribution_vs_revenue": 0.7, "roas_vs_profitability": 0.6,
                            "correlation_vs_causation": 0.5, "mean_vs_median": 0.4, "pp_vs_percent_change": 0.3,
                            "default": 0.15},
    },
    "C_weak_prereq": {
        "label": "Learner C: weak prerequisite knowledge",
        "p_known": {"revenue_conversion": 0.15, "contribution_margin": 0.15, "roas": 0.1, "cac_clv": 0.1,
                    "correlation_causation": 0.3, "decision_assumptions": 0.1},
        "p_misconception": {"revenue_vs_profit": 0.5, "contribution_vs_revenue": 0.4, "default": 0.15},
    },
}


@dataclass
class SimLearner:
    profile: str
    known: dict[str, bool]
    misconceptions: set[str]
    rng: random.Random
    initial_known: dict[str, bool] = field(default_factory=dict)
    initial_misconceptions: set[str] = field(default_factory=set)


def make_learner(profile: str, rng: random.Random, active: set[str]) -> SimLearner:
    p = PROFILES[profile]
    known = {k: rng.random() < v for k, v in p["p_known"].items()}
    mis = {m for m in active if rng.random() < p["p_misconception"].get(m, p["p_misconception"]["default"])}
    return SimLearner(profile, known, mis, rng, dict(known), set(mis))


class Sim:
    def __init__(self, db: Session, course_id: uuid.UUID) -> None:
        self.db = db
        self.course_id = course_id
        self.concepts = {c.id: c for c in db.scalars(select(Concept).where(Concept.course_id == course_id,
                                                                           Concept.kind == "concept"))}
        self.key_of = {cid: c.catalog_key for cid, c in self.concepts.items()}
        prereq = prerequisite_map(db, course_id)
        self.prereq_keys = {self.key_of[c]: [self.key_of[p] for p in ps if p in self.key_of]
                            for c, ps in prereq.items() if c in self.key_of}
        self.catalog = catalog_by_key()

    # ---- ground-truth response model ---------------------------------------------------------
    def respond(self, L: SimLearner, q: Question) -> tuple[dict[str, Any], str | None, bool]:
        ck = self.key_of.get(q.concept_id)
        held = [s for s in q.misconception_signatures if s.get("misconception_key") in L.misconceptions]
        if held and L.rng.random() < ASSUMPTIONS["p_signature_answer_if_misconception"]:
            s = held[0]
            cues = self.catalog[s["misconception_key"]].get("detection_cues", [])[:2]
            reasoning = ("I think it is about the " + " and ".join(cues)) if cues else None
            if q.question_type == "mcq":
                return {"option_id": s["option_id"]}, reasoning, False
            return {"value": str(s["value"])}, reasoning, False
        slip = ASSUMPTIONS["slip"] + ASSUMPTIONS["slip_per_difficulty"] * (q.difficulty - 1)
        correct = L.rng.random() > slip if L.known.get(ck, False) else (
            L.rng.random() < (1 / max(len(q.options), 1) if q.question_type == "mcq" else ASSUMPTIONS["numeric_guess"]))
        if q.question_type == "mcq":
            if correct:
                return {"option_id": q.correct_option_id}, None, True
            wrong = [o["id"] for o in q.options if o["id"] != q.correct_option_id]
            return {"option_id": L.rng.choice(wrong)}, None, False
        if correct:
            return {"value": str(q.numeric_answer)}, None, True
        v = (q.numeric_answer or 1) * L.rng.choice([0.5, 0.7, 1.3, 1.6, 2.0]) + L.rng.choice([-7, 3, 11])
        return {"value": f"{v:.2f}"}, None, False

    def respond_probe(self, L: SimLearner, probe: dict[str, Any], mkey: str, expected: float | None) -> dict[str, Any]:
        holds = mkey in L.misconceptions
        if probe["type"] == "mcq":
            lk = probe["likelihoods"]
            target = "misconception" if holds else "calculation_error" if any(
                "calculation_error" in v for v in lk.values()) else "misread_question"
            best = max(lk, key=lambda r: lk[r].get(target, 0))
            if L.rng.random() < ASSUMPTIONS["probe_consistency"]:
                return {"option_id": best}
            return {"option_id": L.rng.choice(list(lk))}
        entry = self.catalog[mkey]
        ck = entry["concept_keys"][0]
        can = L.known.get(ck, False) or holds
        ok = L.rng.random() < (0.85 if can else 0.2)
        return {"value": str(expected if ok else (expected or 1) * 1.5 + 3)}

    # ---- ground-truth learning model ---------------------------------------------------------
    def learn_from_feedback(self, L: SimLearner, q: Question, used_signature: bool) -> None:
        ck = self.key_of.get(q.concept_id)
        if ck and not L.known.get(ck):
            ready = all(L.known.get(p, False) for p in self.prereq_keys.get(ck, []))
            p = ASSUMPTIONS["p_learn_after_feedback"] if ready else ASSUMPTIONS["p_learn_without_prereqs"]
            if L.rng.random() < p:
                L.known[ck] = True
        if used_signature:
            for s in q.misconception_signatures:
                m = s.get("misconception_key")
                if m in L.misconceptions and L.rng.random() < ASSUMPTIONS["p_fix_misconception_generic_feedback"]:
                    L.misconceptions.discard(m)

    def learn_from_repair(self, L: SimLearner, mkey: str | None) -> None:
        if mkey and mkey in L.misconceptions and L.rng.random() < ASSUMPTIONS["p_fix_misconception_targeted_repair"]:
            L.misconceptions.discard(mkey)
        if mkey:
            ck = self.catalog[mkey]["concept_keys"][0]
            ready = all(L.known.get(p, False) for p in self.prereq_keys.get(ck, []))
            if not L.known.get(ck) and L.rng.random() < (ASSUMPTIONS["p_learn_from_worked_example"] if ready else 0.1):
                L.known[ck] = True

    def forget(self, L: SimLearner) -> None:
        for k in L.known:
            if L.known[k] and L.rng.random() < ASSUMPTIONS["p_forget_per_session"]:
                L.known[k] = False


def _answer_and_learn(sim: Sim, L: SimLearner, user: User, q: Question, **kw: Any) -> Any:
    resp, reasoning, _ = sim.respond(L, q)
    used_sig = any(str(resp.get("option_id", "")) == str(s.get("option_id")) or
                   (s.get("value") is not None and resp.get("value") == str(s["value"]))
                   for s in q.misconception_signatures)
    return resp, reasoning, used_sig


def run_adaptive(sim: Sim, L: SimLearner, user: User, log: dict[str, Any]) -> None:
    db = sim.db
    budget_per = ASSUMPTIONS["interactions_per_session"]
    for sess in range(ASSUMPTIONS["learning_sessions"]):
        budget = budget_per
        if sess > 0:
            sim.forget(L)
        while budget > 0:
            recs = recommend(db, user.id, sim.course_id, limit=3)
            rec = recs[0] if recs else {"type": "practice", "concept_ids": [], "difficulty": None}
            if rec["type"] == "blindspot_session" and rec.get("misconception_key"):
                budget -= _run_blindspot(sim, L, user, rec["misconception_key"], budget, log)
                continue
            kind = "diagnostic" if rec["type"] == "diagnostic_assessment" else (
                "review" if rec["type"] == "review" else "practice")
            cids = [uuid.UUID(c) for c in rec.get("concept_ids", [])] or None
            count = len(sim.concepts) if kind == "diagnostic" else min(budget, 3)
            try:
                a = A.create(db, user, sim.course_id, kind=kind, concept_ids=cids, count=count,
                             difficulty=None, question_types=ASSUMPTIONS["question_types"])
            except Exception:  # noqa: BLE001 - pool exhausted for this scope: fall back to any concept
                try:
                    a = A.create(db, user, sim.course_id, kind="practice", concept_ids=None, count=min(budget, 3),
                                 difficulty=None, question_types=ASSUMPTIONS["question_types"])
                except Exception:  # noqa: BLE001
                    log["exhausted"] = log.get("exhausted", 0) + 1
                    break
            items = A.view(db, a)["items"]
            for it in items:
                if budget <= 0:
                    break
                q = db.get(Question, uuid.UUID(it["question"]["id"]))
                resp, reasoning, used_sig = _answer_and_learn(sim, L, user, q)
                A.answer(db, user, a, q.id, resp, reasoning, 3, None)
                sim.learn_from_feedback(L, q, used_sig)
                log["questions"].append(q.id)
                log["families"].append(mastery.family_of(q))
                log["interactions"] = log.get("interactions", 0) + 1
                budget -= 1
            A.complete(db, user, a)


def _run_blindspot(sim: Sim, L: SimLearner, user: User, mkey: str, budget: int, log: dict[str, Any]) -> int:
    db = sim.db
    used = 0
    try:
        s = E.start_session(db, user, sim.course_id, misconception_key=mkey)
    except Exception:  # noqa: BLE001
        return 1  # count a wasted interaction so the loop always terminates
    log["blindspot_sessions"] += 1
    log["targeted_correctly"] += int(mkey in L.misconceptions)
    while used < budget:
        v = E.view(db, s)
        pend = v["pending"]
        if pend is None:
            break
        if pend["type"] in ("answer_question", "answer_practice", "answer_transfer"):
            q = db.get(Question, uuid.UUID(pend["question"]["id"]))
            resp, reasoning, used_sig = _answer_and_learn(sim, L, user, q)
            if pend["type"] == "answer_question":
                E.answer_question(db, user, s, resp, reasoning, 3)
            elif pend["type"] == "answer_practice":
                E.answer_practice(db, user, s, resp, reasoning, 3)
            else:
                E.answer_transfer(db, user, s, resp, reasoning, 3)
            sim.learn_from_feedback(L, q, used_sig)
            log["questions"].append(q.id)
            log["families"].append(mastery.family_of(q))
            log["interactions"] = log.get("interactions", 0) + 1
            used += 1
        elif pend["type"] == "answer_probe":
            from app.models import DiagnosticProbe

            p = db.get(DiagnosticProbe, uuid.UUID(pend["probe"]["id"]))
            probe = {"type": p.probe_type, "likelihoods": p.discrimination["likelihoods"]}
            resp = sim.respond_probe(L, probe, s.hypotheses[0]["misconception_key"], p.expected_numeric)
            E.answer_probe(db, user, s, p.id, resp)
            log["probes"] = log.get("probes", 0) + 1
            log["interactions"] = log.get("interactions", 0) + 1
            used += 1
        elif pend["type"] == "continue_repair":
            log["repairs"] += 1
            sim.learn_from_repair(L, s.hypotheses[0]["misconception_key"] if s.hypotheses else None)
            E.continue_after_repair(db, user, s)
    return max(used, 1)


def run_baseline(sim: Sim, L: SimLearner, user: User, pool: list[Question], log: dict[str, Any]) -> None:
    for sess in range(ASSUMPTIONS["learning_sessions"]):
        if sess > 0:
            sim.forget(L)
        picks = L.rng.sample(pool, k=min(ASSUMPTIONS["interactions_per_session"], len(pool)))
        a = Assessment(course_id=sim.course_id, user_id=user.id, kind="practice", status="in_progress",
                         config={"baseline": True}, selection_log=[])
        sim.db.add(a)
        sim.db.flush()
        for q in picks:
            resp, reasoning, used_sig = _answer_and_learn(sim, L, user, q)
            submit(sim.db, user=user, course_id=sim.course_id, question=q, response=resp, reasoning=reasoning,
                   confidence=3, context="assessment", assessment_id=a.id, mastery_source="practice")
            sim.learn_from_feedback(L, q, used_sig)
            log["questions"].append(q.id)
            log["families"].append(mastery.family_of(q))


def heldout_items(sim: Sim, seed: int) -> list[tuple[str, Any]]:
    """Held-out post-test: never served during learning (fresh template seeds + 'heldout' bank items)."""
    items: list[tuple[str, Any]] = []
    rng = random.Random(seed)
    for _cid, key in sim.key_of.items():
        tpls = [t for t in T.templates_for_concept(key or "") if t.question_type in ("mcq", "numerical")]
        for t in rng.sample(tpls, k=min(2, len(tpls))):
            g = T.generate(t.key, 900_000 + rng.randint(0, 99_999))
            items.append((key, g))
    for q in sim.db.scalars(select(Question).where(Question.course_id == sim.course_id,
                                                   Question.purpose == "heldout",
                                                   Question.verification_status == "verified")):
        items.append((sim.key_of.get(q.concept_id), q))
    return items


def post_test(sim: Sim, L: SimLearner, items: list[tuple[str, Any]]) -> float:
    correct = 0
    for key, it in items:
        if isinstance(it, Question):
            q = it
        else:
            q = Question(question_type=it.question_type, difficulty=it.difficulty, options=it.options,
                         correct_option_id=it.correct_option_id, numeric_answer=it.numeric_answer,
                         misconception_signatures=it.signatures,
                         concept_id=next(c for c, k in sim.key_of.items() if k == key))
        _resp, _r, ok = sim.respond(L, q)
        correct += int(ok)
    return correct / len(items) if items else 0.0


def _metrics(sim: Sim, L: SimLearner, user: User, log: dict[str, Any], items, post: float, retention: float
             ) -> dict[str, Any]:
    db = sim.db
    states = mastery.states_for(db, user.id, sim.course_id)
    brier, weak_ok, n = 0.0, 0, 0
    for cid, key in sim.key_of.items():
        st = states.get(cid)
        p = st.p_mastery if st and st.n_observations else mastery.bkt.P_INIT
        truth = 1.0 if L.known.get(key) else 0.0
        brier += (p - truth) ** 2
        weak_ok += int((p < 0.5) == (truth == 0.0))
        n += 1
    hyps = active_hypotheses(db, user.id, sim.course_id)
    # Identified = the system ended up believing (suspected/supported) or acted on it (resolving/resolved).
    flagged = {h["misconception_key"] for h in hyps if h["status"] in ("suspected", "supported", "resolving",
                                                                         "resolved")}
    tp = len(flagged & L.initial_misconceptions)
    qs = log["questions"]
    return {
        "post_test_accuracy": round(post, 4), "retention_accuracy": round(retention, 4),
        "true_known_start": round(sum(L.initial_known.values()) / len(L.initial_known), 4),
        "true_known_end": round(sum(L.known.values()) / len(L.known), 4),
        "misconceptions_start": len(L.initial_misconceptions), "misconceptions_end": len(L.misconceptions),
        "misconceptions_resolved_rate": round(1 - len(L.misconceptions & L.initial_misconceptions) /
                                              len(L.initial_misconceptions), 4) if L.initial_misconceptions else None,
        "mastery_brier": round(brier / n, 4), "weak_concept_identification_accuracy": round(weak_ok / n, 4),
        "mean_estimated_mastery": round(statistics.mean(
            [s.p_mastery for s in states.values() if s.n_observations] or [mastery.bkt.P_INIT]), 4),
        "gap_precision": round(tp / len(flagged), 4) if flagged else None,
        "gap_recall": round(tp / len(L.initial_misconceptions), 4) if L.initial_misconceptions else None,
        "questions_answered": len(qs), "interactions": log.get("interactions", len(qs)), "probes": log.get("probes", 0),
        "exact_repeat_rate": round(1 - len(set(qs)) / len(qs), 4) if qs else 0.0,
        "family_repeat_rate": round(1 - len(set(log["families"])) / len(log["families"]), 4) if qs else 0.0,
        "blindspot_sessions": log["blindspot_sessions"], "repairs": log["repairs"],
        "targeting_precision": round(log["targeted_correctly"] / log["blindspot_sessions"], 4)
        if log["blindspot_sessions"] else None,
    }


def evaluate(db: Session, course_id: uuid.UUID, *, learners_per_profile: int = 15, seed: int = 2026,
             progress=None) -> tuple[dict[str, Any], list[dict[str, Any]]]:  # noqa: ANN001
    sim = Sim(db, course_id)
    active = set(catalog_by_key())
    from app.services.diagnosis.store import active_keys

    active &= active_keys(db, course_id)
    pool = list(db.scalars(select(Question).where(Question.course_id == course_id,
                                                  Question.verification_status == "verified",
                                                  Question.purpose == "assessment",
                                                  Question.question_type.in_(["mcq", "numerical"]))))
    items = heldout_items(sim, seed)
    results: list[dict[str, Any]] = []
    total = len(PROFILES) * learners_per_profile * 2
    done = 0
    for pi, profile in enumerate(PROFILES):
        for i in range(learners_per_profile):
            base_seed = seed + 1000 * pi + i
            for arm in ("adaptive", "baseline"):
                random.seed(base_seed)  # engine-side randomness (template seeds) reproducible per learner
                rng = random.Random(base_seed)  # identical hidden learner in both arms
                L = make_learner(profile, rng, active)
                L.rng = random.Random(base_seed * 7 + (1 if arm == "adaptive" else 2))
                nested = db.begin_nested()
                try:
                    user = User(email=f"sim-{profile}-{i}-{arm}-{uuid.uuid4().hex[:6]}@sim.local",
                                display_name=f"Simulated {profile} #{i} ({arm})", auth_provider="demo", is_demo=True,
                                is_simulated=True)
                    db.add(user)
                    db.flush()
                    db.add(CourseMembership(course_id=course_id, user_id=user.id, role="student"))
                    db.flush()
                    log = {"questions": [], "families": [], "blindspot_sessions": 0, "repairs": 0,
                           "targeted_correctly": 0}
                    if arm == "adaptive":
                        run_adaptive(sim, L, user, log)
                    else:
                        run_baseline(sim, L, user, pool, log)
                    post = post_test(sim, L, items)
                    for _ in range(2):  # delay: two sessions without practice
                        sim.forget(L)
                    retention = post_test(sim, L, items)
                    m = _metrics(sim, L, user, log, items, post, retention)
                finally:
                    nested.rollback()
                results.append({"case_key": f"{profile}-{i:02d}-{arm}", "category": f"{profile}:{arm}",
                                "metrics": m, "passed": None,
                                "output": {"profile": profile, "arm": arm, "initial_known": L.initial_known,
                                           "initial_misconceptions": sorted(L.initial_misconceptions),
                                           "final_known": L.known, "final_misconceptions": sorted(L.misconceptions)}})
                done += 1
                if progress:
                    progress(done / total)
    summary: dict[str, Any] = {"assumptions": ASSUMPTIONS, "profiles": {k: v["label"] for k, v in PROFILES.items()},
                               "learners_per_profile": learners_per_profile, "seed": seed,
                               "posttest_items": len(items), "by_profile": {}}
    keys = ["post_test_accuracy", "retention_accuracy", "true_known_end", "misconceptions_end",
            "misconceptions_resolved_rate", "mastery_brier", "weak_concept_identification_accuracy", "gap_precision",
            "gap_recall", "exact_repeat_rate", "family_repeat_rate", "blindspot_sessions", "repairs",
            "targeting_precision", "questions_answered", "interactions", "probes", "true_known_start",
            "misconceptions_start"]
    for profile in PROFILES:
        summary["by_profile"][profile] = {}
        for arm in ("adaptive", "baseline"):
            rows = [r["metrics"] for r in results if r["category"] == f"{profile}:{arm}"]
            agg = {}
            for k in keys:
                vals = [r[k] for r in rows if r.get(k) is not None]
                if vals:
                    agg[k] = {"mean": round(statistics.mean(vals), 4),
                              "sd": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0, "n": len(vals)}
            summary["by_profile"][profile][arm] = agg
    return summary, results
