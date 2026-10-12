"""Bayesian Knowledge Tracing (Corbett & Anderson, 1995) with evidence weighting.

Standard BKT per concept with latent state L (concept known):

    P(L | correct)   = P(L)(1-S) / [P(L)(1-S) + (1-P(L)) G]
    P(L | incorrect) = P(L) S     / [P(L) S     + (1-P(L)) (1-G)]
    P(L_next)        = P(L | obs) + (1 - P(L | obs)) T

Blindspot Lab extensions (documented heuristics, not part of classic BKT):
  * Guess G depends on the question type (MCQ options vs open numerical/short answers).
  * Slip S increases with question difficulty.
  * Evidence weight w in (0, 1] tempers an observation: likelihoods are raised to the
    power w and the learning transition is scaled to T*w. Repeated paraphrases of an
    already-seen question family, uncertain grading and correct answers with
    questionable reasoning get w < 1, so repetition cannot inflate mastery.
Values are model estimates, not validated measures of what a person knows.
"""

from __future__ import annotations

from dataclasses import dataclass

P_INIT = 0.25
P_TRANSIT = 0.10
GUESS = {"mcq": 0.20, "numerical": 0.10, "short_answer": 0.12}
SLIP = {1: 0.08, 2: 0.12, 3: 0.18}


@dataclass(frozen=True)
class Params:
    p_init: float = P_INIT
    p_transit: float = P_TRANSIT
    guess: float = 0.2
    slip: float = 0.1

    def as_dict(self) -> dict[str, float]:
        return {"p_init": self.p_init, "p_transit": self.p_transit, "guess": self.guess, "slip": self.slip}


def params_for(question_type: str, difficulty: int, n_options: int | None = None) -> Params:
    g = GUESS.get(question_type, 0.1)
    if question_type == "mcq" and n_options:
        g = min(g, 1.0 / n_options)
    return Params(guess=g, slip=SLIP.get(difficulty, 0.1))


def posterior(p: float, correct: bool, params: Params, weight: float = 1.0) -> float:
    """Tempered Bayesian update of P(L) after one observation (no learning transition)."""
    w = max(0.0, min(1.0, weight))
    if w == 0:
        return p
    g, s = params.guess, params.slip
    if correct:
        like_known, like_unknown = (1 - s), g
    else:
        like_known, like_unknown = s, (1 - g)
    num = p * like_known**w
    den = num + (1 - p) * like_unknown**w
    return num / den if den > 0 else p


def update(p: float, correct: bool, params: Params, weight: float = 1.0) -> float:
    """Posterior followed by the (weighted) learning transition."""
    post = posterior(p, correct, params, weight)
    t = params.p_transit * max(0.0, min(1.0, weight))
    return min(0.9999, max(0.0001, post + (1 - post) * t))


def p_correct(p: float, params: Params) -> float:
    """Predicted probability of a correct response."""
    return p * (1 - params.slip) + (1 - p) * params.guess


def label(p: float | None, n_obs: int, distinct: int) -> str:
    if p is None or n_obs == 0:
        return "unassessed"
    if p >= 0.9 and distinct >= 3:
        return "mastered"
    if p >= 0.7:
        return "proficient"
    if p >= 0.4:
        return "developing"
    return "emerging"


def evidence_quality(effective_evidence: float) -> str:
    if effective_evidence < 1.5:
        return "low"
    if effective_evidence < 4:
        return "medium"
    return "high"
