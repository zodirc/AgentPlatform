from __future__ import annotations

import hashlib
import logging
import math
import re
import time
from collections.abc import Sequence
from typing import Any, Protocol

from app.settings import settings

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]:
        ...

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
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
            # ``hash()`` is salted per interpreter process, which made persisted
            # hash embeddings incompatible after a restart.
            bucket = int.from_bytes(
                hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(),
                byteorder="big",
            ) % self.dimensions
            vec[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vec))
        if norm == 0.0:
            return vec
        return [value / norm for value in vec]

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class SentenceTransformerEmbedder:
    """Optional neural embeddings when sentence-transformers is installed."""

    # bge-m3 hub default is 8192; that pads/activates like a long-context model and
    # saturates ~16GiB cards at modest batch sizes. Chunked corpora + C-MTEB small
    # docs are far shorter — 512 is the usual dense-retrieval truncate.
    _BGE_M3_DEFAULT_MAX_SEQ = 512

    def __init__(self, model_name: str, *, model_dir: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        cache = model_dir or None
        device = self._resolve_device()
        st_kwargs: dict[str, Any] = {"cache_folder": cache, "device": device}
        # bge-m3 (and some FlagEmbedding hubs) need remote code for ST loaders.
        if "bge-m3" in (model_name or "").lower():
            st_kwargs["trust_remote_code"] = True
        # Prefer local cache so startup cannot hang on HuggingFace hub I/O.
        try:
            self._model = SentenceTransformer(
                model_name,
                local_files_only=True,
                **st_kwargs,
            )
        except Exception:
            logger.warning(
                "local embedder cache miss for %s; falling back to download",
                model_name,
                exc_info=True,
            )
            self._model = SentenceTransformer(model_name, **st_kwargs)
        self._apply_max_seq_length(model_name)

    def _apply_max_seq_length(self, model_name: str) -> None:
        """Cap ST max_seq_length for throughput (does not change model weights)."""
        configured = int(getattr(settings, "embedding_max_seq_length", 0) or 0)
        if configured > 0:
            target = configured
        elif "bge-m3" in (model_name or "").lower():
            target = self._BGE_M3_DEFAULT_MAX_SEQ
        else:
            return
        prev = getattr(self._model, "max_seq_length", None)
        try:
            self._model.max_seq_length = int(target)
        except Exception:
            logger.warning(
                "failed to set embedder max_seq_length=%s (was %s)",
                target,
                prev,
                exc_info=True,
            )
            return
        logger.info(
            "embedder max_seq_length %s → %s (model=%s)",
            prev,
            target,
            model_name,
        )

    @staticmethod
    def _resolve_device() -> str:
        """Use CUDA when a usable GPU torch build is present (e.g. RTX 5080)."""
        forced = (getattr(settings, "embedding_device", None) or "").strip().lower()
        if forced in {"cpu", "cuda"}:
            logger.info("embedder device=%s (forced)", forced)
            return forced
        # "auto" or empty → probe
        try:
            import torch

            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                logger.info("embedder device=cuda gpu=%s", name)
                return "cuda"
        except Exception:
            logger.debug("embedder CUDA probe failed", exc_info=True)
        logger.info("embedder device=cpu")
        return "cpu"

    def embed(self, text: str) -> list[float]:
        vectors = self.embed_many([text])
        return vectors[0] if vectors else []

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        batch_size = max(1, int(getattr(settings, "embedding_batch_size", None) or 64))
        raw = self._model.encode(
            list(texts),
            batch_size=min(batch_size, len(texts)),
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [[float(x) for x in row] for row in raw]


def embed_many(
    embedder: Any,
    texts: Sequence[str],
    *,
    lane: int | None = None,
) -> list[list[float]]:
    """Call ``embed_many`` when available; else fall back to per-text ``embed``.

    ``lane`` selects query vs index priority when the embedder is lane-aware
    (O5 / WP2). Default keeps query priority for hot-path callers.
    """
    if not texts:
        return []
    from app.retrieval.embedding_lanes import LANE_QUERY

    effective_lane = LANE_QUERY if lane is None else int(lane)
    many = getattr(embedder, "embed_many", None)
    if callable(many):
        try:
            out = many(texts, lane=effective_lane)
        except TypeError:
            out = many(texts)
        if isinstance(out, list) and len(out) == len(texts):
            return out
    embed = getattr(embedder, "embed", None)
    if callable(embed):
        try:
            return [embed(text, lane=effective_lane) for text in texts]
        except TypeError:
            return [embed(text) for text in texts]
    raise TypeError("embedder must provide embed or embed_many")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def effective_embedding_dimensions() -> int:
    """Resolve vector width for stores.

    Hash default is 256. GTE-small / legacy MiniLM → 384;
    bge-m3 / GTE-large → 1024. Coerce common misconfig (hash default left on).
    """
    dims = int(settings.embedding_dimensions)
    backend = (settings.embedding_backend or "").lower()
    model = (settings.embedding_model or "").lower()
    if backend in {"sentence_transformers", "minilm", "neural"}:
        if "bge-m3" in model or "gte-large" in model:
            if dims not in {1024}:
                logger.info(
                    "embedding dimensions coerced %s→1024 for sentence_transformers %s",
                    dims,
                    model or "1024d",
                )
            return 1024
        if "gte-small" in model or "minilm-l6" in model or "all-minilm-l6-v2" in model:
            if dims == 256:
                logger.info(
                    "embedding dimensions coerced 256→384 for sentence_transformers "
                    "gte-small/MiniLM"
                )
            return 384
        if dims == 256:
            logger.info(
                "embedding dimensions coerced 256→384 for sentence_transformers default"
            )
            return 384
    return dims


def effective_index_version() -> int:
    """Index schema bump when embed space changes.

    8 = legacy MiniLM@384; 9 = gte-small@384; 10 = gte-large@1024;
    11 = bge-m3@1024 with hub-length (or uncapped) sequences;
    12 = bge-m3@1024 with max_seq≈512 truncate (GPU default; denser short passages).

    Prefer ``settings.embedding_index_version`` when compose/auto.env sets it so the
    console plan and runtime stamp stay aligned.
    """
    configured = int(getattr(settings, "embedding_index_version", 0) or 0)
    if configured > 0:
        return configured
    model = (settings.embedding_model or "").lower()
    dims = effective_embedding_dimensions()
    if "bge-m3" in model:
        # Match resolve_embedding_profile: GPU default truncates to 512 → INDEX 12.
        max_seq = int(getattr(settings, "embedding_max_seq_length", 0) or 0)
        if max_seq <= 0 or max_seq == 512:
            return 12
        return 11
    if "gte-large" in model:
        return 10
    if dims >= 1024:
        return 11
    if "minilm" in model:
        return 8
    # gte-small and other modern 384-d defaults
    return 9


def _cache_key() -> tuple[str, str, str, int]:
    return (
        settings.embedding_backend.lower(),
        settings.embedding_model,
        settings.embedding_model_dir or "",
        effective_embedding_dimensions(),
    )


def _build_embedder() -> Embedder:
    backend = settings.embedding_backend.lower()
    if backend in {"sentence_transformers", "minilm", "neural"}:
        try:
            # O5: cap CPU torch threads so batch embed does not starve the
            # uvicorn event loop / tool threads on constrained hosts.
            try:
                import torch

                if not torch.cuda.is_available():
                    torch.set_num_threads(
                        max(1, int(getattr(settings, "embedding_torch_num_threads", 2) or 2))
                    )
            except Exception:
                logger.debug("torch.set_num_threads skipped", exc_info=True)
            return SentenceTransformerEmbedder(
                settings.embedding_model,
                model_dir=settings.embedding_model_dir or None,
            )
        except ImportError as exc:
            raise RuntimeError(
                "EMBEDDING_BACKEND=sentence_transformers requires the retrieval extra "
                "(pip install '.[retrieval]' or use Dockerfile.retrieval)"
            ) from exc
    return HashEmbedder(dimensions=effective_embedding_dimensions())


def reset_embedder_cache() -> None:
    """Drop the process-wide embedder (tests / config reload)."""
    global _embedder, _embedder_key
    if _embedder is not None:
        close = getattr(_embedder, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.debug("embedder close failed", exc_info=True)
    _embedder = None
    _embedder_key = None


def get_embedder() -> Embedder:
    """Return the process-wide embedder singleton for the current settings."""
    global _embedder, _embedder_key
    key = _cache_key()
    if _embedder is not None and _embedder_key == key:
        return _embedder
    backend, model, model_dir, dims = key
    logger.info(
        "loading embedder; backend=%s model=%s dims=%s (cold start can take minutes)",
        backend,
        model,
        dims,
    )
    t0 = time.monotonic()
    from app.retrieval.embedding_lanes import maybe_wrap_lanes

    _embedder = maybe_wrap_lanes(_build_embedder())
    _embedder_key = key
    logger.info(
        "embedder ready; backend=%s elapsed_s=%.1f model_dir=%s",
        backend,
        time.monotonic() - t0,
        model_dir or "(default)",
    )
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
