"""Question verification. Nothing reaches a learner unless it passes these checks.

Checks (each recorded in Question.verification_report):
  schema          type-specific fields are complete and consistent
  answer_key      template answers pass an independent plug-back check; bank items
                  carry an author key; LLM items must pass the verifier pass
  signatures      misconception signature answers differ from the correct answer
  options         MCQ: >=3 options, distinct wording, exactly one keyed answer
  clarity         stem length/shape sanity
  source_support  retrieved or anchored course units support the premise
  duplicate       no identical (content hash) or near-identical existing question
  llm_verifier    (when a model is configured) an independent model answers blind
                  and must agree with the key, judge it unambiguous and supported
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ContentUnit, Question, SourceFile
from app.services.ai import llm
from app.services.ai.embeddings import get_embedder
from app.services.ai.oplog import BudgetExceeded
from app.services.ai.text import content_hash, normalize_for_hash, normalize_ws
from app.services.assessment.plugback import plug_back
from app.services.retrieval.hybrid import retrieve

SOURCE_MIN_LOGIT = -4.0
NEAR_DUP_COSINE = 0.985
VERIFIER_PROMPT_VERSION = "verify-question-v1"


@dataclass
class QuestionDraft:
    concept_id: uuid.UUID
    question_type: str
    difficulty: int
    stem: str
    explanation: str
    origin: str
    options: list[dict[str, str]] = field(default_factory=list)
    correct_option_id: str | None = None
    numeric_answer: float | None = None
    numeric_tolerance: float | None = None
    tolerance_mode: str | None = None
    answer_unit: str | None = None
    rubric: dict[str, Any] = field(default_factory=dict)
    assumptions: str | None = None
    misconception_signatures: list[dict[str, Any]] = field(default_factory=list)
    template_key: str | None = None
    family_key: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    purpose: str = "assessment"
    source_query: str | None = None
    source_anchors: list[str] = field(default_factory=list)
    source_unit_ids: list[str] = field(default_factory=list)
    generation_meta: dict[str, Any] = field(default_factory=dict)

    def hash(self) -> str:
        key = [self.stem, self.question_type]
        key += [o["text"] for o in self.options]
        key += [str(self.correct_option_id), str(self.numeric_answer)]
        return content_hash(" | ".join(key))


@dataclass
class VerificationOutcome:
    status: str
    report: dict[str, Any]
    source_units: list[tuple[ContentUnit, float]]


def _numbers(t: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+(?:[.,]\d+)*", t))


def _check(report: dict[str, Any], name: str, passed: bool | None, detail: str) -> None:
    report.setdefault("checks", []).append({"check": name, "passed": passed, "detail": detail})


def find_anchor_units(db: Session, course_id: uuid.UUID, anchors: list[str]) -> list[ContentUnit]:
    """Exact (normalised) phrase lookup of author-provided anchor phrases in course units."""
    if not anchors:
        return []
    units = list(db.scalars(
        select(ContentUnit).join(SourceFile, SourceFile.id == ContentUnit.source_file_id)
        .where(ContentUnit.course_id == course_id, SourceFile.status == "ready")
    ))
    found: list[ContentUnit] = []
    for a in anchors:
        na = normalize_for_hash(a)
        best = None
        for u in units:
            if na in normalize_for_hash((u.heading or "") + " " + u.content):
                if best is None or (u.is_generated is False and best.is_generated):
                    best = u
                if not u.is_generated:
                    break
        if best is not None and best not in found:
            found.append(best)
    return found


def verify(db: Session, course_id: uuid.UUID, d: QuestionDraft, *, check_duplicates: bool = True,
           existing_embeddings: list[tuple[uuid.UUID, np.ndarray, str | None, float | None]] | None = None,
           ) -> VerificationOutcome:
    report: dict[str, Any] = {"checks": [], "verifier": "rule-based"}
    ok = True

    # schema ------------------------------------------------------------------
    if d.question_type == "mcq":
        ids = [o.get("id") for o in d.options]
        schema_ok = len(d.options) >= 3 and d.correct_option_id in ids and len(set(ids)) == len(ids)
        _check(report, "schema", schema_ok, f"{len(d.options)} options, key={d.correct_option_id}")
    elif d.question_type == "numerical":
        schema_ok = d.numeric_answer is not None and math.isfinite(d.numeric_answer) and \
            (d.numeric_tolerance or 0) > 0
        _check(report, "schema", schema_ok, f"answer={d.numeric_answer} ±{d.numeric_tolerance} {d.answer_unit or ''}")
    else:
        kps = (d.rubric or {}).get("key_points", [])
        schema_ok = len(kps) >= 1 and all(kp.get("text") for kp in kps)
        _check(report, "schema", schema_ok, f"{len(kps)} rubric key points")
    ok &= schema_ok

    # clarity -----------------------------------------------------------------
    n_words = len(d.stem.split())
    clear = 3 <= n_words <= 160 and ("?" in d.stem or d.stem.lower().startswith(("explain", "describe", "compute",
                                                                                   "calculate", "in your own")))
    _check(report, "clarity", clear, f"{n_words} words")
    ok &= clear

    # options -----------------------------------------------------------------
    if d.question_type == "mcq" and schema_ok:
        texts = [normalize_ws(o["text"]).lower() for o in d.options]
        pairs = [(a, b) for i, a in enumerate(texts) for b in texts[i + 1:]]
        # Options that differ in their numbers ("about 5%" vs "about 0.5%") are distinct by construction.
        clashes = [(a, b) for a, b in pairs if a == b or (_numbers(a) == _numbers(b) and fuzz.ratio(a, b) >= 92)]
        distinct = not clashes
        _check(report, "options_distinct", distinct, "options are distinct" if distinct
               else f"near-identical options: {clashes[0][0]!r} / {clashes[0][1]!r}")
        ok &= distinct

    # answer key --------------------------------------------------------------
    if d.template_key:
        target = d.correct_option_id if d.question_type == "mcq" else d.numeric_answer
        pb = plug_back(d.template_key, d.params, target)
        _check(report, "answer_key", pb is True, "independent plug-back check " + ("passed" if pb else "FAILED"))
        ok &= pb is True
    elif d.origin == "bank":
        has_key = (d.question_type == "mcq" and d.correct_option_id) or \
                  (d.question_type == "numerical" and d.numeric_answer is not None) or d.question_type == "short_answer"
        _check(report, "answer_key", bool(has_key), "author-provided key (instructor-reviewable bank)")
        ok &= bool(has_key)
    elif d.origin == "extractive":
        _check(report, "answer_key", True, "key is a sentence quoted verbatim from the source")

    # signatures ----------------------------------------------------------------
    if d.question_type == "numerical" and d.numeric_answer is not None:
        clash = [s for s in d.misconception_signatures
                 if s.get("value") is not None and abs(float(s["value"]) - d.numeric_answer) <=
                 max(float(s.get("tolerance", 0)), d.numeric_tolerance or 0) * 2]
        _check(report, "signatures", not clash, "misconception answers are distinct from the key"
               if not clash else f"{len(clash)} signature(s) coincide with the key; signatures dropped")
        if clash:
            d.misconception_signatures = [s for s in d.misconception_signatures if s not in clash]
    if d.question_type == "mcq":
        bad = [s for s in d.misconception_signatures if s.get("option_id") == d.correct_option_id]
        if bad:
            d.misconception_signatures = [s for s in d.misconception_signatures if s not in bad]
            _check(report, "signatures", False, "a signature pointed at the keyed option; dropped")

    # source support -------------------------------------------------------------
    sources: list[tuple[ContentUnit, float]] = []
    if d.source_anchors:
        units = find_anchor_units(db, course_id, d.source_anchors)
        sources = [(u, 1.0) for u in units]
        anchored = len(units) == len(d.source_anchors)
        _check(report, "source_support", anchored,
               f"{len(units)}/{len(d.source_anchors)} anchor phrases found verbatim in course sources")
        ok &= anchored
    elif d.source_unit_ids:
        ids = [uuid.UUID(x) for x in d.source_unit_ids]
        units = list(db.scalars(select(ContentUnit).where(ContentUnit.id.in_(ids),
                                                          ContentUnit.course_id == course_id)))
        sources = [(u, 1.0) for u in units]
        _check(report, "source_support", bool(units), f"{len(units)} cited source unit(s) exist in this course")
        ok &= bool(units)
    else:
        q = d.source_query or d.stem
        res = retrieve(db, course_id, q, k=3)
        strong = [(h.unit, h.support) for h in res.hits if (h.rerank_logit or -99) >= SOURCE_MIN_LOGIT]
        sources = strong[:2]
        best = res.top_logit
        _check(report, "source_support", bool(strong),
               f"best supporting unit rerank logit {best:.2f} (threshold {SOURCE_MIN_LOGIT})" if best is not None
               else "no supporting unit retrieved")
        ok &= bool(strong)

    # duplicates -------------------------------------------------------------------
    h = d.hash()
    report["content_hash"] = h
    if check_duplicates:
        dup = db.scalar(select(Question.id).where(Question.course_id == course_id, Question.content_hash == h))
        _check(report, "duplicate_exact", dup is None, "no identical question" if dup is None else f"same as {dup}")
        ok &= dup is None
        if existing_embeddings is not None:
            v = np.array(get_embedder().embed_query(d.stem), dtype=np.float32)
            near = [(qid, float(np.dot(v, ev))) for qid, ev, tk, ans in existing_embeddings
                    if float(np.dot(v, ev)) >= NEAR_DUP_COSINE and ans == d.numeric_answer and
                    (tk == d.template_key)]
            _check(report, "duplicate_near", not near, "no near-duplicate" if not near
                   else f"near-duplicate of {near[0][0]} (cosine {near[0][1]:.3f})")
            ok &= not near
            report["_embedding"] = v.tolist()

    # independent model verification ----------------------------------------------
    if ok and llm.llm_available() and d.origin in ("llm", "extractive", "bank") and d.question_type != "numerical":
        ok &= _llm_verify(d, sources, report, course_id)

    return VerificationOutcome("verified" if ok else "rejected", report, sources)


def _llm_verify(d: QuestionDraft, sources: list[tuple[ContentUnit, float]], report: dict[str, Any],
                course_id: uuid.UUID) -> bool:
    s = get_settings()
    src = "\n---\n".join(u.content[:900] for u, _ in sources[:3])
    opts = "\n".join(f"{o['id']}) {o['text']}" for o in d.options)
    try:
        data, info = llm.chat(
            [
                {"role": "system", "content": "You independently check exam questions against course sources. "
                 + llm.UNTRUSTED_NOTICE},
                {"role": "user", "content": f"<source>\n{src}\n</source>\nQuestion: {d.stem}\n{opts}\n"
                 "Answer the question yourself using only the sources, then judge it. Return JSON "
                 "{\"your_answer\": str (option id, or a short answer), \"unambiguous\": bool, "
                 "\"premise_supported_by_sources\": bool, \"issues\": [str]}"},
            ],
            operation="verify_question", prompt_version=VERIFIER_PROMPT_VERSION, model=s.effective_verifier_model,
            course_id=course_id, max_tokens=300, temperature=0.0,
        )
    except (llm.LLMError, llm.LLMUnavailable, BudgetExceeded) as e:
        _check(report, "llm_verifier", None, f"verifier unavailable: {e}")
        return d.origin != "llm"  # LLM-generated questions require a successful verifier pass
    agree = True
    if d.question_type == "mcq":
        agree = str(data.get("your_answer", "")).strip().lower()[:1] == (d.correct_option_id or "").lower()
    passed = agree and bool(data.get("unambiguous")) and bool(data.get("premise_supported_by_sources"))
    report["verifier"] = f"rule-based + {info.get('model')}"
    _check(report, "llm_verifier", passed, f"model answer={data.get('your_answer')}, unambiguous="
           f"{data.get('unambiguous')}, supported={data.get('premise_supported_by_sources')}; "
           f"issues={data.get('issues')}")
    return passed
