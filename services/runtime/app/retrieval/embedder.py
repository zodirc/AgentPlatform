"""文本嵌入与向量维度解析（RAG 索引/检索链路的向量化层）。

职责：
- 提供 ``Embedder`` 协议及 Hash / SentenceTransformer 两种实现
- 进程级单例 ``get_embedder()``，供切块写入与 ``search_vector`` 查询共用
- 解析 ``effective_embedding_dimensions`` / ``effective_index_version``，驱动索引 stamp 与全量重嵌

在 RAG 链路中的位置：
  sources 切块 → ``chunking.build_embed_text`` → 本模块 ``embed*`` → 向量库（pgvector/JSON）
  用户 query → ``search_vector`` / hybrid → 本模块 ``embed(query)`` → ANN/BM25 融合

不在本模块：切块策略（``chunking``）、存储与 ANN（``pgvector_store`` / ``vector_index``）。
"""

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
    """嵌入器协议：单条与批量向量化接口。"""

    def embed(self, text: str) -> list[float]:
        ...

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        ...


_embedder: Embedder | None = None
_embedder_key: tuple[str, str, str, int] | None = None


def tokenize(text: str) -> list[str]:
    """分词：拉丁词 + CJK 字/2–3 gram，供 HashEmbedder 与 BM25 共用。

    参数:
        text: 原始文本。
    返回:
        小写 token 列表（含 CJK n-gram）。
    """
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
    """确定性 bag-of-words 哈希嵌入（默认后端，无额外依赖）。

    参数（构造）:
        dimensions: 哈希桶维度，默认 256。
    """

    def __init__(self, *, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        """单条文本 → L2 归一化向量。

        参数:
            text: 待嵌入文本。
        返回:
            长度为 ``dimensions`` 的 float 列表。
        """
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
        """批量嵌入，逐条调用 ``embed``。"""
        return [self.embed(text) for text in texts]


class SentenceTransformerEmbedder:
    """可选神经嵌入（需安装 sentence-transformers）。

    bge-m3 等长上下文模型默认截断至 512 token，避免 GPU 显存打满。
    """

    # bge-m3 hub default is 8192; that pads/activates like a long-context model and
    # saturates ~16GiB cards at modest batch sizes. Chunked corpora + C-MTEB small
    # docs are far shorter — 512 is the usual dense-retrieval truncate.
    _BGE_M3_DEFAULT_MAX_SEQ = 512

    def __init__(self, model_name: str, *, model_dir: str | None = None) -> None:
        """加载 ST 模型；优先本地 cache，miss 时再拉 Hub。

        参数:
            model_name: HuggingFace 模型 id。
            model_dir: 可选本地 cache 目录。
        """
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
        """限制 ST ``max_seq_length`` 以提升吞吐（不改权重）。"""
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
        """解析运行设备：``embedding_device`` 强制或自动探测 CUDA。"""
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
        """单条 query/段落嵌入。"""
        vectors = self.embed_many([text])
        return vectors[0] if vectors else []

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """批量 encode，``normalize_embeddings=True``。"""
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
    """统一调用嵌入器的批量/单条接口，支持 query/index 优先级 lane。

    参数:
        embedder: 实现 ``Embedder`` 或 lane 包装后的实例。
        texts: 待嵌入字符串序列。
        lane: ``LANE_QUERY`` / ``LANE_INDEX``；None 时默认 query 优先。
    返回:
        与 ``texts`` 等长的向量列表。
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
    """两向量余弦相似度；维数不匹配或零向量时返回 0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def effective_embedding_dimensions() -> int:
    """解析当前配置下的向量维度（写入 pgvector ``vector(d)`` / JSON）。

    返回:
        Hash 默认 256；gte-small/MiniLM → 384；bge-m3/gte-large → 1024。
        常见误配（ST 后端仍留 256）会自动纠正并打日志。
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
    """嵌入空间变更时的 INDEX 版本号（scope stamp / JSON ``version``）。

    返回:
        8=MiniLM@384；9=gte-small@384；10=gte-large@1024；
        11=bge-m3@1024 长序列；12=bge-m3 截断 512；13=512+对齐切块/标题/表格行。
        若 ``settings.embedding_index_version`` 已设则优先使用，与控制台计划对齐。
    """
    configured = int(getattr(settings, "embedding_index_version", 0) or 0)
    if configured > 0:
        return configured
    model = (settings.embedding_model or "").lower()
    dims = effective_embedding_dimensions()
    if "bge-m3" in model:
        # Match resolve_embedding_profile: GPU default truncates to 512 → INDEX 13.
        max_seq = int(getattr(settings, "embedding_max_seq_length", 0) or 0)
        if max_seq <= 0 or max_seq == 512:
            return 13
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
    """清空进程级 embedder 单例（测试或配置热重载）。"""
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
    """返回与当前 settings 匹配的进程级 embedder 单例（冷启动可能数分钟）。"""
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


def peek_hf_tokenizer():
    """返回已加载 ST 的 HF tokenizer；未加载模型时为 None（不触发加载）。"""
    model = getattr(_embedder, "_model", None) if _embedder is not None else None
    tok = getattr(model, "tokenizer", None)
    return tok


def warmup_embedder() -> str:
    """启动时预热 embedder，避免首条索引/检索冷启动。

    返回:
        日志用短标签，如 ``sentence_transformers:SentenceTransformerEmbedder``。
        retrieval extra 缺失时记 warning 并回退 hash；其它错误抛出。
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
