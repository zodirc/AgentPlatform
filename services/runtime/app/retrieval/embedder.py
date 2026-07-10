from __future__ import annotations

import logging
import math
import re
from typing import Protocol

from app.settings import settings

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


_embedder: Embedder | None = None
_embedder_key: tuple[str, str, str, int] | None = None


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for piece in re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", text.lower()):
        tokens.append(piece)
        cjk = re.fullmatch(r"[\u4e00-\u9fff]{2,}", piece)
        if cjk:
            for width in (2, 3):
                if len(piece) < width:
                    continue
                for start in range(len(piece) - width + 1):
                    grams = piece[start : start + width]
                    if grams not in tokens:
                        tokens.append(grams)
    return tokens


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


def _cache_key() -> tuple[str, str, str, int]:
    return (
        settings.embedding_backend.lower(),
        settings.embedding_model,
        settings.embedding_model_dir or "",
        settings.embedding_dimensions,
    )


def _build_embedder() -> Embedder:
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


def reset_embedder_cache() -> None:
    """Drop the process-wide embedder (tests / config reload)."""
    global _embedder, _embedder_key
    _embedder = None
    _embedder_key = None


def get_embedder() -> Embedder:
    """Return the process-wide embedder singleton for the current settings."""
    global _embedder, _embedder_key
    key = _cache_key()
    if _embedder is not None and _embedder_key == key:
        return _embedder
    _embedder = _build_embedder()
    _embedder_key = key
    return _embedder


def warmup_embedder() -> str:
    """Load the configured embedder at startup so first index/search is cheap.

    Returns a short backend label for logs. Missing retrieval extras are logged
    as warnings so the default hash path can still start; other failures raise.
    """
    backend = settings.embedding_backend.lower()
    try:
        embedder = get_embedder()
        # Force encode path for neural backends (constructor may already load weights).
        embedder.embed("warmup")
    except RuntimeError:
        logger.warning(
            "embedder warmup skipped: backend=%s unavailable; retrieval will fail until fixed",
            backend,
            exc_info=True,
        )
        reset_embedder_cache()
        return f"{backend}:unavailable"
    except Exception:
        logger.exception("embedder warmup failed: backend=%s", backend)
        reset_embedder_cache()
        raise
    label = type(embedder).__name__
    logger.info("embedder ready: backend=%s impl=%s", backend, label)
    return f"{backend}:{label}"
