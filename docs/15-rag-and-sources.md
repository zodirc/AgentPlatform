# 15 — RAG 与资料库（模块正文）

> **本模块唯一维护入口**（含原证据 RAG / 索引设计与执行文）。历史细节见 git。  
> **关联**：文风/成稿走廊 → [14](14-writing-quality.md)；工具宪法 → [06](06-tools-and-context.md)；速率 → [13](13-rate-redlines.md) R1–R5；部署默认栈 → [03](03-docker-runtime.md)。

---

## 0. 去留（合并前必答）

| # | 问题 | 不通过则 |
|---|------|----------|
| Q1 速率 | 是否推迟首 token / 热路径重嵌 / 同步 LLM？ | **否决** |
| Q2 验证 | 契约闸？效果向是否过效果闸？polish 仍 0 搜？ | **否决** |
| Q3 成熟 | 是否对应真实知识库场景，而非再造 pipeline？ | **降级或延后** |

| 方向 | 做？ | 理由 |
|------|------|------|
| 每轮强制 retrieval / 预注入向量 | **否** | 伤 cache 与 TTFB |
| Turn 末自动 judge | **否** | 违 R2 |
| 热路径默认 CE / query rewrite | **否** | 仅离线/可选 |
| `path_prefix` + 离线 A/B | **是（已落地）** | RE3 |
| 成稿取证 + cite 纪律 | **是（已落地）** | RE2 |
| keyword 字段对齐 | **条件（已落地）** | RE1 |
| ACL / 私有库 | **✅ 个人默认（MT5c）**；无 Org/share | RE4 / IX5 · [27](27-multi-tenancy.md) |
| `search_records` 真表 | **产品开闸** | RE5 / [17](17-search-records.md) |
| RQ1 检索质量（切块/embed/混合） | **RQ1a–e ✅** | §9 |

```text
素材卡 pin     → 文风 / 规范（稳定前缀）
search_sources → 事实 / 可引用片段（按需工具）
search_records → 结构化业务行（可选；非写作主路径）
```

**常设既定事实种子（写作）：** 填充路径与格式见 [`seed/sources/FORMAT.md`](../seed/sources/FORMAT.md)；文件放在 `seed/sources/writing/{persons,periods,dramas,novels}/`。  
运行时：**只读挂载**到 `/workspace/sources/seed/writing`（不拷贝进用户沙箱）；索引路径 `sources/seed/writing/...`。与 `eval/retrieval/corpus/`（效果闸）分离。手动重建索引：`make seed-sources`。

---

## 1. 三标尺与两平面

冲突裁决：**① 速率/交互 → ② RAG 质量 → ③ 成熟形态**。

| 标尺 | 过关 | 一票否决 |
|------|------|----------|
| **①** | Turn 无建库；自主搜；polish/outline **0 搜** | 查询内 sync；强制每轮搜；堵 SSE |
| **②** | 真相档 hybrid；**prod-bench** | stub/hash 冒充生产效果 |
| **③** | 目录=真相；索引=后台投影；终局 owner 私有库 | 「必须上传才测 RAG」；per-session 索引 |

```text
交互面（不改）          Index plane（Turn 外）
自然语言 → 自主 search   sources/** → dirty → ST+pgvector
成稿可搜 / polish 0 搜   启动扫 + 目录监视 + 上传 + Web 同步
```

**A9：** `search_sources` 永不在查询路径 `sync()` / 重嵌。

| 阶段 | 索引范围 |
|------|----------|
| 今 | workspace `sources/**`（含 RO 挂载的 `sources/seed/writing/**`） |
| 终局 | 个人默认 Work 私有库（IX5 ✅）+ 可选公共 seed；**无** Org 共享盘 |
| 不做 | per-session 索引 |

---

## 2. 真相档与命令

**裁判栈：** `MODEL_MODE=live` + `RETRIEVAL_BACKEND=pgvector` + `EMBEDDING_BACKEND=sentence_transformers`。

| 命令 | 证明 |
|------|------|
| `make sync-sources` | 手改 md → 索引（运维） |
| `make retrieval-bench` | hash 契约/filter；**≠** 生产召回 |
| `make retrieval-bench-prod` | **真相档**难 qrels（IX4 主闸） |
| `make eval-path-prefix` | RE3；跑完 **restore live** |
| `make turn-effect-bench` | RE2 同题 Turn（stub） |
| Web「同步资料库」 | IX1；不替代 IX4 |
| 目录监视自动投影 | IX2（`SOURCES_WATCH_*`） |
| `index-status.plane=ingestion` | IX3；`effect_ready` 恒 false |

**每日序：** 真相档 → 后台 sync → 自然问句看 `hybrid` → 改协议时 isolated+restore → 质量 PR 须 prod-bench 绿。

题集布局：[`eval/retrieval/README.md`](../eval/retrieval/README.md)；可选人工难句：[`HARD_WORKBENCH.md`](../eval/retrieval/HARD_WORKBENCH.md)。

---

## 3. 验证：契约闸 ≠ 效果闸

```text
轨 A 契约：runtime-test / golden（可 stub）
轨 B 效果：真相档
     ├─ P-offline：retrieval-bench-prod
     └─ P-workbench：自然问句 + 时间线 hybrid + 对 md
```

### 3.1 效果三层（硬闸定义）

| 层 | 内容 | 谁必过 |
|----|------|--------|
| **1 离线 A/B** | 固定语料+qrels；Recall@k；可选 p95 | IX4/RE3；RQ1 |
| **2 同题 Turn** | 同一成稿句前后对照；搜次数与墙钟 | RE2 |
| **3 工作台** | 成稿有用 / polish 0 搜 / 目录隔离 | RE2；IX4 建议 |

**仅 stub 绿不得宣称「优化有效」。**

| 允许 | 禁止（效果叙事） |
|------|------------------|
| 输入框自然问句 | slash `/rag-test` 等 |
| `make retrieval-bench-prod` | 「必须上传才算测过」 |
| 时间线核对 hybrid/path/cite | hash/stub 冒充生产 |

### 3.2 术语

| 词 | 含义 |
|----|------|
| A/B（bench） | A=无 path_prefix；B=带目录过滤（非流量实验） |
| path | workspace 相对路径 |
| Recall@k / hit | 期望 path 是否在 top-k |
| keyword-fallback / index_lag | 降级与索引落后可观测信号 |

---

## 4. 票状态（RE + IX）

| 票 | 主题 | 状态 |
|----|------|------|
| RE0 / RE3 / RE2 / RE1 | 题集、path_prefix、Turn A/B、keyword 字段 | ✅ |
| RE4 / IX5 | ACL + owner 私有库 | ✅ 个人默认 Work（docs/27 MT5c）；**否决** Org/share（原 MT6） |
| RE5 | `search_records` 真表 | ⏳ 见 [17](17-search-records.md) |
| IX0 / IX1 / IX2 / IX3 / IX4 | 启动 sync、Web 同步、目录 watch、上传≠效果闸、prod-bench | ✅ |
| RQ1 | 检索质量下一刀（切块 / embed 文本 / 分层混合；**不开 CE**） | ✅ **RQ1a–e 已落地**（§9）；大库可切 `vector_heavy` profile |

```text
IX0 ✅ → IX4 ✅ → RQ1（§9：设计已定；实现条件触发）
      → IX1 ✅
      → IX2 ✅（目录监视 → debounce 投影）
      → IX3 ✅（摄取面 ≠ 效果闸）
      → IX5 / RE4 ✅（个人默认；无 Org）
```

**主线：** 质量闸已过；Index plane 自动跟上目录；**RQ1a–e 已落地**（§9）；**IX5/RE4 个人多租户已开闸**（docs/27 MT5c）。

---

## 5. 合并门禁

```bash
make runtime-test
make eval-path-prefix    # 跑完 restore → live
# writing：make eval-all 或 writing.12/13
make retrieval-bench-prod   # 效果向必过
```

PR 自检：热路径无 sync · polish 0 搜 · 无默认同步 LLM/CE · restore 后仍 live+ST · 附 prod-bench 证据 · 无 slash 验收。

**否决：** 查询建库 · per-session 索引 · stub 冒充效果 · LLM-ACL · 无难闸上 CE · slash 测 RAG。

---

## 6. 多租户私有库（IX5 / RE4）

自用可先共享 workspace，**不能把共享当终局**。  
**结构正文（Tenant / Work / 速率宪法 / 分期）：** [`27-multi-tenancy`](27-multi-tenancy.md) · [ADR-021](adr/021-multi-tenancy-work-scope.md)。本节只保留检索面要点。

```text
owner / tenant / work
  ├─ 语料：work_root/sources/… 或行带 owner_id + work_id
  ├─ 索引：chunks 带 owner_id / work_id / visibility
  └─ search：工具层注入谓词（模型无感）；仍不 sync
```

| 要 | 不要 |
|----|------|
| 隔离键 = `work_id`（执行）+ `owner_id`（归属） | `session_id` |
| 默认 deny 他人；共享显式 | 默认可搜全站 |
| 热路径仅 SQL 谓词 | 为 ACL 再调模型 |
| 单默认 Work 自用与今日路径语义兼容 | IX0 焊死无 owner/work 列 |
| 谓词始终服务端注入 | 靠关掉 ACL 过日子 |

开闸（已落地 MT5c）：SQL `visibility=seed OR work_id=$current`；跨 Work deny 单测 + `shared.17` / `--filter tenant`；**单人默认 Work** 交互与今日同型。**不做** Org/显式 share。身份复用 [16](16-user-session-history.md) 的 `owner_user_id`；作品根见 [23](23-writing-work-model.md) / [27](27-multi-tenancy.md)。

---

## 7. 完成定义

| 里程碑 | 条件 |
|--------|------|
| 投影可用 | IX0 ✅ |
| 目录自动跟上 | IX2 ✅ |
| 摄取≠效果口径 | IX3 ✅ |
| **生产质量已验收** | IX4 ✅ prod-bench |
| 成熟多租户（个人） | IX5/RE4 ✅ MT5c（无 Org） |
| **RQ1 设计** | §9 口径已定 |
| **RQ1a–e** | ✅ 库况 · path/tag embed · 叶预算/宽表 · profile · 稀疏 tag（`INDEX_VERSION=7`） |
| 全程 | 交互未改；search 不建库；不以 hash/浅常识/上传成功冒充效果 |

---

## 8. 代码索引

| 项 | 路径 |
|----|------|
| path_prefix | `services/runtime/app/retrieval/path_filter.py` |
| keyword section | `…/keyword_hit.py` |
| 切块 | `…/chunking.py`（`build_embed_text` / `path_embed_clue`） |
| BM25 / RRF / two-level / profile | `…/bm25.py` · `fusion.py` · `two_level.py` · `profile.py` |
| embedder | `…/embedder.py` |
| 索引调度 | `…/index_scheduler.py` |
| 目录监视（IX2） | `…/sources_watch.py` |
| 摄取状态（IX3） | `services/runtime/app/services/workspace_browser.py` → `sources_index_status` |
| 层 1 runner | `scripts/retrieval_bench.py` |
| 题集 | `eval/retrieval/qrels*.yaml` |
| 语料格式 | [`seed/sources/FORMAT.md`](../seed/sources/FORMAT.md) |

---

## 9. 下一刀：检索质量优化（RQ1 · 2026-07-22）

> **状态**：**RQ1a–e ✅**（2026-07-22）。大库可将 `RETRIEVAL_PROFILE=vector_heavy`；效果仍以 prod-bench 为准。  
> **服从**：[13](13-rate-redlines.md) R1–R5；§0 Q1–Q3；**禁止**热路径默认同步 LLM / CE / query rewrite。  
> **不混入**：写作去 AI 腔 → [14](14-writing-quality.md)；Harness cache/压缩 → [12](12-model-harness.md)。

### 9.0 执行纪律（速率 × 成熟 agent）

| 约束 | 落地 |
|------|------|
| 不伤交互速率 / 逻辑 | 不改 `AgentEngine` while、不强制 retrieval、搜索路径不 sync/重嵌；质量进 **Index plane** 与**静态**工具/system 文案 |
| 贴近成熟 agent | RAG 仍为可选工具 → `tool_result`；笔记/代码继续 grep；模型自选搜几次 / 低分改 `read_file` |

**已落地序：** RQ1d → RQ1a → RQ1b → **RQ1e**（profile）→ **RQ1c**（稀疏 tag）。`INDEX_VERSION=7`。

### 9.1 问题与分流

真实知识库不是一种东西。优化先**分流**，再谈向量：

| 材料类型 | 典型形态 | 主路径 | 不要 |
|----------|----------|--------|------|
| **个人笔记 / 带格式导图** | 散文件、自用结构 | 文件夹 + `grep` / `read_file`（agent 探索同理） | 为笔记强建 embedding 库 |
| **行业规范 / 既定事实** | 可树状组织的长文、表格、同质专名多 | Index plane：树切块 → hybrid → `search_sources` | 每轮强制检索；用 LLM 改写 query 当默认 |

今日写作种子（`seed/sources/writing/{persons,periods,…}`）属第二类；agent 代码探索偏第一类 + `search_codebase` 退化。**分流纪律已部分落地**（cards pin、polish 0 搜、工具按需）；RQ1 补的是第二类在**预处理与召回混合**上的厚度。

现状差距（相对成熟自用经验）：

| 面 | 今 | 缺口 |
|----|----|------|
| 切块 | 标题树叶软顶默认 4000 字，超则滑窗；宽表 detach | 语义再切分仍不做；外挂表靠作者纪律 + 指针 |
| embed 文本 | 多为 `section_title + body`；`path` 仅元数据/过滤 | path（与可选 tag）未进入向量空间 |
| 查询侧 | 目录约定 + 可选 `path_prefix`；**无**默认同步 query 增强 | 缺显式「库况」提示（有哪些类型/目录） |
| 融合 | `default` 等权 RRF + doc_boost；`vector_heavy` 可切 | 须按库 prod-bench 标定，无通解 |
| 规模 | seed / eval 仍小；profile 已备大库 | 压力题集可后补 |

### 9.2 目标形态（Index plane）

```text
sources/**（树：从类型根 → 专名叶）
  → 按标题树切叶子；叶 ≤ ~2000 token 当量，超则滑窗
  → 表格/宽表 → 外挂文件或指针，正文留锚点（不整表塞进同一 embed）
  → 离线打少量「语义差大」的 tag（脚本；非热路径 LLM）
  → embed_text = path 线索 + tags + 正文   ← 再送 embedding
  → 后台写入 vectorstore（INDEX 版本 bump）
查询：
  → task/工具说明里写清库况（目录类型）+ 用户问句
  → path_prefix 收窄（可选）→ BM25 ∥ 向量 → 库级混合权重 → two-level
  → tool_result（预算内 excerpt）；低分则 read_file
```

**原则：** 质量主要来自**入库前结构 + embed 文本信息量**；查询侧少玩模型增强。热路径仍：**不 sync、不重嵌、不开默认 CE**。

### 9.3 分票（RQ1a–e）

| 票 | 主题 | 做什么 | 不做 |
|----|------|--------|------|
| **RQ1a** | Embed 文本拼装 | ✅ 索引时 `build_embed_text(path线索 + tags? + body)` 再 embed；`text`/excerpt 仍正文；JSON 与 pgvector 均在 `INDEX_VERSION` 变化时强制全量重建 | 查询时再调 LLM 扩写；把完整绝对路径/密钥拼进向量 |
| **RQ1b** | 树叶切块预算 | ✅ 叶优先整节；软顶 `retrieval_chunk_max_chars`（默认 4000 ≈2000 token 当量）超则滑窗；宽 GFM 表 → `[table detached]` 指针（磁盘原文保留）；FORMAT §1.1 外挂约定 | 语义再切分同步流水线；热路径动态改切块 |
| **RQ1c** | 稀疏高差 tag | ✅ 索引时从 path 类型段 + `> 类型:` / 可选 `> tags:` 提取（**不**自动吃别名）；进 RQ1a 拼装；预览 `scripts/suggest_source_tags.py` | 热路径 LLM 打 tag；别名整段灌进向量 |
| **RQ1d** | 库况进查询上下文 | ✅ `search_sources` 工具说明 + writing `system.md` 写明顶层类型；鼓励 `path_prefix`；**无**默认同步 query rewrite / CE | 为「增强 query」加 Turn 内模型调用；slash 测 RAG |
| **RQ1e** | 分层混合可标定 | ✅ `retrieval/profile.py`：`default`（等权 RRF + doc_boost=0.35）\| `vector_heavy`；可调 `RETRIEVAL_RRF_*_WEIGHT` / `RETRIEVAL_DOC_BOOST` | 宣称一套全局最优 hybrid；无 bench 凭感觉改默认 |

**INDEX：** RQ1a/b/c 任一项改变 embed 输入或切块边界 → **bump `INDEX_VERSION`** 并全量/增量重建；契约闸与 prod-bench 同 PR。

### 9.4 与现有栈的衔接

| 已有 | RQ1 怎么用 |
|------|------------|
| `path_prefix`（RE3） | 库况 + 前缀收窄；降低同行业噪声，少依赖 BM25 分词玄学 |
| two-level（doc/chunk） | RQ1e 标定对象；doc 层 ≈「先定哪棵树/哪篇」，chunk 层 ≈ 叶子证据 |
| lexical rerank 默认开 / CE 默认关 | **保持**；CE 仅离线实验 profile，不上热路径默认 |
| keyword-fallback / `index_lag` | 重建窗口内行为不变；不得用 fallback 绿冒充 RQ1 有效 |
| cards 不进 RAG | **保持**；规范类写定仍 pin，不靠向量「搜出文风」 |

Embedding 型号（如 Qwen3-8B / 1536 维半精度）属**部署选型**，不钉死本文；换模型必须过 §2 裁判栈与 `retrieval-bench-prod`，并处理维度迁移（见现 pgvector dim 校验）。

### 9.5 触发与排期

| 条件 | 动作 |
|------|------|
| 现 seed 规模、prod-bench 持续绿 | **可只保持设计**；不强行改默认切块 |
| prod-bench / 难工作台暴露「专名近邻糊、路径语义丢失」 | 优先 **RQ1a**（+ 必要 INDEX bump） |
| 单节过长、表格污染召回 | **RQ1b ✅**（预算 + detach；FORMAT §1.1） |
| 目录已清晰但仍弱 | **RQ1d**（文档/工具描述，改动面小） |
| 同质语料接近大规模（经验阈值：~10万 chunk 量级）或 BM25 贡献转负 | **RQ1e ✅**：设 `RETRIEVAL_PROFILE=vector_heavy`；仍须 prod-bench / 压力题对照 |
| tag 预览 / 补写 | **RQ1c ✅**：索引自动抽 path/元数据 tag；`python scripts/suggest_source_tags.py seed/sources/writing` |

建议落地序（有缺口时）：**RQ1d（便宜）→ RQ1a → RQ1b → RQ1e（随规模）→ RQ1c（有管线再上）**。

### 9.6 验收

| 层 | 要求 |
|----|------|
| 契约 | `make runtime-test` · `make retrieval-bench`（filter / 字段不回归） |
| 效果 | `make retrieval-bench-prod` 难 qrels **不降**；目标项 Recall@k 有对照表 |
| 速率 | 搜索热路径无 sync/重嵌；无默认同步 LLM；首 token / 工具墙钟不触 [13](13-rate-redlines.md) 红线 |
| 工作台 | 自然问句；时间线可见 hybrid / path / cite；polish 仍 0 搜 |
| 叙事禁止 | stub/hash 冒充；「上了 CE 所以更好」无离线对照；无 INDEX bump 改 embed 输入 |

### 9.7 明确不做（RQ1 范围）

1. 恢复强制 retrieval / verify 图节点  
2. 热路径默认 CE、query rewrite、Turn 末 judge  
3. 个人笔记库与行业事实库共用一套「必须向量」策略  
4. 为刷命中率把 cards / 文风材料打进 RAG  
5. 宣称与库无关的全局 hybrid 最优解  
6. 以上传成功或 `plane=ingestion` 冒充效果闸（IX3 已禁）
