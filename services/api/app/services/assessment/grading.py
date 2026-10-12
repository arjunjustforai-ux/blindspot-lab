"""Answer grading.

- MCQ: deterministic key comparison.
- Numerical: parse the learner's number (₹, commas, %, x, negative) and compare with
  the expected value using the question's explicit tolerance.
- Short answer: rubric key points. Local mode scores each key point by keyword
  evidence and embedding similarity; mid-range scores are flagged for review rather
  than given false certainty. LLM mode uses a structured rubric grader.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.models import Question
from app.services.ai import llm
from app.services.ai.embeddings import cosine, get_embedder
from app.services.ai.oplog import BudgetExceeded
from app.services.ai.text import content_terms, normalize_ws, stem

NUM_RE = re.compile(r"[-−]?\s*[₹$€£]?\s*[-−]?\d[\d,]*(?:\.\d+)?|[-−]?\.\d+")


@dataclass
class Grade:
    is_correct: bool | None
    score: float | None
    method: str
    detail: dict[str, Any] = field(default_factory=dict)
    needs_review: bool = False


def parse_number(raw: Any) -> tuple[float | None, bool]:
    """Return (value, had_percent_sign). Handles '₹1,25,000', '-₹200', '25%', '2.5x', '1.5 lakh'."""
    if raw is None:
        return None, False
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return (float(raw) if math.isfinite(float(raw)) else None), False
    s = str(raw).strip().lower().replace("−", "-")
    if not s:
        return None, False
    had_pct = "%" in s or "percent" in s
    m = NUM_RE.search(s)
    if not m:
        return None, had_pct
    token = m.group(0)
    neg = "-" in token or bool(re.search(r"(^|\s)(minus|loss of|negative)\s", s)) or s.startswith("(")
    num = re.sub(r"[^\d.]", "", token)
    try:
        v = float(num)
    except ValueError:
        return None, had_pct
    if re.search(r"\blakh\b", s):
        v *= 100_000
    elif re.search(r"\bcrore\b", s):
        v *= 10_000_000
    elif re.search(r"\d\s*k\b", s):
        v *= 1000
    return (-v if neg else v), had_pct


def grade_mcq(q: Question, response: dict[str, Any]) -> Grade:
    choice = str(response.get("option_id") or "").strip().lower()
    valid = {o["id"] for o in q.options}
    if choice not in valid:
        return Grade(None, None, "deterministic_mcq", {"error": "no valid option selected"}, needs_review=False)
    ok = choice == (q.correct_option_id or "").lower()
    return Grade(ok, 1.0 if ok else 0.0, "deterministic_mcq", {"selected": choice, "correct": q.correct_option_id})


def numeric_match(value: float, expected: float, tol: float, mode: str | None) -> bool:
    if mode == "rel":
        return abs(value - expected) <= abs(expected) * tol
    return abs(value - expected) <= tol


def grade_numerical(q: Question, response: dict[str, Any]) -> Grade:
    raw = response.get("value", response.get("text"))
    value, had_pct = parse_number(raw)
    expected = q.numeric_answer
    tol = q.numeric_tolerance if q.numeric_tolerance is not None else 0.01
    if value is None or expected is None:
        return Grade(None, None, "numeric_tolerance", {"error": "could not read a number", "raw": str(raw)[:80]},
                     needs_review=expected is None)
    detail: dict[str, Any] = {"parsed": value, "expected": expected, "tolerance": tol,
                              "tolerance_mode": q.tolerance_mode or "abs", "unit": q.answer_unit}
    ok = numeric_match(value, expected, tol, q.tolerance_mode)
    if not ok and q.answer_unit == "%" and not had_pct and abs(value) <= 5 and \
            numeric_match(value * 100, expected, tol, q.tolerance_mode):
        ok = True
        detail["interpreted_as_fraction"] = True
        value = value * 100
    detail["normalized"] = value
    return Grade(ok, 1.0 if ok else 0.0, "numeric_tolerance", detail)


def _keypoint_hit(text_terms: set[str], kp: dict[str, Any]) -> float:
    groups: list[list[str]] = kp.get("keyword_groups") or [[k] for k in kp.get("keywords", [])]
    if not groups:
        return 0.0
    hit = 0
    for g in groups:
        alts = [" ".join(stem(t) for t in content_terms(a)) for a in g]
        if any(all(w in text_terms for w in alt.split()) for alt in alts if alt):
            hit += 1
    return hit / len(groups)


def grade_short_answer_local(q: Question, response: dict[str, Any]) -> Grade:
    text = normalize_ws(str(response.get("text") or ""))
    rubric = q.rubric or {}
    kps: list[dict[str, Any]] = rubric.get("key_points", [])
    if len(text.split()) < 3:
        return Grade(False if text else None, 0.0, "rubric_local",
                     {"error": "answer too short to assess"}, needs_review=False)
    terms = set(content_terms(text))
    emb = get_embedder()
    rv = emb.embed_query(text)
    kvecs = emb.embed_documents([kp["text"] for kp in kps]) if kps else []
    points, total_w, got = [], 0.0, 0.0
    for kp, kv in zip(kps, kvecs):
        w = float(kp.get("weight", 1.0))
        kw = _keypoint_hit(terms, kp)
        sim = cosine(rv, kv)
        credit = max(kw, 1.0 if sim >= 0.82 else (0.5 if sim >= 0.74 else 0.0))
        points.append({"id": kp.get("id"), "text": kp["text"], "keyword_evidence": round(kw, 2),
                       "similarity": round(sim, 3), "credit": round(credit, 2)})
        total_w += w
        got += w * credit
    score = got / total_w if total_w else 0.0
    contradiction = any(re.search(p, text.lower()) for p in rubric.get("contradiction_patterns", []))
    if contradiction:
        score = min(score, 0.3)
    threshold = float(rubric.get("pass_threshold", 0.7))
    uncertain = 0.45 <= score < threshold or (score >= threshold and score < threshold + 0.08)
    return Grade(
        score >= threshold, round(score, 3), "rubric_local",
        {"key_points": points, "threshold": threshold, "contradiction": contradiction,
         "note": "Local rubric scoring (keywords + embedding similarity). Borderline scores are flagged for review."},
        needs_review=uncertain,
    )


def grade_short_answer_llm(q: Question, response: dict[str, Any], sources: list[str], *, user_id=None,
                           course_id=None) -> Grade:
    text = normalize_ws(str(response.get("text") or ""))
    kps = (q.rubric or {}).get("key_points", [])
    rubric = "\n".join(f"- [{kp.get('id')}] {kp['text']}" for kp in kps)
    data, info = llm.chat(
        [
            {"role": "system", "content": "You grade short answers strictly against a rubric and course sources. "
             "Judge only whether each key point is clearly expressed. " + llm.UNTRUSTED_NOTICE},
            {"role": "user", "content": f"Question: {q.stem}\nRubric key points:\n{rubric}\n<source>\n"
             + "\n---\n".join(sources)[:3000] + f"\n</source>\nStudent answer (untrusted): <answer>{text}</answer>\n"
             "Return JSON {\"points\": [{\"id\": str, \"met\": bool, \"evidence\": str}], \"confidence\": number 0-1, "
             "\"misconception_signals\": [str]}"},
        ],
        operation="grade_short_answer", prompt_version="grade-sa-v1", user_id=user_id, course_id=course_id,
        max_tokens=500,
    )
    pts = data.get("points", []) if isinstance(data, dict) else []
    met = {str(p.get("id")): bool(p.get("met")) for p in pts}
    total = sum(float(kp.get("weight", 1)) for kp in kps) or 1.0
    got = sum(float(kp.get("weight", 1)) for kp in kps if met.get(str(kp.get("id"))))
    score = got / total
    conf = float(data.get("confidence", 0.5)) if isinstance(data, dict) else 0.0
    threshold = float((q.rubric or {}).get("pass_threshold", 0.7))
    return Grade(score >= threshold, round(score, 3), "rubric_llm",
                 {"points": pts, "confidence": conf, "model": info.get("model"),
                  "signals": data.get("misconception_signals", []) if isinstance(data, dict) else []},
                 needs_review=conf < 0.6)


def grade(q: Question, response: dict[str, Any], *, sources: list[str] | None = None, user_id=None,
          course_id=None) -> Grade:
    if q.question_type == "mcq":
        return grade_mcq(q, response)
    if q.question_type == "numerical":
        return grade_numerical(q, response)
    if llm.llm_available():
        try:
            return grade_short_answer_llm(q, response, sources or [], user_id=user_id, course_id=course_id)
        except (llm.LLMError, llm.LLMUnavailable, BudgetExceeded):
            pass  # fall back to the transparent local rubric scorer
    return grade_short_answer_local(q, response)
