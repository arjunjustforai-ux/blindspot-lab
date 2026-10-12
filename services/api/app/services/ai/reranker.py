"""Cross-encoder reranking (local ONNX). Scores are logits; we expose a sigmoid probability."""

from __future__ import annotations

import math
import threading
from functools import lru_cache

from app.config import get_settings


class Reranker:
    def __init__(self, model_name: str, cache_dir: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.name = f"local:{model_name}"
        self._model = TextCrossEncoder(model_name, cache_dir=cache_dir)
        self._lock = threading.Lock()

    def score(self, query: str, docs: list[str]) -> list[float]:
        """Return relevance logits (higher = more relevant)."""
        if not docs:
            return []
        with self._lock:
            return [float(x) for x in self._model.rerank(query, docs, batch_size=16)]


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@lru_cache
def get_reranker() -> Reranker | None:
    s = get_settings()
    if not s.reranker_enabled:
        return None
    return Reranker(s.reranker_model, str(s.model_cache_dir))
