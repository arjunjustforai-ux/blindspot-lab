"""Response classification and initial misconception hypotheses.

Correctness (from the grader) is kept separate from the *interpretation* of a
response. The classifier combines three evidence sources:

  1. Misconception signatures: the exact wrong answer (or MCQ option) a catalogued
     misconception predicts for this question (computed by the template, or authored).
  2. Reasoning cues: phrases in the learner's explanation associated with the
     misconception, or with correct reasoning (instructor-reviewable cue lists).
  3. Execution-error patterns: numeric answers close to the key, off by a factor of
     10/100, a sign flip, or a rounding slip.

It returns one of seven categories plus a prior distribution over competing
hypotheses. These priors are hand-set design assumptions (documented in
docs/MASTERY_AND_MISCONCEPTIONS.md), not empirically calibrated probabilities.
A single wrong answer never yields more than a *suspected* misconception.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.models import Question
from app.services.assessment.grading import Grade, parse_number

CATEGORIES = {
    "correct_supported": "Correct, with reasoning consistent with the concept",
    "correct_questionable_reasoning": "Correct answer, but the reasoning suggests a flawed or lucky route",
    "calculation_error": "Incorrect, most likely an execution/arithmetic slip",
    "likely_misconception": "Incorrect in the way a known misconception predicts (hypothesis, not a verdict)",
    "missing_prerequisite": "Incorrect, and the evidence points to a weak prerequisite",
    "incomplete_or_ambiguous": "Response could not be interpreted reliably",
    "insufficient_evidence": "Incorrect, but there is not enough evidence to explain why",
}

# Hypothesis priors per evidence pattern (design assumptions).
PRIORS = {
    "signature": {"misconception": 0.55, "calculation_error": 0.08, "misread_question": 0.15,
                  "missing_prerequisite": 0.12, "guess": 0.10},
    "cue_only": {"misconception": 0.35, "calculation_error": 0.12, "misread_question": 0.15,
                 "missing_prerequisite": 0.18, "guess": 0.20},
    "near_miss": {"misconception": 0.08, "calculation_error": 0.62, "misread_question": 0.10,
                  "missing_prerequisite": 0.10, "guess": 0.10},
    "unexplained": {"misconception": 0.15, "calculation_error": 0.10, "misread_question": 0.10,
                    "missing_prerequisite": 0.25, "guess": 0.40},
}
CUE_LR = 2.0            # reasoning matches misconception cues
CORRECT_CUE_LR = 0.5    # reasoning matches correct-reasoning cues
CONFIDENT_ERROR_LR = 1.4  # wrong with self-reported confidence 4-5 (assumption: confident errors are more often systematic)
WEAK_PREREQ_LR = 2.0    # a prerequisite concept is estimated < 0.4 with evidence


@dataclass
class Classification:
    category: str
    summary: str
    candidates: list[dict[str, Any]] = field(default_factory=list)  # per-misconception hypothesis sets
    evidence: list[dict[str, Any]] = field(default_factory=list)
    reasoning_cues: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"category": self.category, "label": CATEGORIES[self.category], "summary": self.summary,
                "candidates": self.candidates, "evidence": self.evidence, "reasoning_cues": self.reasoning_cues}


def _cue_hits(text: str, cues: list[str]) -> list[str]:
    t = " " + re.sub(r"\s+", " ", text.lower()) + " "
    return [c for c in cues if c.lower() in t]


def _near_miss(value: float, expected: float) -> str | None:
    if expected == 0:
        return None
    if value == expected:
        return None
    rel = abs(value - expected) / abs(expected)
    if rel <= 0.06:
        return f"within {rel:.0%} of the key (rounding or arithmetic slip)"
    for f in (10, 100, 1000):
        if abs(value * f - expected) <= abs(expected) * 0.01 or abs(value / f - expected) <= abs(expected) * 0.01:
            return f"off by a factor of {f} (decimal/percentage slip)"
    if abs(value + expected) <= abs(expected) * 0.01:
        return "sign flipped"
    return None


def normalize(dist: dict[str, float]) -> dict[str, float]:
    z = sum(dist.values()) or 1.0
    return {k: v / z for k, v in dist.items()}


def classify(
    q: Question, response: dict[str, Any], grade: Grade, reasoning: str | None, confidence: int | None, *,
    catalog: dict[str, dict[str, Any]], active_keys: set[str], weak_prereqs: list[str],
    concept_key: str | None = None,
) -> Classification:
    reasoning = (reasoning or "").strip()
    evidence: list[dict[str, Any]] = []
    if grade.is_correct is None:
        return Classification("incomplete_or_ambiguous", "The response could not be graded reliably "
                              f"({grade.detail.get('error', 'unreadable')}).", evidence=evidence)

    # Reasoning cue analysis for every active misconception relevant to this question's signatures.
    sig_keys = [s.get("misconception_key") for s in q.misconception_signatures if s.get("misconception_key")]
    relevant = [k for k in dict.fromkeys(sig_keys) if k in active_keys and k in catalog]
    if not relevant:
        relevant = [k for k, e in catalog.items() if k in active_keys and concept_key in e.get("concept_keys", [])]
    cues = {k: _cue_hits(reasoning, catalog[k].get("detection_cues", [])) for k in relevant}
    good = {k: _cue_hits(reasoning, catalog[k].get("correct_cues", [])) for k in relevant}

    if grade.is_correct:
        flagged = [k for k in relevant if cues[k] and not good[k]]
        if reasoning and flagged:
            k = flagged[0]
            evidence.append({"kind": "reasoning_cue", "misconception_key": k, "cues": cues[k],
                             "summary": f"Reasoning mentions {', '.join(cues[k])!r}, typical of "
                             f"'{catalog[k]['title']}'."})
            return Classification(
                "correct_questionable_reasoning",
                "The answer is correct, but the explanation uses reasoning associated with a known misconception. "
                "The correct answer is weaker evidence of understanding here.",
                evidence=evidence, reasoning_cues={k: cues[k]},
            )
        note = "" if reasoning else " No reasoning was given, so only the answer itself counts as evidence."
        return Classification("correct_supported", "Correct answer." + note, evidence=evidence)

    # Incorrect --------------------------------------------------------------------
    matched: list[dict[str, Any]] = []
    if q.question_type == "numerical":
        value, _ = parse_number(response.get("value", response.get("text")))
        value = grade.detail.get("normalized", value)
        for s in q.misconception_signatures:
            if value is not None and s.get("value") is not None and \
                    abs(value - float(s["value"])) <= max(float(s.get("tolerance", 0)), 1e-9):
                matched.append(s)
        near = _near_miss(value, q.numeric_answer) if value is not None and q.numeric_answer is not None else None
    else:
        sel = str(response.get("option_id", "")).lower()
        matched = [s for s in q.misconception_signatures if str(s.get("option_id", "")).lower() == sel]
        near = None

    candidates: list[dict[str, Any]] = []
    for s in matched:
        k = s.get("misconception_key")
        if not k:
            evidence.append({"kind": "signature_other", "summary": s.get("label")})
            continue
        if k not in active_keys or k not in catalog:
            evidence.append({"kind": "signature_inactive", "misconception_key": k,
                             "summary": f"Matches '{k}', but that entry is not supported by this course's sources."})
            continue
        evidence.append({"kind": "signature_match", "misconception_key": k, "summary": s.get("label")})
        candidates.append(_hypothesis_set(k, catalog[k], "signature", cues.get(k, []), good.get(k, []), confidence,
                                          weak_prereqs))
    if not candidates:
        for k in relevant:
            if cues.get(k) and not good.get(k):
                evidence.append({"kind": "reasoning_cue", "misconception_key": k, "cues": cues[k],
                                 "summary": f"Reasoning mentions {', '.join(cues[k])!r}."})
                candidates.append(_hypothesis_set(k, catalog[k], "cue_only", cues[k], good[k], confidence,
                                                  weak_prereqs))
    if candidates:
        candidates.sort(key=lambda c: c["distribution"]["misconception"], reverse=True)
        top = candidates[0]
        return Classification(
            "likely_misconception",
            f"The answer matches the pattern predicted by '{top['title']}'. This is a hypothesis to test, not a "
            "conclusion: one answer can also come from a slip, a misreading or a guess.",
            candidates=candidates, evidence=evidence, reasoning_cues={k: v for k, v in cues.items() if v},
        )
    if near:
        evidence.append({"kind": "near_miss", "summary": near})
        return Classification("calculation_error", f"The answer is {near}; the approach may be right.",
                               evidence=evidence)
    if weak_prereqs:
        evidence.append({"kind": "weak_prerequisite", "summary": f"Weak prerequisite(s): {', '.join(weak_prereqs)}"})
        return Classification("missing_prerequisite", "The answer is incorrect and a prerequisite concept is "
                              "estimated as weak, so a prerequisite gap is a plausible explanation.", evidence=evidence)
    return Classification(
        "insufficient_evidence",
        "The answer is incorrect, but it does not match a known misconception pattern" +
        (" and no reasoning was given." if not reasoning else "."), evidence=evidence,
    )


def _hypothesis_set(key: str, entry: dict[str, Any], pattern: str, cues: list[str], good: list[str],
                    confidence: int | None, weak_prereqs: list[str]) -> dict[str, Any]:
    allowed = {"misconception"} | {c["key"] for c in entry.get("competing_interpretations", [])}
    prior = {h: p for h, p in PRIORS[pattern].items() if h in allowed}
    adjustments = []
    if cues and pattern == "signature":
        prior["misconception"] *= CUE_LR
        adjustments.append(f"reasoning cues {cues} (×{CUE_LR} on misconception)")
    if good:
        prior["misconception"] *= CORRECT_CUE_LR
        adjustments.append(f"correct-reasoning cues {good} (×{CORRECT_CUE_LR} on misconception)")
    if confidence and confidence >= 4:
        prior["misconception"] *= CONFIDENT_ERROR_LR
        adjustments.append(f"self-reported confidence {confidence}/5 (×{CONFIDENT_ERROR_LR} on misconception)")
    if weak_prereqs and "missing_prerequisite" in prior:
        prior["missing_prerequisite"] *= WEAK_PREREQ_LR
        adjustments.append(f"weak prerequisite(s) {weak_prereqs} (×{WEAK_PREREQ_LR})")
    dist = normalize(prior)
    labels = {"misconception": entry["title"]}
    labels.update({c["key"]: c["label"] for c in entry.get("competing_interpretations", [])})
    return {"misconception_key": key, "title": entry["title"], "pattern": pattern,
            "distribution": {k: round(v, 4) for k, v in dist.items()}, "labels": labels,
            "adjustments": adjustments}
