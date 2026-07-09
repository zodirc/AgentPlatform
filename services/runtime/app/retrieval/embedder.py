from __future__ import annotations

import math
import re
from typing import Protocol

from app.settings import settings


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", text.lower())


class HashEmbedder:
    """Deterministic bag-of-words hashing embedding (default, no extra deps)."""

    def __init__(self, *, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for token in tokenize(text):
            bucket = hash(token) % self.dimensions
            vec[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vec))
        if norm == 0.0:
            return vec
        return [value / norm for value in vec]


class SentenceTransformerEmbedder:
    """Optional neural embeddings when sentence-transformers is installed."""

    def __init__(self, model_name: str, *, model_dir: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        cache = model_dir or None
        self._model = SentenceTransformer(model_name, cache_folder=cache)

    def embed(self, text: str) -> list[float]:
        vector = self._model.encode(text, normalize_embeddings=True)
        return [float(x) for x in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_embedder() -> Embedder:
    backend = settings.embedding_backend.lower()
    if backend in {"sentence_transformers", "minilm", "neural"}:
        try:
            return SentenceTransformerEmbedder(
                settings.embedding_model,
                model_dir=settings.embedding_model_dir or None,
            )
        except ImportError as exc:
            raise RuntimeError(
                "EMBEDDING_BACKEND=sentence_transformers requires the retrieval extra "
                "(pip install '.[retrieval]' or use Dockerfile.retrieval)"
            ) from exc
    return HashEmbedder(dimensions=settings.embedding_dimensions)
