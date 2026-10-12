"""Source-grounded question answering.

Pipeline: retrieve -> grounding gate -> compose (extractive or LLM) -> validate
citations -> return answer with navigable citations, or an explicit refusal.

Local (no-LLM) mode is *extractive*: it answers only with sentences quoted from the
retrieved course units, selected by a cross-encoder, each followed by its citation.
It never paraphrases, so it cannot introduce unsupported claims, but it also cannot
synthesise. LLM mode asks an OpenAI-compatible model for a JSON answer that may
only cite the provided source ids; invalid citations are stripped and answers
without valid citations are refused.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ConceptSource
from app.services.ai import llm
from app.services.ai.oplog import BudgetExceeded, log_operation
from app.services.ai.reranker import get_reranker, sigmoid
from app.services.ai.text import content_terms, lexical_overlap, normalize_ws, split_sentences
from app.services.retrieval.hybrid import (
    MODALITY_HINT_BONUS,
    Hit,
    RetrievalResult,
    modality_hints,
    query_coverage,
    retrieve,
)
from app.services.tutor.citations import build_citation, validate_citation_ids

ANSWER_PROMPT_VERSION = "grounded-answer-v1"
GATE_LOGIT = -0.85          # ~0.30 relevance probability for the best unit
GATE_COVERAGE = 0.34        # share of query content terms present in top units
SENTENCE_MIN_LOGIT = -1.0   # a quoted sentence must itself be relevant
SENTENCE_RELATIVE_CUT = 5.0  # ...and within this many logits of the best sentence (drops tangents)
MAX_SENTENCES = 4

PRONOUN_FOLLOWUP = re.compile(r"\b(it|this|that|they|those|these|its|their|above|same)\b", re.IGNORECASE)


@dataclass
class TutorAnswer:
    status: str  # grounded | refused | error
    mode: str  # extractive | llm
    content: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    external_content: str | None = None
    support_score: float | None = None
    concept_ids: list[str] = field(default_factory=list)
    nearest: list[dict[str, Any]] = field(default_factory=list)
    retrieval: dict[str, Any] = field(default_factory=dict)
    log_id: uuid.UUID | None = None


def standalone_query(question: str, history: list[str] | None) -> str:
    q = normalize_ws(question)
    if history and PRONOUN_FOLLOWUP.search(q) and len(content_terms(q)) < 6:
        return f"{history[-1]} {q}"
    return q


STRUCTURED = ("pdf_table", "slide_table", "slide_chart", "pdf_figure", "slide_figure")


@dataclass
class _Cand:
    text: str
    hit: Hit
    start: float | None = None
    structured: bool = False


def _unit_candidates(h: Hit) -> list[_Cand]:
    """Quotable spans of a unit. Transcript sentences keep the start time of the Whisper
    segment in which they begin; structured units (tables, charts, figures) are quoted whole."""
    u = h.unit
    if u.modality in STRUCTURED:
        body = "\n".join(ln for ln in u.content.split("\n") if ln.strip() and not set(ln.strip()) <= set("|-"))
        return [_Cand(body[:700], h, structured=True)]
    if u.modality == "transcript":
        segs = (u.extraction_meta or {}).get("segments") or []
        if segs:
            full, offsets = "", []
            for sg in segs:
                offsets.append((len(full), sg["start"]))
                full += sg["text"].strip() + " "
            out, pos = [], 0
            for sent in split_sentences(full):
                i = full.find(sent, pos)
                pos = i + len(sent) if i >= 0 else pos
                st = max((o for o in offsets if o[0] <= max(i, 0)), key=lambda o: o[0])[1]
                out.append(_Cand(sent, h, start=st))
            return out
    if u.modality in ("slide_text", "video_frame"):
        return [_Cand(ln.strip(), h) for ln in re.split(r"\n| / ", u.content) if len(ln.strip()) > 3]
    out = []
    for para in u.content.split("\n"):
        out.extend(_Cand(sent, h) for sent in split_sentences(para))
    return out


def _concepts_for_units(db: Session, unit_ids: list[uuid.UUID]) -> list[str]:
    if not unit_ids:
        return []
    rows = db.execute(select(ConceptSource.concept_id).where(ConceptSource.content_unit_id.in_(unit_ids),
                                                              ConceptSource.is_primary.is_(True))).all()
    seen: dict[str, None] = {}
    for (cid,) in rows:
        seen[str(cid)] = None
    return list(seen)


def _refusal(question: str, res: RetrievalResult, reason: str, mode: str) -> TutorAnswer:
    nearest = [
        build_citation(f"N{i + 1}", h.unit, h.source, focus_text=question, support=h.support)
        for i, h in enumerate(res.hits[:3])
    ]
    msg = (
        "I can't answer that from your course materials. " + reason
        + " I won't fill the gap with outside knowledge in grounded mode."
    )
    return TutorAnswer(status="refused", mode=mode, content=msg, nearest=nearest,
                       support_score=max((h.support for h in res.hits), default=0.0))


def answer(
    db: Session, course_id: uuid.UUID, question: str, *, user_id: uuid.UUID | None = None,
    history: list[str] | None = None, allow_external: bool = False, force_mode: str | None = None,
) -> TutorAnswer:
    s = get_settings()
    query = standalone_query(question, history)
    res = retrieve(db, course_id, query, k=s.retrieval_top_k)
    mode = force_mode or ("llm" if llm.llm_available() else "extractive")
    top = res.top_logit if res.top_logit is not None else -99.0
    cov = query_coverage(query, res.hits)
    retrieval_meta = {
        "query": query, "top_logit": round(top, 3), "coverage": round(cov, 3), "timings_ms": res.timings_ms,
        "hits": [h.debug() for h in res.hits], "gate": {"logit": GATE_LOGIT, "coverage": GATE_COVERAGE},
    }
    # Lexical coverage is only consulted when the reranker is not confident.
    if not res.hits or top < GATE_LOGIT or (top < 3.0 and cov < GATE_COVERAGE):
        out = _refusal(question, res, "The closest passages I found are not about this topic.", mode)
    elif mode == "llm":
        try:
            out = _answer_llm(db, course_id, question, res, user_id=user_id, allow_external=allow_external)
        except (llm.LLMError, llm.LLMUnavailable, BudgetExceeded) as e:
            out = TutorAnswer(status="error", mode="llm", content=f"The language model request failed ({e}). "
                              "No answer was generated; please retry.")
    else:
        out = _answer_extractive(db, question, res)
        if allow_external:
            out.external_content = None
            out.content += ("\n\n_Outside-knowledge mode needs a configured generative model; this deployment runs "
                            "in local extractive mode, so only source-backed content is shown._")
    out.retrieval = retrieval_meta
    out.concept_ids = _concepts_for_units(db, [uuid.UUID(c["unit_id"]) for c in out.citations])
    out.log_id = log_operation(
        operation="tutor_answer", provider="openai" if mode == "llm" else "local",
        model=s.llm_model if mode == "llm" else "extractive+" + (get_reranker().name if get_reranker() else "none"),
        status="ok" if out.status == "grounded" else ("refused" if out.status == "refused" else "error"),
        course_id=course_id, user_id=user_id, prompt_version=ANSWER_PROMPT_VERSION,
        latency_ms=sum(res.timings_ms.values()), meta={**retrieval_meta, "status": out.status},
    )
    return out


def _answer_extractive(db: Session, question: str, res: RetrievalResult) -> TutorAnswer:
    reranker = get_reranker()
    cands: list[_Cand] = []
    for h in res.hits[:4]:
        if (h.rerank_logit or -99) < GATE_LOGIT - 2:
            continue
        for c in _unit_candidates(h):
            c.text = normalize_ws(c.text) if not c.structured else c.text.strip()
            heading = (h.unit.heading or "").strip().rstrip(":.").lower()
            if not c.structured and heading and c.text.rstrip(":.").lower() == heading:
                continue  # a bare title is context, not an answer
            if c.structured or 4 <= len(c.text.split()) <= 70:
                cands.append(c)
    if not cands:
        return _refusal(question, res, "No passage contains a usable answer.", "extractive")
    if reranker:
        # Sentences are scored with their section heading as context, but quoted without it.
        logits = reranker.score(question, [((c.hit.unit.heading + ": ") if c.hit.unit.heading else "") + c.text
                                           for c in cands])
    else:
        logits = [lexical_overlap(question, c.text) * 10 - 5 for c in cands]
    # A structured unit is judged by the better of its unit-level and span-level relevance
    # (the unit-level score already includes any source-type hint bonus).
    hinted = modality_hints(question)
    logits = [max(lg, c.hit.rerank_logit or -99) if c.structured
              else lg + (MODALITY_HINT_BONUS if c.hit.source.modality in hinted else 0.0)
              for c, lg in zip(cands, logits)]
    scored = sorted(zip(cands, logits), key=lambda x: x[1], reverse=True)
    picked: list[tuple[_Cand, float]] = []
    floor = max(SENTENCE_MIN_LOGIT, scored[0][1] - SENTENCE_RELATIVE_CUT) if scored else SENTENCE_MIN_LOGIT
    for c, lg in scored:
        if lg < floor or len(picked) >= MAX_SENTENCES:
            break
        st = set(content_terms(c.text))
        if any(len(st & set(content_terms(p.text))) / max(len(st), 1) > 0.6 for p, _ in picked):
            continue
        picked.append((c, lg))
    if not picked or picked[0][1] < 0:
        return _refusal(question, res, "Related material exists, but no passage states an answer to this question.",
                        "extractive")
    cid_of: dict[uuid.UUID, str] = {}
    by_unit: dict[uuid.UUID, list[_Cand]] = {}
    lines = []
    for c, _ in picked:
        uid = c.hit.unit.id
        if uid not in cid_of:
            cid_of[uid] = f"S{len(cid_of) + 1}"
        by_unit.setdefault(uid, []).append(c)
        if c.structured:
            quoted = "\n".join("> " + ln for ln in c.text.split("\n"))
            lines.append(f"{quoted} [{cid_of[uid]}]")
        else:
            lines.append(f"> {c.text} [{cid_of[uid]}]")
    hits_by_id = {h.unit.id: h for h in res.hits}
    citations = []
    for uid, cid in cid_of.items():
        cs = by_unit[uid]
        h = hits_by_id[uid]
        citations.append(build_citation(cid, h.unit, h.source, focus_text=" ".join(c.text for c in cs),
                                        excerpt=" … ".join(c.text for c in cs), support=h.support,
                                        start_override=cs[0].start))
    for h in res.hits[:4]:
        if h.unit.modality in ("pdf_figure", "slide_figure", "slide_chart") and h.unit.id not in cid_of and \
                (h.rerank_logit or -99) >= max(0.0, floor):
            cid = f"S{len(cid_of) + 1}"
            cid_of[h.unit.id] = cid
            citations.append(build_citation(cid, h.unit, h.source, support=h.support))
            lines.append(f"\nRelated figure/diagram: [{cid}]")
            break
    body = "From your course materials (quoted directly):\n\n" + "\n\n".join(lines)
    return TutorAnswer(status="grounded", mode="extractive", content=body, citations=citations,
                       support_score=round(sigmoid(picked[0][1]), 4))


def _answer_llm(db: Session, course_id: uuid.UUID, question: str, res: RetrievalResult, *,
                user_id: uuid.UUID | None, allow_external: bool) -> TutorAnswer:
    hits = res.hits[:6]
    ids = {f"S{i + 1}": h for i, h in enumerate(hits)}
    blocks = []
    for sid, h in ids.items():
        anchor = (f"page {h.unit.page_number}" if h.unit.page_number else f"slide {h.unit.slide_number}"
                  if h.unit.slide_number else f"{h.unit.start_seconds:.0f}s")
        gen = " (model-generated figure description)" if h.unit.is_generated else ""
        blocks.append(f'<source id="{sid}" file="{h.source.filename}" anchor="{anchor}"{gen}>\n'
                      f"{h.unit.content[:1800]}\n</source>")
    ext_rule = (
        'You MAY add a separate "outside_knowledge" field with general knowledge that is NOT in the sources; '
        "keep it clearly separate and never cite sources for it." if allow_external else
        'Set "outside_knowledge" to null. Do not use knowledge beyond the sources.'
    )
    system = (
        "You are Blindspot Lab's course tutor. Answer ONLY from the provided course sources. Every factual sentence "
        "in answer_markdown must end with one or more citation markers like [S1]. If the sources do not contain "
        "the answer, set supported=false and explain briefly what is missing. " + ext_rule + " "
        + llm.UNTRUSTED_NOTICE
    )
    user = ("\n".join(blocks) + f"\n\nStudent question: {question}\n"
            'Return JSON: {"supported": bool, "answer_markdown": str, "used_sources": [str], '
            '"unsupported_reason": str|null, "outside_knowledge": str|null}')
    data, _info = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                          operation="tutor_generate", prompt_version=ANSWER_PROMPT_VERSION, course_id=course_id,
                          user_id=user_id)
    if not isinstance(data, dict) or not data.get("supported"):
        reason = (data or {}).get("unsupported_reason") if isinstance(data, dict) else None
        out = _refusal(question, res, reason or "The model judged the sources insufficient.", "llm")
        if allow_external and isinstance(data, dict) and data.get("outside_knowledge"):
            out.external_content = str(data["outside_knowledge"])
        return out
    text = str(data.get("answer_markdown", ""))
    markers = re.findall(r"\[(S\d+)\]", text)
    valid, invalid = validate_citation_ids(markers + list(data.get("used_sources", [])), ids)
    for bad in invalid:
        text = text.replace(f"[{bad}]", "")
    if not valid:
        return _refusal(question, res, "The generated answer did not cite any course source, so it was withheld.",
                        "llm")
    # Paragraphs without any citation are flagged rather than silently shown as grounded.
    paras = [p for p in text.split("\n\n") if p.strip()]
    uncited = [p for p in paras if not re.search(r"\[S\d+\]", p)]
    if uncited:
        text += "\n\n_Note: some sentences above have no citation; treat them as unverified._"
    citations = [build_citation(cid, ids[cid].unit, ids[cid].source, focus_text=text, support=ids[cid].support)
                 for cid in valid]
    return TutorAnswer(status="grounded", mode="llm", content=text, citations=citations,
                       external_content=str(data["outside_knowledge"]) if allow_external and
                       data.get("outside_knowledge") else None,
                       support_score=round(max(h.support for h in hits), 4))
