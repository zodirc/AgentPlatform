# 结构杠杆提案（检索 + 上下文 · 外部审视）

> **落地状态（2026-08-06）**：代码已落地（P1①② / P2 开关 / P3 doc 表+降级 / P4 标定脚本 / C1–C3）；**验收冒烟、离线 L0、INDEX 重嵌未做**。P1 词面 A/B：`make micro-p1`。SciFact **中库微图**（gold+干扰 · 20q · `scifact-micro`，不影响多库主图）：`make micro-l1-prepare` + Ops 检索档位「SciFact 微 L1」。P5/P6 仍为备案不实施。
> **受众**：下一轮调优负责人 / 高级模型
> **日期戳记**：2026-08-06（基于 brief 收敛版 + 全代码栈审读；原提案均未实施，现除 P5/P6 外已有代码落地）
> **上游裁决文件**：同目录 `retrieval-free-l1-tuning-brief.md`（门禁 / 停机线 / 不做清单以其为准；本文不推翻任何已收裁决）
> **本文性质**：外部视角对当前栈的结构性缺口盘点。每条提案标注：代码事实 → 与已有归因的对应 → 门禁相容性 → 执行细节 → 验收位 → 回滚路径
> **总裁决预告**：显著优化空间**几乎全在检索结构层**；上下文抬分刀维持停手，仅还三笔"工程成熟"债（不承诺分数）

---

## 0. 结论速览

| 序 | 提案 | 类别 | 置信度 | 与门禁关系 | 预期效果位 |
|----|------|------|--------|-----------|-----------|
| **P1** | 真 BM25 替换 `ts_rank_cd('simple')` | 检索结构刀 | **高** | 结构刀，不计停机线 | lexical_miss 收窄 · FiQA absent 收窄 |
| **P2** | embed 输入去 path/tags 噪声 | 检索结构刀（L0 先行） | 高 | 纯离线 L0，零运行时风险 | L0 macro；重嵌后冒烟 |
| **P3** | two-level doc lane 做实（真文档向量） | 检索结构刀 | 中高 | 结构刀，加深已证有效层 | nDCG@10 · doc lane 命中质量 |
| **P4** | HNSW ef_search 标定 + absent@100 对照 | 观测/标定 | 中 | 观测先于改动（门禁 6） | absent@100 |
| **P5** | 非对称 embed 模型入 L0 候选（条件触发） | 检索选型（备选） | 中 | 仅当 RET-4 验收后 FiQA 仍不收窄 | FiQA nDCG / absent |
| **P6** | 切块禁令复议（条件触发 · 仅备案） | 被禁事项备案 | — | **现行不做清单禁止**；仅记录复议条件 | — |
| **C1** | fold ↔ read_registry 重读硬门矛盾修复 | 上下文工程债（bug） | **高** | bug 修复，非契约刀 | 单测 + 行为桶无恶化 |
| **C2** | 工具 schema 全程静态（prompt cache 卫生） | 上下文工程债（成本/速率） | **高** | 与 R1 同向 | `cached_tokens` / TTFB |
| **C3** | token 估计器闭环校准 + 双重截断审计 | 上下文工程债（观测先行） | 中 | 观测刀 | fill 误差带 · 截断发生率 |

**明确不投入**（与仓内证据一致，仅确认）：查询路径 LLM 改写/HyDE（R2 红线）；全库 doc2query 复活（RET-11(b) 已回滚）；热路径 CE（RET-19 +0.51pp 已关议题）；任何上下文契约/文案抬分刀（停机线 2/2 + CTX-13 暴露面=0）。

---

## 1. 立论基础：代码事实与归因的三处对不上

brief 的归因链已经闭环到三个残余桶：**lexical_miss**（RET-8 主桶）、**FiQA absent_from_ranked**（RET-6/14/17）、**wrong_answer 残余 = 定位 + 真错**（CTX-13 + EVAL-8 后）。但代码审读发现三个结构事实，恰好坐在这些归因的因果上游，且未被任何已有票覆盖：

1. **生产 BM25 车道不是 BM25**（→ P1）。`pgvector_store.py` 的 `_search_bm25_db` 实际是 `to_tsvector('simple') + plainto_tsquery + ts_rank_cd`：无词干化、无停用词、无 Okapi 的词频饱和与长度归一。JSON fallback 路径（`bm25.py`）却是真 Okapi（k1=1.5, b=0.75）——两条路径行为不一致，且生产走的是弱的那条。
2. **embedding 输入被合成噪声污染**（→ P2）。`chunking.py` 的 `build_embed_text` 把 `path: …` + `tags: …` 前缀拼进 embedding 输入开头。BEIR 物化语料的 path 是合成 ID，等于给每个向量在对句向量模型影响最大的位置注入无语义 token。
3. **唯一有证据的正贡献层运行在打折实现上**（→ P3）。RET-18 证明 two-level ON 值 +10.1pp，但 pgvector 侧的 doc lane 是"宽 ANN 取 distinct path"的近似；真 `doc_vector` 只存在于 JSON fallback 路径（`vector_index.py`）。

这三条的共同点：**都是 Index/车道结构问题，不是契约、不是行为、不是判分**——正好落在停机线不管辖、且 brief 高杠杆优先序（结构 Index/embed > 离线增强 > 消融）鼓励的区间。

---

## 2. 检索提案

### P1 · 真 BM25 车道（最高置信 · 建议首刀）

```text
加热层: hybrid 词面车道（Index plane + 查询路径毫秒级 CPU）
代码事实: pgvector_store._search_bm25_db 用 ts_rank_cd + 'simple' 配置；
          bm25.py 已有完整 Okapi BM25Scorer（k1=1.5, b=0.75）但仅 JSON 路径使用
归因对应: RET-8 lexical_miss 主桶；FiQA 问句词形变化（invest/investing/investment）
          在 'simple' 分词下全部 miss；BEIR 各 hybrid 基线假设的都是真 BM25——
          本仓这条车道的天花板被 Postgres FTS 压死，RRF 融合救不回弱车道
R1–R5: 通过——候选池百级、内存 Okapi 重打分毫秒级（R3）；无新模型调用（R2）；
        词干化在建索引侧（R4）
```

**执行细节（三档，由轻到重，逐档验收后再进下一档）**

| 档 | 改动 | 成本 | 说明 |
|----|------|------|------|
| ① | `to_tsvector('simple')` → `to_tsvector('english')`（含查询侧 `plainto_tsquery` 同步换） | 一次 FTS 重建（GIN 索引重刷，离线） | 先拿词干化 + 停用词；BEIR 为英文语料，`english` 配置无副作用。注意 `bm25_document.py` 的 `BM25_EXTRA_FTS_VERSION` 需 bump 以触发重建 |
| ② | FTS 只做**召回**（候选池 `top_k`），排序换成内存 `BM25Scorer` 对候选池重打分 | 查询侧 +毫秒级 CPU | 复用现有 `bm25.py`；候选池语料统计（df/avgdl）可离线预计算随索引落库；与 JSON 路径行为收敛为同一套 Okapi |
| ③ | 真 BM25 扩展（ParadeDB pg_search / VectorChord-bm25 类） | 引入扩展依赖 | 仅当 ①② 后 lexical 车道仍是短板才考虑；本轮**不建议**（依赖面大） |

**验收位**
- 主观测位：RET-8 口径下 lexical_miss 桶收窄（子桶证据，符合 EVAL-7 ②）
- 宏分：free 20q N≥2，锚 = two-level ON + gte-large `61f00a6d` ≈0.483；分库看 FiQA
- 硬指标：FiQA absent_from_ranked（RET-14/17 口径）前后对照
- **脚本基准（本机 CPU / 无 sync）**：`make micro-p1` 或 Ops 评测台预设「P1 词面微基准」→ `scripts/official_bench/p1_lexical_micro.py`；默认 SciFact 10q，A/B `fts_ts_rank` vs `fts_okapi_rescore`；报告 `eval/reports/official/p1_lexical_micro*.json`。**不进 SCORECARD、不触发重嵌**。

**回滚**：① 档 FTS 配置切回 + 重建；② 档开关位 `RETRIEVAL_BM25_RESCORE_ENABLED=false` 即回 `ts_rank_cd`。

**禁止**：不与 P2/P3 绑同一 commit（门禁"禁止多杠杆绑同一 commit"）；不顺手改 RRF 权重。

### P2 · embed 输入去 path/tags 噪声（零风险 · L0 先行）

```text
加热层: Index plane（embed 文本构造；离线重嵌兑现）
代码事实: build_embed_text = "path: …" + "tags: …" + body；对 BEIR 语料 path 为合成 ID
归因对应: 向量车道整体信噪比；对 absent_from_ranked 有直接机制解释
          （gold chunk 的向量被开头无语义 token 拉偏）
R1–R5: 通过——纯离线；查询路径零改动
```

**执行细节**

1. L0 选型架子复用 `ret4_selection` 流程：同模型（当前锁定档）× {现行 embed 文本, 纯 body, body+section_title} 三变体，SciFact/NFCorpus/FiQA 各跑 nDCG@10。**数字不进主栏**（RET-4 同款纪律）。
2. 若纯 body 或 body+title 变体稳定占优 → bump INDEX_VERSION（新号，勿复用 9/10）→ 离线重嵌 → free 20q N≥2。
3. 产品语料与 BEIR 语料可以**分策略**：`build_embed_text` 按语料来源（seed vs 评测物化）决定是否拼 path/tags——但注意这不得做成"评测专用质量分支"（门禁 2）；正确形态是**配置开关**（如 `EMBEDDING_TEXT_INCLUDE_METADATA`），产品与评测同值跑对照后统一裁决。

**验收位**：L0 三库对照（选型用）→ 重嵌后冒烟 N≥2 + FiQA absent 对照。

**回滚**：配置切回旧 INDEX_VERSION，零重建（RET-4 同款）。

**排期约束**：与 RET-4 gte-large 验收**不绑同一影子索引**；建议 RET-4 free 验收收口后作为下一次重嵌的搭车项评估（重嵌成本共摊）。

### P3 · two-level doc lane 做实（在已证有效层上加深）

```text
加热层: Index plane（doc 向量离线构建）+ 融合层（doc lane 数据源替换）
代码事实: RET-18 证明 two-level ON +10.1pp（0.483 vs 0.382）——排序栈唯一有硬证据的加成层；
          但 pgvector 侧 doc lane = 宽 ANN 取 distinct path 近似，非真文档向量；
          JSON 路径的 search_docs 有真 doc_vector
归因对应: doc lane 命中质量依赖 chunk ANN 覆盖——chunk 向量没召回的文档，
          doc lane 也永远看不见（与 absent_from_ranked 机制耦合）
R1–R5: 通过——doc 向量离线建（R4）；查询侧多一条 ANN 查询，已有 0.3s 超时预算兜底（R3）
```

**执行细节**

1. 建 `source_docs` 表（或 `source_chunks` 加 doc 级行）：每文档一条向量。文档表示法两个候选：(a) 头部 N 字符 + 标题；(b) 该文档全部 chunk 向量取质心。先离线 L0 对比两者。
2. `two_level.py` 的 `parallel_two_level` doc lane 从"宽 ANN dedup"切到真 doc 表 ANN；`merge_doc_and_chunk_hits` 的 `doc_boost=0.35` 保持不动（不顺手调参）。
3. doc 向量随重嵌管线走（`index_embed.py` 加 doc 批次）；INDEX stamp 加 doc 表在场校验，缺 doc 表时**降级回现行近似**（不是报错），保证部署兼容。

**验收位**：主看 nDCG@10 冒烟 N≥2（锚 0.483）；辅看 RET-10 lanes 口径下 doc lane 独立命中的 gold 数（现行近似下这个数≈chunk lane 子集，做实后应出现 chunk lane 未召回、doc lane 召回的增量）。

**回滚**：`RETRIEVAL_TWO_LEVEL_DOC_TABLE=false` 切回近似实现，零重建。

### P4 · HNSW 召回标定（观测先行 · 低成本）

```text
代码事实: HNSW 用 pgvector 默认参数（m / ef_construction / ef_search 均未显式设置）；
          带 work_id/visibility 过滤时依赖 hnsw.iterative_scan=relaxed_order
问题: ef_search 默认 40，过滤场景下有效候选可能不足——absent@100 的一部分
      可能不是"向量空间里不相邻"，而是"ANN 没扫到"
```

**执行细节**：纯观测先行——同一批 query 在 `ef_search ∈ {40, 100, 200}` 下跑 absent@100 与 nDCG@10 对照（离线，不动生产配置）；若 ef_search=100 下 absent 显著收窄 → 设 `SET hnsw.ef_search` 于查询会话（+若干毫秒，R3 内）→ 冒烟 N≥2。若无差异 → 排除该假设，归因更干净（两种结果都是收束）。

### P5 · 非对称 embed 模型入 L0 候选（条件触发 · 备案）

**触发条件**：RET-4 gte-large free 验收后，FiQA absent 仍不收窄。

**依据**：仓内已有证据——RET-4 L0 表中 bge-small FiQA 0.465 > gte-small 0.432（bge macro 输，FiQA 赢）。FiQA 是"自然语言问句 vs 论坛陈述文档"的分布错位，正是非对称 query/passage prompt 模型（e5 系 `query:`/`passage:` 前缀、bge 系 instruction 前缀、bge-m3）的设计目标。gte 系无非对称前缀。

**纪律**：走 RET-4 同款 L0 选型流程；查询侧前缀属于 embed 调用参数**不是 LLM 改写**（R2 不涉）；若引入前缀模型，注意查询与文档必须分别用各自前缀嵌入（`embedder.py` 需要 query/passage 双模式接口）。数字不进主栏。

### P6 · 切块禁令复议条件（**不执行** · 仅备案）

现行不做清单写死"不开 BEIR 切块刀"，本文**遵守**。仅记录复议条件，供未来另开票时引用：

- 事实：`retrieval_chunk_max_chars=4000`（约千 token 级）对 BEIR passage 级 qrels 偏大——gold passage 被稀释进大块，句向量相似度被块内无关内容摊平；这与 absent_from_ranked 的机制自洽。
- 复议触发：P1–P3 + RET-4 全部收口后，FiQA/NFCorpus absent 仍 ≥ 当前水平 → 归因链上只剩切块粒度未排除 → 届时"观测先于改动"的证据已齐，另开票复议不算破戒。
- 若复议：先纯离线 L0（同模型 × chunk 大小 {4000, 1200, 600 chars}），不动生产索引。

---

## 3. 上下文提案（工程债 · 不承诺分数 · 不进抬分叙事）

> 前提重申：CTX-13 暴露面=0 + EVAL-8 校准后，上下文**没有可信的抬分刀**，产品侧停手裁决维持。以下三条是**正确性 / 成本 / 可测性**欠账，属于 brief §1.1 的"目标（因）= 生产工程成熟"本体，验收全部不看 F1。

### C1 · fold ↔ read_registry 重读硬门矛盾（语义 bug）

```text
代码事实: context/engine.py 的 read_fold 把旧 read body 换成 stub，
          stub 与 collapse pointer 文案均鼓励"需要时重读"；
          但 engine/read_registry.py 对已完整读过的文件硬拒同 Turn 重读
          （read_after_complete / overlap 拒绝）
后果: 被 fold 掉的内容在该 Turn 内实际不可恢复——"可恢复压缩（丢内容不丢指针）"
      的指针是断的。§7.7 采纳表第一行的产品语义没有兑现
```

**执行细节**：`read_registry` 增加豁免——当目标 path 的最近完整读**已被 fold/collapse/snip 移出可见窗**时（ContextEngine 可在 assemble 时回写一个 `evicted_paths` 集合到 TurnState），放行重读，且该次重读不计重复警告。成熟 harness 的通行不变式是"重读永远合法，代价是 token"（Claude Code / Cursor 均如此）；本仓至少要做到"被压缩掉的允许重读"。

**验收位**：单测（fold 后重读放行、未 fold 重读仍拒）；free 冒烟 N≥1 确认行为桶无恶化（gave_up 不升）。**不记任何分数叙事**。

**风险**：放行过宽 → 读循环。缓解：豁免仅限 evicted 集合内 path，且每 path 每 Turn 豁免 1 次。

### C2 · 工具 schema 全程静态（prompt cache 卫生 · 与 R1 同向）

```text
代码事实: tools/bootstrap.py 的 stage_tool_scope 在 Turn 晚阶段裁掉
          search/delegate/memory 等工具——tools JSON 是 Anthropic/OpenAI/DeepSeek
          前缀缓存的一部分，schema 变更 = 后续每步冷缓存
外部对标: Claude Code / Cursor 工具 schema 全程静态，行为限制靠文案或运行时拒绝；
          DeepSeek 磁盘 KV cache 计价使前缀稳定性直接可折算为成本与 TTFB
```

**执行细节**：`stage_tool_scope` 从"改 schema"改为"运行时闸"——tools 列表全程不变；越权调用在工具执行层返回统一拒绝文案（如 `{"error": "tool disabled at this stage"}`）。可选：Anthropic 路径把 `cache_control` 断点从"最后一个 tool"上移，使 system+tools 前缀恒定命中。

**验收位**：同题集前后对照 usage 的 `cached_tokens` / `prompt_cache_hit_tokens` 与每步延迟（EVAL-3 token 台账现成）。**这是速率/成本验收，不是质量验收**。

**风险**：模型可能在晚阶段调用被闸工具浪费一步。对照时同时看 step 数分布；若步数显著上升则回滚（开关位保留两种模式）。

### C3 · token 估计器闭环校准 + 双重截断审计（观测先行）

```text
代码事实①: _estimate_text_tokens 用 CJK≈1 / ASCII≈1/3 粗估，驱动
           fill 0.80/0.90/0.95 三条阈值——估计偏差直接平移 collapse/snip 触发点
代码事实②: 双重截断链——工具层 read 32k → 组装层"全局最近一次 read 32k、其余 4k"；
           search_sources 先 RET-12 tier 再受 4k 硬截，长 JSON 仍可能尾截
```

**执行细节**

1. **观测**：assemble 时记 `estimated_tokens` vs provider usage 实际 `input_tokens` 的比值分布（INFRA 系落盘，一次跑批即可拿到误差带）；同时落盘 tool_result 被 4k 硬截的发生率与被截工具分布。
2. **校准**：按误差带修估计系数（或接真 tokenizer 离线标定常数）；阈值不动。
3. **条件动作**：若审计显示 search_sources JSON 尾截发生率非零 → 把 tool_result 序列化从 JSON 换紧凑文本行（`path:line score excerpt`，Claude Code/Cursor 惯例），同预算下证据密度约翻倍。**此步涉及呈现层，须单独卡片 + 行为桶验收（RET-12 同款"不写 IR 胜"纪律）**；审计为零则不动。

**验收位**：估计误差带收窄（观测指标）；截断发生率（观测指标）。不进宏分叙事。

---

## 4. 外部 harness 对标摘要（Cursor / Claude Code / OpenCode / DeepSeek）

| Harness | 与本仓已对齐 | 值得借鉴且未做 | 对应提案 |
|---------|-------------|---------------|----------|
| **Claude Code** | 不强制搜、agentic 循环、/compact | 工具输出精简文本非 JSON；被压缩内容无条件可重取 | C1 / C3-3 |
| **Cursor** | hybrid 双轨（语义+词面）、截断 hint | doc-level 真向量结构；索引新鲜度一等公民（不静默降级） | P3 |
| **OpenCode** | — | LSP/结构化导航补充文本检索（对 agent 场景，非本轮） | 产品票备案 |
| **DeepSeek** | provider 已接、吃 cache usage 字段 | 前缀稳定性可直接计价 → 缓存卫生有硬验收位 | C2 |

共同结论：四家的检索质量没有一家靠"更聪明的单次检索"，靠的是**干净的车道 + 便宜的迭代 + 稳定的前缀**。本仓行为面已近天花板（drift≤1），剩余空间就在车道质量（P1–P3）与前缀/预算卫生（C1–C3）。

---

## 5. 执行序建议（不构成排期裁决）

```text
即刻可并行（互不绑 commit）:
  P4 ef_search 离线标定（纯观测，半天级）
  P2 L0 三变体选型（纯离线，搭 ret4_selection 架子）
  C3-1 估计误差 + 截断发生率审计（一次跑批）

RET-4 free 验收收口后:
  P1① english 词干化 → 冒烟 N≥2 → 视结果进 P1②
  P2 若 L0 占优 → 搭下一次重嵌兑现
  P3 doc 向量表（可与 P2 共摊同一次重嵌，但分 commit 分验收）

工程债（与检索日历解耦，随时可做）:
  C1 fold 重读豁免（bug 修复 + 单测）
  C2 schema 静态化（cache 命中率验收）

条件触发（备案，不排期）:
  P5 非对称模型 L0（FiQA absent 不收窄才开）
  P6 切块复议（P1–P3+RET-4 全收口且 absent 仍高才另开票）
```

**纪律重申**：每条单刀单 commit；冒烟 N≥2 只去留不入库；P 系主看子桶（lexical_miss / absent）而非宏分；C 系一律不进分数叙事；任何一条若与 brief 现行裁决冲突，以 brief 为准、本文让位。
