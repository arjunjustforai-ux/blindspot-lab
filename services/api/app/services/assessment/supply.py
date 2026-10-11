"""Question supply: templates, instructor banks, extractive generation and (optionally) LLM generation.

Every candidate passes `verification.verify` before being stored as `verified`;
rejected candidates are stored too (status `rejected`) so assessment-quality
evaluation can inspect them, but they are never shown to learners.
"""

from __future__ import annotations

import json
import logging
import random
import re
import uuid
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.models import Concept, ConceptSource, ContentUnit, Course, Question, QuestionSource
from app.services.ai import llm
from app.services.ai.embeddings import get_embedder
from app.services.ai.oplog import BudgetExceeded
from app.services.ai.text import content_terms, normalize_ws, split_sentences
from app.services.assessment import templates as T
from app.services.assessment.verification import QuestionDraft, verify

log = logging.getLogger(__name__)
POOL_SEEDS = (11, 23, 37)
GEN_PROMPT_VERSION = "generate-questions-v1"


def draft_from_template(g: T.Generated, concept_id: uuid.UUID, *, seed: int, purpose: str = "assessment") -> QuestionDraft:
    return QuestionDraft(
        concept_id=concept_id, question_type=g.question_type, difficulty=g.difficulty, stem=g.stem,
        explanation=g.explanation, origin="template", options=g.options, correct_option_id=g.correct_option_id,
        numeric_answer=g.numeric_answer, numeric_tolerance=g.tolerance, tolerance_mode=g.tolerance_mode,
        answer_unit=g.unit, assumptions=g.assumptions, misconception_signatures=g.signatures,
        template_key=g.template_key, family_key=g.family, params={**g.params, "seed": seed}, purpose=purpose,
        source_query=g.source_query,
        generation_meta={"worked_steps": g.worked_steps, "subconcept_key": g.subconcept_key, "seed": seed,
                         "source_query": g.source_query, "generator": "parametric-template"},
    )


def persist(db: Session, course_id: uuid.UUID, d: QuestionDraft, *, existing_embeddings=None,
            check_duplicates: bool = True) -> Question | None:
    out = verify(db, course_id, d, existing_embeddings=existing_embeddings, check_duplicates=check_duplicates)
    if out.status == "rejected" and any(c["check"] == "duplicate_exact" and c["passed"] is False
                                        for c in out.report["checks"]):
        return None  # already stored
    emb = out.report.pop("_embedding", None) or get_embedder().embed_query(d.stem)
    q = Question(
        course_id=course_id, concept_id=d.concept_id, question_type=d.question_type, difficulty=d.difficulty,
        stem=d.stem, options=d.options, correct_option_id=d.correct_option_id, numeric_answer=d.numeric_answer,
        numeric_tolerance=d.numeric_tolerance, tolerance_mode=d.tolerance_mode, answer_unit=d.answer_unit,
        rubric=d.rubric, explanation=d.explanation, assumptions=d.assumptions,
        misconception_signatures=d.misconception_signatures, origin=d.origin, template_key=d.template_key,
        family_key=d.family_key, params=d.params, content_hash=d.hash(), embedding=emb,
        verification_status=out.status, verification_report=out.report,
        generation_meta={**d.generation_meta, "source_anchors": d.source_anchors, "source_query": d.source_query},
        purpose=d.purpose,
    )
    db.add(q)
    db.flush()
    for u, sc in out.source_units:
        db.add(QuestionSource(question_id=q.id, content_unit_id=u.id, support_score=round(float(sc), 4)))
    db.flush()
    if existing_embeddings is not None:
        existing_embeddings.append((q.id, np.array(emb, dtype=np.float32), q.template_key, q.numeric_answer))
    return q


def _existing_embeddings(db: Session, course_id: uuid.UUID) -> list[tuple[uuid.UUID, np.ndarray, str | None, float | None]]:
    rows = db.execute(select(Question.id, Question.embedding, Question.template_key, Question.numeric_answer)
                      .where(Question.course_id == course_id, Question.embedding.is_not(None))).all()
    return [(r[0], np.array(r[1], dtype=np.float32), r[2], r[3]) for r in rows]


def generate_template_question(
    db: Session, course_id: uuid.UUID, template_key: str, *, purpose: str, seed: int | None = None,
    overrides: dict[str, Any] | None = None, avoid_hashes: set[str] | None = None,
) -> Question | None:
    """On-demand generation (practice/transfer/adaptive top-up). Returns a verified question or None."""
    tpl = T.TEMPLATES[template_key]
    concept = db.scalar(select(Concept).where(Concept.course_id == course_id, Concept.catalog_key == tpl.concept_key,
                                              Concept.kind == "concept"))
    if concept is None:
        return None
    rng = random.Random(seed)
    for _ in range(6):
        s = rng.randint(1000, 10_000_000)
        g = T.generate(template_key, s, overrides)
        d = draft_from_template(g, concept.id, seed=s, purpose=purpose)
        if avoid_hashes and d.hash() in avoid_hashes:
            continue
        q = persist(db, course_id, d)
        if q is not None and q.verification_status == "verified":
            return q
        if overrides:  # fixed parameters: retrying with another seed would not change the stem
            existing = db.scalar(select(Question).where(Question.course_id == course_id,
                                                        Question.content_hash == d.hash()))
            if existing is not None and existing.verification_status == "verified":
                return existing
            return None
    return None


def ensure_question_pool(db: Session, course_id: uuid.UUID) -> dict[str, Any]:
    stats = {"template_verified": 0, "template_rejected": 0, "extractive_verified": 0, "extractive_rejected": 0,
             "llm_verified": 0, "llm_rejected": 0, "resourced": 0, "bank_verified": 0, "bank_rejected": 0}
    _reattach_sources(db, course_id, stats)
    embs = _existing_embeddings(db, course_id)
    concepts = list(db.scalars(select(Concept).where(Concept.course_id == course_id, Concept.kind == "concept",
                                                     Concept.review_status != "rejected")))
    have = {(q.template_key, (q.params or {}).get("seed")) for q in db.scalars(
        select(Question).where(Question.course_id == course_id, Question.origin == "template"))}
    for c in concepts:
        if not c.catalog_key:
            continue
        for tpl in T.templates_for_concept(c.catalog_key):
            for seed in POOL_SEEDS:
                if (tpl.key, seed) in have:
                    continue
                d = draft_from_template(T.generate(tpl.key, seed), c.id, seed=seed)
                q = persist(db, course_id, d, existing_embeddings=embs)
                if q is not None:
                    stats["template_verified" if q.verification_status == "verified" else "template_rejected"] += 1
    course = db.get(Course, course_id)
    bank_path = REPO_ROOT / "demo" / "course-materials" / "question_bank.json"
    if course is not None and course.is_demo and bank_path.exists():
        r = import_question_bank(db, course_id, json.loads(bank_path.read_text()), existing_embeddings=embs)
        stats["bank_verified"] += r["verified"]
        stats["bank_rejected"] += r["rejected"]
    for c in concepts:
        n_ok = db.scalar(select(func.count(Question.id)).where(Question.concept_id == c.id,
                                                              Question.verification_status == "verified")) or 0
        if n_ok < 4:
            v, r = _extractive_questions(db, course_id, c, embs)
            stats["extractive_verified"] += v
            stats["extractive_rejected"] += r
        if llm.llm_available() and n_ok < 8:
            v, r = _llm_questions(db, course_id, c, embs)
            stats["llm_verified"] += v
            stats["llm_rejected"] += r
    db.flush()
    return stats


def _reattach_sources(db: Session, course_id: uuid.UUID, stats: dict[str, Any]) -> None:
    """After a reindex, unit ids change; re-resolve sources for questions that lost them."""
    from app.services.assessment.verification import find_anchor_units
    from app.services.retrieval.hybrid import retrieve

    orphan = list(db.scalars(
        select(Question).where(Question.course_id == course_id, ~Question.id.in_(select(QuestionSource.question_id)))
    ))
    for q in orphan:
        meta = q.generation_meta or {}
        units: list[tuple[ContentUnit, float]] = []
        if meta.get("source_anchors"):
            units = [(u, 1.0) for u in find_anchor_units(db, course_id, meta["source_anchors"])]
        elif meta.get("source_query"):
            res = retrieve(db, course_id, meta["source_query"], k=2)
            units = [(h.unit, h.support) for h in res.hits if (h.rerank_logit or -99) >= -4.0]
        for u, sc in units:
            db.add(QuestionSource(question_id=q.id, content_unit_id=u.id, support_score=sc))
        if not units and q.verification_status == "verified":
            q.verification_status = "rejected"
            q.verification_report = {**(q.verification_report or {}),
                                     "revoked": "source support no longer found after reindex"}
        stats["resourced"] += 1
    db.flush()


def import_question_bank(db: Session, course_id: uuid.UUID, bank: dict[str, Any], *,
                         existing_embeddings=None) -> dict[str, int]:
    concepts = {c.catalog_key: c for c in db.scalars(select(Concept).where(Concept.course_id == course_id))
                if c.catalog_key}
    have_keys: set[str] = set()
    removed: set[uuid.UUID] = set()
    for q in db.scalars(select(Question).where(Question.course_id == course_id, Question.origin == "bank")):
        if q.verification_status == "rejected":
            removed.add(q.id)
            db.delete(q)  # re-verify rejected items on every import (rules or sources may have changed)
        else:
            have_keys.add((q.generation_meta or {}).get("bank_key"))
    db.flush()
    if existing_embeddings is not None and removed:
        existing_embeddings[:] = [e for e in existing_embeddings if e[0] not in removed]
    out = {"verified": 0, "rejected": 0, "skipped": 0}
    for item in bank.get("items", []):
        if item["key"] in have_keys:
            out["skipped"] += 1
            continue
        c = concepts.get(item["concept_key"])
        if c is None:
            out["skipped"] += 1
            continue
        d = QuestionDraft(
            concept_id=c.id, question_type=item["type"], difficulty=int(item["difficulty"]), stem=item["stem"],
            explanation=item["explanation"], origin="bank", options=item.get("options", []),
            correct_option_id=item.get("correct_option_id"), numeric_answer=item.get("numeric_answer"),
            numeric_tolerance=item.get("tolerance"), tolerance_mode=item.get("tolerance_mode", "abs"),
            answer_unit=item.get("unit"), rubric=item.get("rubric", {}), assumptions=item.get("assumptions"),
            misconception_signatures=item.get("misconception_signatures", []), family_key=item.get("family"),
            purpose=item.get("purpose", "assessment"), source_anchors=item.get("source_anchors", []),
            generation_meta={"bank_key": item["key"], "bank_version": bank.get("version"), "author": bank.get("author"),
                             "tags": item.get("tags", [])},
        )
        q = persist(db, course_id, d, existing_embeddings=existing_embeddings)
        if q is None:
            out["skipped"] += 1
        else:
            out["verified" if q.verification_status == "verified" else "rejected"] += 1
    db.flush()
    return out


DEF_RE = re.compile(
    r"^(?:the |a |an )?(?P<term>[a-z][a-z0-9 \-/()]{2,60}?)\s+(?:is|are|refers to|means|measures|describes)\s+"
    r"(?P<def>.{25,260})$", re.IGNORECASE,
)


def _definitions(db: Session, course_id: uuid.UUID) -> dict[uuid.UUID, list[tuple[str, str, ContentUnit]]]:
    out: dict[uuid.UUID, list[tuple[str, str, ContentUnit]]] = {}
    rows = db.execute(
        select(ConceptSource.concept_id, ContentUnit)
        .join(ContentUnit, ContentUnit.id == ConceptSource.content_unit_id)
        .where(ContentUnit.course_id == course_id, ConceptSource.is_primary.is_(True),
               ContentUnit.is_generated.is_(False),
               ContentUnit.modality.in_(["pdf_text", "slide_text", "slide_notes", "transcript", "pdf_ocr"]))
    ).all()
    for cid, u in rows:
        for s in split_sentences(u.content.replace("\n", " ")):
            m = DEF_RE.match(s.rstrip("."))
            if m and len(m.group("term").split()) <= 7:
                out.setdefault(cid, []).append((m.group("term").strip(), m.group("def").strip().rstrip("."), u))
    return out


def _extractive_questions(db: Session, course_id: uuid.UUID, concept: Concept, embs) -> tuple[int, int]:
    """Definition-based MCQ + short answer quoted from the sources (generic, no LLM)."""
    defs = _definitions(db, course_id)
    mine = defs.get(concept.id, [])
    others = [(t, d) for cid, lst in defs.items() if cid != concept.id for t, d, _ in lst]
    v = r = 0
    rng = random.Random(str(concept.id))
    for term, definition, unit in mine[:2]:
        distractors = [d for t, d in others if t.lower() != term.lower() and term.lower() not in d.lower()]
        rng.shuffle(distractors)
        if len(distractors) >= 3:
            opts_text = [definition] + distractors[:3]
            order = list(range(4))
            rng.shuffle(order)
            ids = "abcd"
            options = [{"id": ids[i], "text": normalize_ws(opts_text[j])[:240]} for i, j in enumerate(order)]
            correct = ids[order.index(0)]
            d = QuestionDraft(
                concept_id=concept.id, question_type="mcq", difficulty=1,
                stem=f"According to the course materials, which statement best describes {term}?",
                explanation=f"The source states that {term} {definition}.", origin="extractive", options=options,
                correct_option_id=correct, source_unit_ids=[str(unit.id)],
                generation_meta={"generator": "extractive-definition", "term": term},
            )
            q = persist(db, course_id, d, existing_embeddings=embs)
            if q is not None:
                v, r = (v + 1, r) if q.verification_status == "verified" else (v, r + 1)
        key_terms = list(dict.fromkeys(content_terms(definition)))[:4]
        if len(key_terms) >= 2:
            d = QuestionDraft(
                concept_id=concept.id, question_type="short_answer", difficulty=2,
                stem=f"In your own words, explain {term} as it is described in the course materials.",
                explanation=f"The source states that {term} {definition}.", origin="extractive",
                rubric={"key_points": [{"id": "k1", "text": f"{term} {definition}", "weight": 1.0,
                                        "keyword_groups": [[k] for k in key_terms]}],
                        "pass_threshold": 0.6, "auto_extracted": True},
                source_unit_ids=[str(unit.id)], generation_meta={"generator": "extractive-definition", "term": term},
            )
            q = persist(db, course_id, d, existing_embeddings=embs)
            if q is not None:
                v, r = (v + 1, r) if q.verification_status == "verified" else (v, r + 1)
    return v, r


def _llm_questions(db: Session, course_id: uuid.UUID, concept: Concept, embs) -> tuple[int, int]:
    from app.services.retrieval.hybrid import retrieve

    res = retrieve(db, course_id, f"{concept.name}. {concept.description or ''}", k=4)
    if not res.hits:
        return 0, 0
    src = "\n".join(f"<source id=\"U{i + 1}\">{h.unit.content[:900]}</source>" for i, h in enumerate(res.hits))
    try:
        data, info = llm.chat(
            [
                {"role": "system", "content": "You write rigorous assessment questions strictly grounded in the "
                 "provided course sources. " + llm.UNTRUSTED_NOTICE},
                {"role": "user", "content": f"{src}\nConcept: {concept.name}\nWrite 3 questions: one MCQ (4 options, "
                 "one defensible answer, plausible distractors reflecting common misconceptions), one short-answer "
                 "with a 2-3 point rubric, and one applied scenario MCQ. Return JSON {\"questions\": [{\"type\": "
                 "\"mcq\"|\"short_answer\", \"difficulty\": 1-3, \"stem\": str, \"options\": [{\"id\": \"a\", "
                 "\"text\": str}], \"correct_option_id\": str, \"rubric\": {\"key_points\": [{\"id\": str, \"text\": "
                 "str, \"keywords\": [str]}]}, \"explanation\": str, \"source_ids\": [\"U1\"]}]}"},
            ],
            operation="generate_questions", prompt_version=GEN_PROMPT_VERSION, course_id=course_id, max_tokens=1400,
        )
    except (llm.LLMError, llm.LLMUnavailable, BudgetExceeded) as e:
        log.warning("LLM question generation failed: %s", e)
        return 0, 0
    v = r = 0
    for item in (data or {}).get("questions", [])[:3]:
        try:
            ids = [res.hits[int(str(s).lstrip("U")) - 1].unit.id for s in item.get("source_ids", [])
                   if str(s).lstrip("U").isdigit() and 0 < int(str(s).lstrip("U")) <= len(res.hits)]
            d = QuestionDraft(
                concept_id=concept.id, question_type=item["type"], difficulty=int(item.get("difficulty", 2)),
                stem=str(item["stem"]), explanation=str(item.get("explanation", "")), origin="llm",
                options=item.get("options", []) if item["type"] == "mcq" else [],
                correct_option_id=item.get("correct_option_id"), rubric=item.get("rubric", {}),
                source_unit_ids=[str(i) for i in ids],
                generation_meta={"generator": "llm", "model": info.get("model"), "prompt_version": GEN_PROMPT_VERSION},
            )
        except (KeyError, ValueError, TypeError):
            r += 1
            continue
        q = persist(db, course_id, d, existing_embeddings=embs)
        if q is not None:
            v, r = (v + 1, r) if q.verification_status == "verified" else (v, r + 1)
    return v, r
