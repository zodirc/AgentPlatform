# RAG

索引面（Turn 外）与交互面（`search_sources`）。生产默认数字与逐步经过以本文为准；图展开店内召回与建库。写作 / 情报走这条面；编码 Agent **不**用资料检索来找代码位置。

## 图

1. [hybrid 店内召回详流](../assets/rag/search-sources-flow-zh.png) — Chunk/Doc 双车道 · RRF · rerank · cover · fallback  
2. [索引面详流](../assets/rag/index-sync-zh.png) — 触发 · 切块 · embed · HNSW/GIN · 进度  

![search_sources hybrid](../assets/rag/search-sources-flow-zh.png)

![索引面](../assets/rag/index-sync-zh.png)

## 1. 原则与两面

冲突裁决顺序：**速率/交互 → 检索质量 → 成熟形态**。

| 面 | 何时跑 | 硬规则 |
|----|--------|--------|
| **索引面** | 启动延迟同步、目录 watch、上传、工作台「同步资料库」、内部同步命令 | 可慢；写切块向量、文档中心点、FTS |
| **交互面** | Turn 内模型调 `search_sources` | 必须快；**禁止**查询路径当场建库 / 整库重嵌 / 每轮预注入向量包 |

目录文件是真相；向量库是投影。检索结果只能经 `tool_result` 回灌下一轮组窗，**不**在 StartTurn 时预塞召回包。每 Turn 最多 **3** 次；超限这次调用直接拒绝再搜。无资料目录则 `retrieval=none`，不当成空库去 sync。

去留（一票否决向）：

| 做 | 不做 |
|----|------|
| 按需 `search_sources` · path_prefix · ACL · cite 纪律 | 每轮强制检索 · Turn 末 judge · 热路径 CE/query rewrite（默认关） |
| 个人默认 Work 私有库 + 可选 seed | Org 共享盘 · per-session 索引 |

## 2. 生产默认旋钮

| 项 | 默认 |
|----|------|
| `retrieval_mode` | `hybrid` |
| `retrieval_backend` | `pgvector` |
| 工具 `limit` | **30** |
| 每 Turn 调用上限 | **3** |
| Over-fetch | 无 prefix → `limit×2=60`；有 prefix → `limit×3=90` |
| RRF `k` | **60**；向量/BM25 权重默认 **1.0 / 1.0** |
| `doc_boost` | **0.35**（`vector_heavy` 档 0.45） |
| two-level | **ON**；超时 **0.3s**；doc 上限 **8** path |
| BM25 rescore | ON；Okapi `k1=1.5` `b=0.75` |
| Rerank | lexical **ON**；cross-encoder **OFF**；pool≥**20** |
| 摘录 | `excerpt_chars=400`；模型窗前 **5** 条带摘录 |
| Chunk（建库） | **450 token / 重叠 64**（INDEX **13**）；无分词器时字符回退 **1800 / 200**（不再按 4000 字硬切） |
| 宽表 | 行数/长度超阈可拆成指针；全文仍在磁盘，用 `read_file` 再读 |
| 交叉编码器 | 默认 **关**（R-5；召回未稳定抬之前不开）；热路径 query rewrite 默认关 |

## 3. 一次 hybrid `search_sources`（逐步）

### 3.1 入口

1. 解析查询、条数、路径前缀；合并场景默认前缀（情报默认站内情报语料）与排除（写作默认排除情报站）。  
2. 无资料目录 → `retrieval=none`，结束。  
3. 打开审计槽（融合前 / 精排后 / 进窗），供 Ops 漏斗，不进模型。  
4. **不**在查询路径上同步索引。

### 3.2 店内 hybrid（并行车道）

入口在 runtime `search_hybrid`。对传入的 `fetch_limit`（60/90），每侧 lane 深度大致：

```text
top_k = max(fetch_limit × 4, 20)
若开启 rerank：top_k = max(top_k, rerank_pool=20)
→ 常见 top_k = 240 或 360
```

**并行的是两条车道**（预算约 **0.3s**）：Doc 只出 path；Chunk 出带摘录的切块。Chunk **内部** 向量路与词法路是同线程先后召回，再融合——不是第三套并行。两车道各自 `embed(query)` 一次（同模型同维），不是全进程只 embed 一次。

**Chunk lane（主）**

| 步 | 做什么 | 要点 |
|----|--------|------|
| 向量 | 查询串 embed 一次 → 切块表 HNSW | 余弦距离；score = `1 − (embedding <=> q)`。seed 与多 Work **共用一张图**，SQL 再滤 `work_id` / `visibility`。过滤后窗可能空：会话侧 `hnsw.iterative_scan=relaxed_order`，扫描上限 `max(20000, limit×500)`，避免「库里有、窗里没有」。**不改**默认 `ef_search=40`。 |
| 词法 | GIN FTS → 可选 Okapi 重排 | 表达式：标题+正文权 **A**，`bm25_extra` 权 **C**（离线伪查询，不进向量列）。查询优先强词 OR（约 12 token 封顶），否则 AND。rescore 开时先多拉约 `limit×4` 再 Okapi（k1=1.5, b=0.75；extra 分×0.35）。 |
| 融合 | 两路都有命中 → **RRF** | `k=60`；默认向量/BM25 权重 **1.0 / 1.0**。按 **位次** 累加 `weight/(k+rank+1)`，不是把两路 raw 分相加。仅一路有命中则跳过 RRF。→ **L1 召回池**。 |
| 精排 | 词法 rerank | 词重叠 / 标题 / 短语位置加在 fusion 分上。交叉编码器默认关。→ **L2**。 |

**Doc lane（两级，默认开，与 Chunk 并行）**

1. `source_docs` 上 HNSW：该 path 下切块向量的 **算术均值**（centroid），最多 **8** 条 path。不是再 embed 一遍摘要。  
2. 空表 / 失败 / 关表开关 → 用更宽 chunk ANN 按 path 去重近似。  
3. 超时 **0.3s**：丢 doc、**保 chunk**；chunk 也空则同步再跑一遍 Chunk。

**车道合并（在 L2 之后）**

切块 `path` 落在 Doc 赢家上则 **+doc_boost（0.35）**（`vector_heavy` 档 0.45）。boosted 整段排在未命中 doc 的切块之前，**不删除**仅 chunk 命中的结果。再截到本次 `fetch_limit`（60 或 90）。doc 加分 **不写进** L2 审计快照。

### 3.3 回到工具层

1. 再滤租户：seed 需账户可见；private 必须本 Work；路径必须在沙箱内。越权则 `retrieval=denied`，不装无库。  
2. 前缀 / 排除 → 最终 **最多 30** 条。  
3. **Cover**：特色词（如 CJK≥2、较长拉丁/实体）是否出现在任一命中的 path 或摘录。  
4. Cover 过：前 **5** 条保留 ≤400 字摘录，其余只留 path/title/score；相对分 0–100（相对本轮第一名）。标记 `retrieval=hybrid`。  
5. Cover 失败 / ANN 空 / 滤空 → **keyword-fallback**：扫盘词面命中；有结果则标记回退并提示索引滞后（重建走索引面，**不在查询时**）。词面仍空但本轮曾有 ANN → **保留 ANN**，禁止整集清空装成「无库」。

### 3.4 审计三层（Ops 可读）

顺序是 **L1a → L1 → L2 →（doc_boost）→ 工具层过滤 / cover / tier → L3**。

| 层 | 何时 | 含义 |
|----|------|------|
| **L1a** | RRF 前 | 向量榜 / BM25 榜分列预览与真实条数 |
| **L1 召回池** | RRF 后、rerank 前 | 融合池；审计预览最多 20 行，真实深度另记 |
| **L2 精排** | rerank 后 | 词法（或 none / CE）后的顺序 |
| **L3 进窗** | 写入 `tool_result` 前 | 模型下一轮组窗真正看见的摘录（常短于索引 excerpt） |

旁路检索完成事件给 Ops 审计；**不进**模型上下文。

## 4. 索引面（逐步）

### 4.1 触发

| 来源 | 行为 |
|------|------|
| 启动 | 约 **3s** 延迟后增量同步（可关） |
| Watch | 轮询约 **2s**，去抖约 **1.5s** → 增量 |
| 手工 | 工作台同步、内部命令 |
| Worker | 默认可把重活扔出受理热路径（批量 / 补偿） |

范围：seed + 各 Work 私有库；跳过评测面语料；private 禁止空 work_id。

### 4.2 同步逐步

1. 比 **scope stamp**（模型名、维数、INDEX 协议、backend）与目录 mtime → 增量或强制全量。stamp 按 work/seed 分 scope，seed 抬版本不得误标评测 Work 已重嵌。  
2. 强制全量：写库前 **DROP** 切块/文档两张 HNSW（带活索引大批量 UPSERT 很慢），写完再 `CREATE INDEX`。增量 **不** drop：向量落库后由 pgvector 维护图。  
3. 脏文件 `chunk_source_text(embed=False)`：只挂 `embed_input`，本文件内不碰 GPU。  
   - **Markdown**：宽表剥离 → 按标题切节 → 宽表按行组线性化另切 → 超长滑窗 **450 token / 重叠 64**（无分词器则 **1800 / 200** 字符）。宽表指针在索引投影里；磁盘原文不变，`read_file` 仍见全表。  
   - **代码后缀**（若出现在 `sources/`）：符号分节（tree-sitter 优先）→ 同一滑窗，无表双轨。  
4. 跨文件缓冲到 cap 后批量 embed（index lane，query 可插队）：`text` 给人看 / BM25 / 摘录；送模型的是标题面包屑 + 正文（路径/标签默认不焊进前缀）。短窗仍输出 **满维** 向量（384/1024），不是更短的向量。  
5. 同一 flush 内：删该 path 旧切块 → UPSERT `source_files`（mtime）→ `source_chunks`（text + embedding）→ `source_docs`（切块向量均值）→ 把 path 级 `bm25_extra` 拷到切块（FTS C 权）。  
6. FTS **GIN** 在 schema 初始化/版本升级时建；之后随列更新由 Postgres 维护，不在每次 flush 里 `CREATE INDEX`。  
7. 私有路径存成 Work 视图前缀，展示时剥掉。进度条与就绪事件分开：扫完 ≠ 可宣称检索效果。

查询撞上空索引或滞后：**只**词面回退或提示滞后，**绝不**在 `search_sources` 里当场建库。

### 4.3 Embedding 档位与 HNSW 默认

由 `scripts/resolve_embedding_profile.sh` 写 `embedding.auto.env`：无 GPU / `RUNTIME_GPU=0` → **gte-small@384**（INDEX≈9）；VRAM≥8192 或 `RUNTIME_GPU=1` → **bge-m3@1024**、截断 **512**（INDEX **13**）。产品 runtime 与评测 bench **各加载一份**。CI / lite / 单测走 **Hash**（词面哈希，256 或测试 64 维），不承担产品召回质量。换模型、维数或截断策略 → stamp 变 → 强制重嵌。

HNSW 由 pgvector 在 `CREATE INDEX … USING hnsw (embedding vector_cosine_ops)` 时建图。本仓库 **未** 写 `WITH (m, ef_construction)`，用扩展默认：**m=16**（每层连边）、**ef_construction=64**（建图候选池）。查询默认 **ef_search=40**；生产只覆盖 iterative 扫描，不改建图参数。GIN 无应用层超参，表达式权重写在 FTS 定义里。

离线 **doc2query** 可后写 `bm25_extra`，不挡首次 sync，也不进向量列。

### 4.4 种子语料

写作常设 seed 只读挂到资料树（不拷进用户可写沙箱）。账户可关 seed 可见性：本 Work 检索与资料库 UI 看不见，挂载与索引仍可留给别的 Work。下一 Turn 生效。

## 5. 验证怎么读

| 闸 | 证明什么 | 注意 |
|----|----------|------|
| 契约 / golden / stub | 协议与主路径不炸 | **不能**冒充生产召回 |
| `make retrieval-bench-prod` 等真相档 | 离线召回/排序 | 需 live embed + pgvector |
| 工作台自然问句 | hybrid 轨迹、cite、polish **0 搜** | 时间线 + `/retrieval` 审计漏斗 |
| Ops `/official` L1 | BEIR / C-MTEB agent-path 宏分 | 独立 schema；**≠** 契约 golden；现行数字见 [`RESULTS.md`](../../eval/official/baseline/RESULTS.md)（第4轮 BEIR R@100 **0.525**，回近 INDEX12；不升 SCORECARD） |
| `make ci-proof`（Ops `suite=ci` 只是触发器） | 主路径不炸 + gate | **CI**，≠ 生产召回分数 |

三标尺同时满足才谈「检索变好」：不伤 TTFB、效果闸有对照、形态仍是工具中介而非每轮预注入。

## 6. Ops L1 多轮融合（评测侧，不改店内）

产品一次 `search_sources` 仍是店内 RRF（§3.2）。free 臂一题可多次搜索；L1 **评测侧**再把各次 `retrieval.completed` 做一次 RRF（k=60），用融合分而不是 first-seen 或 `limit-i` 伪分去算 nDCG。单次搜索顺序不变。

```text
Turn
  → search_sources #1  ranked A
  → search_sources #2  ranked B
  → L1 merge: score[d] += 1/(60+rank)   （评测侧）
  → nDCG / Recall / MAP
```

C-MTEB 写 `latest_retrieval_zh.json`，BEIR 写 `latest_retrieval.json`，互不覆盖。
