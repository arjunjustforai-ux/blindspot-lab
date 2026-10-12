"""Blindspot Lab diagnostic session: Diagnose -> Investigate -> Explain -> Repair -> Transfer.

Stages: answer -> (probing) -> (repair) -> practice -> transfer -> completed.
Every scored step goes through learning.attempts.submit (the same grading, BKT and
evidence code as ordinary assessments). Probes update a per-session distribution
over competing explanations; the learner-level hypothesis mirrors the session's
misconception posterior and keeps an auditable evidence trail.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import APIError, bad_request, conflict, not_found
from app.models import (
    Concept,
    DiagnosticProbe,
    DiagnosticSession,
    LearningIntervention,
    Question,
    QuestionAttempt,
    User,
)
from app.services.ai import llm
from app.services.ai.oplog import BudgetExceeded
from app.services.assessment import templates as T
from app.services.assessment.grading import numeric_match, parse_number
from app.services.assessment.supply import generate_template_question
from app.services.diagnosis import hypotheses as H
from app.services.diagnosis.store import active_keys, catalog_by_key, definition, get_hypothesis, record_evidence
from app.services.learner import mastery
from app.services.learning.attempts import record_exposure, submit
from app.services.retrieval.hybrid import retrieve
from app.services.tutor.citations import build_citation

TRANSFER_SUCCESS_LR = 0.3
TRANSFER_FAILURE_LR = 2.0
MAX_PRACTICE = 2
REVISIT_AFTER = timedelta(days=3)
DEMO_SCENARIO = {
    "contribution_price_cut": {
        "template": "price_cut_volume",
        "overrides": {"price": 100, "var_cost": 60, "new_price": 80, "context": ["a company", "product", "units"]},
        "scripted_answer": {"value": "25"},
        "scripted_reasoning": "25% more units, because that compensates for the price reduction.",
        "scripted_confidence": 4,
        "scripted_probe_answers": {"which_quantity": {"option_id": "a"}, "new_unit_contribution": {"value": "20"}},
    }
}


def _now() -> datetime:
    return datetime.now(UTC)


def _event(session: DiagnosticSession, kind: str, **data: Any) -> None:
    session.timeline = [*session.timeline, {"type": kind, "at": _now().isoformat(), **data}]
    session.updated_at = _now()


def public_question(q: Question) -> dict[str, Any]:
    return {"id": str(q.id), "concept_id": str(q.concept_id), "question_type": q.question_type,
            "difficulty": q.difficulty, "stem": q.stem, "options": q.options, "answer_unit": q.answer_unit,
            "assumptions": q.assumptions, "origin": q.origin, "template_key": q.template_key,
            "family": q.family_key or q.template_key}


def _seen_hashes(db: Session, user_id: uuid.UUID) -> set[str]:
    rows = db.execute(select(Question.content_hash).join(QuestionAttempt, QuestionAttempt.question_id == Question.id)
                      .where(QuestionAttempt.user_id == user_id)).all()
    return {r[0] for r in rows}


def _seen_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = db.execute(select(QuestionAttempt.question_id).where(QuestionAttempt.user_id == user_id)).all()
    return {r[0] for r in rows}


def _bank_question(db: Session, user_id: uuid.UUID, concept_id: uuid.UUID, *, misconception_key: str | None,
                   exclude_families: set[str]) -> Question | None:
    seen = _seen_ids(db, user_id)
    qs = list(db.scalars(select(Question).where(Question.concept_id == concept_id,
                                                Question.verification_status == "verified",
                                                Question.purpose.in_(["assessment", "practice", "transfer"]),
                                                Question.question_type.in_(["mcq", "numerical"]))))
    qs = [q for q in qs if q.id not in seen and mastery.family_of(q) not in exclude_families]
    if misconception_key:
        targeted = [q for q in qs if any(s.get("misconception_key") == misconception_key
                                         for s in q.misconception_signatures)]
        if targeted:
            qs = targeted
    qs.sort(key=lambda q: (q.difficulty, str(q.id)))
    return qs[0] if qs else None


def start_session(db: Session, user: User, course_id: uuid.UUID, *, concept_id: uuid.UUID | None = None,
                  misconception_key: str | None = None, scenario: str | None = None) -> DiagnosticSession:
    q: Question | None = None
    is_demo = False
    if scenario:
        sc = DEMO_SCENARIO.get(scenario)
        if sc is None:
            raise bad_request(f"Unknown scenario '{scenario}'")
        q = generate_template_question(db, course_id, sc["template"], purpose="assessment", overrides=sc["overrides"])
        if q is None:
            raise conflict("This course's sources do not support the demonstration scenario", code="unsupported")
        is_demo = True
    elif misconception_key:
        entry = catalog_by_key().get(misconception_key)
        md = definition(db, misconception_key)
        if entry is None or md is None or misconception_key not in active_keys(db, course_id):
            raise bad_request("That misconception is not active for this course")
        concept = db.scalar(select(Concept).where(Concept.course_id == course_id,
                                                  Concept.catalog_key.in_(entry["concept_keys"]),
                                                  Concept.kind == "concept"))
        tk = entry.get("repair", {}).get("worked_example_template")
        if tk:
            q = generate_template_question(db, course_id, tk, purpose="assessment", seed=random.randint(1, 10**9),
                                           avoid_hashes=_seen_hashes(db, user.id))
        if q is None and concept is not None:
            q = _bank_question(db, user.id, concept.id, misconception_key=misconception_key, exclude_families=set())
    elif concept_id:
        concept = db.get(Concept, concept_id)
        if concept is None or concept.course_id != course_id:
            raise not_found("Concept")
        act = active_keys(db, course_id)
        keys = [e["key"] for e in catalog_by_key().values() if concept.catalog_key in e["concept_keys"] and e["key"] in act]
        for k in keys:
            tk = catalog_by_key()[k].get("repair", {}).get("worked_example_template")
            if tk:
                q = generate_template_question(db, course_id, tk, purpose="assessment", seed=random.randint(1, 10**9),
                                               avoid_hashes=_seen_hashes(db, user.id))
                if q:
                    break
        if q is None:
            q = _bank_question(db, user.id, concept.id, misconception_key=keys[0] if keys else None,
                               exclude_families=set())
    else:
        raise bad_request("Provide a concept, a misconception or a scenario")
    if q is None:
        raise conflict("No verified diagnostic question is available for this selection", code="no_question")
    s = DiagnosticSession(user_id=user.id, course_id=course_id, concept_id=q.concept_id, question_id=q.id,
                          stage="answer", hypotheses=[], timeline=[], is_demo_script=is_demo)
    db.add(s)
    db.flush()
    record_exposure(db, user.id, q.id)
    _event(s, "question", role="diagnostic", question_id=str(q.id))
    db.flush()
    return s


# ---------------------------------------------------------------------------------------------


def answer_question(db: Session, user: User, s: DiagnosticSession, response: dict[str, Any], reasoning: str | None,
                    confidence: int | None) -> DiagnosticSession:
    if s.stage != "answer":
        raise conflict(f"This session is in the '{s.stage}' stage", code="wrong_stage")
    q = db.get(Question, s.question_id)
    assert q is not None
    res = submit(db, user=user, course_id=s.course_id, question=q, response=response, reasoning=reasoning,
                 confidence=confidence, context="diagnostic", session_id=s.id, mastery_source="diagnostic",
                 hypothesis_evidence=False)
    _event(s, "answer", role="diagnostic", question_id=str(q.id), attempt_id=str(res.attempt.id),
           response=response, reasoning=reasoning, confidence=confidence, feedback=res.feedback)
    cls = res.classification
    catalog = catalog_by_key()
    if res.grade.is_correct:
        # Avoiding the trap a misconception predicts is evidence against it.
        for sig in q.misconception_signatures:
            mk = sig.get("misconception_key")
            md0 = definition(db, mk) if mk else None
            h0 = get_hypothesis(db, user.id, s.course_id, md0) if md0 else None
            if h0 is not None and h0.status not in ("rejected", "resolved"):
                record_evidence(db, user_id=user.id, course_id=s.course_id, md=md0, concept_id=s.concept_id,
                                kind="avoided_trap", summary="Answered the investigation question correctly, avoiding "
                                "the answer this misconception predicts.", likelihood_ratio=0.4, session_id=s.id,
                                attempt_id=res.attempt.id,
                                status_override="resolved" if h0.status == "resolving" else None)
    if cls.category == "correct_supported":
        s.outcome = "no_blindspot_detected"
        _event(s, "note", text="Correct answer with consistent reasoning. To check that this understanding transfers, "
               "here is a structurally different problem.")
        _start_transfer(db, user, s, q, misconception_key=None)
        return s
    if cls.category == "calculation_error":
        _event(s, "note", text="This looks like an execution slip rather than a conceptual problem, so no "
               "misconception hypothesis is opened. A short practice item checks the method.")
        s.outcome = "calculation_error"
        _start_practice(db, user, s, q, misconception_key=None)
        return s

    sets = cls.candidates
    if not sets:
        # No signature: probe the concept's active misconceptions from an 'unexplained' prior.
        act = active_keys(db, s.course_id)
        concept = db.get(Concept, s.concept_id)
        keys = [k for k, e in catalog.items() if k in act and concept and concept.catalog_key in e["concept_keys"]]
        from app.services.diagnosis.classifier import _hypothesis_set

        sets = [_hypothesis_set(k, catalog[k], "unexplained" if cls.category != "correct_questionable_reasoning"
                                else "cue_only", [], [], confidence, []) for k in keys[:1]]
    if not sets:
        s.outcome = cls.category
        _event(s, "note", text="No catalogued misconception applies to this concept in your course, so the lab moves "
               "straight to a source-grounded explanation.")
        _start_repair(db, user, s, misconception_key=None)
        return s

    top = sets[0]
    md = definition(db, top["misconception_key"])
    prev = get_hypothesis(db, user.id, s.course_id, md) if md else None
    dist = H.prior_from_history(dict(top["distribution"]), prev.posterior if prev else None)
    s.hypotheses = [{"misconception_key": top["misconception_key"], "title": top["title"], "labels": top["labels"],
                     "distribution": dist, "asked": [], "pattern": top["pattern"],
                     "adjustments": top["adjustments"] + ([f"learner history (previous posterior "
                                                           f"{prev.posterior:.2f})"] if prev else [])}]
    if md is not None:
        kind = "signature_match" if top["pattern"] == "signature" else "reasoning_cue"
        if top["pattern"] != "unexplained":
            record_evidence(db, user_id=user.id, course_id=s.course_id, md=md, concept_id=s.concept_id, kind=kind,
                            summary=cls.summary, set_posterior=dist["misconception"], session_id=s.id,
                            attempt_id=res.attempt.id, detail={"distribution": dist})
    _event(s, "hypotheses", distribution=dist, misconception_key=top["misconception_key"],
           note="Initial hypotheses from the answer and reasoning (hand-set priors; see methodology).")
    _next_probe_or_conclude(db, user, s)
    return s


def _next_probe_or_conclude(db: Session, user: User, s: DiagnosticSession) -> None:
    hs = s.hypotheses[0]
    entry = catalog_by_key()[hs["misconception_key"]]
    q = db.get(Question, s.question_id)
    probes = []
    for p in entry.get("diagnostic_probes", []):
        p2 = dict(p)
        p2["likelihoods"] = {r: {h: lk.get(h, 1e-6) for h in hs["distribution"]} for r, lk in p["likelihoods"].items()}
        if p.get("type") == "numerical" and p.get("expected_param") and \
                (q is None or (q.params or {}).get(p["expected_param"]) is None):
            continue
        probes.append(p2)
    if len(hs["asked"]) < H.MAX_PROBES:
        probe, gain = H.choose_probe(hs["distribution"], probes, set(hs["asked"]))
        if probe is not None and gain >= H.MIN_EIG_BITS:
            expected = None
            prompt = probe["prompt"]
            if probe["type"] == "numerical":
                expected = float(q.params[probe["expected_param"]]) if probe.get("expected_param") else \
                    float(probe["expected_value"])
            row = DiagnosticProbe(session_id=s.id, misconception_id=definition(db, hs["misconception_key"]).id,
                                  probe_key=probe["key"], probe_type=probe["type"], prompt=prompt,
                                  options=probe.get("options", []),
                                  discrimination={"likelihoods": probe["likelihoods"], "notes": probe.get("notes", {}),
                                                  "tolerance": probe.get("tolerance", 0.01),
                                                  "expected_information_gain_bits": round(gain, 4)},
                                  expected_numeric=expected)
            db.add(row)
            db.flush()
            s.stage = "probing"
            _event(s, "probe", probe_id=str(row.id), probe_key=probe["key"], eig_bits=round(gain, 4))
            return
    _conclude(db, user, s)


def answer_probe(db: Session, user: User, s: DiagnosticSession, probe_id: uuid.UUID, response: dict[str, Any]
                 ) -> DiagnosticSession:
    if s.stage != "probing":
        raise conflict(f"This session is in the '{s.stage}' stage", code="wrong_stage")
    p = db.get(DiagnosticProbe, probe_id)
    if p is None or p.session_id != s.id or p.answered_at is not None:
        raise not_found("Open probe")
    likelihoods = p.discrimination["likelihoods"]
    if p.probe_type == "mcq":
        r = str(response.get("option_id", "")).lower()
        if r not in likelihoods:
            raise bad_request("Choose one of the options")
    else:
        v, _ = parse_number(response.get("value", response.get("text")))
        if v is None:
            raise bad_request("Enter a number")
        r = "correct" if numeric_match(v, p.expected_numeric or 0, float(p.discrimination.get("tolerance", 0.01)),
                                       "abs") else "incorrect"
    hs = s.hypotheses[0]
    before = dict(hs["distribution"])
    after = H.bayes(before, likelihoods[r])
    note = p.discrimination.get("notes", {}).get(r, "")
    p.response = response
    p.answered_at = _now()
    p.interpretation = {"response_key": r, "before": before, "after": after, "note": note}
    hs = {**hs, "distribution": after, "asked": [*hs["asked"], p.probe_key]}
    s.hypotheses = [hs, *s.hypotheses[1:]]
    md = definition(db, hs["misconception_key"])
    if md is not None:
        record_evidence(db, user_id=user.id, course_id=s.course_id, md=md, concept_id=s.concept_id,
                        kind="probe_response", summary=f"Probe '{p.prompt[:100]}' answered '{r}'. {note}",
                        set_posterior=after["misconception"], session_id=s.id, probe_id=p.id,
                        detail={"before": before, "after": after})
    _event(s, "probe_answer", probe_id=str(p.id), response=response, response_key=r, before=before, after=after,
           note=note)
    _next_probe_or_conclude(db, user, s)
    return s


def _conclude(db: Session, user: User, s: DiagnosticSession) -> None:
    hs = s.hypotheses[0]
    lead, pmax = H.leading(hs["distribution"])
    pm = hs["distribution"].get("misconception", 0.0)
    md = definition(db, hs["misconception_key"])
    h = get_hypothesis(db, user.id, s.course_id, md) if md else None
    status = h.status if h else H.status_for(pm, 1)
    _event(s, "conclusion", leading=lead, leading_label=hs["labels"].get(lead, lead), leading_p=round(pmax, 3),
           misconception_posterior=round(pm, 3), status=status,
           text=f"Most likely explanation: {hs['labels'].get(lead, lead)} (model probability {pmax:.2f}). "
           f"Misconception hypothesis status: {status}.")
    if pm >= H.SUSPECTED_P:
        s.outcome = f"misconception_{status}"
        _start_repair(db, user, s, misconception_key=hs["misconception_key"])
    elif lead in ("calculation_error", "misread_question"):
        s.outcome = lead
        q = db.get(Question, s.question_id)
        _event(s, "note", text="The evidence points away from the misconception. A focused practice item checks the "
               "method instead.")
        _start_practice(db, user, s, q, misconception_key=None)
    else:
        s.outcome = lead
        _start_repair(db, user, s, misconception_key=hs["misconception_key"] if pm >= H.REJECT_P else None)


# ---------------------------------------------------------------------------------------------


def _citations_for(db: Session, s: DiagnosticSession, query: str) -> list[dict[str, Any]]:
    res = retrieve(db, s.course_id, query, k=8)
    strong = [h for h in res.hits if (h.rerank_logit or -99) >= -2.0]
    # Prefer one strong unit per source file (PDF page, slide, lecture timestamp) for a multimodal repair.
    picked, seen_sources = [], set()
    for h in strong:
        if h.source.id in seen_sources:
            continue
        seen_sources.add(h.source.id)
        picked.append(h)
    for h in strong:
        if len(picked) >= 4:
            break
        if h not in picked:
            picked.append(h)
    return [build_citation(f"S{i + 1}", h.unit, h.source, focus_text=query, support=h.support)
            for i, h in enumerate(picked[:4])]


def _worked_example(q: Question, entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not q.template_key:
        return None
    params = {k: v for k, v in (q.params or {}).items() if k != "seed"}
    try:
        g = T.generate(q.template_key, int((q.params or {}).get("seed", 1)), params)
    except Exception:
        return None
    contrast = None
    if entry is not None:
        sig = next((x for x in g.signatures if x.get("misconception_key") == entry["key"]), None)
        if sig:
            contrast = {"misconception_answer": sig.get("value"), "label": sig.get("label")}
    return {"stem": g.stem, "steps": g.worked_steps, "answer": g.numeric_answer, "unit": g.unit, "contrast": contrast,
            "note": "Worked with the numbers from your original question."}


def _start_repair(db: Session, user: User, s: DiagnosticSession, *, misconception_key: str | None) -> None:
    entry = catalog_by_key().get(misconception_key) if misconception_key else None
    q = db.get(Question, s.question_id)
    concept = db.get(Concept, s.concept_id)
    query = entry["support_query"] if entry else f"{concept.name}. {concept.description or ''}"
    cites = _citations_for(db, s, query)
    md = definition(db, misconception_key) if misconception_key else None
    explanation = {
        "contrast": entry["repair"]["contrast"] if entry else (concept.description or ""),
        "key_rule": entry["repair"].get("key_rule") if entry else None,
        "provenance": "Instructor-reviewable catalogue explanation, checked against your course sources below."
        if entry else "Concept summary derived from your course sources.",
    }
    if llm.llm_available() and cites:
        try:
            explanation["generated"] = _llm_explanation(db, s, q, entry, cites, user)
        except (llm.LLMError, llm.LLMUnavailable, BudgetExceeded):
            explanation["generated"] = None
    worked = _worked_example(q, entry)
    iv = LearningIntervention(user_id=user.id, course_id=s.course_id, session_id=s.id, concept_id=s.concept_id,
                              misconception_id=md.id if md else None, kind="contrastive_explanation",
                              content={"explanation": explanation, "worked_example": worked}, citations=cites)
    db.add(iv)
    db.flush()
    s.stage = "repair"
    _event(s, "repair", intervention_id=str(iv.id), misconception_key=misconception_key)


def _llm_explanation(db: Session, s: DiagnosticSession, q: Question, entry: dict[str, Any] | None,
                     cites: list[dict[str, Any]], user: User) -> dict[str, Any] | None:
    src = "\n".join(f'<source id="{c["id"]}">{c["excerpt"]}</source>' for c in cites)
    data, info = llm.chat(
        [{"role": "system", "content": "You are a tutor repairing a specific misunderstanding. Use only the sources; "
          "cite them as [S1]. Be concise (<=120 words). " + llm.UNTRUSTED_NOTICE},
         {"role": "user", "content": f"{src}\nQuestion the learner got wrong: {q.stem}\nSuspected misunderstanding: "
          f"{entry['title'] if entry else 'unclear'}\nReturn JSON {{\"explanation\": str}}"}],
        operation="repair_explanation", prompt_version="repair-v1", course_id=s.course_id, user_id=user.id,
        max_tokens=350,
    )
    text = str((data or {}).get("explanation", ""))
    import re

    ids = {c["id"] for c in cites}
    used = set(re.findall(r"\[(S\d+)\]", text))
    if not used or not used <= ids:
        return None
    return {"text": text, "model": info.get("model")}


def continue_after_repair(db: Session, user: User, s: DiagnosticSession) -> DiagnosticSession:
    if s.stage != "repair":
        raise conflict(f"This session is in the '{s.stage}' stage", code="wrong_stage")
    q = db.get(Question, s.question_id)
    key = s.hypotheses[0]["misconception_key"] if s.hypotheses else None
    iv = db.scalar(select(LearningIntervention).where(LearningIntervention.session_id == s.id,
                                                      LearningIntervention.kind == "contrastive_explanation"))
    if iv:
        iv.completed_at = _now()
    _start_practice(db, user, s, q, misconception_key=key)
    return s


def _template_choice(db: Session, s: DiagnosticSession, keys: list[str], *, purpose: str, user: User,
                     exclude_families: set[str]) -> Question | None:
    avoid = _seen_hashes(db, user.id)
    for tk in keys:
        if tk not in T.TEMPLATES or T.TEMPLATES[tk].family in exclude_families:
            continue
        q = generate_template_question(db, s.course_id, tk, purpose=purpose, seed=random.randint(1, 10**9),
                                       avoid_hashes=avoid)
        if q is not None:
            return q
    return None


def _start_practice(db: Session, user: User, s: DiagnosticSession, orig: Question | None,
                    misconception_key: str | None) -> None:
    entry = catalog_by_key().get(misconception_key) if misconception_key else None
    keys = list((entry or {}).get("repair", {}).get("practice_templates", []))
    if not keys and orig is not None and orig.template_key:
        keys = [orig.template_key]
    q = _template_choice(db, s, keys, purpose="practice", user=user, exclude_families=set())
    if q is None:
        q = _bank_question(db, user.id, s.concept_id, misconception_key=misconception_key, exclude_families=set())
    if q is None:
        _event(s, "note", text="No further practice item is available; moving to the transfer check.")
        _start_transfer(db, user, s, orig, misconception_key)
        return
    s.practice_question_id = q.id
    s.stage = "practice"
    record_exposure(db, user.id, q.id)
    db.add(LearningIntervention(user_id=user.id, course_id=s.course_id, session_id=s.id, concept_id=s.concept_id,
                                kind="targeted_practice", question_id=q.id,
                                misconception_id=definition(db, misconception_key).id if misconception_key else None,
                                content={"template": q.template_key}))
    _event(s, "question", role="practice", question_id=str(q.id))
    db.flush()


def answer_practice(db: Session, user: User, s: DiagnosticSession, response: dict[str, Any], reasoning: str | None,
                    confidence: int | None) -> DiagnosticSession:
    if s.stage != "practice" or s.practice_question_id is None:
        raise conflict(f"This session is in the '{s.stage}' stage", code="wrong_stage")
    q = db.get(Question, s.practice_question_id)
    res = submit(db, user=user, course_id=s.course_id, question=q, response=response, reasoning=reasoning,
                 confidence=confidence, context="practice", session_id=s.id, mastery_source="practice",
                 hypothesis_evidence=False)
    _event(s, "answer", role="practice", question_id=str(q.id), attempt_id=str(res.attempt.id), response=response,
           reasoning=reasoning, feedback=res.feedback)
    n_practice = sum(1 for e in s.timeline if e["type"] == "answer" and e.get("role") == "practice")
    key = s.hypotheses[0]["misconception_key"] if s.hypotheses else None
    if not res.grade.is_correct and n_practice < MAX_PRACTICE:
        _event(s, "note", text="Not quite: review the worked solution above, then try one more practice item.")
        orig = db.get(Question, s.question_id)
        _start_practice(db, user, s, orig, key)
        return s
    _start_transfer(db, user, s, db.get(Question, s.question_id), key)
    return s


def _start_transfer(db: Session, user: User, s: DiagnosticSession, orig: Question | None,
                    misconception_key: str | None) -> None:
    entry = catalog_by_key().get(misconception_key) if misconception_key else None
    used_families = set()
    for qid in [s.question_id, s.practice_question_id]:
        qq = db.get(Question, qid) if qid else None
        if qq is not None:
            used_families.add(mastery.family_of(qq))
            if qq.template_key:
                used_families.add(T.TEMPLATES[qq.template_key].family)
    keys = list((entry or {}).get("repair", {}).get("transfer_templates", []))
    concept = db.get(Concept, s.concept_id)
    if not keys and concept and concept.catalog_key:
        keys = [t.key for t in T.templates_for_concept(concept.catalog_key)]
    random.shuffle(keys) if not entry else None
    q = _template_choice(db, s, keys, purpose="transfer", user=user, exclude_families=used_families)
    if q is None:
        q = _bank_question(db, user.id, s.concept_id, misconception_key=misconception_key,
                           exclude_families=used_families)
    if q is None:
        s.stage = "completed"
        s.completed_at = _now()
        _event(s, "note", text="No unseen transfer problem is available for this concept yet.")
        return
    s.transfer_question_id = q.id
    s.stage = "transfer"
    record_exposure(db, user.id, q.id)
    db.add(LearningIntervention(user_id=user.id, course_id=s.course_id, session_id=s.id, concept_id=s.concept_id,
                                kind="transfer_test", question_id=q.id,
                                misconception_id=definition(db, misconception_key).id if misconception_key else None,
                                content={"template": q.template_key, "excluded_families": sorted(used_families)}))
    _event(s, "question", role="transfer", question_id=str(q.id),
           note="A structurally different problem (different question family, context and numbers).")
    db.flush()


def answer_transfer(db: Session, user: User, s: DiagnosticSession, response: dict[str, Any], reasoning: str | None,
                    confidence: int | None) -> DiagnosticSession:
    if s.stage != "transfer" or s.transfer_question_id is None:
        raise conflict(f"This session is in the '{s.stage}' stage", code="wrong_stage")
    q = db.get(Question, s.transfer_question_id)
    res = submit(db, user=user, course_id=s.course_id, question=q, response=response, reasoning=reasoning,
                 confidence=confidence, context="transfer", session_id=s.id, mastery_source="transfer",
                 hypothesis_evidence=False)
    _event(s, "answer", role="transfer", question_id=str(q.id), attempt_id=str(res.attempt.id), response=response,
           reasoning=reasoning, feedback=res.feedback)
    key = s.hypotheses[0]["misconception_key"] if s.hypotheses else None
    md = definition(db, key) if key else None
    h = get_hypothesis(db, user.id, s.course_id, md) if md else None
    if md is not None and h is not None and h.status != "rejected":
        if res.grade.is_correct:
            h2, _ = record_evidence(db, user_id=user.id, course_id=s.course_id, md=md, concept_id=s.concept_id,
                                    kind="transfer_success", summary="Solved a structurally different transfer problem "
                                    "after the repair.", likelihood_ratio=TRANSFER_SUCCESS_LR, session_id=s.id,
                                    attempt_id=res.attempt.id, status_override="resolving")
            h2.revisit_at = _now() + REVISIT_AFTER
        else:
            record_evidence(db, user_id=user.id, course_id=s.course_id, md=md, concept_id=s.concept_id,
                            kind="transfer_failure", summary="Transfer problem answered incorrectly after the repair.",
                            likelihood_ratio=TRANSFER_FAILURE_LR, session_id=s.id, attempt_id=res.attempt.id)
    s.stage = "completed"
    s.completed_at = _now()
    _event(s, "complete", transfer_correct=res.grade.is_correct)
    return s


# ---------------------------------------------------------------------------------------------


def view(db: Session, s: DiagnosticSession) -> dict[str, Any]:
    qids = {uuid.UUID(e["question_id"]) for e in s.timeline if e.get("question_id")}
    qs = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(qids)))} if qids else {}
    probes = {p.id: p for p in db.scalars(select(DiagnosticProbe).where(DiagnosticProbe.session_id == s.id))}
    ivs = list(db.scalars(select(LearningIntervention).where(LearningIntervention.session_id == s.id)
                          .order_by(LearningIntervention.created_at)))
    concept = db.get(Concept, s.concept_id)
    timeline = []
    for e in s.timeline:
        e2 = dict(e)
        if e.get("question_id") and e["type"] == "question":
            q = qs.get(uuid.UUID(e["question_id"]))
            if q:
                e2["question"] = public_question(q)
        if e["type"] == "probe":
            p = probes.get(uuid.UUID(e["probe_id"]))
            if p:
                e2["probe"] = {"id": str(p.id), "key": p.probe_key, "type": p.probe_type, "prompt": p.prompt,
                               "options": p.options, "answered": p.answered_at is not None,
                               "eig_bits": p.discrimination.get("expected_information_gain_bits")}
        if e["type"] == "repair":
            iv = next((i for i in ivs if str(i.id) == e.get("intervention_id")), None)
            if iv:
                e2["intervention"] = {"id": str(iv.id), "content": iv.content, "citations": iv.citations}
        timeline.append(e2)
    pending: dict[str, Any] | None = None
    if s.stage == "answer":
        pending = {"type": "answer_question", "question": public_question(qs[s.question_id])}
    elif s.stage == "probing":
        open_p = next((p for p in sorted(probes.values(), key=lambda p: p.created_at) if p.answered_at is None), None)
        if open_p:
            pending = {"type": "answer_probe", "probe": {"id": str(open_p.id), "prompt": open_p.prompt,
                                                         "type": open_p.probe_type, "options": open_p.options}}
    elif s.stage == "repair":
        pending = {"type": "continue_repair"}
    elif s.stage == "practice" and s.practice_question_id:
        pending = {"type": "answer_practice", "question": public_question(db.get(Question, s.practice_question_id))}
    elif s.stage == "transfer" and s.transfer_question_id:
        pending = {"type": "answer_transfer", "question": public_question(db.get(Question, s.transfer_question_id))}
    md_key = s.hypotheses[0]["misconception_key"] if s.hypotheses else None
    hyp = None
    if md_key:
        md = definition(db, md_key)
        h = get_hypothesis(db, s.user_id, s.course_id, md) if md else None
        if h:
            hyp = {"misconception_key": md_key, "title": md.title, "status": h.status, "posterior": h.posterior,
                   "evidence_count": h.evidence_count, "revisit_at": h.revisit_at.isoformat() if h.revisit_at else None,
                   "description": md.description,
                   "competing": catalog_by_key()[md_key].get("competing_interpretations", [])}
    hist = list(db.execute(
        select(QuestionAttempt.id).where(QuestionAttempt.diagnostic_session_id == s.id)).all())
    from app.models import MasteryHistory

    mh = list(db.scalars(select(MasteryHistory).where(MasteryHistory.attempt_id.in_([h[0] for h in hist]))
                         .order_by(MasteryHistory.created_at))) if hist else []
    mastery_change = None
    if mh:
        mastery_change = {"concept": concept.name if concept else None, "before": round(mh[0].p_before, 4),
                          "after": round(mh[-1].p_after, 4),
                          "steps": [{"source": m.source, "correct": m.observed_correct, "weight": m.evidence_weight,
                                     "p_after": round(m.p_after, 4)} for m in mh]}
    scenario = None
    if s.is_demo_script:
        sc = DEMO_SCENARIO["contribution_price_cut"]
        # After the repair the scripted learner answers practice/transfer items correctly, so a recorded demo can
        # show the full loop. Only demo-script sessions expose this; it is shown in the UI as a scripted response.
        followup = None
        pq = db.get(Question, s.practice_question_id) if s.stage == "practice" and s.practice_question_id else None
        tq = db.get(Question, s.transfer_question_id) if s.stage == "transfer" and s.transfer_question_id else None
        fq = pq or tq
        if fq is not None and fq.question_type in ("numerical", "mcq"):
            followup = ({"value": f"{fq.numeric_answer:g}"} if fq.question_type == "numerical"
                        else {"option_id": fq.correct_option_id})
            followup["reasoning"] = ("Kept contribution, not revenue, constant: compared contribution per unit "
                                     "before and after the change.")
        scenario = {"key": "contribution_price_cut", "scripted_answer": sc["scripted_answer"],
                    "scripted_reasoning": sc["scripted_reasoning"], "scripted_confidence": sc["scripted_confidence"],
                    "scripted_probe_answers": sc["scripted_probe_answers"], "scripted_followup": followup,
                    "label": "Scripted demonstration learner: responses are pre-written, all grading, probing, "
                    "retrieval and mastery updates are computed live."}
    return {
        "id": str(s.id), "course_id": str(s.course_id), "concept": {"id": str(s.concept_id),
                                                                   "name": concept.name if concept else None},
        "stage": s.stage, "outcome": s.outcome, "is_demo_script": s.is_demo_script, "scenario": scenario,
        "hypotheses": s.hypotheses, "hypothesis": hyp, "timeline": timeline, "pending": pending,
        "mastery_change": mastery_change, "created_at": s.created_at.isoformat(),
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
    }


def get_session(db: Session, user: User, session_id: uuid.UUID) -> DiagnosticSession:
    s = db.get(DiagnosticSession, session_id)
    if s is None or s.user_id != user.id:
        raise APIError(404, "not_found", "Diagnostic session not found")
    return s
