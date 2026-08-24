"""Postgres + pgvector 源文档检索存储（RAG 持久化与查询后端）。

English: Index-plane persistence + query — sync writes vectors/FTS rows;
search reads ANN (HNSW) + GIN (FTS) + hybrid fusion. Not on Turn hot path.

=============================================================================
职责边界
=============================================================================
- **本模块**：DDL（三表 + HNSW + FTS GIN）；``sync`` 切块→embed→落库→索引维护；
  ``search*`` 向量/BM25/hybrid/doc lane。
- **不在本模块**：切块/embed 细节（``chunking`` / ``embedder`` / ``index_embed``）、
  Turn 内 ``search_sources`` 工具编排（``tools``）、Ops 独立 schema（``ops_plane``）。

=============================================================================
sync 写入链（embed 之后 — 读代码时的主心智模型）
=============================================================================
``sync`` 把上游 ``chunk_source_text(embed=False)`` 的 ``embed_input`` 变成库内可检索行。
**没有**单独的 Python「建图 API」；HNSW / GIN 是 PostgreSQL 索引，行为如下：

::

  phase=chunk     chunk_source_text → pending_jobs（仅 embed_input）
  phase=embed     _flush_buffer → assign_deferred_vectors → chunk["vector"]
  phase=write     同一 _flush_buffer 内：
                    DELETE 旧 chunk（按 path）
                    UPSERT source_files（mtime / chunk_count / ACL）
                    UPSERT source_chunks（text + embedding 列）
                    UPSERT source_docs（同 path 的 chunk 向量 centroid）
                    UPDATE bm25_extra（path → chunk，供 FTS C 权）
                  conn.commit()  →  pgvector/Postgres 维护 HNSW 边（增量）
  phase=index     force reindex：写前 DROP HNSW，全部写完 _ensure_embedding_hnsw 重建
                  增量：sync 末 _ensure_embedding_hnsw（IF NOT EXISTS，补建）

HNSW 参数（本仓库未写 ``WITH``，用 pgvector 默认 m=16 / ef_construction=64；
查询默认 ef_search=40，生产仅覆盖 iterative_scan / max_scan_tuples —— 见
``_ensure_embedding_hnsw`` / ``_prepare_hnsw_filtered_scan`` docstring）::

  建图期（CREATE INDEX，不可事后改）     查询期（SET LOCAL，可 per-query）
  m=16  每层最大连边                    ef_search=40（默认，prod 未动）
  ef_construction=64  建图候选池         iterative_scan=relaxed_order（我们设）
  vector_cosine_ops  余弦距离            max_scan_tuples=max(20k, limit×500)

FTS GIN（``source_chunks_text_fts_idx``）在 ``ensure_schema`` 一次性创建/版本升级重建，
不在每个 flush 里建；chunk UPSERT 更新 ``text``/``section_title``/``bm25_extra`` 后
由 Postgres 维护 GIN 倒排。``bm25_extra`` 正文来自离线 ``doc2query``（RET-11b）。

检索消费（``search_sources`` 热路径，只读）::

  chunk lane   ORDER BY embedding <=> query   （HNSW + iterative_scan 过滤 seed/work）
  doc lane     source_docs 同上（centroid ANN，最多 8 path）
  BM25 lane    BM25_TSVECTOR_SQL @@ tsquery  （GIN）
  hybrid       RRF 融合 + 词法精排 + doc_boost → 工具层 cover/tier/L3

=============================================================================
查询面（``search_hybrid`` — 索引建完后的 read path）
=============================================================================
入口: ``store.search(mode=hybrid)`` → ``PgvectorSourceRetrievalStore.search_hybrid``。
**只读** — 不 ``sync``、不 ``CREATE INDEX``；消费 sync 写入的 HNSW/GIN/行数据。

典型 ``limit`` 与深度::

  search_sources 传入 limit≈30，store 常 over-fetch (×2/×3)
  hybrid 内 lane 深度 top_k = max(limit×4, 20) [rerank 时 ≥ rerank_pool]

并行与串行::

  parallel_two_level(doc ∥ chunk)     ← 两线程，预算 ~0.3s（profile）
  chunk 内: vector ∥ bm25 同线程顺序执行 → RRF → rerank

审计（``audit.begin_audit_capture`` 在 ``search_sources`` 开启）::

  L1a  record_lane_hits        vector/bm25 分榜（融合前）
  L1   record_recall_pool      RRF 后、rerank 前
  L2   record_ranked           rerank 后（method=lexical/none/…）
  L3   在 tools/sources_search  format/tier 后进 tool_result（非本模块）

链路位置::

  index_scheduler / sync_cli → sync → DB
  search_sources → get_sources_store → search_vector / search_hybrid
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.retrieval.bm25 import BM25Scorer
from app.retrieval.bm25_document import (
    BM25_EXTRA_FTS_VERSION,
    BM25_TSVECTOR_SQL,
    build_weighted_or_tsquery,
)
from app.retrieval.chunking import chunk_source_text, should_index_source
from app.retrieval.embedder import (
    effective_embedding_dimensions,
    effective_index_version,
    get_embedder,
)
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.rerank import rerank_hits
from app.retrieval.vector_index import ChunkHit, _chunk_to_hit
from app.settings import settings

logger = logging.getLogger(__name__)

_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Per-scope stamp fields (RET-4 / Ops BEIR). Global ``version`` alone is not enough:
# seed sync writing INDEX 9 must not mark FiQA/SciFact works as already re-embedded.
_SCOPE_STAMP_FIELDS = (
    "version",
    "embedding_model",
    "embedding_dimensions",
    "embedding_backend",
)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in values) + "]"


_CHUNK_HNSW = "source_chunks_embedding_hnsw"
_DOCS_HNSW = "source_docs_embedding_hnsw"


def _drop_embedding_hnsw(cur: Any) -> None:
    """删除 chunk/doc 两张 HNSW 索引（force reindex 批量写表前）。

    English: Bulk UPSERT with live HNSW is slow — each row updates the graph.
    Drop both indexes, load rows, recreate at sync end via ``_ensure_embedding_hnsw``.

    仅 ``sync(force_reindex)`` 在写库前调用；增量 sync 不 drop。
    """
    cur.execute(f"DROP INDEX IF EXISTS {_CHUNK_HNSW}")
    cur.execute(f"DROP INDEX IF EXISTS {_DOCS_HNSW}")


def _ensure_embedding_hnsw(cur: Any) -> None:
    """确保 pgvector HNSW 余弦索引存在（chunk 主车道 + doc centroid 车道）。

    English: ``CREATE INDEX IF NOT EXISTS ... USING hnsw (embedding vector_cosine_ops)``.
    Incremental sync: index already exists → pgvector maintains graph on UPSERT.
    Force reindex: called after bulk load to rebuild from scratch.

    =============================================================================
    我们显式配置的 vs pgvector 默认（镜像 ``pgvector/pgvector:pg16``）
    =============================================================================
    **本仓库 DDL 只指定** index method + 距离算子；**未**写 ``WITH (m=…, ef_construction=…)``，
    建图算法与下列默认值均由扩展 ``src/hnsw.h`` 决定（随镜像内 pgvector 版本，通常如下）：

    建图期（``CREATE INDEX`` 时固定，之后不可改，除非 DROP + 重建）::

      参数              默认    合法范围        含义
      m                 16      2–100           每层每节点最大双向连边数；↑ recall/索引体积/建图耗时
      ef_construction   64      4–1000 (≥2×m)  插入时每点扩展的候选邻居数；↑ 图质量/建图耗时

    查询期（session GUC，见 ``_prepare_hnsw_filtered_scan``；生产未改 ``ef_search``）::

      hnsw.ef_search           40      1–1000   贪心搜索候选池；↑ recall/延迟（bench 脚本可观测）
      hnsw.iterative_scan      off     off|strict_order|relaxed_order
      hnsw.max_scan_tuples     20000   …        iterative 模式最多扫描 heap 行数

    **为何 ``vector_cosine_ops``**：ST ``normalize_embeddings=True`` → 单位向量，
    余弦距离 ``<=>`` 与内积排序一致；维数由 ``effective_embedding_dimensions``（384/1024）。

    **建图何时发生**：(1) 空表上首次 ``CREATE INDEX`` → 空图骨架；(2) 已有行上
    ``CREATE INDEX``（force reindex 末）→ 全表扫描离线建图；(3) 索引已存在时的
    UPSERT → 扩展增量插入节点（非 Python 侧逻辑）。
    """
    # DDL：无 WITH → m=16, ef_construction=64（pgvector 默认，见本函数 docstring）。
    cur.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_CHUNK_HNSW}
        ON source_chunks
        USING hnsw (embedding vector_cosine_ops)
        """
    )
    cur.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_DOCS_HNSW}
        ON source_docs
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def _chunk_vectors_centroid(vectors: list[list[float]]) -> list[float] | None:
    """单文件内 chunk 嵌入的算术均值 → doc lane 用 ``source_docs.embedding``。

    English: P3 two-level retrieval — doc HNSW returns paths; chunk HNSW returns
    excerpts. Centroid is not re-embedded; mean of chunk vectors in embed space.

    参数:
        vectors: 同维 ``list[float]`` 列表（通常来自同一 ``storage_path`` 的 flush batch）。
    返回:
        与 chunk 同维的均值向量；空或维数不齐 → ``None``（跳过 doc UPSERT）。
    """
    if not vectors:
        return None
    dim_n = len(vectors[0])
    if dim_n <= 0:
        return None
    if any(not isinstance(v, list) or len(v) != dim_n for v in vectors):
        return None
    return [sum(float(v[i]) for v in vectors) / len(vectors) for i in range(dim_n)]


def _safe_schema(name: str) -> str:
    raw = (name or "public").strip() or "public"
    if not _SCHEMA_RE.match(raw):
        raise ValueError(f"invalid retrieval_pg_schema: {name!r}")
    return raw


def index_scope_id(*, work_id: str | None, visibility: str) -> str:
    """生成 per-work/seed 索引 stamp 的稳定 scope id。

    参数:
        work_id: Work UUID 字符串；seed 时为 None。
        visibility: ``seed`` | ``private`` 等。
    返回:
        ``seed``、``private-unscoped`` 或 ``work:{id}``。
    """
    vis = (visibility or "private").strip() or "private"
    if vis == "seed":
        return "seed"
    wid = (work_id or "").strip()
    if not wid:
        return "private-unscoped"
    return f"work:{wid}"


def scope_meta_key(scope_id: str, field: str) -> str:
    """``source_index_meta`` 中 scope 字段键名。"""
    return f"scope:{scope_id}:{field}"


def current_index_stamp() -> dict[str, str]:
    """当前嵌入空间指纹；增量 sync 跳过条件。

    返回:
        version、embedding_model、dimensions、backend 四元组字符串 dict。
    """
    return {
        "version": str(effective_index_version()),
        "embedding_model": (settings.embedding_model or "").strip(),
        "embedding_dimensions": str(effective_embedding_dimensions()),
        "embedding_backend": (settings.embedding_backend or "").strip(),
    }


def scope_stamp_mismatch(stored: dict[str, str], current: dict[str, str] | None = None) -> bool:
    """scope 从未 stamp 或嵌入空间与当前配置不一致时为 True（触发 force reindex）。"""
    want = current or current_index_stamp()
    for field in _SCOPE_STAMP_FIELDS:
        got = (stored.get(field) or "").strip()
        if not got:
            return True
        if got != (want.get(field) or "").strip():
            return True
    return False


def _read_scope_stamp(cur: Any, scope_id: str) -> dict[str, str]:
    prefix = f"scope:{scope_id}:"
    cur.execute(
        "SELECT key, value FROM source_index_meta WHERE key LIKE %s",
        (prefix + "%",),
    )
    out: dict[str, str] = {}
    for key, value in cur.fetchall():
        field = str(key)[len(prefix) :]
        if field in _SCOPE_STAMP_FIELDS:
            out[field] = str(value)
    return out


def _write_scope_stamp(cur: Any, scope_id: str, stamp: dict[str, str] | None = None) -> None:
    want = stamp or current_index_stamp()
    for field in _SCOPE_STAMP_FIELDS:
        cur.execute(
            """
            INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (scope_meta_key(scope_id, field), want[field]),
        )
    # Global keys: observability + legacy readers (not used alone for force_reindex).
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ("version", want["version"]),
    )
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ("embedding_model", want["embedding_model"]),
    )
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ("embedding_dimensions", want["embedding_dimensions"]),
    )
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ("embedding_backend", want["embedding_backend"]),
    )
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ("updated_at", datetime.now(UTC).isoformat()),
    )


def _read_reindex_epoch(cur: Any, scope_id: str) -> float | None:
    cur.execute(
        "SELECT value FROM source_index_meta WHERE key = %s",
        (scope_meta_key(scope_id, "reindex_epoch"),),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def _write_reindex_epoch(cur: Any, scope_id: str, epoch: float) -> None:
    cur.execute(
        """
        INSERT INTO source_index_meta (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        (scope_meta_key(scope_id, "reindex_epoch"), f"{float(epoch):.6f}"),
    )


def _clear_reindex_epoch(cur: Any, scope_id: str) -> None:
    cur.execute(
        "DELETE FROM source_index_meta WHERE key = %s",
        (scope_meta_key(scope_id, "reindex_epoch"),),
    )


def _prepare_hnsw_filtered_scan(cur: Any, *, limit: int) -> None:
    """查询前调整 pgvector HNSW 会话 GUC（共享图 + ACL 后过滤）。

    English: Shared HNSW graph holds seed + many private works. Plain
    ``ORDER BY <=> LIMIT k`` post-filtered by ``work_id`` can yield 0 hits when
    global NN are all seed rows.

    =============================================================================
    默认 vs 本函数覆盖（查询期，不改索引结构）
    =============================================================================
    生产 ``search_vector`` / ``_search_docs_ann`` 在每条 ANN SQL 前调用本函数。

    | GUC | pgvector 默认 | 本仓库 |
    |-----|---------------|--------|
    | ``hnsw.ef_search`` | **40** | **未改**（需更高 recall 可 ``SET LOCAL``；见 ``p4_hnsw_ef_search_calib.py`` 观测脚本，不改 prod） |
    | ``hnsw.iterative_scan`` | **off** | **relaxed_order** — 过滤后候选不足时继续扫 heap |
    | ``hnsw.max_scan_tuples`` | **20000** | **max(20000, limit×500)** — seed 占全局近邻时给 FiQA 级 work 留 headroom |

    ``ef_search`` 应 ≥ SQL ``LIMIT``；top_k 常 240+ 时默认 40 偏保守，靠 iterative_scan
    补召回而非全局抬高 ``ef_search``（避免所有查询延迟上涨）。

    参数:
        limit: 本次 ANN ``LIMIT``；用于推导 ``max_scan_tuples`` 下限。
    """
    try:
        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        max_tuples = max(20_000, int(limit) * 500)
        cur.execute(f"SET LOCAL hnsw.max_scan_tuples = {max_tuples}")
    except Exception:
        logger.debug("hnsw.iterative_scan unavailable; continuing", exc_info=True)


class PgvectorSourceRetrievalStore:
    """Postgres + pgvector ANN 检索后端。

    写入仅经 ``sync``（worker/admin）；查询路径只读 schema + ANN/FTS，不重建索引。
    """

    backend = "pgvector"

    def __init__(
        self,
        database_url: str,
        *,
        dimensions: int | None = None,
        schema: str | None = None,
    ) -> None:
        """参数:
            database_url: psycopg 连接串。
            dimensions: 向量维数；None 时从 ``effective_embedding_dimensions`` 解析。
            schema: PG schema；默认 ``settings.retrieval_pg_schema``。
        """
        self._database_url = database_url
        self._schema = _safe_schema(
            schema if schema is not None else settings.retrieval_pg_schema
        )
        if dimensions is not None:
            self._dimensions = int(dimensions)
        else:
            from app.retrieval.embedder import effective_embedding_dimensions

            self._dimensions = effective_embedding_dimensions()
        self._ready = False
        self._chunk_cache: list[dict[str, Any]] = []
        self._chunk_by_id: dict[str, dict[str, Any]] = {}

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "RETRIEVAL_BACKEND=pgvector requires psycopg (pip install psycopg[binary])"
            ) from exc
        conn = psycopg.connect(self._database_url, autocommit=False)
        with conn.cursor() as cur:
            if self._schema != "public":
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            # vector extension lives in public; keep it on the path.
            cur.execute(f"SET search_path TO {self._schema}, public")
            # Fail fast instead of hanging behind orphan idle-in-transaction syncs.
            cur.execute("SET lock_timeout = '15s'")
            cur.execute("SET statement_timeout = '0'")
        conn.commit()
        return conn

    def ensure_schema(self) -> None:
        """创建/迁移表、pgvector 扩展、HNSW 与 FTS GIN（幂等，进程内只跑一次）。

        English: Called at start of ``sync`` and search. Creates three tables:
        ``source_files`` (path metadata), ``source_chunks`` (chunk + embedding + text),
        ``source_docs`` (path-level centroid). HNSW on both embedding columns;
        GIN on ``BM25_TSVECTOR_SQL`` expression (title+body A, bm25_extra C).

        维数变更（256→384 等）会 DROP 三表重建 —— 与 ``scope_stamp_mismatch`` 全量重嵌一致。
        """
        if self._ready:
            return
        dim = self._dimensions
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                # If an older table was created at a different width (e.g. hash 256 → ST 384),
                # embeddings are incompatible — drop and recreate (IX0 / docs/03).
                cur.execute(
                    """
                    SELECT format_type(a.atttypid, a.atttypmod)
                    FROM pg_attribute a
                    JOIN pg_class c ON a.attrelid = c.oid
                    JOIN pg_namespace n ON c.relnamespace = n.oid
                    WHERE n.nspname = %s
                      AND c.relname = 'source_chunks'
                      AND a.attname = 'embedding'
                      AND NOT a.attisdropped
                    """,
                    (self._schema,),
                )
                row = cur.fetchone()
                if row and isinstance(row[0], str) and row[0].startswith("vector("):
                    try:
                        existing = int(row[0].removeprefix("vector(").rstrip(")"))
                    except ValueError:
                        existing = -1
                    if existing != dim:
                        logger.warning(
                            "source_chunks embedding dim %s != configured %s "
                            "(schema=%s); recreating index tables",
                            existing,
                            dim,
                            self._schema,
                        )
                        cur.execute("DROP TABLE IF EXISTS source_chunks CASCADE")
                        cur.execute("DROP TABLE IF EXISTS source_docs CASCADE")
                        cur.execute("DROP TABLE IF EXISTS source_files CASCADE")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS source_files (
                        path TEXT PRIMARY KEY,
                        mtime DOUBLE PRECISION NOT NULL,
                        chunk_count INT NOT NULL DEFAULT 0,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        owner_user_id UUID NULL
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS source_chunks (
                        chunk_id TEXT PRIMARY KEY,
                        path TEXT NOT NULL REFERENCES source_files(path) ON DELETE CASCADE,
                        section_title TEXT NOT NULL DEFAULT '',
                        text TEXT NOT NULL,
                        citation_id TEXT NOT NULL,
                        line_start INT,
                        line_end INT,
                        embedding vector({dim}) NOT NULL,
                        owner_user_id UUID NULL
                    )
                    """
                )
                # IX0: nullable owner prep for IX5 ACL (existing DBs created before this column).
                cur.execute(
                    """
                    ALTER TABLE source_files
                    ADD COLUMN IF NOT EXISTS owner_user_id UUID NULL
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_chunks
                    ADD COLUMN IF NOT EXISTS owner_user_id UUID NULL
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_files
                    ADD COLUMN IF NOT EXISTS work_id UUID NULL
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_chunks
                    ADD COLUMN IF NOT EXISTS work_id UUID NULL
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_files
                    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_chunks
                    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'
                    """
                )
                # RET-11(b): path-level pseudo-queries for BM25 only (not embedded).
                cur.execute(
                    """
                    ALTER TABLE source_files
                    ADD COLUMN IF NOT EXISTS bm25_extra TEXT NOT NULL DEFAULT ''
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE source_chunks
                    ADD COLUMN IF NOT EXISTS bm25_extra TEXT NOT NULL DEFAULT ''
                    """
                )
                self._ensure_bm25_fts_index(cur)
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS source_chunks_path_idx
                    ON source_chunks (path)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS source_chunks_owner_idx
                    ON source_chunks (owner_user_id)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS source_chunks_work_idx
                    ON source_chunks (work_id)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS source_index_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                # P3: path-level centroid for doc-lane HNSW (see _chunk_vectors_centroid).
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS source_docs (
                        path TEXT PRIMARY KEY
                            REFERENCES source_files(path) ON DELETE CASCADE,
                        embedding vector({dim}) NOT NULL,
                        work_id UUID NULL,
                        visibility TEXT NOT NULL DEFAULT 'private',
                        owner_user_id UUID NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS source_docs_work_idx
                    ON source_docs (work_id)
                    """
                )
                _ensure_embedding_hnsw(cur)
            conn.commit()
        self._ready = True

    def _ensure_bm25_fts_index(self, cur: Any) -> None:
        """创建/升级 BM25 用 FTS GIN 索引（RET-11b；不在每次 sync flush 里建）。

        English: Index expression ``BM25_TSVECTOR_SQL`` — weighted tsvector of
        ``section_title||text`` (A) and ``bm25_extra`` (C). Version in
        ``source_index_meta.bm25_extra_fts_version``; bump → DROP + CREATE 全量重建。

        **GIN 无应用层 tunable**：倒排结构由 Postgres ``USING gin(...)`` 默认算法维护；
        表达式权重 A/C 在 ``bm25_document.BM25_TSVECTOR_SQL`` 写死。数据变更后由
        UPSERT/UPDATE 触发行级 GIN 更新（同 HNSW 增量维护，非 Python 逻辑）。

        数据写入：``sync`` flush UPSERT chunk 行（A 权字段）+ 拷贝 ``bm25_extra``（C 权）；
        ``doc2query`` 离线写 ``source_files.bm25_extra``，不嵌入、不进向量列。
        """
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS source_index_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            SELECT value FROM source_index_meta WHERE key = 'bm25_extra_fts_version'
            """
        )
        row = cur.fetchone()
        if row and str(row[0]) == BM25_EXTRA_FTS_VERSION:
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS source_chunks_text_fts_idx
                ON source_chunks
                USING gin ({BM25_TSVECTOR_SQL})
                """
            )
            return
        cur.execute("DROP INDEX IF EXISTS source_chunks_text_fts_idx")
        cur.execute(
            f"""
            CREATE INDEX source_chunks_text_fts_idx
            ON source_chunks
            USING gin ({BM25_TSVECTOR_SQL})
            """
        )
        cur.execute(
            """
            INSERT INTO source_index_meta (key, value) VALUES ('bm25_extra_fts_version', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (BM25_EXTRA_FTS_VERSION,),
        )

    @property
    def is_ready(self) -> bool:
        return self._ready

    def _default_owner_user_id(self) -> str | None:
        raw = (settings.sources_index_owner_user_id or "").strip()
        return raw or None

    def load(self) -> None:
        """预热 schema，不把 chunk 全量载入进程内存。"""
        self.ensure_schema()

    def delete_orphan_private_rows(self) -> dict[str, int]:
        """删除 ``work_id IS NULL`` 的 private 行（MT5c 泄漏面清理）。

        返回:
            ``orphan_chunks_deleted`` / ``orphan_files_deleted`` 计数。
        """
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM source_chunks
                    WHERE visibility = 'private' AND work_id IS NULL
                    """
                )
                chunks = cur.rowcount or 0
                cur.execute(
                    """
                    DELETE FROM source_files
                    WHERE visibility = 'private' AND work_id IS NULL
                    """
                )
                files = cur.rowcount or 0
            conn.commit()
        return {"orphan_chunks_deleted": int(chunks), "orphan_files_deleted": int(files)}

    def sync(
        self,
        sources_dir: Path,
        *,
        workspace_root: Path,
        work_id: str | None = None,
        visibility: str = "private",
        owner_user_id: str | None = None,
    ) -> dict[str, Any]:
        """增量/全量同步 ``sources_dir`` → PostgreSQL（切块·embed·落库·索引）。

        English: Index-plane only (Turn 外). Phases reported via ``sync_progress``:
        chunk → loading_embedder → embed → write → index (HNSW rebuild if force).

        流程概要::

          1. ensure_schema（HNSW/GIN 已存在则跳过 DDL）
          2. scope stamp vs ``current_index_stamp()`` → 增量 or force_reindex
          3. 扫描 mtime → dirty 文件 ``chunk_source_text(embed=False)``
          4. 跨文件缓冲 → ``_flush_buffer``：
               assign_deferred_vectors（embed）
               DELETE+UPSERT 三表 + bm25_extra 拷贝（write）
          5. force：写前 drop HNSW；末 ``_ensure_embedding_hnsw`` + scope stamp

        参数:
            sources_dir: 待扫描源目录。
            workspace_root: 相对路径 / ``index_storage_path`` 前缀。
            work_id: private 必填；seed 为 None。
            visibility: ``seed`` | ``private``（决定 scope_id 与 ACL 列）。
            owner_user_id: 可选行级 owner UUID。
        返回:
            indexed_files、chunks、added/updated/skipped/removed、reindexed、
            ann=hnsw、flush_chunk_cap 等统计。
        """
        import logging
        import time

        from app.retrieval.index_embed import (
            assign_deferred_vectors,
            embedding_batch_size,
            index_commit_every_flushes,
            index_flush_chunk_cap,
            progress_every_files,
        )

        logger = logging.getLogger(__name__)
        self.ensure_schema()
        if not sources_dir.exists():
            return {
                "indexed_files": 0,
                "chunks": 0,
                "added": 0,
                "updated": 0,
                "skipped": 0,
                "removed": 0,
                "backend": self.backend,
            }

        from app.retrieval.tenant_visibility import index_storage_path

        # Defer get_embedder() until dirty work is known — cold ST load is 1–3 min
        # and must not run when stamp+mtime already match (clean make sync skip).
        owner_id = owner_user_id if owner_user_id is not None else self._default_owner_user_id()
        vis = (visibility or "private").strip() or "private"
        wid = work_id
        if vis == "private" and not wid:
            raise ValueError("private source sync requires work_id (docs/27 MT5c)")
        scope_id = index_scope_id(work_id=wid, visibility=vis)
        stamp = current_index_stamp()
        added = 0
        updated = 0
        skipped = 0
        seen_paths: set[str] = set()
        total_chunks = 0
        sync_t0 = time.monotonic()

        with self._connect() as conn:
            with conn.cursor() as cur:
                # Per-work/seed stamp — not global version. Seed bumping INDEX to 9
                # must not skip FiQA/SciFact that still hold the previous embed space.
                stored_stamp = _read_scope_stamp(cur, scope_id)
                force_reindex = scope_stamp_mismatch(stored_stamp, stamp)
                reindex_reason = None
                if force_reindex:
                    if not stored_stamp:
                        reindex_reason = "缺少 scope stamp（升级后首次需全量）"
                    else:
                        reindex_reason = "模型/INDEX 与库内 stamp 不一致"

                # Resume epoch: files flushed+committed during an interrupted force
                # reindex keep matching mtime + updated_at >= epoch → skip on takeover.
                reindex_epoch: float | None = None
                if force_reindex:
                    reindex_epoch = _read_reindex_epoch(cur, scope_id)
                    if reindex_epoch is None:
                        reindex_epoch = time.time()
                        _write_reindex_epoch(cur, scope_id, reindex_epoch)
                        conn.commit()

                # Scope previous set to this work (or seed) so we do not delete other works' rows.
                # Load mtime + chunk_count + updated_at in one query.
                if wid:
                    cur.execute(
                        """
                        SELECT path, mtime, chunk_count,
                               EXTRACT(EPOCH FROM updated_at)
                        FROM source_files WHERE work_id = %s::uuid
                        """,
                        (wid,),
                    )
                elif vis == "seed":
                    cur.execute(
                        """
                        SELECT path, mtime, chunk_count,
                               EXTRACT(EPOCH FROM updated_at)
                        FROM source_files WHERE visibility = 'seed'
                        """
                    )
                else:
                    cur.execute(
                        """
                        SELECT path, mtime, chunk_count,
                               EXTRACT(EPOCH FROM updated_at)
                        FROM source_files WHERE false
                        """
                    )
                prev_meta = {
                    row[0]: (
                        float(row[1]),
                        int(row[2] or 0),
                        float(row[3] or 0.0),
                    )
                    for row in cur.fetchall()
                }
                prev_files = {path: meta[0] for path, meta in prev_meta.items()}

                # Two-pass: (1) fast mtime/stamp classify (2) chunk only dirty files.
                pending_jobs: list[dict[str, Any]] = []
                scanned = 0
                scan_every = max(progress_every_files() or 25, 25)
                logger.info(
                    "sources index sync scan start; visibility=%s scope=%s dir=%s "
                    "force_reindex=%s stamp=%s",
                    vis,
                    scope_id,
                    sources_dir,
                    force_reindex,
                    stamp,
                )
                try:
                    from app.retrieval.sync_progress import report_sync_progress

                    report_sync_progress(
                        force=True,
                        status="building",
                        phase="scan",
                        visibility=vis,
                        path=str(sources_dir),
                        work_id=wid,
                        files_done=0,
                        files_total=None,
                        dirty_files=0,
                        skipped=0,
                        chunks_embedded=0,
                        chunks_total=None,
                        rate_chunks_per_s=None,
                        eta_s=None,
                        elapsed_s=0.0,
                        force_reindex=force_reindex,
                        reindex_reason=reindex_reason,
                    )
                except Exception:
                    pass

                dirty_paths: list[tuple[Any, str, float, bool]] = []
                ws_root = workspace_root.resolve()
                last_scan_report = time.monotonic()
                for fp in sources_dir.rglob("*"):
                    from app.retrieval.index_scheduler import check_sync_cancelled

                    check_sync_cancelled()
                    if not fp.is_file() or not should_index_source(fp):
                        continue
                    rel = str(fp.relative_to(ws_root)).replace("\\", "/")
                    if vis != "seed" and (
                        rel == "sources/seed" or rel.startswith("sources/seed/")
                    ):
                        continue
                    storage_path = index_storage_path(
                        rel, work_id=wid, visibility=vis
                    )
                    seen_paths.add(storage_path)
                    mtime = fp.stat().st_mtime
                    scanned += 1
                    now_mono = time.monotonic()
                    if (
                        scanned == 1
                        or (scan_every and scanned % scan_every == 0)
                        or (now_mono - last_scan_report) >= 1.0
                    ):
                        last_scan_report = now_mono
                        try:
                            from app.retrieval.sync_progress import report_sync_progress

                            report_sync_progress(
                                status="building",
                                phase="scan",
                                visibility=vis,
                                path=str(sources_dir),
                                files_done=scanned,
                                dirty_files=len(dirty_paths),
                                skipped=skipped,
                                force_reindex=force_reindex,
                                reindex_reason=reindex_reason,
                                elapsed_s=round(now_mono - sync_t0, 1),
                            )
                        except Exception:
                            pass
                    prev = prev_meta.get(storage_path)
                    if prev is not None and prev[0] == mtime:
                        # Normal incremental skip, or resume after cancelled force reindex.
                        if (not force_reindex) or (
                            reindex_epoch is not None
                            and prev[2] >= (reindex_epoch - 1.0)
                            and prev[1] > 0
                        ):
                            total_chunks += prev[1]
                            skipped += 1
                            continue
                    dirty_paths.append(
                        (fp, storage_path, mtime, storage_path in prev_files)
                    )

                try:
                    from app.retrieval.sync_progress import report_sync_progress

                    report_sync_progress(
                        force=True,
                        status="building",
                        phase="chunk",
                        visibility=vis,
                        path=str(sources_dir),
                        files_done=0,
                        files_total=len(dirty_paths),
                        dirty_files=len(dirty_paths),
                        skipped=skipped,
                        force_reindex=force_reindex,
                        reindex_reason=reindex_reason,
                        elapsed_s=round(time.monotonic() - sync_t0, 1),
                    )
                except Exception:
                    pass

                chunk_every = max(scan_every, 10)
                for i, (fp, storage_path, mtime, is_update) in enumerate(
                    dirty_paths, start=1
                ):
                    from app.retrieval.index_scheduler import check_sync_cancelled

                    check_sync_cancelled()
                    text_body = fp.read_text(encoding="utf-8", errors="replace")
                    # Index path: defer embed — only stash embed_input on each chunk dict.
                    # Cross-file batch embed happens in _flush_buffer (throughput + LANE_INDEX).
                    new_chunks = chunk_source_text(
                        fp, storage_path, text_body, embedder=None, embed=False
                    )
                    pending_jobs.append(
                        {
                            "storage_path": storage_path,
                            "mtime": mtime,
                            "chunks": new_chunks,
                            "is_update": is_update,
                        }
                    )
                    if chunk_every and (
                        i % chunk_every == 0 or i == len(dirty_paths)
                    ):
                        try:
                            from app.retrieval.sync_progress import report_sync_progress

                            report_sync_progress(
                                status="building",
                                phase="chunk",
                                visibility=vis,
                                path=str(sources_dir),
                                files_done=i,
                                files_total=len(dirty_paths),
                                dirty_files=len(dirty_paths),
                                skipped=skipped,
                                elapsed_s=round(time.monotonic() - sync_t0, 1),
                            )
                        except Exception:
                            pass

                chunks_total = sum(len(j["chunks"]) for j in pending_jobs)
                logger.info(
                    "sources index sync plan; visibility=%s dirty_files=%s "
                    "dirty_chunks=%s skipped=%s batch_size=%s force_reindex=%s",
                    vis,
                    len(pending_jobs),
                    chunks_total,
                    skipped,
                    embedding_batch_size(),
                    force_reindex,
                )

                # Flush deferred embeds in cross-file batches, then write rows.
                # Report loading_embedder before plan so CLI order matches real work.
                embedder = None
                if pending_jobs:
                    try:
                        from app.retrieval.sync_progress import report_sync_progress

                        report_sync_progress(
                            force=True,
                            status="building",
                            phase="loading_embedder",
                            visibility=vis,
                            path=str(sources_dir),
                            files_done=None,
                            files_total=len(pending_jobs),
                            chunks_total=chunks_total,
                            dirty_files=len(pending_jobs),
                            skipped=skipped,
                            embedding_backend=settings.embedding_backend,
                            elapsed_s=round(time.monotonic() - sync_t0, 1),
                            force_reindex=force_reindex,
                            reindex_reason=reindex_reason,
                        )
                    except Exception:
                        pass
                    embedder = get_embedder()
                    try:
                        from app.retrieval.sync_progress import report_sync_progress

                        report_sync_progress(
                            force=True,
                            status="building",
                            phase="plan",
                            visibility=vis,
                            path=str(sources_dir),
                            files_done=0,
                            files_total=len(pending_jobs),
                            chunks_embedded=0,
                            chunks_total=chunks_total,
                            skipped=skipped,
                            dirty_files=len(pending_jobs),
                            elapsed_s=round(time.monotonic() - sync_t0, 1),
                            embedding_backend=settings.embedding_backend,
                            rate_chunks_per_s=None,
                            eta_s=None,
                            force_reindex=force_reindex,
                            reindex_reason=reindex_reason,
                        )
                    except Exception:
                        pass

                # ── Embed + 落库主循环 ─────────────────────────────────────────────
                # 跨文件缓冲 pending_jobs，满 batch_cap 条 chunk 触发 _flush_buffer：
                #   (1) assign_deferred_vectors  → phase=embed
                #   (2) DELETE 旧 chunk + UPSERT 三表 + bm25_extra  → phase=write
                #   (3) commit → 增量时 pgvector 自动维护 HNSW；GIN 随 text 列更新
                # force_reindex：写前 _drop_embedding_hnsw，更大 flush、更少 commit。
                batch_cap = index_flush_chunk_cap(force_reindex=force_reindex)
                commit_every = index_commit_every_flushes(force_reindex=force_reindex)
                buffer_jobs: list[dict[str, Any]] = []
                buffer_chunk_count = 0
                chunks_embedded = 0
                files_done = 0
                flush_count = 0
                hnsw_dropped = False
                every = progress_every_files()

                if force_reindex and pending_jobs:
                    # Bulk load without HNSW: each UPSERT would otherwise rebuild graph edges.
                    try:
                        from app.retrieval.sync_progress import report_sync_progress

                        report_sync_progress(
                            status="building",
                            phase="index",
                            visibility=vis,
                            path=str(sources_dir),
                            label="drop-hnsw",
                            force_reindex=True,
                            reindex_reason=reindex_reason,
                            elapsed_s=round(time.monotonic() - sync_t0, 1),
                        )
                    except Exception:
                        pass
                    logger.info(
                        "sources index sync drop HNSW for bulk load; scope=%s "
                        "dirty_files=%s flush_cap=%s commit_every=%s",
                        scope_id,
                        len(pending_jobs),
                        batch_cap,
                        commit_every,
                    )
                    _drop_embedding_hnsw(cur)
                    conn.commit()
                    hnsw_dropped = True

                # 三表 UPSERT：chunk 向量 + 文件元数据 + doc centroid（见 _flush_buffer）。
                _CHUNK_UPSERT_SQL = """
                    INSERT INTO source_chunks (
                        chunk_id, path, section_title, text, citation_id,
                        line_start, line_end, embedding, owner_user_id,
                        work_id, visibility
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s::vector, %s,
                        %s, %s
                    )
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        path = EXCLUDED.path,
                        section_title = EXCLUDED.section_title,
                        text = EXCLUDED.text,
                        citation_id = EXCLUDED.citation_id,
                        line_start = EXCLUDED.line_start,
                        line_end = EXCLUDED.line_end,
                        embedding = EXCLUDED.embedding,
                        owner_user_id = EXCLUDED.owner_user_id,
                        work_id = EXCLUDED.work_id,
                        visibility = EXCLUDED.visibility
                    """
                _FILE_UPSERT_SQL = """
                    INSERT INTO source_files (
                        path, mtime, chunk_count, updated_at, owner_user_id,
                        work_id, visibility
                    )
                    VALUES (%s, %s, %s, NOW(), %s, %s, %s)
                    ON CONFLICT (path) DO UPDATE SET
                        mtime = EXCLUDED.mtime,
                        chunk_count = EXCLUDED.chunk_count,
                        updated_at = NOW(),
                        owner_user_id = EXCLUDED.owner_user_id,
                        work_id = EXCLUDED.work_id,
                        visibility = EXCLUDED.visibility
                    """
                _DOC_UPSERT_SQL = """
                    INSERT INTO source_docs (
                        path, embedding, work_id, visibility, owner_user_id
                    ) VALUES (%s, %s::vector, %s, %s, %s)
                    ON CONFLICT (path) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        work_id = EXCLUDED.work_id,
                        visibility = EXCLUDED.visibility,
                        owner_user_id = EXCLUDED.owner_user_id,
                        updated_at = NOW()
                    """

                def _flush_buffer(*, force_commit: bool = False) -> None:
                    """单批 flush：embed → 删旧 chunk → 写三表 → 拷 bm25_extra → 可选 commit。

                    English: One index-plane write unit. Vectors land in ``embedding``
                    columns; HNSW/GIN maintenance is PostgreSQL-side (no Python graph API).
                    ``phase=write`` progress fires after executemany, before commit.
                    """
                    nonlocal chunks_embedded, files_done, added, updated, total_chunks
                    nonlocal flush_count
                    if not buffer_jobs:
                        return
                    from app.retrieval.index_scheduler import check_sync_cancelled

                    check_sync_cancelled()
                    flat: list[dict[str, Any]] = []
                    for job in buffer_jobs:
                        flat.extend(job["chunks"])
                    # Step 1 — embed: pop embed_input → chunk["vector"] (LANE_INDEX batches).
                    chunks_embedded += assign_deferred_vectors(
                        flat,
                        embedder,
                        label=vis,
                        chunks_done_before=chunks_embedded,
                        chunks_total_hint=chunks_total,
                    )

                    paths = [job["storage_path"] for job in buffer_jobs]
                    # Step 2 — replace chunks for touched paths (file-level atomicity).
                    cur.execute(
                        "DELETE FROM source_chunks WHERE path = ANY(%s)",
                        (paths,),
                    )

                    file_rows: list[tuple[Any, ...]] = []
                    chunk_rows: list[tuple[Any, ...]] = []
                    doc_rows: list[tuple[Any, ...]] = []
                    for job in buffer_jobs:
                        storage_path = job["storage_path"]
                        new_chunks = job["chunks"]
                        mtime = job["mtime"]
                        file_rows.append(
                            (
                                storage_path,
                                mtime,
                                len(new_chunks),
                                owner_id,
                                wid,
                                vis,
                            )
                        )
                        for chunk in new_chunks:
                            vec = chunk.get("vector")
                            if not isinstance(vec, list):
                                raise RuntimeError(
                                    f"missing embedding for chunk {chunk.get('chunk_id')}"
                                )
                            if len(vec) != self._dimensions:
                                raise RuntimeError(
                                    f"embedding dim {len(vec)} != configured {self._dimensions}"
                                )
                            chunk_rows.append(
                                (
                                    chunk["chunk_id"],
                                    storage_path,
                                    chunk.get("section_title", ""),
                                    chunk.get("text", ""),
                                    chunk.get("citation_id", ""),
                                    chunk.get("line_start"),
                                    chunk.get("line_end"),
                                    _vector_literal(vec),
                                    owner_id,
                                    wid,
                                    vis,
                                )
                            )
                        vectors = [
                            c.get("vector")
                            for c in new_chunks
                            if isinstance(c.get("vector"), list)
                        ]
                        # Doc lane: one centroid row per path (mean of chunk embeddings).
                        centroid = _chunk_vectors_centroid(
                            [v for v in vectors if isinstance(v, list)]
                        )
                        if centroid is not None:
                            doc_rows.append(
                                (
                                    storage_path,
                                    _vector_literal(centroid),
                                    wid,
                                    vis,
                                    owner_id,
                                )
                            )
                        total_chunks += len(new_chunks)
                        if job["is_update"]:
                            updated += 1
                        else:
                            added += 1
                        files_done += 1

                    # Step 3 — persist rows (HNSW/GIN updated by Postgres on commit).
                    if file_rows:
                        cur.executemany(_FILE_UPSERT_SQL, file_rows)
                    if chunk_rows:
                        cur.executemany(_CHUNK_UPSERT_SQL, chunk_rows)
                    if doc_rows:
                        cur.executemany(_DOC_UPSERT_SQL, doc_rows)
                    # Step 4 — FTS C-weight: path-level bm25_extra (doc2query) → each chunk row.
                    cur.execute(
                        """
                        UPDATE source_chunks AS c
                        SET bm25_extra = f.bm25_extra
                        FROM source_files AS f
                        WHERE c.path = f.path AND c.path = ANY(%s)
                        """,
                        (paths,),
                    )

                    if every and files_done % every == 0:
                        logger.info(
                            "sources index sync files; visibility=%s files=%s/%s "
                            "chunks_embedded=%s/%s elapsed_s=%.1f",
                            vis,
                            files_done,
                            len(pending_jobs),
                            chunks_embedded,
                            chunks_total,
                            time.monotonic() - sync_t0,
                        )
                    try:
                        from app.retrieval.sync_progress import report_sync_progress

                        elapsed = time.monotonic() - sync_t0
                        rate = chunks_embedded / elapsed if elapsed > 0 else 0.0
                        report_sync_progress(
                            status="building",
                            phase="write",
                            visibility=vis,
                            files_done=files_done,
                            files_total=len(pending_jobs),
                            chunks_embedded=chunks_embedded,
                            chunks_total=chunks_total,
                            rate_chunks_per_s=round(rate, 2),
                            elapsed_s=round(elapsed, 1),
                            batch_size=batch_cap,
                        )
                    except Exception:
                        pass

                    buffer_jobs.clear()
                    flush_count += 1
                    # Checkpoint for takeover/resume; force reindex commits less often.
                    if force_commit or (flush_count % commit_every) == 0:
                        conn.commit()

                for job in pending_jobs:
                    buffer_jobs.append(job)
                    buffer_chunk_count += len(job["chunks"])
                    if buffer_chunk_count >= batch_cap:
                        _flush_buffer()
                        buffer_chunk_count = 0
                _flush_buffer(force_commit=True)

                removed = [path for path in prev_files if path not in seen_paths]
                for path in removed:
                    cur.execute("DELETE FROM source_files WHERE path = %s", (path,))
                if hnsw_dropped:
                    # Logged as create-hnsw; actual DDL is _ensure_embedding_hnsw below.
                    try:
                        from app.retrieval.sync_progress import report_sync_progress

                        report_sync_progress(
                            status="building",
                            phase="index",
                            visibility=vis,
                            path=str(sources_dir),
                            label="create-hnsw",
                            chunks_embedded=chunks_embedded,
                            chunks_total=chunks_total,
                            files_done=files_done,
                            files_total=len(pending_jobs),
                            force_reindex=True,
                            elapsed_s=round(time.monotonic() - sync_t0, 1),
                        )
                    except Exception:
                        pass
                    logger.info(
                        "sources index sync rebuild HNSW; scope=%s chunks=%s",
                        scope_id,
                        chunks_embedded,
                    )
                # HNSW：增量 → IF NOT EXISTS 无操作（图已在 UPSERT 时维护）；
                # force / 中断恢复 → CREATE 重建 chunk+doc 两张 ANN 索引。
                # 随后写 scope stamp，标记本 work/seed 嵌入空间与当前配置一致。
                _ensure_embedding_hnsw(cur)
                _write_scope_stamp(cur, scope_id, stamp)
                _clear_reindex_epoch(cur, scope_id)
            conn.commit()

        self.load()
        elapsed = time.monotonic() - sync_t0
        logger.info(
            "sources index sync scope done; visibility=%s scope=%s indexed_files=%s "
            "chunks=%s added=%s updated=%s skipped=%s removed=%s elapsed_s=%.1f",
            vis,
            scope_id,
            len(seen_paths),
            total_chunks,
            added,
            updated,
            skipped,
            len(removed),
            elapsed,
        )
        return {
            "indexed_files": len(seen_paths),
            "chunks": total_chunks,
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "removed": len(removed),
            "reindexed": force_reindex,
            "scope": scope_id,
            "backend": self.backend,
            "ann": "hnsw",
            "elapsed_s": round(elapsed, 2),
            "embed_batch_size": embedding_batch_size(),
            "flush_chunk_cap": index_flush_chunk_cap(force_reindex=force_reindex),
        }

    def _search_docs_ann(self, query: str, *, limit: int) -> list[str]:
        """Doc lane：在 ``source_docs`` centroid 向量上做 path 级 HNSW ANN。

        English: P3 two-level retrieval — coarse document routing before chunk hybrid.
        Unlike ``search_vector``, returns **file paths only** (no excerpts). Chunk
        lane still produces the actual text hits; doc lane only biases which paths win.

        =============================================================================
        心智模型：centroid 是什么
        =============================================================================
        索引时 ``sync._flush_buffer`` 对该 path 下所有 chunk 的 ``embedding`` 做
        算术均值（``_chunk_vectors_centroid``），写入 ``source_docs.embedding``。
        因此 doc 向量 ≈「整篇文档在 embed 空间里的粗中心」，不是重新 embed 摘要。

        查询语义: query 与 **文档级中心** 近 → 该 path 下 chunk 在 merge 阶段
        获得 ``doc_boost``（默认 +0.35），排序靠前；**不会**丢弃仅 chunk 命中的结果。

        =============================================================================
        执行流程
        =============================================================================
        ::

          ensure_schema()
          query_vec = get_embedder().embed(query)   # 与 chunk lane 同一模型/维数
          _prepare_hnsw_filtered_scan(limit)        # iterative_scan（共享 HNSW 图）
          SELECT path FROM source_docs
            WHERE visibility/work_id ACL
            ORDER BY embedding <=> query_vec
            LIMIT limit
          display_path_from_index(path)             # 剥 work 视图前缀

        =============================================================================
        降级与调用关系
        =============================================================================
        仅由 ``search_hybrid._doc_lane`` 调用（与 ``_chunk_lane`` 并行）::

          source_docs 空表 → 返回 [] → caller ``_doc_lane_approx``
          SQL 异常 / 过滤后 0 行 → ``_doc_lane_approx``
          ``retrieval_two_level_doc_table=False`` → 直接 approx，不进本函数

        ``_doc_lane_approx``: 宽 ``search_vector(limit≥40)`` → 按 path 去重 ≤8。

        =============================================================================
        参数 / 返回 / 不变量
        =============================================================================
        参数:
            query: 用户检索串。
            limit: 最多 path 数（``RetrievalProfile.two_level_doc_limit``，默认 8）。
        返回:
            展示用相对 path，余弦近邻序；无 tenant 窗口（无 work 且 seed 不可见）→ ``[]``。
        不变量:
            不读 ``source_chunks.text``；不写入库；维数 ≠ 配置 → ``[]``（不抛）。
        """
        self.ensure_schema()
        query_vec = get_embedder().embed(query)
        if not query_vec or len(query_vec) != self._dimensions:
            return []
        literal = _vector_literal(query_vec)
        from app.retrieval.tenant_visibility import display_path_from_index
        from app.tenant_context import current_visibility_seed, current_work_id

        work_id = current_work_id()
        seed_ok = current_visibility_seed()
        with self._connect() as conn:
            with conn.cursor() as cur:
                # Cheap presence check — empty table → approx lane.
                cur.execute("SELECT 1 FROM source_docs LIMIT 1")
                if cur.fetchone() is None:
                    return []
                _prepare_hnsw_filtered_scan(cur, limit=limit)
                if work_id is not None and seed_ok:
                    cur.execute(
                        """
                        SELECT path
                        FROM source_docs
                        WHERE visibility = 'seed' OR work_id = %s::uuid
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (str(work_id), literal, limit),
                    )
                elif work_id is not None:
                    cur.execute(
                        """
                        SELECT path
                        FROM source_docs
                        WHERE work_id = %s::uuid
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (str(work_id), literal, limit),
                    )
                elif seed_ok:
                    cur.execute(
                        """
                        SELECT path
                        FROM source_docs
                        WHERE visibility = 'seed'
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (literal, limit),
                    )
                else:
                    return []
                rows = cur.fetchall()
        return [
            display_path_from_index(str(row[0] or ""))
            for row in rows
            if row and row[0]
        ]

    def search_vector(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        """Chunk lane · 稠密向量路：``source_chunks`` 上 HNSW 余弦 ANN。

        English: Dense retrieval leg of hybrid. One ``embed(query)`` per call; results
        are chunk-level ``ChunkHit`` with excerpt, line range, and cosine-like score.

        =============================================================================
        与索引的对应关系
        =============================================================================
        读 ``source_chunks.embedding``（sync 时 ``assign_deferred_vectors`` 写入；
        输入曾由 ``build_embed_text`` 组装）。索引 HNSW: ``source_chunks_embedding_hnsw``，
        距离 ``vector_cosine_ops``；ST 向量已 L2 归一化 → ``score = 1 - (emb <=> q)``。

        =============================================================================
        执行流程
        =============================================================================
        ::

          get_embedder().embed(query)              # LANE_QUERY（检索优先）
          _prepare_hnsw_filtered_scan(limit):
              SET LOCAL hnsw.iterative_scan = relaxed_order
              SET LOCAL hnsw.max_scan_tuples = max(20000, limit×500)
          SQL: … FROM source_chunks
               WHERE seed / work_id ACL
               ORDER BY embedding <=> q LIMIT limit
          组装 ChunkHit（path 经 display_path_from_index）

        **为何 iterative_scan**: 全库共用一张 HNSW（seed + 多 work）。纯
        ``ORDER BY <=> LIMIT k`` 再 SQL 过滤 work，可能 k 个全局近邻全是 seed →
        当前 work 0 命中。relaxed_order 在过滤后不足时继续扫 heap。

        =============================================================================
        在 hybrid 中的位置
        =============================================================================
        ``search_hybrid._chunk_lane`` 以 ``top_k``（非最终 limit）调用本函数，
        与 ``search_bm25`` 并列；两榜经 ``reciprocal_rank_fusion`` 合并。
        仅 vector 有命中 / 仅 bm25 有命中时跳过 RRF，直接单榜进 pool。

        参数:
            query: 检索文本（自然语言或关键词）。
            limit: ANN 深度；hybrid 内为 ``top_k``，通常 80–360。
        返回:
            相似度降序 ``ChunkHit``；``score<=0`` 丢弃；无 ACL 窗口 → ``[]``。
        """
        self.ensure_schema()
        query_vec = get_embedder().embed(query)
        if not query_vec or len(query_vec) != self._dimensions:
            return []
        literal = _vector_literal(query_vec)
        from app.retrieval.tenant_visibility import display_path_from_index
        from app.tenant_context import current_visibility_seed, current_work_id

        work_id = current_work_id()
        seed_ok = current_visibility_seed()
        with self._connect() as conn:
            with conn.cursor() as cur:
                _prepare_hnsw_filtered_scan(cur, limit=limit)
                if work_id is not None and seed_ok:
                    cur.execute(
                        """
                        SELECT chunk_id, path, section_title, text, citation_id,
                               line_start, line_end, work_id, visibility,
                               1 - (embedding <=> %s::vector) AS score
                        FROM source_chunks
                        WHERE visibility = 'seed'
                           OR work_id = %s::uuid
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (literal, str(work_id), literal, limit),
                    )
                elif work_id is not None:
                    cur.execute(
                        """
                        SELECT chunk_id, path, section_title, text, citation_id,
                               line_start, line_end, work_id, visibility,
                               1 - (embedding <=> %s::vector) AS score
                        FROM source_chunks
                        WHERE work_id = %s::uuid
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (literal, str(work_id), literal, limit),
                    )
                elif seed_ok:
                    # No Work bound: seed only — never dump the full private table.
                    cur.execute(
                        """
                        SELECT chunk_id, path, section_title, text, citation_id,
                               line_start, line_end, work_id, visibility,
                               1 - (embedding <=> %s::vector) AS score
                        FROM source_chunks
                        WHERE visibility = 'seed'
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (literal, literal, limit),
                    )
                else:
                    return []
                rows = cur.fetchall()
        hits: list[ChunkHit] = []
        for row in rows:
            score = float(row[9] or 0.0)
            if score <= 0.0:
                continue
            hits.append(
                ChunkHit(
                    path=display_path_from_index(str(row[1])),
                    chunk_id=str(row[0]),
                    excerpt=str(row[3] or "").strip(),
                    citation_id=str(row[4] or ""),
                    score=score,
                    section_title=str(row[2] or ""),
                    line_start=int(row[5]) if row[5] is not None else None,
                    line_end=int(row[6]) if row[6] is not None else None,
                    work_id=str(row[7]) if row[7] is not None else None,
                    visibility=str(row[8] or ""),
                )
            )
        return hits

    def _bm25_visible_chunks(self) -> list[dict[str, Any]]:
        from app.tenant_context import current_visibility_seed, current_work_id

        work_id = current_work_id()
        seed_ok = current_visibility_seed()
        wid = str(work_id) if work_id is not None else None
        kept: list[dict[str, Any]] = []
        for chunk in self._chunk_cache:
            vis = str(chunk.get("visibility") or "private")
            cw = chunk.get("work_id")
            if vis == "seed":
                if seed_ok:
                    kept.append(chunk)
                continue
            if wid is not None and cw == wid:
                kept.append(chunk)
        return kept

    def search_bm25(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        """Chunk lane · 稀疏词法路：GIN FTS 召回 + 可选 Okapi BM25 重排。

        English: Lexical leg of hybrid — complements ``search_vector`` for exact
        tokens, titles, and doc2query ``bm25_extra`` pseudo-queries. Production
        pgvector always hits Postgres; ``_chunk_cache`` branch is test/JSON parity.

        =============================================================================
        生产路径 ``_search_bm25_db``（pgvector 默认）
        =============================================================================
        ::

          build_weighted_or_tsquery(query)
              → 强词/实体 OR（:A/:D 权重），否则 plainto_tsquery AND
          GIN: BM25_TSVECTOR_SQL @@ tsquery
              A 权 = section_title + text（chunk 正文）
              C 权 = bm25_extra（path 级，doc2query 离线写入）
          ts_rank_cd 初排 → LIMIT fetch_limit
          [若 retrieval_bm25_rescore_enabled]
              fetch_limit ≈ limit×4 → BM25Scorer Okapi 在池内重排
              bm25_extra 词命中 ×0.35 加成

        =============================================================================
        与 vector 路的差异（为何要两路）
        =============================================================================
        - Vector: 语义相近即可，不要求字面相同（gte-small / bge-m3）。
        - BM25: 专名、编号、罕见词、标题精确匹配；extra 模拟「用户可能怎么搜」。
        - Hybrid: RRF 按 **rank 位次** 融合，非 raw 分数加权；默认 vector/bm25 等权
          （``RetrievalProfile``；``vector_heavy`` profile 偏向量）。

        =============================================================================
        参数 / 返回
        =============================================================================
        参数:
            query: 检索串。
            limit: 返回条数；rescore 时 SQL 先拉更大池再 Okapi 截断。
        返回:
            ``ChunkHit``；ACL 与 ``search_vector`` 相同。
        分支:
            ``self._chunk_cache`` 非空 → ``_search_bm25_cached``（内存 Okapi，单测）。
        """
        # Retain the cache path for focused unit tests and callers that explicitly
        # provide a small cache. Normal pgvector requests query FTS directly.
        if self._chunk_cache:
            chunks = self._bm25_visible_chunks()
            if not chunks:
                return []
            return self._search_bm25_cached(query, chunks=chunks, limit=limit)
        return self._search_bm25_db(query, limit=limit)

    def _search_bm25_cached(
        self, query: str, *, chunks: list[dict[str, Any]], limit: int
    ) -> list[ChunkHit]:
        """内存 chunk 列表上 Okapi BM25（``_chunk_cache`` / rescore 二次排序用）。

        English: Pure-Python ``BM25Scorer`` over provided dict rows — no GIN SQL.
        Used by ``search_bm25`` when cache populated (tests) and by ``_search_bm25_db``
        rescore path after FTS candidate fetch.
        """
        by_id = {str(c["chunk_id"]): c for c in chunks if c.get("chunk_id")}
        ranked = BM25Scorer(chunks).search(query, limit=limit)
        hits: list[ChunkHit] = []
        for chunk_id, score in ranked:
            chunk = by_id.get(chunk_id)
            if chunk is None:
                continue
            hits.append(_chunk_to_hit(chunk, score))
        return hits

    def _search_bm25_db(self, query: str, *, limit: int) -> list[ChunkHit]:
        """Postgres FTS 拉取 chunk 行；可选在候选池内 Okapi 重排（P1②）。

        English: Low-level BM25 lane for pgvector — issues ``@@`` against GIN index
        ``source_chunks_text_fts_idx``, then optionally reranks with ``BM25Scorer``.

        =============================================================================
        SQL 两模式（由 ``retrieval_bm25_rescore_enabled`` 决定）
        =============================================================================
        **rescore=True**（默认生产）::

          SELECT …, bm25_extra   -- 无 ts_rank 作最终分
          WHERE BM25_TSVECTOR_SQL @@ tsquery
          ORDER BY ts_rank_cd DESC
          LIMIT fetch_limit (≈ limit×4)
          → Python BM25Scorer.search → _chunk_to_hit

        **rescore=False**::

          SELECT …, ts_rank_cd AS score
          ORDER BY score DESC LIMIT limit
          → 直接 ChunkHit（不再 Okapi）

        tsquery 构造见 ``bm25_document.build_weighted_or_tsquery``；ACL 三分支
        （seed+work / work only / seed only）与 ``search_vector`` 一致。

        参数:
            query: 检索串。
            limit: 最终返回条数上限。
        返回:
            ``ChunkHit`` 列表；不可见 tenant → ``[]``。
        """
        self.ensure_schema()
        from app.retrieval.tenant_visibility import display_path_from_index
        from app.tenant_context import current_visibility_seed, current_work_id

        work_id = current_work_id()
        seed_ok = current_visibility_seed()
        if work_id is not None and seed_ok:
            visibility_sql = "(visibility = 'seed' OR work_id = %s::uuid)"
            visibility_args: tuple[Any, ...] = (str(work_id),)
        elif work_id is not None:
            visibility_sql = "work_id = %s::uuid"
            visibility_args = (str(work_id),)
        elif seed_ok:
            visibility_sql = "visibility = 'seed'"
            visibility_args = ()
        else:
            return []

        rescore = bool(settings.retrieval_bm25_rescore_enabled)
        # Over-fetch when rescoring so Okapi can reorder a wider FTS pool.
        fetch_limit = max(limit * 4, limit) if rescore else limit
        # Weighted OR recall (entity/long :A, else :D). Fall back to plainto AND
        # only when tokenization yields nothing usable.
        or_q = build_weighted_or_tsquery(query)
        if or_q:
            tsquery_sql = "to_tsquery('english', %s)"
            tsquery_arg: str = or_q
        else:
            tsquery_sql = "plainto_tsquery('english', %s)"
            tsquery_arg = query

        with self._connect() as conn:
            with conn.cursor() as cur:
                if rescore:
                    # FTS ranks the candidate pool; Okapi reorders within it (P1②).
                    cur.execute(
                        f"""
                        WITH query_terms AS (
                            SELECT {tsquery_sql} AS value
                        )
                        SELECT chunk_id, path, section_title, text, citation_id,
                               line_start, line_end, work_id, visibility,
                               coalesce(bm25_extra, '') AS bm25_extra
                        FROM source_chunks, query_terms
                        WHERE {visibility_sql}
                          AND {BM25_TSVECTOR_SQL} @@ query_terms.value
                        ORDER BY ts_rank_cd(
                            {BM25_TSVECTOR_SQL},
                            query_terms.value
                        ) DESC
                        LIMIT %s
                        """,
                        (tsquery_arg, *visibility_args, fetch_limit),
                    )
                else:
                    cur.execute(
                        f"""
                        WITH query_terms AS (
                            SELECT {tsquery_sql} AS value
                        )
                        SELECT chunk_id, path, section_title, text, citation_id,
                               line_start, line_end, work_id, visibility,
                               ts_rank_cd(
                                   {BM25_TSVECTOR_SQL},
                                   query_terms.value
                               ) AS score
                        FROM source_chunks, query_terms
                        WHERE {visibility_sql}
                          AND {BM25_TSVECTOR_SQL} @@ query_terms.value
                        ORDER BY score DESC
                        LIMIT %s
                        """,
                        (tsquery_arg, *visibility_args, fetch_limit),
                    )
                rows = cur.fetchall()

        if not rows:
            return []

        if rescore:
            chunks: list[dict[str, Any]] = []
            for row in rows:
                chunks.append(
                    {
                        "chunk_id": str(row[0]),
                        # Align with vector/doc lanes for merge_doc_and_chunk_hits.
                        "path": display_path_from_index(str(row[1] or "")),
                        "section_title": str(row[2] or ""),
                        "text": str(row[3] or ""),
                        "citation_id": str(row[4] or ""),
                        "line_start": row[5],
                        "line_end": row[6],
                        "work_id": str(row[7]) if row[7] is not None else None,
                        "visibility": str(row[8] or ""),
                        "bm25_extra": str(row[9] or ""),
                    }
                )
            return self._search_bm25_cached(query, chunks=chunks, limit=limit)

        return [
            ChunkHit(
                path=display_path_from_index(str(row[1] or "")),
                chunk_id=str(row[0]),
                excerpt=str(row[3] or "").strip(),
                citation_id=str(row[4] or ""),
                score=float(row[9] or 0.0),
                section_title=str(row[2] or ""),
                line_start=int(row[5]) if row[5] is not None else None,
                line_end=int(row[6]) if row[6] is not None else None,
                work_id=str(row[7]) if row[7] is not None else None,
                visibility=str(row[8] or ""),
            )
            for row in rows
        ]

    def search_hybrid(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
        """店内 hybrid 检索 orchestrator（``search_sources`` 默认 ``retrieval_mode``）。

        English: Read-only query path after index build. Orchestrates dense+sparse
        chunk recall, optional rerank, optional two-level doc path boost. Does **not**
        call ``sync`` or mutate indexes. L1/L2 audit when ``begin_audit_capture`` active.

        =============================================================================
        职责边界
        =============================================================================
        - **本函数**: lane 调度、RRF、rerank、doc_boost、返回 ``ChunkHit[:limit]``。
        - **不在本函数**: 工具层 cover/tier/keyword-fallback/L3（``sources_search``）；
          切块/embed/建 HNSW（``sync``）；Turn 内索引同步。

        =============================================================================
        深度与 profile 旋钮
        =============================================================================
        ::

          top_k = max(limit × 4, 20)
          若 retrieval_rerank_enabled:
              top_k = max(top_k, retrieval_rerank_pool)   # 常见 240–360

          active_retrieval_profile() → RetrievalProfile:
              rrf_k, vector_weight, bm25_weight     # RRF 融合
              two_level_enabled, two_level_timeout_seconds (~0.3)
              two_level_doc_limit (8), doc_boost (0.35)

        =============================================================================
        主流程（two_level_enabled 默认 True）
        =============================================================================
        ::

          ┌─ parallel_two_level ─────────────────────────────────────┐
          │  Thread A: _doc_lane()                                   │
          │    _search_docs_ann(limit=8)  或  _doc_lane_approx       │
          │  Thread B: _chunk_lane()                                 │
          │    search_vector(top_k)  ──┐                             │
          │    search_bm25(top_k)    ──┼─ audit L1a record_lane_hits│
          │    reciprocal_rank_fusion  ──┘ audit L1 record_recall_pool│
          │    rerank_hits (optional)     audit L2 record_ranked     │
          └──────────────────────────────────────────────────────────┘
          merge_doc_and_chunk_hits(doc_paths, chunk_hits, doc_boost)
          return merged[:limit]

        **two_level 关闭**: 仅 ``_chunk_lane()`` → ``[:limit]``，无 doc 并行。

        **RRF**（``fusion.reciprocal_rank_fusion``）: 按 chunk_id 在位次 k 上累加
        ``weight/(rrf_k+rank+1)``；仅一路有命中则跳过 RRF（pool_source=vector|bm25）。

        **rerank**（``rerank.rerank_hits``）: 默认 lexical（词重叠/标题/短语）；
        ``retrieval_rerank_cross_encoder`` 开时用 cross-encoder（池 capped 20）。

        **doc_boost**（``two_level.merge_doc_and_chunk_hits``）: chunk.path ∈ doc_paths
        → score += doc_boost；boosted 块整体排在 rest 前，**不删除**仅 chunk 命中项。
        发生在 L2 rerank **之后**，不再记入 ``record_ranked``。

        **超时**: ``parallel_two_level`` 预算用尽 → doc 或 chunk 可能为空；
        chunk 空且 timed_out → 同步再跑一遍 ``_chunk_lane()`` 保底。

        =============================================================================
        审计层（需 ``search_sources`` 已 ``begin_audit_capture``）
        =============================================================================
        | 阶段 | 函数 | 含义 |
        | L1a | ``record_lane_hits`` | vector/bm25 分榜预览（融合前） |
        | L1 | ``record_recall_pool`` | RRF 后、rerank 前 fused/单榜池 |
        | L2 | ``record_ranked`` | rerank 后；method=lexical/none/cross_encoder |
        | L3 | ``sources_search`` | tool_result 摘录（本函数不写入） |

        =============================================================================
        参数 / 返回 / 下游
        =============================================================================
        参数:
            query: 与索引同 embed 空间（``build_embed_text`` 训练出的向量几何）。
            limit: 本层返回上限；caller 常传入更大 fetch 再滤 prefix/tenant。
        返回:
            ``ChunkHit``，len ≤ limit；score 已含 RRF/rerank/doc_boost 效果。
        下游:
            ``store.search`` → ``sources_search.search_sources`` → 模型 tool_result。

        相关实现:
            ``search_vector`` · ``search_bm25`` · ``_search_docs_ann``
            ``two_level.parallel_two_level`` · ``two_level.merge_doc_and_chunk_hits``
            ``fusion.reciprocal_rank_fusion`` · ``rerank.rerank_hits`` · ``audit.*``
        """
        from app.retrieval.profile import active_retrieval_profile

        profile = active_retrieval_profile()
        rerank = settings.retrieval_rerank_enabled
        top_k = max(limit * 4, 20)
        if rerank:
            top_k = max(top_k, settings.retrieval_rerank_pool)

        def _chunk_lane() -> list[ChunkHit]:
            """Chunk 主车道：dense ANN + sparse FTS → RRF → rerank（L1/L2 审计）。

            English: Runs inside ``parallel_two_level`` worker or alone when two-level
            disabled. Vector and BM25 share the same ``query`` string but hit different
            indexes (HNSW vs GIN). Fusion uses rank positions, not raw scores.

            顺序（同线程）::

              search_vector(top_k)
              search_bm25(top_k)
              → [两路皆空] return []
              → [单路] 该路作 pool
              → [双路] reciprocal_rank_fusion(k=profile.rrf_k, weights)
              record_recall_pool  # L1
              rerank_hits?        # L2
            """
            from app.retrieval.audit import (
                audit_capture_active,
                record_lane_hits,
                record_ranked,
                record_recall_pool,
            )

            vector_hits = self.search_vector(query, limit=top_k)
            bm25_hits = self.search_bm25(query, limit=top_k)
            if audit_capture_active():
                record_lane_hits(vector=vector_hits, bm25=bm25_hits)
                from app.retrieval.audit import record_lane_depth_meta

                record_lane_depth_meta(
                    lane_top_k=top_k,
                    requested_limit=limit,
                    two_level_enabled=bool(profile.two_level_enabled),
                )
            if not vector_hits and not bm25_hits:
                return []
            if not vector_hits:
                hits = bm25_hits
                pool_source = "bm25"
            elif not bm25_hits:
                hits = vector_hits
                pool_source = "vector"
            else:
                fusion_limit = top_k if rerank else limit
                fused = reciprocal_rank_fusion(
                    [
                        [(hit.chunk_id, hit.score) for hit in vector_hits],
                        [(hit.chunk_id, hit.score) for hit in bm25_hits],
                    ],
                    limit=fusion_limit,
                    k=profile.rrf_k,
                    weights=[profile.vector_weight, profile.bm25_weight],
                )
                by_id = {hit.chunk_id: hit for hit in vector_hits + bm25_hits}
                hits = []
                for chunk_id, score in fused:
                    hit = by_id.get(chunk_id)
                    if hit is None:
                        continue
                    hits.append(
                        ChunkHit(
                            path=hit.path,
                            chunk_id=hit.chunk_id,
                            excerpt=hit.excerpt,
                            citation_id=hit.citation_id,
                            score=score,
                            section_title=hit.section_title,
                            line_start=hit.line_start,
                            line_end=hit.line_end,
                        )
                    )
                pool_source = "fused"
            if audit_capture_active():
                record_recall_pool(hits, source=pool_source)
            if rerank and hits:
                ranked = rerank_hits(query, hits, limit=max(limit, top_k))
                if audit_capture_active():
                    method = (
                        "cross_encoder"
                        if settings.retrieval_rerank_cross_encoder
                        else "lexical"
                    )
                    record_ranked(ranked, method=method)
                return ranked
            if audit_capture_active():
                record_ranked(hits, method="none")
            return hits

        def _doc_lane_approx() -> list[str]:
            """Doc lane 降级：不读 ``source_docs``，用宽 chunk ANN 推断 path。

            English: Fallback when centroid table empty, ANN fails, or
            ``retrieval_two_level_doc_table=False``. Pulls ``max(top_k,40)`` chunk
            hits, dedupe by ``path``, cap at ``two_level_doc_limit``.

            语义: 近似「哪些文件的 chunk 在向量空间里离 query 最近」，精度低于
            centroid，但无 ``source_docs`` 依赖时仍能给 merge 提供 doc_paths。
            """
            wide = self.search_vector(query, limit=max(top_k, 40))
            seen: list[str] = []
            for hit in wide:
                if hit.path not in seen:
                    seen.append(hit.path)
                if len(seen) >= profile.two_level_doc_limit:
                    break
            return seen

        def _doc_lane() -> list[str]:
            """Doc lane：``source_docs`` centroid HNSW，失败则 ``_doc_lane_approx``。

            English: Submitted to ``parallel_two_level`` as ``doc_fn``. Returns path
            list only; does not embed separately from chunk lane (same query string
            when ``_search_docs_ann`` runs — each lane embeds once in its thread).

            分支::

              retrieval_two_level_doc_table=False → approx only
              _search_docs_ann → 非空 paths
              异常 / 空 → _doc_lane_approx
            """
            if not bool(settings.retrieval_two_level_doc_table):
                return _doc_lane_approx()
            try:
                paths = self._search_docs_ann(query, limit=profile.two_level_doc_limit)
            except Exception:
                logger.debug("source_docs ANN failed; falling back to approx", exc_info=True)
                return _doc_lane_approx()
            if not paths:
                return _doc_lane_approx()
            return paths

        if not profile.two_level_enabled:
            hits = _chunk_lane()
            return hits[:limit]

        from app.retrieval.two_level import merge_doc_and_chunk_hits, parallel_two_level

        doc_paths, chunk_hits, timed_out = parallel_two_level(
            doc_fn=_doc_lane,
            chunk_fn=_chunk_lane,
            timeout_seconds=profile.two_level_timeout_seconds,
        )
        if timed_out and not chunk_hits:
            chunk_hits = _chunk_lane()
        from app.retrieval.audit import audit_capture_active, record_lane_depth_meta

        if audit_capture_active():
            record_lane_depth_meta(
                two_level_doc_n=len(doc_paths),
                two_level_enabled=True,
            )
        return merge_doc_and_chunk_hits(
            doc_paths=doc_paths,
            chunk_hits=chunk_hits,
            limit=limit,
            doc_boost=profile.doc_boost,
        )

    def set_path_bm25_extra(self, path: str, extra: str) -> int:
        """RET-11(b): store path-level pseudo-queries and denormalize onto chunks.

        Returns number of chunks updated.
        """
        from app.retrieval.bm25_document import prune_bm25_extra_lines

        self.ensure_schema()
        text = prune_bm25_extra_lines(str(extra or ""))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE source_files SET bm25_extra = %s, updated_at = NOW()
                    WHERE path = %s
                    """,
                    (text, path),
                )
                if cur.rowcount == 0:
                    return 0
                cur.execute(
                    """
                    UPDATE source_chunks SET bm25_extra = %s WHERE path = %s
                    """,
                    (text, path),
                )
                n = int(cur.rowcount or 0)
            conn.commit()
        return n

    def prune_all_bm25_extra(self, *, path_like: str | None = None) -> dict[str, int]:
        """Rewrite stored bm25_extra through :func:`prune_bm25_extra_lines`.

        Returns counts: scanned / changed / cleared.
        """
        from app.retrieval.bm25_document import prune_bm25_extra_lines

        self.ensure_schema()
        args: list[Any] = []
        where = "bm25_extra <> ''"
        if path_like:
            where += " AND path LIKE %s"
            args.append(path_like)
        scanned = changed = cleared = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT path, bm25_extra FROM source_files WHERE {where}",
                    tuple(args),
                )
                rows = cur.fetchall()
            for path, extra in rows:
                scanned += 1
                pruned = prune_bm25_extra_lines(str(extra or ""))
                if pruned == str(extra or "").strip():
                    continue
                changed += 1
                if not pruned:
                    cleared += 1
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE source_files SET bm25_extra = %s, updated_at = NOW()
                        WHERE path = %s
                        """,
                        (pruned, path),
                    )
                    cur.execute(
                        """
                        UPDATE source_chunks SET bm25_extra = %s WHERE path = %s
                        """,
                        (pruned, path),
                    )
            conn.commit()
        return {"scanned": scanned, "changed": changed, "cleared": cleared}

    def iter_paths_for_doc2query(
        self,
        *,
        path_prefix: str | None = None,
        path_like: str | None = None,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """List indexed files with a short text sample for offline doc2query."""
        self.ensure_schema()
        args: list[Any] = []
        where = "1=1"
        if path_like:
            where += " AND f.path LIKE %s"
            args.append(path_like)
        if path_prefix:
            where += " AND f.path LIKE %s"
            args.append(path_prefix.rstrip("/") + "%")
        limit_sql = ""
        if limit and limit > 0:
            limit_sql = " LIMIT %s"
            args.append(int(limit))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT f.path, f.bm25_extra, f.chunk_count,
                           (
                             SELECT string_agg(sub.t, E'\\n\\n')
                             FROM (
                               SELECT c.text AS t
                               FROM source_chunks c
                               WHERE c.path = f.path
                               ORDER BY c.line_start NULLS FIRST, c.chunk_id
                               LIMIT 3
                             ) sub
                           ) AS sample
                    FROM source_files f
                    WHERE {where}
                    ORDER BY f.path
                    {limit_sql}
                    """,
                    tuple(args),
                )
                rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "path": str(row[0]),
                    "bm25_extra": str(row[1] or ""),
                    "chunk_count": int(row[2] or 0),
                    "sample": str(row[3] or ""),
                }
            )
        return out

    def search(self, query: str, *, limit: int = 10, mode: str | None = None) -> list[ChunkHit]:
        """统一检索入口：keyword / vector / hybrid（默认 settings.retrieval_mode）。"""
        resolved = (mode or settings.retrieval_mode).lower()
        if resolved == "keyword":
            return self.search_bm25(query, limit=limit)
        if resolved == "vector":
            return self.search_vector(query, limit=limit)
        return self.search_hybrid(query, limit=limit)
