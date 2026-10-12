"""Assessment-quality evaluation.

  pool                 verified/rejected counts by origin, type and difficulty (valid question rate)
  answer_keys          independent plug-back re-check of every verified template question
  verifier             detection of deliberately flawed drafts (adversarial set) vs sound drafts
  source_tags          share of verified questions whose cited source unit is tagged to the
                       question's concept (or one of its sub-concepts)
  numeric_grading      grader decisions on labelled numerical responses
  short_answer_grading local rubric grader on labelled good / partial / wrong answers
  repetition           exact and family-level repetition over 6 consecutive adaptive
                       assessments for one fresh learner vs a uniform-random selector
"""

from __future__ import annotations

import json
import random
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.models import Concept, ConceptSource, CourseMembership, Question, QuestionSource, User
from app.services.assessment import templates as T
from app.services.assessment.grading import grade
from app.services.assessment.plugback import plug_back
from app.services.assessment.selection import select_questions
from app.services.assessment.supply import draft_from_template
from app.services.assessment.verification import QuestionDraft, verify
from app.services.learner import mastery
from app.services.learning.attempts import record_exposure

DATA = REPO_ROOT / "evaluation" / "datasets"


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def evaluate(db: Session, course_id: uuid.UUID, *, seed: int = 7) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    concepts = {c.catalog_key: c for c in db.scalars(select(Concept).where(Concept.course_id == course_id))
                if c.catalog_key}
    qs = list(db.scalars(select(Question).where(Question.course_id == course_id)))
    verified = [q for q in qs if q.verification_status == "verified"]

    # ---- pool -----------------------------------------------------------------------------
    by_origin: dict[str, dict[str, int]] = {}
    for q in qs:
        d = by_origin.setdefault(q.origin, {"verified": 0, "rejected": 0})
        d[q.verification_status if q.verification_status in d else "rejected"] += 1
    pool = {
        "total": len(qs), "verified": len(verified),
        "valid_question_rate": _rate(len(verified), len(qs)),
        "by_origin": by_origin,
        "by_type": dict(Counter(q.question_type for q in verified)),
        "by_difficulty": {str(k): v for k, v in sorted(Counter(q.difficulty for q in verified).items())},
        "by_concept": dict(Counter(next((c.name for c in concepts.values() if c.id == q.concept_id), "other")
                                   for q in verified)),
    }

    # ---- answer keys (templates) --------------------------------------------------------------
    tmpl = [q for q in verified if q.template_key]
    ok = 0
    for q in tmpl:
        target = q.correct_option_id if q.question_type == "mcq" else q.numeric_answer
        passed = plug_back(q.template_key, {k: v for k, v in q.params.items()}, target) is True
        ok += int(passed)
        if not passed:
            results.append({"case_key": f"key:{q.id}", "category": "answer_key", "passed": False,
                            "metrics": {}, "output": {"stem": q.stem, "template": q.template_key}})
    answer_keys = {"template_questions": len(tmpl), "plug_back_pass_rate": _rate(ok, len(tmpl)),
                   "note": "Bank items carry author keys (instructor-reviewable); they are covered by the verifier "
                   "and grading checks rather than an automatic oracle."}

    # ---- verifier on adversarial drafts ----------------------------------------------------------
    vset = json.loads((DATA / "question_verification_v1.json").read_text())
    tp = fp = tn = fn = 0
    for item in vset["items"]:
        if item["kind"] == "template":
            tpl = T.TEMPLATES[item["template"]]
            g = T.generate(item["template"], item["seed"])
            d = draft_from_template(g, concepts[tpl.concept_key].id, seed=item["seed"])
            if item.get("tamper") == "signature":
                sig = next(s for s in g.signatures if s.get("misconception_key"))
                d.numeric_answer = float(sig["value"])
                d.misconception_signatures = []
            elif item.get("tamper") == "plus10pct":
                d.numeric_answer = round((d.numeric_answer or 0) * 1.1, 2)
        else:
            dd = item["draft"]
            d = QuestionDraft(concept_id=concepts[item["concept_key"]].id, question_type=dd["question_type"],
                              difficulty=dd["difficulty"], stem=dd["stem"], explanation=dd["explanation"],
                              origin=dd["origin"], options=dd.get("options", []),
                              correct_option_id=dd.get("correct_option_id"), numeric_answer=dd.get("numeric_answer"),
                              numeric_tolerance=dd.get("numeric_tolerance"), answer_unit=dd.get("answer_unit"),
                              rubric=dd.get("rubric", {}), source_anchors=dd.get("source_anchors", []),
                              source_unit_ids=dd.get("source_unit_ids", []), source_query=dd.get("source_query"))
        out = verify(db, course_id, d, existing_embeddings=None)
        got = out.status
        correct = got == item["expect"]
        if item["expect"] == "rejected":
            tp += int(got == "rejected")
            fn += int(got != "rejected")
        else:
            tn += int(got == "verified")
            fp += int(got != "verified")
        failed = [c for c in out.report["checks"] if c["passed"] is False]
        results.append({"case_key": item["key"], "category": "verifier", "passed": correct,
                        "metrics": {"expected": item["expect"], "got": got},
                        "output": {"flaw": item.get("flaw"), "stem": d.stem, "failed_checks": failed}})
    verifier = {"n": len(vset["items"]), "flawed": tp + fn, "sound": tn + fp,
                "flaw_detection_rate": _rate(tp, tp + fn), "false_rejection_rate": _rate(fp, tn + fp),
                "accuracy": _rate(tp + tn, len(vset["items"]))}

    # ---- source tags ---------------------------------------------------------------------------------
    sub_of = {c.id: c.parent_id for c in db.scalars(select(Concept).where(Concept.course_id == course_id))}
    tag_ok = with_src = 0
    for q in verified:
        units = [r[0] for r in db.execute(select(QuestionSource.content_unit_id).where(
            QuestionSource.question_id == q.id)).all()]
        if not units:
            continue
        with_src += 1
        tagged = {r[0] for r in db.execute(select(ConceptSource.concept_id).where(
            ConceptSource.content_unit_id.in_(units))).all()}
        family = {q.concept_id} | {cid for cid, parent in sub_of.items() if parent == q.concept_id}
        tag_ok += int(bool(tagged & family))
    source_tags = {"verified_with_sources": _rate(with_src, len(verified)),
                   "source_concept_agreement": _rate(tag_ok, with_src),
                   "definition": "a cited source unit is tagged to the question's concept or a sub-concept"}

    # ---- grading -----------------------------------------------------------------------------------------
    gset = json.loads((DATA / "grading_cases_v1.json").read_text())
    n_ok = 0
    for case in gset["numerical"]:
        q = Question(question_type="numerical", numeric_answer=case["answer"], numeric_tolerance=case["tolerance"],
                     tolerance_mode="abs", answer_unit=case["unit"], options=[], rubric={})
        g = grade(q, {"value": case["response"]})
        good = g.is_correct == case["expect"]
        n_ok += int(good)
        results.append({"case_key": case["key"], "category": "numeric_grading", "passed": good,
                        "metrics": {"expected": case["expect"], "got": g.is_correct},
                        "output": {"response": case["response"], "answer": case["answer"], "detail": g.detail,
                                   "note": case.get("note")}})
    numeric = {"n": len(gset["numerical"]), "accuracy": _rate(n_ok, len(gset["numerical"]))}

    bank = {(q.generation_meta or {}).get("bank_key"): q for q in verified if q.origin == "bank"}
    sa_ok = sa_review = sa_n = 0
    confusion = Counter()
    for case in gset["short_answer"]:
        q = bank.get(case["bank_key"])
        if q is None:
            continue
        g = grade(q, {"text": case["response"]})
        sa_n += 1
        decided = bool(g.is_correct)
        good = decided == case["expect"]
        sa_ok += int(good)
        sa_review += int(g.needs_review)
        confusion[f"{case['label']}->{'pass' if decided else 'fail'}{'+review' if g.needs_review else ''}"] += 1
        results.append({"case_key": case["key"], "category": "short_answer_grading", "passed": good,
                        "metrics": {"expected": case["expect"], "got": g.is_correct, "score": g.score,
                                    "needs_review": g.needs_review},
                        "output": {"label": case["label"], "response": case["response"], "detail": g.detail}})
    short = {"n": sa_n, "accuracy": _rate(sa_ok, sa_n), "flagged_for_review": _rate(sa_review, sa_n),
             "confusion": dict(confusion), "grader": "local rubric (keywords + embedding similarity)"}

    # ---- repetition ----------------------------------------------------------------------------------------
    repetition = _repetition(db, course_id, seed)
    summary = {"pool": pool, "answer_keys": answer_keys, "verifier": verifier, "source_tags": source_tags,
               "numeric_grading": numeric, "short_answer_grading": short, "repetition": repetition}
    return summary, results


def _repetition(db: Session, course_id: uuid.UUID, seed: int, sessions: int = 6, per_session: int = 6
                ) -> dict[str, Any]:
    """Novelty over consecutive assessments. Runs inside the caller's transaction (rolled back)."""
    rng = random.Random(seed)
    u = User(email=f"eval-repeat-{uuid.uuid4().hex[:8]}@sim.local", display_name="Repetition probe (simulated)",
             auth_provider="demo", is_demo=True, is_simulated=True)
    db.add(u)
    db.flush()
    db.add(CourseMembership(course_id=course_id, user_id=u.id, role="student"))
    seen_q: list[uuid.UUID] = []
    fams: list[str] = []
    for _ in range(sessions):
        picks, _log = select_questions(db, u.id, course_id, kind="practice", concept_ids=None, count=per_session,
                                       difficulty=None, question_types=["mcq", "numerical"], rng=rng)
        for p in picks:
            record_exposure(db, u.id, p.question.id)
            seen_q.append(p.question.id)
            fams.append(mastery.family_of(p.question))
    pool = [q for q in db.scalars(select(Question).where(Question.course_id == course_id,
                                                         Question.verification_status == "verified",
                                                         Question.purpose == "assessment",
                                                         Question.question_type.in_(["mcq", "numerical"])))]
    rand_q = [rng.choice(pool) for _ in range(len(seen_q))]
    def rep(xs: list) -> float:  # noqa: E306
        return round(1 - len(set(xs)) / len(xs), 4) if xs else 0.0

    return {
        "sessions": sessions, "questions_per_session": per_session, "delivered": len(seen_q),
        "adaptive_exact_repeat_rate": rep(seen_q), "adaptive_family_repeat_rate": rep(fams),
        "random_exact_repeat_rate": rep([q.id for q in rand_q]),
        "random_family_repeat_rate": rep([mastery.family_of(q) for q in rand_q]),
        "note": "Family = template or bank item family; template families legitimately recur with new numbers "
        "once a concept's families are exhausted (evidence from repeats is down-weighted in BKT).",
    }
