"""Small, dependency-free text utilities shared by ingestion, retrieval and grading."""

from __future__ import annotations

import hashlib
import re
import unicodedata

STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before being below between both
    but by can could did do does doing down during each few for from further had has have having he her here hers
    herself him himself his how i if in into is it its itself just me more most my myself no nor not now of off on
    once only or other our ours ourselves out over own same she should so some such than that the their theirs them
    themselves then there these they this those through to too under until up very was we were what when where which
    while who whom why will with would you your yours yourself yourselves also may might must shall within without
    per via e g eg ie etc one two three use used using us does doesn whether""".split()
)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9₹\"'(])")
_WORD = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_hash(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"[^a-z0-9₹%.]+", " ", t)
    return normalize_ws(t)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    return sha256_text(normalize_for_hash(text))


def split_sentences(text: str) -> list[str]:
    text = normalize_ws(text)
    if not text:
        return []
    parts = _SENT_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def tokens(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", text).lower())


def stem(word: str) -> str:
    """Very light suffix stripping, good enough for lexical overlap scoring."""
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "es", "ed", "s"):
        if len(word) > len(suf) + 3 and word.endswith(suf):
            return word[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
    return word


def content_terms(text: str) -> list[str]:
    return [stem(t) for t in tokens(text) if t not in STOPWORDS and len(t) > 1]


def word_count(text: str) -> int:
    return len(text.split())


def lexical_overlap(query: str, text: str) -> float:
    """Fraction of the query's content terms present in `text`."""
    q = set(content_terms(query))
    if not q:
        return 0.0
    t = set(content_terms(text))
    return len(q & t) / len(q)


INJECTION_PATTERNS = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard (the )?(system|previous)|"
    r"you are now|system prompt|act as (an? )?(admin|developer)|reveal (your|the) (prompt|instructions)|"
    r"do not cite|override (the )?(rules|instructions))",
    re.IGNORECASE,
)


def looks_like_injection(text: str) -> bool:
    return bool(INJECTION_PATTERNS.search(text))
