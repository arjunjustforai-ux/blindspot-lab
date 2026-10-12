"""Discrete Bayesian hypothesis tracking and contrastive probe selection.

A diagnostic session keeps a probability distribution over competing explanations
of an error (the catalogued misconception, an arithmetic slip, a misreading, a
missing prerequisite, a guess). Each probe has a likelihood table
P(response | hypothesis); observing a response updates the distribution by Bayes'
rule. The next probe is the one with the largest expected information gain
(expected reduction in Shannon entropy), i.e. the question that best *discriminates*
between the explanations still in play.

Status of a misconception hypothesis (never "confirmed"):
  supported   posterior >= 0.75 and at least 2 independent pieces of evidence
  suspected   posterior >= 0.35
  unresolved  0.15 <= posterior < 0.35
  rejected    posterior < 0.15
  resolving   repaired and transferred successfully; revisit scheduled
  resolved    a later revisit was also answered correctly
"""

from __future__ import annotations

import math
from typing import Any

SUPPORTED_P = 0.75
SUSPECTED_P = 0.35
REJECT_P = 0.15
MIN_EIG_BITS = 0.08
MAX_PROBES = 2


def entropy(dist: dict[str, float]) -> float:
    return -sum(p * math.log2(p) for p in dist.values() if p > 0)


def bayes(dist: dict[str, float], likelihood: dict[str, float]) -> dict[str, float]:
    post = {h: p * likelihood.get(h, 1e-6) for h, p in dist.items()}
    z = sum(post.values())
    if z <= 0:
        return dist
    return {h: v / z for h, v in post.items()}


def response_keys(probe: dict[str, Any]) -> list[str]:
    return list(probe["likelihoods"].keys())


def expected_information_gain(dist: dict[str, float], probe: dict[str, Any]) -> float:
    h0 = entropy(dist)
    eig = 0.0
    for _r, lk in probe["likelihoods"].items():
        pr = sum(dist[h] * lk.get(h, 1e-6) for h in dist)
        if pr <= 0:
            continue
        eig += pr * (h0 - entropy(bayes(dist, lk)))
    return eig


def choose_probe(dist: dict[str, float], probes: list[dict[str, Any]], asked: set[str]) -> tuple[dict | None, float]:
    best, best_gain = None, 0.0
    for p in probes:
        if p["key"] in asked:
            continue
        g = expected_information_gain(dist, p)
        if g > best_gain:
            best, best_gain = p, g
    return best, best_gain


def status_for(posterior: float, evidence_count: int) -> str:
    if posterior >= SUPPORTED_P and evidence_count >= 2:
        return "supported"
    if posterior >= SUSPECTED_P:
        return "suspected"
    if posterior >= REJECT_P:
        return "unresolved"
    return "rejected"


def prior_from_history(dist: dict[str, float], previous_posterior: float | None, base_rate: float = 0.25) -> dict[str, float]:
    """Shift the misconception prior by the learner's earlier evidence (odds ratio vs. a base rate)."""
    if previous_posterior is None or "misconception" not in dist:
        return dist
    prev = min(max(previous_posterior, 0.02), 0.98)
    factor = (prev / (1 - prev)) / (base_rate / (1 - base_rate))
    factor = min(max(factor, 0.33), 3.0)
    adj = dict(dist)
    adj["misconception"] *= factor
    z = sum(adj.values())
    return {k: v / z for k, v in adj.items()}


def leading(dist: dict[str, float]) -> tuple[str, float]:
    k = max(dist, key=lambda h: dist[h])
    return k, dist[k]
