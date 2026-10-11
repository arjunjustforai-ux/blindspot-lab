"""Chunk paragraphs into retrieval units without crossing source anchors."""

from __future__ import annotations

from app.services.ai.text import normalize_ws, split_sentences, word_count

TARGET_MIN_WORDS = 50
TARGET_MAX_WORDS = 170


def chunk_paragraphs(paragraphs: list[str], *, min_words: int = TARGET_MIN_WORDS,
                     max_words: int = TARGET_MAX_WORDS) -> list[str]:
    """Greedy packing of paragraphs (split long ones on sentence boundaries)."""
    pieces: list[str] = []
    for p in paragraphs:
        p = normalize_ws(p)
        if not p:
            continue
        if word_count(p) <= max_words:
            pieces.append(p)
            continue
        cur: list[str] = []
        for s in split_sentences(p):
            if cur and word_count(" ".join(cur + [s])) > max_words:
                pieces.append(" ".join(cur))
                cur = []
            cur.append(s)
        if cur:
            pieces.append(" ".join(cur))

    chunks: list[str] = []
    cur_chunk: list[str] = []
    for piece in pieces:
        candidate = cur_chunk + [piece]
        if cur_chunk and word_count(" ".join(candidate)) > max_words and word_count(" ".join(cur_chunk)) >= min_words:
            chunks.append("\n".join(cur_chunk))
            cur_chunk = [piece]
        else:
            cur_chunk = candidate
    if cur_chunk:
        if chunks and word_count(" ".join(cur_chunk)) < min_words // 2 and \
                word_count(chunks[-1]) + word_count(" ".join(cur_chunk)) <= max_words + 40:
            chunks[-1] = chunks[-1] + "\n" + "\n".join(cur_chunk)
        else:
            chunks.append("\n".join(cur_chunk))
    return chunks
