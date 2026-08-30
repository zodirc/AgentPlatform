"""文本嵌入与向量维度解析（RAG 索引/检索链路的「字符串 → 稠密向量」层）。

English: Index/query vectorization — Hash or SentenceTransformer backends,
process-singleton ``get_embedder()``, dimension / index-version stamps.
Not on the search hot path for *loading* weights (cold start is startup/sync);
``embed(query)`` *is* on the search path once the model is warm.

=============================================================================
职责边界
=============================================================================
- **本模块**：``Embedder`` 协议；Hash / ST 实现；``embed`` / ``embed_many``；
  进程级单例；``effective_embedding_dimensions`` / ``effective_index_version``。
- **不在本模块**：切块与 ``build_embed_text``（``chunking``）、延迟批量赋向量
  （``index_embed``）、ANN/BM25 存储（``pgvector_store`` / ``vector_index``）、
  query/index 双 lane 调度（``embedding_lanes``，本模块 ``get_embedder`` 外包）。

=============================================================================
切好的 chunk 如何进入本模型（索引侧心智模型）
=============================================================================
上游 ``chunk_source_text`` 产出的是 **chunk 业务记录**（``text`` / 元数据），
不是向量。进入本模块前必须先变成**字符串**：

::

  chunk.text          → 给人看 / BM25 / excerpt（干净正文）
  build_embed_text()  → 标题面包屑 + 可选 path/tags + part
  embed_many(...)     → 本模块 encode → list[float] 固定维
  chunk["vector"]     → 写入 pgvector / JSON（与 text 并存）

两条写入时机（内容相同，吞吐不同）::

  embed=True   同步：切完立刻 ``embed_many(embedder, embed_inputs)``
  embed=False  延迟：只挂 ``embed_input``，sync 末由
               ``index_embed.assign_deferred_vectors`` 批量 encode（LANE_INDEX）

不变量（读代码时优先记住）::

  - 输入是字符串，**不是**整份 chunk JSON。
  - 输出维数固定（256 / 384 / 1024），与 chunk 文本长短无关；
    短窗仍得满维稠密向量，语义覆盖面更窄，不是「更短的向量」。
  - ST 侧 ``normalize_embeddings=True`` → 下游可用点积 ≈ 余弦。
  - bge-m3 默认 ``max_seq_length=512`` 截断（权重不变）；切块 ~450 tok
    与此对齐，避免长上下文显存打满。

检索侧：``get_embedder().embed(query)`` 与索引共用同一后端/维数/版本 stamp；
模型或截断策略变更 → ``effective_index_version`` 升高 → 全量重嵌。

=============================================================================
两种后端：当前配置下谁在用、各自作用
=============================================================================
**同一职责**：``build_embed_text`` 字符串 → 固定维 L2 归一化 ``list[float]`` →
写入 ``chunk["vector"]`` / 检索 query 向量 → pgvector ANN 或 hybrid 点积。
接口相同（``Embedder``），**不是**两套检索系统；``_build_embedder`` 按
``settings.embedding_backend`` 二选一实例化。

当前仓库里的**实际分工**（见 ``settings``、``deploy/compose``、
``scripts/resolve_embedding_profile.sh``）::

  环境                              backend              实现类              模型 / 维数
  ─────────────────────────────────────────────────────────────────────────────────────
  make up / retrieval compose       sentence_transformers  ST Embedder       GPU→bge-m3@1024
  (embedding.auto.env)                                                         CPU→gte-small@384
  CI · 单测 · runtime-lite          hash                 HashEmbedder        无 HF；测试常 64d
  裸 import（未加载 compose env）   hash（settings 默认） HashEmbedder        256d（或 env 维数）

**HashEmbedder — 词面哈希向量（非语义）**

  · 算法：``tokenize`` → 每 token ``blake2b`` 落桶计数 → L2 归一化。
  · 检索行为：近似 **词袋 / 字面重合**；同义换说法、跨语言 paraphrase 几乎无效。
  · 工程价值：零 GPU、零 HuggingFace、毫秒级、进程重启后向量**确定**（不用
    ``hash()``，避免 salt 导致持久化失效）。
  · **不承担**产品 RAG 召回质量；用于 CI 跑通索引/检索/pgvector 全链路。

**SentenceTransformerEmbedder — 产品 RAG 的实际向量化**

  · ``make up`` 时 ``resolve_embedding_profile`` 写 ``EMBEDDING_BACKEND=
    sentence_transformers``；模型按 CUDA 自动解析：
      - VRAM ≥ 8192（或 ``RUNTIME_GPU=1``）→ ``BAAI/bge-m3`` · 1024-d · INDEX≈13
        · ``max_seq_length=512`` · batch≈128 · ``EMBEDDING_DEVICE=cuda``
      - 否则 → ``thenlper/gte-small`` · 384-d · INDEX≈9 · CPU · batch≈64
  · 算法：预训练 Transformer ``encode``，``normalize_embeddings=True``。
  · 检索行为：**语义相近**即可命中（不限于相同词）；bge-m3 覆盖中英混合语料。
  · 冷启动加载权重可能数分钟；``chunk_split`` 可经 ``peek_hf_tokenizer`` 共用
    同一 BPE 计 ~450 token 窗。

**切 backend / 模型后**：维数或向量空间变 → ``effective_index_version`` 变 →
须全量 re-embed；Hash 与 ST 向量**不可混存**于同一 INDEX stamp。

链路位置::

  sources 切块 → build_embed_text → 本模块 embed* → 向量库
  用户 query   → search_vector / hybrid → 本模块 embed(query) → ANN 融合
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
    """嵌入器协议：单条与批量「字符串 → 稠密向量」。

    English: Contract for index-time chunk strings and query-time search text.
    Implementations must return L2-ready float lists of equal length per call.
    """

    def embed(self, text: str) -> list[float]:
        ...

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        ...


_embedder: Embedder | None = None
_embedder_key: tuple[str, str, str, int] | None = None


def tokenize(text: str) -> list[str]:
    """分词：拉丁词 + CJK 字/2–3 gram。

    English: Shared tokenizer for HashEmbedder buckets and BM25 indexing —
    keeps lexical hash vectors aligned with sparse retrieval vocabulary.

    Hash 路径专用：神经 embedder 走 HF tokenizer，不经本函数。
    CJK 2–3 gram 弥补无空格中文在纯词切分下的召回盲区。

    参数:
        text: 原始文本（通常为 ``build_embed_text`` 或 query）。
    返回:
        小写 token 列表（含 CJK n-gram，顺序即首次出现顺序）。
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
    """词面哈希嵌入 — CI / lite / 无 compose env 时的 ``embedding_backend=hash`` 实现。

    English: Lexical bag-of-words via blake2b hashing — not semantic retrieval.
    Product RAG uses ``SentenceTransformerEmbedder`` instead (see module docstring).

    =============================================================================
    当前配置下的位置
    =============================================================================
    · **不会**出现在 ``make up`` 后的产品 runtime（compose 固定
      ``EMBEDDING_BACKEND=sentence_transformers``）。
    · **会**出现在：``.github/workflows/ci.yml``、``runtime-lite.yml``、
      ``tests/conftest.py``（强制 hash@64d）、裸 ``settings`` 默认。

    =============================================================================
    算法与检索语义
    =============================================================================
    ``tokenize(text)`` → 每个 token 映射到 ``dimensions`` 个桶之一（blake2b，
    跨进程稳定）→ 桶内 +1 → L2 归一化 → ``list[float]``。

    相似度 ≈ **共有 token 的重合度**，不是 Transformer 语义空间：
    「删除向量」与「移除 embedding」若词不同，向量可能几乎正交。

    =============================================================================
    与 ST 路径的接口对齐
    =============================================================================
    同样实现 ``embed`` / ``embed_many``；输出维数由 ``effective_embedding_dimensions``
    决定（hash 时通常 256，测试可压到 64）。下游 pgvector / hybrid **不区分**
    实现类，只认维数与 INDEX stamp。

    参数（构造）:
        dimensions: 哈希桶数 = 向量长度（默认 256；compose 未加载时随 settings）。
    """

    def __init__(self, *, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        """单条文本 → L2 归一化哈希向量。

        参数:
            text: ``build_embed_text`` 产物或用户 query（与 ST 路径相同输入形状）。
        返回:
            长度恒为 ``self.dimensions``；空/无 token 时返回零向量（不归一化除零）。
        """
        vec = [0.0] * self.dimensions
        for token in tokenize(text):
            # blake2b (not built-in hash): deterministic across processes/restarts so
            # persisted hash embeddings stay valid after runtime recycle.
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
        """逐条 ``embed``；CI 索引路径常一次送入整文件 ``embed_inputs`` 列表。"""
        return [self.embed(text) for text in texts]


class SentenceTransformerEmbedder:
    """神经语义嵌入 — 产品 RAG（``make up`` / retrieval compose）的实际向量化后端。

    English: HuggingFace SentenceTransformer loaded once per process; semantic
    dense vectors for ``search_sources`` recall quality. Requires retrieval extra.

    =============================================================================
    当前配置下的模型解析（resolve_embedding_profile.sh）
    =============================================================================
    ``EMBEDDING_BACKEND=sentence_transformers``（compose 默认，非 hash）::

      CUDA 且 VRAM ≥ 8192（或 RUNTIME_GPU=1）
        模型   BAAI/bge-m3
        维数   1024
        设备   cuda（``embedding.auto.env``）
        截断   max_seq_length=512（hub 默认 8192 会打满 16G 显存）
        batch  默认 128
        INDEX  ≈13

      无可用 GPU / RUNTIME_GPU=0
        模型   thenlper/gte-small
        维数   384
        设备   CPU（``embedding_torch_num_threads`` 默认 2，避免饿死 event loop）
        batch  默认 64
        INDEX  ≈9

    权重目录：``settings.embedding_model_dir``（默认 ``/data/models``）；
    构造时 ``local_files_only=True`` 优先，cache miss 再拉 Hub。

    =============================================================================
    算法与检索语义
    =============================================================================
    ``model.encode(texts, normalize_embeddings=True)`` → 语义稠密向量。
    相近**含义**的 chunk 与 query 在内积空间靠近，不要求字面相同；
    bge-m3 面向中英混合 seed + BEIR/C-MTEB 语料。

    输入字符串仍来自 ``build_embed_text``（标题面包屑 + part）；
    超长串由 ``max_seq_length`` 在模型侧截断 —— 切块 ~450 tok 即为此对齐。

    =============================================================================
    与 Hash 的切换
    =============================================================================
    二者向量空间不兼容；换 backend 或换 model 必须 bump INDEX 并全量 re-embed。
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
        """限制 ST ``max_seq_length``（吞吐/显存；**不改**模型权重）。

        当前策略:
            · ``settings.embedding_max_seq_length > 0`` → 强制该值
            · bge-m3 且未配置 → 512（``_BGE_M3_DEFAULT_MAX_SEQ``，与切块对齐）
            · gte-small → 保持模型默认（profile 写 ``EMBEDDING_MAX_SEQ_LENGTH=0``）
        """
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
        """单条嵌入（检索 query 或单 chunk）；内部走 ``embed_many``。"""
        vectors = self.embed_many([text])
        return vectors[0] if vectors else []

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """批量 ``SentenceTransformer.encode``：切块后的主向量化入口。

        English: This is where chunk strings become dense vectors. Callers
        pass ``build_embed_text`` outputs (or deferred ``embed_input`` lists),
        not raw chunk dicts.

        行为:
            - ``normalize_embeddings=True`` → 单位向量，ANN 可用内积当余弦。
            - ``batch_size`` 来自 ``settings.embedding_batch_size``（默认 64）。
            - 超 ``max_seq_length`` 的字符串由模型侧截断，不在此二次切块。
        返回:
            与 ``texts`` 等长的 ``list[list[float]]``；维数由模型决定
            （见 ``effective_embedding_dimensions``）。
        """
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
    """统一批量嵌入入口（切块同步路径与 ``index_embed`` 延迟路径共用）。

    English: Preferred call site for «chunk strings → vectors». Wraps
    ``embedder.embed_many`` / ``embed``, and forwards optional priority
    ``lane`` when the singleton is wrapped by ``PriorityLaneEmbedder``.

    典型调用方:
        - ``chunk_source_text(..., embed=True)`` — 文件切完立刻向量化
        - ``assign_deferred_vectors`` — sync 缓冲后批量向量化（``LANE_INDEX``）
        - doc2query / 文档摘要向量（JSON 索引平面）

    参数:
        embedder: ``Embedder`` 或 lane 包装后的实例（通常 ``get_embedder()``）。
        texts: ``build_embed_text`` / ``embed_input`` 字符串序列，**非** chunk dict。
        lane: ``LANE_QUERY`` / ``LANE_INDEX``；``None`` → 默认 query 优先。
    返回:
        与 ``texts`` 等长的向量列表；空输入 → ``[]``。
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
    """解析当前配置下 pgvector ``vector(d)`` / JSON 应使用的维数。

    English: Coerces common misconfigs when ST or remote backend is active.
    Hash backend returns ``settings.embedding_dimensions`` unchanged.

    当前 compose / profile 下的典型值:
        · ``hash`` backend          → env 维数（CI 64；settings 默认 256）
        · ``gte-small`` / MiniLM    → **384**（即使 env 仍写 256 也会纠正）
        · ``bge-m3`` / ``gte-large``→ **1024**
        · ``remote``                → 按 ``embedding_model`` 名与 ST 相同规则

    返回:
        写入索引平面的向量长度；须与 ``get_embedder()`` 实际输出一致。
    """
    dims = int(settings.embedding_dimensions)
    backend = (settings.embedding_backend or "").lower()
    model = (settings.embedding_model or "").lower()
    if backend in {"sentence_transformers", "minilm", "neural", "remote"}:
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
    """嵌入空间变更时的 INDEX 版本 stamp（触发全量 re-embed）。

    English: Bumps when model, truncate policy, or chunk/embed text pipeline
    changes make old vectors incompatible with new queries.

    当前 profile 解析结果（``EMBEDDING_INDEX_VERSION`` 未显式覆盖时）::

        8   MiniLM @384（遗留）
        9   gte-small @384          ← CPU ``make up`` 默认
        10  gte-large @1024
        11  bge-m3 @1024 长序列（max_seq ≠ 512）
        13  bge-m3 @1024 + max_seq=512 + 对齐切块  ← GPU ``make up`` 默认

    若 ``settings.embedding_index_version > 0`` 则优先（与控制台计划对齐）。
    **Hash 与 ST 切换、或 gte-small ↔ bge-m3 切换，必须 version 不同。**
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
    """按 ``settings.embedding_backend`` 构造裸 Embedder（尚未包 lane）。

    English: Factory for Hash / ST / remote backends. Product orchestrator uses
    ``remote`` → sources-retrieval; retrieval service uses ST (ADR-020).

    分支（读 env / compose，不是运行时探测）::

        embedding_backend ∈ {remote}
            → ``RemoteEmbedder`` → HTTP ``SOURCES_RETRIEVAL_URL``

        embedding_backend ∈ {sentence_transformers, minilm, neural}
            → ``SentenceTransformerEmbedder(settings.embedding_model)``
            → 需 retrieval extra；CPU 上 ``torch.set_num_threads`` 限流

        其它（含默认 ``hash``）
            → ``HashEmbedder(dimensions=effective_embedding_dimensions())``
            → CI / lite / 无 compose env 的裸进程

    lane 包装在 ``get_embedder()`` 的 ``maybe_wrap_lanes``，不在此函数。
    """
    backend = settings.embedding_backend.lower()
    if backend == "remote":
        from app.retrieval.remote_embedder import RemoteEmbedder

        return RemoteEmbedder()
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
    """清空进程级 embedder 单例（测试或配置热重载后强制重建）。"""
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
    """进程级 embedder 单例：切块写入与 ``search_vector`` 共用同一模型。

    English: Lazy-loads Hash or ST once per (backend, model, dir, dims) key,
    then wraps with ``maybe_wrap_lanes`` so index batches yield to query embeds.

    冷启动（首次 ST 加载）可能数分钟；sync 路径会推迟到确有 dirty 文件再调。
    settings 变更 → cache key 变 → 自动重建。
    """
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

    # 为何在裸 Embedder 外再包一层 PriorityLaneEmbedder（lane 包装）：
    #
    # 同一进程、同一 ST/Hash 实例同时服务两条热路径——
    #   · LANE_INDEX：sources sync 批量 embed 切块（``assign_deferred_vectors``，可持续数分钟）
    #   · LANE_QUERY：``search_sources`` / hybrid 对用户 query 做单条 embed（交互延迟敏感）
    # encode 是 CPU/GPU 重活且底层模型通常串行 batch；若无调度，长索引 batch 会占满 worker，
    # 检索 query 只能排队 → search 尾延迟劣化（与向量是否正确无关，是吞吐/优先级问题）。
    #
    # 包装器 = 单后台线程 + 优先级堆：lane 数字小者优先（QUERY=0 < INDEX=1），
    # index batch 之间 ``sleep(0)`` 让出调度，使已排队的 query 能插队。
    # 裸实现（``_build_embedder``）只管选后端与 ``encode``；lane 是跨路径的 QoS 层，可经
    # ``embedding_query_priority=False`` 关闭（测试或单用途进程）。
    # remote：lane QoS 在 sources-retrieval 进程内；编排侧直连 HTTP，不再套本地 lane。
    inner = _build_embedder()
    if backend == "remote":
        _embedder = inner
    else:
        _embedder = maybe_wrap_lanes(inner)
    _embedder_key = key
    logger.info(
        "embedder ready; backend=%s elapsed_s=%.1f model_dir=%s",
        backend,
        time.monotonic() - t0,
        model_dir or "(default)",
    )
    return _embedder


def peek_hf_tokenizer():
    """返回已加载 ST 的 HF tokenizer；未加载时为 ``None``（**不**触发加载）。

    供 ``chunk_split`` 按与 embedder 同一 tokenizer 计量 ~450 token 窗，
    避免「切块用字数、模型用 BPE」两套尺子。
    """
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
