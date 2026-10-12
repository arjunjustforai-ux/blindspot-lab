"""Hybrid retrieval over course content units.

1. Embed the query (same model as the units).
2. Semantic search: pgvector cosine distance.
3. Lexical search: PostgreSQL full-text search (OR of stemmed content terms, ts_rank_cd).
4. Reciprocal-rank fusion (k=60) of the two candidate lists.
5. Cross-encoder reranking of the fused candidates (local ONNX MiniLM).
6. Return the strongest units with full provenance plus scores for logging/eval.

All queries are scoped to one course id (authorization happens in the API layer).
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ContentUnit, SourceFile
from app.services.ai.embeddings import get_embedder
from app.services.ai.reranker import get_reranker, sigmoid
from app.services.ai.text import STOPWORDS, content_terms, tokens

RRF_K = 60
MODALITY_HINT_BONUS = 1.5  # logit bonus when the question names a source type ("in the lecture ...")
HINTS = {
    "video": re.compile(r"\b(lecture|video|recording|narrat\w*|speaker said|in the talk)\b", re.I),
    "pptx": re.compile(r"\b(slides?|deck|presentation|speaker notes)\b", re.I),
    "pdf": re.compile(r"\b(primer|textbook|chapter|pdf|reading|handout)\b", re.I),
}
META_TERMS = frozenset({"course", "material", "say", "according", "lecture", "slide", "primer", "deck", "video",
                        "chapter", "explain", "describe", "mention", "show", "note", "speaker", "text", "listed"})


def modality_hints(query: str) -> set[str]:
    return {m for m, rx in HINTS.items() if rx.search(query)}


@dataclass
class Hit:
    unit: ContentUnit
    source: SourceFile
    vector_sim: float | None = None
    vector_rank: int | None = None
    lexical_score: float | None = None
    lexical_rank: int | None = None
    rrf: float = 0.0
    rerank_logit: float | None = None

    @property
    def support(self) -> float:
        """Relevance probability used for grounding decisions."""
        if self.rerank_logit is not None:
            return sigmoid(self.rerank_logit)
        return max(0.0, self.vector_sim or 0.0)

    def debug(self) -> dict[str, Any]:
        return {
            "unit_id": str(self.unit.id),
            "source": self.source.filename,
            "modality": self.unit.modality,
            "page": self.unit.page_number,
            "slide": self.unit.slide_number,
            "start": self.unit.start_seconds,
            "vector_sim": None if self.vector_sim is None else round(self.vector_sim, 4),
            "vector_rank": self.vector_rank,
            "lexical": None if self.lexical_score is None else round(self.lexical_score, 4),
            "lexical_rank": self.lexical_rank,
            "rrf": round(self.rrf, 5),
            "rerank_logit": None if self.rerank_logit is None else round(self.rerank_logit, 3),
        }


@dataclass
class RetrievalResult:
    query: str
    hits: list[Hit]
    candidates: int
    timings_ms: dict[str, int] = field(default_factory=dict)

    @property
    def top_logit(self) -> float | None:
        vals = [h.rerank_logit for h in self.hits if h.rerank_logit is not None]
        return max(vals) if vals else None


def _or_tsquery(query: str) -> str | None:
    terms = [t for t in tokens(query) if t not in STOPWORDS and len(t) > 1 and re.fullmatch(r"[a-z0-9]+", t)]
    terms = list(dict.fromkeys(terms))[:16]
    return " | ".join(terms) if terms else None


def retrieve(
    db: Session,
    course_id: uuid.UUID,
    query: str,
    *,
    k: int | None = None,
    candidates: int | None = None,
    source_ids: list[uuid.UUID] | None = None,
    include_generated: bool = True,
    rerank: bool = True,
) -> RetrievalResult:
    s = get_settings()
    k = k or s.retrieval_top_k
    n = candidates or s.retrieval_candidates
    timings: dict[str, int] = {}

    t0 = time.perf_counter()
    qvec = get_embedder().embed_query(query)
    timings["embed"] = int((time.perf_counter() - t0) * 1000)

    filters = "course_id = :c"
    params: dict[str, Any] = {"c": course_id, "n": n}
    if source_ids:
        filters += " AND source_file_id = ANY(:sids)"
        params["sids"] = list(source_ids)
    if not include_generated:
        filters += " AND is_generated = false"

    t0 = time.perf_counter()
    db.execute(text("SET LOCAL hnsw.ef_search = 100"))
    vec_rows = db.execute(
        text(
            f"SELECT id, 1 - (embedding <=> CAST(:q AS vector)) AS sim FROM content_units "
            f"WHERE {filters} AND embedding IS NOT NULL ORDER BY embedding <=> CAST(:q AS vector) LIMIT :n"
        ),
        {**params, "q": str(qvec)},
    ).all()
    timings["vector"] = int((time.perf_counter() - t0) * 1000)

    lex_rows: list[Any] = []
    tsq = _or_tsquery(query)
    t0 = time.perf_counter()
    if tsq:
        lex_rows = db.execute(
            text(
                f"SELECT id, ts_rank_cd(tsv, to_tsquery('english', :tq), 32) AS r FROM content_units "
                f"WHERE {filters} AND tsv @@ to_tsquery('english', :tq) ORDER BY r DESC LIMIT :n"
            ),
            {**params, "tq": tsq},
        ).all()
    timings["lexical"] = int((time.perf_counter() - t0) * 1000)

    fused: dict[uuid.UUID, dict[str, Any]] = {}
    for rank, (uid, sim) in enumerate(vec_rows, start=1):
        d = fused.setdefault(uid, {"rrf": 0.0})
        d["rrf"] += 1.0 / (RRF_K + rank)
        d["vector_sim"], d["vector_rank"] = float(sim), rank
    for rank, (uid, r) in enumerate(lex_rows, start=1):
        d = fused.setdefault(uid, {"rrf": 0.0})
        d["rrf"] += 1.0 / (RRF_K + rank)
        d["lexical_score"], d["lexical_rank"] = float(r), rank

    top_ids = sorted(fused, key=lambda u: fused[u]["rrf"], reverse=True)[:n]
    if not top_ids:
        return RetrievalResult(query=query, hits=[], candidates=0, timings_ms=timings)
    rows = db.execute(
        select(ContentUnit, SourceFile).join(SourceFile, SourceFile.id == ContentUnit.source_file_id)
        .where(ContentUnit.id.in_(top_ids))
    ).all()
    by_id = {u.id: (u, sf) for u, sf in rows}
    hits = [
        Hit(unit=by_id[i][0], source=by_id[i][1], **{kk: vv for kk, vv in fused[i].items()})
        for i in top_ids if i in by_id
    ]

    reranker = get_reranker() if rerank else None
    if reranker and hits:
        t0 = time.perf_counter()
        docs = [((h.unit.heading + ". ") if h.unit.heading else "") + h.unit.content for h in hits]
        logits = reranker.score(query, docs)
        hinted = modality_hints(query)
        for h, lg in zip(hits, logits):
            h.rerank_logit = lg + (MODALITY_HINT_BONUS if h.source.modality in hinted else 0.0)
        hits.sort(key=lambda h: (h.rerank_logit or -99.0), reverse=True)
        timings["rerank"] = int((time.perf_counter() - t0) * 1000)
    return RetrievalResult(query=query, hits=hits[:k], candidates=len(fused), timings_ms=timings)


def query_coverage(query: str, hits: list[Hit], top: int = 3) -> float:
    """Fraction of the query's content terms (ignoring meta words such as 'course', 'lecture')
    that appear in the top retrieved units."""
    if not hits:
        return 0.0
    terms = {t for t in content_terms(query) if t not in META_TERMS}
    if not terms:
        return 1.0
    joined = set(content_terms(" ".join(((h.unit.heading or "") + " " + h.unit.content) for h in hits[:top])))
    return len(terms & joined) / len(terms)


def key_terms(query: str) -> list[str]:
    return content_terms(query)
