# 27 — 证据 RAG 与文档检索优化（去留与设计）

> **性质**：可排期的设计稿；**本文本身不改代码**。票级落地见 [`28-rag-evidence-execution.md`](28-rag-evidence-execution.md)。  
> **问题**：在 WQ0–WQ4 与 S0–S3 检索骨架已落地后，下一刀优化应落在哪里？「写作再加 RAG」是否值得？企业文档 / Agent App 搜索应如何与写作共用同一检索面？  
> **约束继承**：[17](17-execution-plan.md) R1–R5；[11](11-product-experience.md) TTFB / 首 token；[23](23-writing-quality.md) §4（RAG 只服务证据）；[06](06-tools-and-context.md) §0.1 / §10（RAG = 工具，禁止每轮预注入）；[ADR-005/006](adr/)。  
> **现状基线**（2026-07）：`search_sources` 热路径只查不建索引；markdown section 切块已带 `section_title` / 行号；hybrid + **默认 pgvector**（不可用时回退 json）+ two-level；lexical rerank 默认开、cross-encoder 默认关；写作 pass 走廊仅成稿/核对可检索；`writing.12/13` 断言 0 RAG；`search_records` 仍为诚实 stub（[`18`](18-a20-multitable-recall.md)）。  
> **本文结论（摘要）**：**禁止**把「写作质量」做成每轮强制检索或默认 judge。下一阶段优化两条并行主线——**(A) 成稿取证质量**（W2/W7）与 **(B) 企业文档/Agent 搜索工程**（filter / ACL / 可追溯）——共享同一工具协议与速率红线；文风与规范继续靠卡 pin（23），不靠多搜。**验证分两闸**：契约/回归闸（stub golden）≠ 效果闸（离线 Recall A/B + 同题 Turn 对照 + 工作台交互清单）；合并效果向改动必须过效果闸。详见 §0 / §5.4 / §8 / §8.1。

---

## 0. 去留与优先级（先读）

### 0.1 优化准入三问（合并前必答）

任何检索相关改动，合并前必须书面回答：

| # | 问题 | 不通过则 |
|---|------|----------|
| **Q1 速率** | 是否推迟 `turn.accepted` / 首 token 前多一轮模型 / 把重活塞进热路径？ | **否决** |
| **Q2 验证** | 是否有契约闸（golden/单测）？效果向改动是否过效果闸（离线 A/B / 同题对照 / 清单）？改稿是否仍 0×`search_sources`？ | **否决** |
| **Q3 成熟** | 是否对应真实岗位场景（知识库检索、引用闭环、ACL），而非「再造 pipeline」？ | **降级或延后** |

### 0.2 决策表

| 方向 | 近期末？ | 理由 |
|------|----------|------|
| 每轮强制 retrieval / 预注入向量包 | **否** | 违 23§4、06§0.1；伤 cache 与 TTFB |
| Turn 末自动 fact-check / judge Agent | **否** | 违 17 否决项与 R2 |
| 热路径默认 cross-encoder rerank | **否** | A12 已定；仅离线/可选 profile |
| Skills 预注入扛「检索质量」 | **否** | 见 22；主路径应在工具与索引 |
| **`path_prefix` filter + 离线 Recall A/B 题集** | **是（优先，效果清晰）** | 降噪可感知；题集证明 A/B；速率友好 |
| **成稿取证：同题 A/B Turn + cite 纪律 + stub 回归** | **是（紧随）** | stub 证契约；同题对照证体感 |
| **命中字段对齐（keyword fallback）** | **是（条件做）** | 仅当 fallback/可追溯真痛；须耗时预算 |
| **命中 ACL 谓词（最小）** | **是（B 后半，有产品触发再做）** | 内部知识库硬门槛；deny→0 hits |
| **`search_records` 接一张真实表** | **可选（产品触发）** | 18 蓝图；通道超时降级；非写作主路径 |
| 前缀稳定 / cache（C1–C5）继续守住 | **保持** | 检索结果永不进 cache 前缀 |
| 万档图检索 / 多租户 SaaS 检索中台 | **非当前目标** | 与 17 产品焦点一致；先有评测集再扩 |

### 0.3 一句话分工

```text
素材卡 pin     → 文风 / 规范 / 少样本（稳定前缀，吃 cache）
search_sources → 事实 / 细节 / 可引用片段（可变后缀，按需工具）
search_records → 结构化业务行（可选；非写作主路径）
```

**质量 ≠ 资料越多、检索越勤。** 资料解决「写得对不对得上材料」；卡与模板解决「像不像、排得齐不齐」。

---

## 1. 现状盘点（已有 vs 缺口）

### 1.1 已落地（勿重复造）

| 能力 | 位置 | 备注 |
|------|------|------|
| 工具化 RAG | `tools/core/tools.py` `search_sources` | 模型按需调用；热路径 `load+search` |
| Section 切块 | `retrieval/chunking.py` | `section_title`、行号、`citation_id` |
| Hybrid / BM25 / vector | `vector_index` / `fusion` / `bm25` | `RETRIEVAL_MODE` |
| 两级召回 | `two_level.py` | doc↔chunk；超时可降级 |
| **默认 ANN** | `pgvector_store.py` | 默认 `RETRIEVAL_BACKEND=pgvector`；探测失败回退 json |
| 异步索引 | A9 / worker | 禁止 query 时 `sync()` |
| 写作检索纪律 | 23§4 + `writing.12/13` | 改稿/polish 0 检索可断言 |
| 假引用标记 | A2 evidence set | 不阻断流式；`unverified` |
| 低分 hint | `search_sources_low_score_hint` | 引导 `read_file` |

### 1.2 真实缺口（本方案只补这些）

| 缺口 ID | 表现 | 影响场景 |
|---------|------|----------|
| **G1** | 取证效果缺少 **同题对照 / 工作台验收**；仅 stub golden 不够 | 写作 W2「更好用」无法证明 |
| **G2** | `search_sources` 无 `path_prefix` / `tags` 等过滤 | 资料一多噪声大；不像企业文档搜索 |
| **G3** | keyword fallback 命中形态弱于向量命中（缺 section/行号时） | 索引滞后时 cite 闭环变脆（**条件修**） |
| **G4** | 无最小 ACL（谁可见哪份 sources） | 无法对标内部知识库岗位叙事 |
| **G5** | `search_records` 仍 stub | 结构化业务检索无法演示 |

G2 优先落地（效果清晰）；G1 用效果闸补齐；G3 条件做。G2+G4（+可选 G5）构成 **线 B**；G1+G3 构成 **线 A**。

---

## 2. 场景切片（从用户任务出发，不从技术名词倒推）

### 2.1 写作（继承 23 W1–W7）

| 场景 | RAG？ | 本方案动作 |
|------|-------|------------|
| W1 立人设/定调 | 否 | 不动；继续卡 pin |
| **W2 据材料新写** | **要（预算内）** | **线 A**：同题 A/B + cite 纪律 + stub 回归 |
| W3 局部改稿 | 通常否 | 锁死 0 检索回归 |
| W4 去 AI 味 | 否 | 锁死 0 检索回归 |
| W5 大纲 | 否 | 不动 |
| W6 交稿排版 | 否 | 不动 |
| **W7 核对引用** | 按需补证 | **线 A**：`check_citation` + 缺口补搜 |

### 2.2 岗位向：企业文档 / Agent App 搜索

| 场景 ID | 用户在做什么 | 痛点 | 主杠杆 | 速率注意 |
|---------|--------------|------|--------|----------|
| **D1 库内问答** | 「按制度说明 X」 | 幻觉、假出处 | hybrid + cite + `read_file` | 工具调用；索引异步 |
| **D2 目录/标签缩小范围** | 「只在 `hr/` 下找」 | 全库噪声 | **path/tag filter** | 过滤在检索侧 |
| **D3 权限隔离** | 普通员工不能见机密 | 越权命中 | **ACL 谓词** | 命中后过滤或索引打标 |
| **D4 结构化工单/记录** | 「查我名下未关单」 | 纯文档 RAG 不够 | `search_records` 通道 | 每通道 ≤300ms 降级 |

D1–D3 与写作共用 `search_sources`；D4 走独立工具，避免把 SQL 语义塞进文档索引。

---

## 3. 速率红线（R1–R5 在本方案中的含义）

| 红线 | 本方案含义 |
|------|------------|
| **R1** | 建索引、重嵌、全库扫描 **不得**推迟 `turn.accepted` |
| **R2** | 首 token 前禁止「为检索质量再问一小模型」（含 query rewrite LLM） |
| **R3** | filter / ACL / schema 校验：毫秒级；禁止默认 CE rerank |
| **R4** | 重嵌、批量评测、召回曲线 → 异步 / 离线 / `make eval-retrieval` |
| **R5** | 每票至少：单测或 golden；涉及写作时必须保留 `writing.12/13` 绿 |

**禁止的「质量换速度」模式**：

```text
用户提问 → 自动全库向量预注入 → 再生成
成稿完 → 自动 delegate(fact_checker) → 再改一稿再给用户
查询前 → 同步 LLM 改写 query → 再检索
```

**允许的成熟模式**：

```text
模型调用 search_sources(query, path_prefix?) → tool_result（可变后缀）
  → 低分 hint → read_file
  → draft / 回答 + citation_id ∈ evidence
索引 / 重嵌 → worker / 上传路径（不在 query 热路径）
```

---

## 4. 成熟做法对照（岗位叙事）

| 业界常见组件 | 本仓库对应 | 本方案是否加厚 |
|--------------|------------|----------------|
| Chunking + 标题上下文 | `chunking.py` section 切块 | 是：命中展示与 golden 对齐 |
| Hybrid 检索 | BM25 + vector + RRF | 保持；不默认 CE |
| Parent / 两级召回 | `two_level.py` | 保持；超时降级已有 |
| Metadata filter | **缺口 G2** | **要做** |
| ACL | **缺口 G4** | 最小谓词；产品触发 |
| Citation grounding | A2 + `check_citation` | golden 加厚 |
| 结构化检索 | `search_records` stub | 可选一张表 |
| Agentic RAG（模型决定是否搜） | 已是主路径 | **保持**；禁止改回固定检索节点 |

面试/履历可讲的闭环：

> 在 agentic loop 内把文档检索做成工具；写作场景用 pass 检索开关保护速率；企业场景用 filter+ACL 降噪与隔离；用 golden 证明「该搜才搜、假引用可标记」。

---

## 5. 线 A — 成稿取证质量（设计）

### 5.1 目标

在 **不增加默认检索次数** 的前提下，提高 W2「按资料写」时：命中正确片段 → 可引用 → 可核对。

### 5.2 手段（确定性优先）

1. **命中载荷一致**：向量命中与 keyword fallback 尽量对齐字段（`path` / `chunk_id` / `section_title` / `line_*` / `citation_id` / `excerpt`）。  
2. **Golden 加厚**：固定资料库 → 固定 query → 断言 top hit 落在期望 path/section；成稿 cite ∈ evidence；假 cite → `unverified`。  
3. **预算纪律不变**：成稿 ≤2–3 次 `search_sources`；低分改 `read_file`；改稿/polish **0 次**。

### 5.3 非目标

- 不引入「写作专用检索服务」或图节点。  
- 不把检索命中写入 system / cache 前缀。  
- 不用 LLM judge 给「取证分」。

### 5.4 验证面（契约闸 ⊂ 效果闸）

| 闸 | 类型 | 用例意图 | 能否证明「更好用」 |
|----|------|----------|-------------------|
| **契约/回归** | 单测 + stub golden | filter/字段/0-RAG/假 cite 标记 | **否**（只证没写坏） |
| **效果** | 离线题集 A/B | Recall@k / section 命中率 / 检索 p95 | **是**（检索本身） |
| **效果** | 同题 Turn A/B | 引用对材料、搜次数、墙钟 | **是**（agent 交互） |
| **效果** | 工作台清单 | 成稿有用、polish 不搜、目录隔离 | **是**（体感） |

完整三层定义见 **§8.1**。仅过 stub 绿 **不得**宣称「取证质量已提升」。

---

## 6. 线 B — 企业文档 / Agent 搜索（设计）

### 6.1 Filter（先做）

`search_sources` 增加可选参数（名称落地以 contracts / ToolSpec 为准）：

| 参数 | 语义 | 实现要点 |
|------|------|----------|
| `path_prefix` | 只搜 `sources/` 下某前缀 | 命中后或索引侧过滤；非法前缀 → 空 + hint |
| `tags`（可选二期） | frontmatter / 侧车标签 | 无标签文件视为不匹配该 filter |

速率：纯字符串前缀/集合，不引入模型。

### 6.2 ACL（有产品触发再做）

最小形态（避免做成权限中台）：

```text
search_sources → 原始 hits
  → acl_predicate(user_id, path)   # 确定性；默认 allow-all（dev）
  → 过滤后 hits（越权直接丢弃，不报路径 enumeration 细节）
```

- 默认配置：**关闭或 allow-all**，保证本地/golden 不破。  
- Golden：deny 策略下机密路径 **0 hits**。  
- **禁止**为 ACL 再调一轮模型。

### 6.3 `search_records`（可选）

继承 [`18`](18-a20-multitable-recall.md)：一张业务表 + 一通道 + `asyncio.wait_for(..., 0.3)` + ACL。  
与文档 RAG **分工具**，避免「用向量搜工单号」。

### 6.4 验证面

| 闸 | 类型 | 用例意图 |
|----|------|----------|
| 契约 | 单测 | `path_prefix` 只返回子集；越界前缀空结果 |
| 契约 | Golden | 带 filter 的检索 Turn；writing 0-RAG 仍绿 |
| **效果** | 离线 A/B | 同题：无 filter vs 有 filter → 噪声命中下降、目标 path 仍召回 |
| **效果** | 工作台 | 只挂 `sources/hr/` 时不应冒出 `legal/` 片段 |
| 开闸后 | ACL / records golden | deny → 0；timeout → `degraded` |

---

## 7. 明确不做（全程否决）

| 项 | 原因 |
|----|------|
| 每轮预注入 RAG | 速率 + cache |
| 默认 CE rerank | R3；A12 |
| 同步 LLM query rewrite | R2 |
| 自动串联「成稿→审校→再写」 | 17 否决 |
| 为检索质量默认开启 Skills 层 | 22 |
| 写作与企业库两套 loop | 违「一个内核」 |

---

## 8. 优先级与依赖

效果优先于「字段整洁」。推荐顺序：

```text
RE0 基线 + 离线题集骨架
  → RE3 path_prefix + 离线 Recall A/B（效果清晰、速率友好）
  → RE2 stub 回归 + 同题 Turn A/B + 工作台清单
  → RE1 命中字段对齐（仅当 fallback/可追溯真痛；须耗时预算）
  → RE4 ACL / RE5 records（产品开闸）
```

| 相对旧草案 | 变更理由 |
|------------|----------|
| RE3 提前到 RE1 前 | filter 用户可感知；离线 A/B 易做；几乎不增延迟 |
| RE1 降为条件票 | 多数 hybrid 正常路径感知弱；避免无效果闸的整洁度工程 |
| RE2 不只 stub | stub 证契约；同题对照 + 清单证「实际更好」 |

与既有文档关系：

| 文档 | 关系 |
|------|------|
| [23](23-writing-quality.md) / [24](24-writing-quality-execution.md) | 文风与排版已收口；本文不重复 WQ，只补证据 RAG |
| [17](17-execution-plan.md) | S0–S3 检索骨架已落地；本文是其后的质量/产品向增量 |
| [18](18-a20-multitable-recall.md) | RE5 的蓝图来源 |
| [06](06-tools-and-context.md) | 工具协议与「RAG 必须是工具」宪法 |
| [12](12-eval-and-golden-turns.md) | 契约/golden 分层；**效果闸是其上的产品验收** |

---

## 8.1 效果验证三层（硬闸定义）

Stub golden **必要但不充分**。凡宣称「检索/取证优化有效」的 PR，除契约闸外须满足本节约定。

### 层 1 — 离线检索 A/B（不跑完整 agent）

```text
固定小语料（约 10～30 篇 sources）+ 题集（query → 期望 path/section）
  A = 合并前实现 / 无 filter
  B = 合并后实现 / 有 filter（或新字段路径）
指标：Recall@k、MRR 或 section 命中率；可选检索耗时 p95
```

- **证明什么**：切块、过滤、fallback 对齐是否让「该命中的更容易命中」。  
- **不依赖** live 模型；可脚本化；适合 RE3（必做）、RE1（若做则必做）。  
- **落地位置建议**：`eval/retrieval/` 或 `scripts/` 下小型 bench（票级见 28）。

### 层 2 — 同题 A/B Turn（真 agent 交互）

同一用户句（例：「按资料写第 N 章并引用」），合并前后各跑一轮（Workbench 或 `recorded`/`live`）：

| 观察 | 通过标准（最小） |
|------|------------------|
| `search_sources` 次数 | 未无故增多；仍 ≤ 预算 |
| 引用 vs evidence | 关键细节可核对；假 cite 仍标记 |
| 人工 2～3 题 | 对 / 偏 / 错；B 不差于 A，至少 1 题更准或噪声更少 |
| 墙钟或 first_token | 同机对比：B 不明显变差（无额外模型轮次） |

样本量小但必须 **同题对照**；禁止只交 stub 绿就合并效果向 PR。

### 层 3 — 工作台交互清单（约 30 分钟）

1. **成稿**：能搜到并写出可核对材料细节。  
2. **`/polish`**：时间线 **无** `search_sources`。  
3. **目录隔离（RE3 后）**：限定子目录时不出现域外片段。

### 两闸关系

```text
契约闸（每票）：runtime-test + eval-all（含 writing.12/13）+ eval-retrieval
效果闸（效果向票）：层1 必过；层2+层3 至少完成并在 PR 贴结果摘要
```

**速率口径（诚实）**：本方案不增加默认模型轮次、不挡首 token；RE1 可能略增 **单次** `search_sources` 工具耗时 → 必须有大小/时间预算，超时降级字段。层 1 的 p95 与层 2 墙钟用于抓住这类回归。

---

## 9. 结论

| 维度 | 口径 |
|------|------|
| **写作还要不要做 RAG 优化？** | **要，但只做取证质量（线 A）**，不做「更多默认检索」 |
| **岗位向做什么？** | **文档 filter +（可选）ACL +（可选）结构化 records（线 B）**；filter 优先于字段整洁 |
| **速率** | 工具化、异步索引、改稿 0 RAG、无默认同步 LLM；RE1 有预算才允许 |
| **验证** | **契约闸**（golden/单测）+ **效果闸**（离线 A/B、同题 Turn、工作台清单） |
| **是否成熟** | 是：Agentic RAG + metadata filter + citation grounding，对应企业知识库与 Agent App 搜索 |

**最终口径**：下一阶段 = **可过滤的文档检索（B 先）** + **可证明的成稿取证（A）**；stub 绿只证明没写坏，**效果闸**才证明更好用；全部落在 R1–R5 内。

票级拆分与验收清单 → [`28-rag-evidence-execution.md`](28-rag-evidence-execution.md)。

### 落地索引（2026-07）

| 项 | 路径 |
|----|------|
| `path_prefix` 实现 | `services/runtime/app/retrieval/path_filter.py` + `tools/core/tools.py` |
| keyword section（RE1） | `services/runtime/app/retrieval/keyword_hit.py` |
| 离线题集 / corpus | `eval/retrieval/` |
| 层 1 runner | `scripts/retrieval_bench.py`（`make retrieval-bench`） |
| 层 2 自动化子集 | `scripts/turn_effect_bench.py`（`make turn-effect-bench`） |
| 层 2/3 清单 | `eval/retrieval/EFFECT_CHECKLIST.md` |
| Stub golden | `eval/golden/writing/14_path_prefix_section_hit.yaml` |
| 字段差异表 | `eval/retrieval/README.md` |
