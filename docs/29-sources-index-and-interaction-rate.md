# 29 — 资料库索引与交互速率（思路）

> **性质**：产品/工程思路对齐，指导后续实现；**本文不强制立刻改代码**。  
> **问题**：写作模块测 RAG 时，是否必须上传？本地 `workspace/sources` 何时进向量库？如何在**不影响 Agent 交互速率**的前提下，对齐成熟 Agent 的知识库习惯？  
> **约束继承**：[17](17-execution-plan.md) R1–R5（尤其「查询路径不建库」）；[06](06-tools-and-context.md) §0.1 / RAG=工具；[11](11-product-experience.md) TTFB；[27](27-rag-evidence-and-doc-search.md) / [28](28-rag-evidence-execution.md) 效果闸。  
> **现状刺点**（2026-07）：手改/拷贝进 `workspace/sources` **不会**自动进 pgvector；上传会触发异步 sync；`search_sources` 在 ANN 空/过期时 **keyword-fallback**（可答但不是 hybrid）。

---

## 0. 先分清三件事

| 概念 | 是什么 | 不是什么 |
|------|--------|----------|
| **语料目录** | `workspace/sources/**`（写作知识库约定根） | 不等于「已可向量召回」 |
| **索引** | pgvector（首选）或 JSON 文件库中的切块+向量+倒排 | 不是聊天记录；不是每次 Turn 的副产品 |
| **上传** | 把文件**写入**语料目录的一种 UI/API | 不是测 RAG 效果的唯一合法入口 |

成熟 Agent 的心智模型：

> **知识库 = 约定目录的持续内容；索引 = 对该目录的后台投影；对话 = 只读投影（失败再降级）。**

---

## 1. 成熟产品通常怎么做

### 1.1 会不会「本地文档全都建一次索引」？

**会，但有边界：**

1. **范围**：当前 Project / Workspace / 勾选文件夹（对应我们的 `sources/`），外加 ignore（超大文件、二进制、密钥）。  
2. **时机**：打开工程或首次启用知识库时做**初始全量**；之后只做**增量**（mtime / content hash）。  
3. **查询路径**：搜索**不重建**索引——与本仓库 A9 / docs/17 一致。

### 1.2 两种常见产品形态

| 形态 | 典型产品 | 用户感知 |
|------|----------|----------|
| **本地/挂载工作区 Agent** | IDE Agent、自托管写作台 | 「目录里有文件就能用」；后台自己索引 |
| **云端知识库** | ChatGPT Projects、企业 RAG | 「上传/连接器导入」；上传=导入语料，不是检索仪式 |

本项目写作栈更接近前者：**Docker 挂载的 `workspace` 就是知识库**；上传是导入的一种方式。

### 1.3 验证分层（不要混）

| 层 | 验什么 | 怎么验 |
|----|--------|--------|
| **契约** | 工具协议、filter、兜底 | golden / 单测 / `make eval-path-prefix` |
| **检索效果** | Recall、噪声、prefix | `make retrieval-bench` + 固定 `eval/retrieval/corpus` |
| **交互体感** | 自然问句下会不会取证、cite 能否核对 | Writing 工作台；**索引须 current** |
| **上传冒烟** | 写入→pending→ready→可搜 | 1～2 条产品路径用例即可 |

**测 RAG 算法/召回 ≠ 必须点上传。**  
上传用例验的是「导入管道」，不是「自然交互下 hybrid 是否健康」。

---

## 2. 速率红线（推荐方案的硬约束）

从「尽量不影响 Agent 交互速率」出发：

| 允许 | 禁止 |
|------|------|
| 启动后**异步**扫 `sources/`，脏文件入队 | 用户每发一条消息前全量 rebuild |
| 上传/保存后 outbox worker 增量 sync | 在 `search_sources` 热路径里 `store.sync()` |
| 索引未就绪时 **keyword-fallback**（已有） | 为等 embedding 阻塞 SSE / 首 token |
| 可选：慢轮询 mtime（30–60s）或显式「同步资料库」 | 查询时发现 empty 就同步（尾延迟炸弹） |
| 交叉编码器默认关；池与超时有预算 | Turn 内无界重排 / 多路强制检索 |

**一句话：投影永远在对话外；对话永远可降级回答。**

---

## 3. 推荐目标架构（P0 → P1）

```text
workspace/sources/**  ──(变更)──►  Index planner（脏路径）
                                      │
                                      ▼
                              outbox / 后台任务
                                      │
                          ┌───────────┴───────────┐
                          ▼                       ▼
                     pgvector 切块+向量      （失败）JSON 文件库
                          │
用户自然语言 Turn ──► search_sources 只读 ──► 命中则 hybrid
                          │
                          └─ ANN 空/过期 ──► keyword-fallback（不阻塞）
```

### P0（最小、保速率）

1. **保持** `search_sources` 只查不建。  
2. **启动后异步增量 sync**（或 `make sync-sources` / 内部命令）：对比磁盘 vs 索引 mtime，只处理脏文件。  
3. **保留 keyword-fallback**，并在 `retrieval.completed` / UI 可观测 `index_lag`（已有字段可复用）。  
4. 手测清单：语料在 `workspace/sources` → 触发一次 sync → 自然提问 → 期望 `hybrid` 而非长期 fallback。

### P1（体验对齐 IDE Agent）

1. 对 `sources/` 轻量 watch / 定时 mtime（低频）。  
2. Web「同步资料库」按钮（同一 worker，给手改 md 用）。  
3. 工作台展示「索引中 / 已同步 N 文件」（信息性，不挡发送）。

### 明确不做

- 把「每次测 RAG 必须上传」写成产品规范。  
- 查询路径同步。  
- 无 ignore 的整盘索引。

---

## 4. 手测写作 RAG 的合理做法

1. 固定小语料放在 `workspace/sources/{writing,hr,legal}/`（可与 `eval/retrieval/corpus` 同源思想，不必同一路径）。  
2. **测前**确保索引 current（P0 异步 sync 或一键同步——**不是**每次上传）。  
3. 用自然话提问（不提工具名、不提 path_prefix）。  
4. 看：是否检索、是否 hybrid、细节能否对上 md、polish 是否 0 搜。  
5. 另开 1 条上传冒烟（可选），与效果闸分开记录。

离线：`make retrieval-bench`（层 1）不依赖工作台，也不依赖上传。

---

## 5. 与现有文档的关系

| 文档 | 关系 |
|------|------|
| [27](27-rag-evidence-and-doc-search.md) | 取证 vs 文档搜索；效果三层 |
| [28](28-rag-evidence-execution.md) | RE0–RE5 票；path_prefix 已落地 |
| [03](03-docker-runtime.md) | 默认 live + pgvector + ST 镜像 |
| [17](17-execution-plan.md) A9 | 查询不建库——本文强化为产品原则 |
| 本文 | **索引生命周期与速率**：目录投影、增量、降级、手测口径 |

---

## 6. 开闸后的实现票（草案，未排期）

| 票 | 内容 | 速率影响 |
|----|------|----------|
| **IX0** | 启动异步增量 sync + `make sync-sources` | 后台 only |
| **IX1** | Web「同步资料库」+ 索引状态展示 | 无 Turn 税 |
| **IX2** | sources mtime 低频 watch | 可关；默认保守间隔 |
| **IX3** | 上传冒烟 golden（与效果闸分离） | CI 短路径 |

合并标准：Turn 路径无新增同步；`eval-all` / `retrieval-bench` 绿；手测同学句在 sync 后走 hybrid。

---

## 7. 结论口径

- **成熟做法**：对约定知识库目录做持续索引投影；对话只读；上传只是写入手段之一。  
- **我们缺的**：手改 workspace 时的投影闭环——不是缺「强制上传」。  
- **保速率推荐**：查询零建库 + 启动/变更异步增量 + keyword 降级 + 可选一键同步。  
- **验 RAG**：固定语料 + 索引 current + 自然交互；上传另测产品管道。
