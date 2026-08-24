# RAG 深描：索引面与查询面端到端（代码对照）

`docs/topics/rag.md` 负责导览级心智模型；本页负责“能顺着代码和运行时心智读懂”的深描级流程。

> 阅读顺序建议：先看两面边界，再沿着 **索引面（Turn 外）** -> **查询面（`search_sources` 工具调用）** 的端到端主链走一遍。

---

## 0. 一句话定义（先把边界立住）

RAG 在本仓库拆成两条面：

1. **索引面（Turn 外）**：把 `sources/` 的文本切块、拼向量输入、写入向量表，并让 Postgres/pgvector 在两张表上维护 **HNSW（ANN）** 与 **GIN（FTS）**。
2. **查询面（Turn 内）**：模型只调用工具 `search_sources`；在已有索引上做 **Doc lane（centroid）** 与 **Chunk lane（文本 chunk）** 的混合检索，融合后再做 cover/tier/fallback，把结果回灌 `tool_result` 给下一轮组窗。

索引面不在查询面里同步；查询面不负责建图或重嵌入。

---

## 1. 代码对照索引（快速定位你在读哪一段）

### 1.1 索引面主链（pgvector）

- 扫描/触发：[`services/runtime/app/retrieval/index_scheduler.py`](services/runtime/app/retrieval/index_scheduler.py)
- 写入入口：[`services/runtime/app/retrieval/pgvector_store.py:PgvectorSourceRetrievalStore.sync`](services/runtime/app/retrieval/pgvector_store.py)
- 切块与 embed_input 组装：[`services/runtime/app/retrieval/chunking.py:chunk_source_text`](services/runtime/app/retrieval/chunking.py)
- deferred 批量 embed：[`services/runtime/app/retrieval/index_embed.py:assign_deferred_vectors`](services/runtime/app/retrieval/index_embed.py)
- 模型加载与 encode：[`services/runtime/app/retrieval/embedder.py:get_embedder`、`embed_many`](services/runtime/app/retrieval/embedder.py)
- 建图/倒排：[`services/runtime/app/retrieval/pgvector_store.py:_ensure_embedding_hnsw`、`_ensure_bm25_fts_index`](services/runtime/app/retrieval/pgvector_store.py)

### 1.2 查询面主链（tools + store）

- 工具入口：[`services/runtime/app/tools/core/sources_search.py:search_sources`](services/runtime/app/tools/core/sources_search.py)
- store 代理：[`services/runtime/app/retrieval/store.py:get_sources_store` 与 `search`](services/runtime/app/retrieval/store.py)
- hybrid 检索编排：[`services/runtime/app/retrieval/pgvector_store.py:search_hybrid`](services/runtime/app/retrieval/pgvector_store.py)
- 两级并行合并：[`services/runtime/app/retrieval/two_level.py:parallel_two_level`、`merge_doc_and_chunk_hits`](services/runtime/app/retrieval/two_level.py)
- 向量 lane：[`services/runtime/app/retrieval/pgvector_store.py:search_vector`](services/runtime/app/retrieval/pgvector_store.py)
- 词法 lane：[`services/runtime/app/retrieval/pgvector_store.py:search_bm25`](services/runtime/app/retrieval/pgvector_store.py)
- 融合：[`services/runtime/app/retrieval/fusion.py:reciprocal_rank_fusion`](services/runtime/app/retrieval/fusion.py)
- 精排：[`services/runtime/app/retrieval/rerank.py:rerank_hits`](services/runtime/app/retrieval/rerank.py)
- 审计 L1/L2/L3：[`services/runtime/app/retrieval/audit.py`](services/runtime/app/retrieval/audit.py)

---

## 2. 数据结构心智模型（你在 DB / Python 里看见的是什么）

### 2.1 Chunk dict：业务记录，不等于向量

索引面切块产物是 chunk dict（最终写入 `source_chunks` 表的行）。常见字段：

- `chunk_id`: `path#chunk-N`
- `path`: 相对源文件路径（用于 ACL/展示/FTS path 分组）
- `text`: 用于 BM25/截图/引用展示的正文片段
- `section_title`: 所属标题
- `citation_id`: `cite:{stem}`
- `line_start/end`: 原文行号
- `vector`: 长度固定的稠密向量（只在同步 embed=True 时直接写入 chunk dict）
- `embed_input`: deferred 路径中，先塞这里，最后 batch embed 写 `vector`

关键：**送进 embedder 的永远是字符串**，而不是 chunk dict。

### 2.2 向量维数：与 chunk 长度解耦

embedding 输出维数来自当前 embedder/模型配置：

- Hash：默认 256（或测试里压到更小）
- `gte-small`：384
- `bge-m3`：1024

短 chunk 仍输出满维稠密向量；短语义覆盖面更窄，但不是更短向量。

---

## 3. 索引面（Turn 外）端到端：从扫描到 HNSW/GIN 就绪

> 这里的“端到端”以 `PgvectorSourceRetrievalStore.sync()` 为中心。

### 3.1 `sync()`：scope stamp 决定增量还是强制重建

入口在 [`pgvector_store.py:sync`](services/runtime/app/retrieval/pgvector_store.py)：

1. `ensure_schema()`：创建/迁移三表 + 启用 pgvector 扩展 + 建（或重建）FTS GIN + HNSW（见后文）。
2. `stored_stamp = _read_scope_stamp(scope_id)`：读取 `source_index_meta` 中的 scope 版本信息。
3. `force_reindex = scope_stamp_mismatch(stored_stamp, stamp)`：模型/维数/INDEX 协议/后端变了就 force。
4. 扫描 `sources_dir` 下 mtime 改变的“dirty 文件列表”，并把每个 dirty 文件交给 chunk_source_text 产出 chunk dict（但 **embed=False**，只写 `embed_input`）。

> 注：`stamp` 是 per-work/per-seed 的，不是全局 version。seed 的升级不能误跳过评测 Work。

#### 代码片段：`PgvectorSourceRetrievalStore.sync` 主线（索引面）

```python
def sync(
    self,
    sources_dir: Path,
    *,
    workspace_root: Path,
    work_id: str | None = None,
    visibility: str = "private",
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    """增量/全量同步 sources_dir -> PostgreSQL（切块 -> embed -> 落库 -> 索引）。"""
    # 流程概要:
    # 1) ensure_schema()
    # 2) scope stamp 决定增量或 force_reindex
    # 3) dirty files -> chunk_source_text(embed=False)
    # 4) _flush_buffer(): assign_deferred_vectors() + UPSERT 三表 + bm25_extra 拷贝
    # 5) force 时 drop HNSW 再 _ensure_embedding_hnsw() + 写回 scope stamp
```

### 3.2 `chunk_source_text(embed=False)`：为什么不是在这里立刻 embed？

`chunk_source_text` 在 [`chunking.py`](services/runtime/app/retrieval/chunking.py) 中负责：

- 切块（Markdown 四段流水线、代码分节、宽表剥离等）
- 对每个 chunk 滑窗 part：
  - 写 `chunk["text"]`（干净正文，用于展示/FTS A 权）
  - 写 `chunk["embed_input"]`（标题面包屑 + 正文 part + 可选 tags/prefix，用于稠密向量）

当 `embed=False` 时，它不会调用 embedder，只返回 chunk dict 列表（每条带 `embed_input`）。

#### 代码片段：`chunk_source_text`（embed=False 延迟路径）

```python
def chunk_source_text(
    path: Path,
    rel_path: str,
    text: str,
    *,
    embedder,
    tags: Sequence[str] | None = None,
    embed: bool = True,
) -> list[dict[str, Any]]:
    """
    embed=True  -> 写 vector（同步 encode）
    embed=False -> 写 embed_input（交 index_embed.assign_deferred_vectors）
    """
```

延迟 embed 的核心原因：生产 sync 可能持续很久，应该用批量 encode 吞吐，并避免把 GPU/ST 冷启动/长 batch 挤在每个文件上。

### 3.3 `assign_deferred_vectors()`：跨文件批量 embed（index lane）

当 dirty 文件收集完，sync 会跨文件缓冲 chunk dict 到 cap（由 `index_flush_chunk_cap` 控制），然后调用：

- [`services/runtime/app/retrieval/index_embed.py:assign_deferred_vectors`](services/runtime/app/retrieval/index_embed.py)

它的行为是：

1. 从每条 chunk dict 中 `pop("embed_input")`
2. `embed_many(embedder, texts, lane=LANE_INDEX)`
3. 把得到的 `vector` 填回 chunk dict

其中 `LANE_INDEX` 来自 [`embedding_lanes.py`](services/runtime/app/retrieval/embedding_lanes.py)，用于让 query lane 可以插队（QoS 隔离）。

#### 代码片段：`assign_deferred_vectors`（跨文件批量 embed）

```python
def assign_deferred_vectors(
    chunks: list[dict[str, Any]],
    embedder: Any,
    *,
    label: str = "sources",
    chunks_done_before: int = 0,
    chunks_total_hint: int | None = None,
) -> int:
    """把切块阶段挂起的 embed_input 送进向量模型，原地写入 vector。"""
    # 关键动作:
    # - pop("embed_input") -> batch encode via embed_many(..., lane=LANE_INDEX)
    # - write chunk["vector"]
```

### 3.4 `_flush_buffer()`：一次 flush 写入三表 + FTS C 权

在 `sync()` 的内部嵌套函数 `_flush_buffer()` 中，实际写入发生在同一批事务里：

1. **DELETE**：`DELETE FROM source_chunks WHERE path = ANY(paths)`
2. **UPSERT**：
   - `source_files`：`mtime/chunk_count/work_id/visibility/owner_user_id`
   - `source_chunks`：chunk 行（`text` + `embedding vector`）
   - `source_docs`：doc centroid（同一 path 的 chunk embedding 均值）
3. **bm25_extra 拷贝**：`UPDATE source_chunks SET bm25_extra = source_files.bm25_extra`

`bm25_extra` 的来源是离线 doc2query（RET-11b），其优点是：FTS 的稀疏命中增强不依赖 dense 向量。

> 注意：HNSW/GIN 索引本身是 Postgres/pgvector 的机制，Python 写入的是表行数据；索引更新由数据库侧维护或由 force 重建保证一致性。

### 3.5 HNSW/GIN 何时“建图/建索引”

#### HNSW（两张图）

- `_ensure_embedding_hnsw()`：在 `ensure_schema()` 或 sync 末尾调用。
- 全量 force 时：`_drop_embedding_hnsw()` 先删除两张 HNSW 索引，写完再 `_ensure_embedding_hnsw()` 重建。

DDL 在 [`pgvector_store.py:_ensure_embedding_hnsw`](services/runtime/app/retrieval/pgvector_store.py)：

```sql
CREATE INDEX IF NOT EXISTS source_chunks_embedding_hnsw
ON source_chunks
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS source_docs_embedding_hnsw
ON source_docs
USING hnsw (embedding vector_cosine_ops);
```

本仓库未写 `WITH (m=..., ef_construction=...)`，因此使用 pgvector 默认值（当前注释已在代码里对齐默认 m=16 / ef_construction=64 的语义与范围）。

#### GIN FTS

`_ensure_bm25_fts_index()` 在 `ensure_schema()` 阶段幂等创建（或按版本重建）。

表达式 `BM25_TSVECTOR_SQL` 用：

- `section_title + text` 作为 FTS A 权
- `bm25_extra` 作为 FTS C 权

同步 flush 只负责更新 `text/section_title/bm25_extra` 列；倒排结构由 Postgres 维护。

---

## 4. 查询面（Turn 内）端到端：从 `search_sources` 到 tool_result

> 查询面以工具入口 `search_sources()` 为主，后面委托 store.search 与 store.search_hybrid。

### 4.1 工具层：`search_sources()` 负责“热路径约束 + cover/tier/fallback”

入口在 [`services/runtime/app/tools/core/sources_search.py:search_sources`](services/runtime/app/tools/core/sources_search.py)。

关键约束：

- 热路径不 `store.sync()`（禁止查询时建库）
- 只在 schema ready 时加载 index（pgvector_store 的 `load()`）
- 如果 ANN 命中但 cover 失败，会先尝试 keyword-fallback；如果 keyword 也空，会保留 ANN（某些 SciFact 场景 claim!=abstract）。

因此“下一步是什么”不是再建图，而是：

1. `raw_hits = store.search(query, limit=fetch_limit, mode=mode)`
2. tenant/path/exclude 过滤
3. 格式化 hit（摘录、tier、相对分）
4. cover 校验
5. cover miss -> keyword-fallback（不在查询时建库）
6. 组装 `tool_result`，并写入 L3

#### 代码片段：`search_sources` 工具层（热路径约束 + fallback）

```python
async def search_sources(
    query: str,
    limit: int = 30,
    path_prefix: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """在 sources/ 语料库中检索（vector/hybrid/keyword + 多层 fallback）。"""
    # 关键约束:
    # - 热路径不 store.sync()
    # - schema ready 时 load() index
    # - raw_hits = store.search(query, limit=fetch_limit, mode=mode)
    # - cover fail -> keyword-fallback; keyword 也空可能保留 ANN
```

### 4.2 店内 hybrid：`store.search_hybrid()` 负责召回融合与 rerank

入口在 [`pgvector_store.py:search_hybrid`](services/runtime/app/retrieval/pgvector_store.py)。

结构上它做两层工作：

1. **并行两车道**：doc lane + chunk lane（预算约 0.3s）
2. **串行融合/精排**：RRF -> rerank -> doc_boost merge

#### 代码片段：`search_hybrid`（two_level并行 + RRF/rerank + doc_boost）

```python
def search_hybrid(self, query: str, *, limit: int = 10) -> list[ChunkHit]:
    """店内 hybrid 检索 orchestrator（query path, 不调用 sync）。"""
    # 主流程（two_level 默认启用）:
    # - parallel_two_level(doc_fn, chunk_fn, timeout_seconds)
    #   - doc_fn: source_docs centroid HNSW -> doc_paths
    #   - chunk_fn: search_vector(HNSW) + search_bm25(FTS GIN) -> RRF -> rerank_hits
    # - merge_doc_and_chunk_hits(doc_paths, chunk_hits, doc_boost)
    # - 返回 merged[:limit]
```

#### 4.2.1 并行：Doc lane + Chunk lane

并行在 [`two_level.py:parallel_two_level`](services/runtime/app/retrieval/two_level.py) 内跑两个 worker：

- Doc lane：`_search_docs_ann()`（只返回 path 列表）
  - 依赖 `source_docs_embedding_hnsw`
  - 每个 doc 向量是该 path 下 chunk embedding 的均值（centroid）
- Chunk lane：`_chunk_lane()`，内部包含：
  - `search_vector()`：HNSW ANN 召回 chunk
  - `search_bm25()`：GIN FTS 召回 chunk（可选 Okapi rescore）
  - `reciprocal_rank_fusion()`：按 chunk_id 的 rank 位次做 RRF 融合
  - `rerank_hits()`：默认 lexical 精排（cross-encoder 默认关）

#### 4.2.2 Chunk lane：向量路 + 词法路

**向量路**：`search_vector()` 在 [`pgvector_store.py`](services/runtime/app/retrieval/pgvector_store.py) 内执行：

- `query_vec = get_embedder().embed(query)`
- `_prepare_hnsw_filtered_scan()`：开启 iterative_scan 的 relaxed_order，并抬扫描上限（避免 seed+work 过滤导致 ANN 空窗）
- SQL：`ORDER BY embedding <=> query_vec LIMIT k`
- 从结果行构造 `ChunkHit`（包含 `excerpt/text/line/citation/score` 等）

**词法路**：`search_bm25()` 直接利用 GIN 索引：

- 构造 tsquery（强词 OR / 否则 plainto AND）
- `BM25_TSVECTOR_SQL @@ tsquery`
- 初排：`ts_rank_cd` 或在 rescore 关闭时直接按 ts_rank 返回
- rescore 开时：拉更大池（`limit*4`），再用 Okapi BM25 在 Python 重排（并考虑 `bm25_extra*0.35`）

#### 4.2.3 融合：RRF + rerank

`reciprocal_rank_fusion()` 在 [`fusion.py`](services/runtime/app/retrieval/fusion.py) 中：

- 输入是两路 ranked list：`[(chunk_id, score)]`，score 只用来读位次
- RRF 公式用 `weight/(rrf_k+rank+1)` 累加到同一个 chunk_id
- 取 fused top-N

随后 `rerank_hits()`：

- lexical 模式：词重叠、标题/短语位置等信号加权在 fusion 结果上
- cross-encoder 模式：由实验开关决定（默认 off）

最后 L2（审计）会记录 rerank 后的 ranked 列表。

#### 4.2.4 Doc lane 加分：`doc_boost` 发生在 L2 之后

doc lane 只返回 doc paths。

`merge_doc_and_chunk_hits()` 在 [`two_level.py`](services/runtime/app/retrieval/two_level.py) 内：

- 如果 chunk.path in doc_paths：`score += doc_boost`（默认 0.35）
- boosted 的 chunk 排到未命中 doc 的 chunk 前面
- 不会丢弃仅 chunk 命中的结果

---

## 5. 审计层：L1a / L1 / L2 / L3 与代码的对应

审计逻辑在 [`audit.py`](services/runtime/app/retrieval/audit.py)。

本页给你一个对照表，直接对应代码里的 `record_*` 调用点：

#### 代码片段：审计（`audit.py` 的 L1a/L1/L2/L3 写入）

```python
def record_lane_hits(*, vector: list[Any], bm25: list[Any]) -> None:
    """L1a: 融合前 lane 预览（vector/bm25）。"""

def record_recall_pool(hits: list[Any], *, source: str = "fused") -> None:
    """L1: RRF 后 recall pool（进入 rerank 前）。"""

def record_ranked(hits: list[Any], *, method: str) -> None:
    """L2: rerank 之后 ranked 列表。"""

def build_entered_context(hits: list[dict[str, Any]], *, excerpt_chars: int) -> list[dict[str, Any]]:
    """L3: 写入 tool_result 的摘录行。"""
```

| 层 | 对应代码（函数） | 在哪里触发 |
|---|---|---|
| **L1a** | `record_lane_hits(vector=..., bm25=...)` | `search_hybrid._chunk_lane()` 中，RRF 前 |
| **L1** | `record_recall_pool(hits, source=...)` | RRF 后、rerank 前 |
| **L2** | `record_ranked(hits, method=...)` | rerank_hits 后（或 rerank 关闭 method=none） |
| **L3** | `build_entered_context()` / `finalize_audit_for_result()` | `sources_search` 工具层写入 `tool_result` 前 |

审计槽只在你打开 capture 时工作；默认关闭不会进入模型上下文。

---

## 6. 典型问题如何定位（对照代码找原因）

下面把常见 symptom 与“该读哪个函数”对应起来。

### 6.1 结果为空，但资料目录存在

优先检查：

1. 工具层 `search_sources` 的 `index_lag` / `prefix_empty_after_filter` 标记
2. pgvector_store 的 `ensure_schema()` 是否已经成功，HNSW/GIN 是否存在
3. `scope stamp` 是否发生 mismatch 导致 force_reindex 未完成

定位函数：

- [`sources_search.search_sources`](services/runtime/app/tools/core/sources_search.py)
- [`pgvector_store.PgvectorSourceRetrievalStore.ensure_schema`](services/runtime/app/retrieval/pgvector_store.py)

### 6.2 向量 lane 有命中但 cover miss

这不是索引错误，属于“结果不够贴近 query 的 cover 约束”：

- `search_sources` 会触发 keyword-fallback
- 若 keyword 也空，保留 ANN 排序（避免 SciFact claim!=abstract 场景被清空）

定位函数：

- [`sources_search.search_sources` 的 cover 分支](services/runtime/app/tools/core/sources_search.py)

### 6.3 doc lane 永远为空

检查：

- `source_docs` 表是否写入（看 sync 是否写 `source_docs_embedding_hnsw` 的 centroid）
- 过滤条件是否在 seed/work 时导致空窗（若过滤空，会走 `_doc_lane_approx` 降级）

定位函数：

- [`pgvector_store._search_docs_ann`](services/runtime/app/retrieval/pgvector_store.py)

### 6.4 BM25 召回弱（专名/数字问题）

检查：

- 离线 doc2query 是否跑过并写了 `bm25_extra`
- `BM25_TSVECTOR_SQL` 权重（A vs C）是否符合当前 chunking 策略

定位函数：

- [`doc2query.run_doc2query`](services/runtime/app/retrieval/doc2query.py)
- [`pgvector_store._ensure_bm25_fts_index`](services/runtime/app/retrieval/pgvector_store.py)

---

## 7. 读代码的最后技巧：从“你要回答什么问题”反推函数入口

如果你在读代码时卡住，问自己下面三类问题之一：

1. **你在看“向量是怎么来的”**：从 `chunking.chunk_source_text` -> `index_embed.assign_deferred_vectors` -> `embedder.embed_many`。
2. **你在看“图/索引怎么来的”**：从 `_drop_embedding_hnsw` / `_ensure_embedding_hnsw`（HNSW）或 `_ensure_bm25_fts_index`（FTS）。
3. **你在看“为什么本次 search_sources 结果是这样”**：从 `sources_search.search_sources` -> `store.search_hybrid` -> `search_vector/search_bm25` -> RRF/rerank -> cover/tier/fallback。

---

