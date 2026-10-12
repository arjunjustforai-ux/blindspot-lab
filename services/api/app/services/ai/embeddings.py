"""Embedding provider adapters (local ONNX via fastembed, or OpenAI-compatible API)."""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Protocol

import httpx
import numpy as np

from app.config import get_settings


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    n[n == 0] = 1.0
    return v / n


class LocalEmbedder:
    """BAAI/bge-small-en-v1.5 (384-d) through fastembed/onnxruntime. No network after download."""

    def __init__(self, model_name: str, cache_dir: str, dim: int) -> None:
        from fastembed import TextEmbedding

        self.name = f"local:{model_name}"
        self.dim = dim
        self._model = TextEmbedding(model_name, cache_dir=cache_dir)
        self._lock = threading.Lock()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._lock:
            vecs = np.array(list(self._model.passage_embed(texts, batch_size=32)), dtype=np.float32)
        return _normalize(vecs).tolist()

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            v = np.array(list(self._model.query_embed([text]))[0], dtype=np.float32)
        return _normalize(v[None, :])[0].tolist()


class OpenAIEmbedder:
    """OpenAI-compatible /embeddings. Requests `dimensions` so vectors fit the pgvector column."""

    def __init__(self, model: str, dim: int, base_url: str, api_key: str, timeout: float) -> None:
        self.name = f"openai:{model}"
        self.model = model
        self.dim = dim
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.timeout = timeout

    def _call(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 96):
            batch = texts[i : i + 96]
            r = httpx.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": batch, "dimensions": self.dim},
                headers=self.headers,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
        return _normalize(np.array(out, dtype=np.float32)).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._call(texts) if texts else []

    def embed_query(self, text: str) -> list[float]:
        return self._call([text])[0]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedding_provider == "openai":
        if not s.openai_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY")
        return OpenAIEmbedder(s.openai_embedding_model, s.embedding_dim, s.openai_base_url, s.openai_api_key,
                              s.llm_timeout_seconds)
    return LocalEmbedder(s.embedding_model, str(s.model_cache_dir), s.embedding_dim)


def cosine(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))
