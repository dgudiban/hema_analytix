"""Lexical retrieval over the curated knowledge base.

Uses TF-IDF cosine similarity (scikit-learn): deterministic, dependency-light,
zero-cost, and with no model download. The corpus is small (51 curated chunks),
so lexical retrieval is effective here. The `Retriever` protocol keeps the door
open to swap in embedding retrieval (e.g. MiniLM + pgvector) later without
changing callers.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.services import kb_loader


@dataclass
class Hit:
    chunk: kb_loader.Chunk
    score: float


class Retriever(Protocol):
    def retrieve(self, query: str, top_k: int = 4) -> list[Hit]: ...


class TfidfRetriever:
    def __init__(self, chunks: list[kb_loader.Chunk] | None = None):
        self._chunks = chunks if chunks is not None else kb_loader.load_chunks()
        # Title terms get extra weight by repeating the title in the document.
        docs = [f"{c.title} {c.title} {c.text}" for c in self._chunks]
        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._matrix = (
            self._vectorizer.fit_transform(docs) if docs else None
        )

    def retrieve(self, query: str, top_k: int = 4) -> list[Hit]:
        if not query.strip() or self._matrix is None:
            return []
        q = self._vectorizer.transform([query])
        scores = cosine_similarity(q, self._matrix)[0]
        ranked = sorted(
            (Hit(chunk=c, score=float(s)) for c, s in zip(self._chunks, scores)),
            key=lambda h: h.score,
            reverse=True,
        )
        return [h for h in ranked[:top_k] if h.score > 0]


_lock = Lock()
_default: TfidfRetriever | None = None


def get_retriever() -> TfidfRetriever:
    """Process-wide singleton so the TF-IDF index is built once."""
    global _default
    with _lock:
        if _default is None:
            _default = TfidfRetriever()
        return _default


def retrieve(query: str, top_k: int = 4) -> list[Hit]:
    return get_retriever().retrieve(query, top_k)
