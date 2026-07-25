# 33 — Harness 工程完善（上下文 · 审计 · Proof）

> **状态**：✅ 核心落地（2026-07-24）— HM1–HM9 已接线；HM5/RO1 Ops 检索审计可用；合并前请跑约定单测 / `make gate`。  
> **范围**：在 **不改交互逻辑、不伤速率** 的前提下，加厚 Context / Proof / 异步审计，使长会话、压缩、检索与交付行为达到「可契约、可回放、可回归」的成熟度。  
> **不在范围**：改写 `AgentEngine` while；恢复固定 pipeline；预循环 LLM 路由；每轮同步总结；热路径精确 tokenizer；默认 cross-encoder；K8s / MCP / Skills 提前开工（仍见 [19](19-skills-layer.md)）。

关联：[12](12-model-harness.md)（Harness 总纲 · §5.1）· [13](13-rate-redlines.md)（R1–R5）· [06](06-tools-and-context.md) · [20](20-context-compaction-walkthrough.md) · [08](08-event-projection-pipeline.md) · [11](11-eval-and-golden-turns.md) · [15](15-rag-and-sources.md) · [14](14-writing-quality.md) · [24](24-writing-token-economy.md)（WT5）· [28](28-proof-gate-and-ux-signals.md) · [30](30-quality-and-agility.md)。

问题来源备忘：仓库内 [`question.txt`](../question.txt) 收录了一组成熟 Agent 落地岗常深挖的工程问题（上下文阈值、增量摘要、原始持久化、按需记忆、工具 schema 成本、RAG 归因、幻觉分层等）。本文 **§2** 将其转写为「问题 → 本项目现状 → 对应优化票」；**§8** 另做「教材式 RAG / 记忆 / 第 10→11 轮摘要」对照，避免把对方答法误当成更优默认。不改变 §0 速率/交互红线。

---

## 0. 原则与准入

与 [30](30-quality-and-agility.md)、[12](12-model-harness.md) 一致，本模块所有票必须同时满足：

1. **不影响交互逻辑**  
   - 不改 `AgentEngine` while / 终止条件、事件名与主路径语义、审批门、Plan 相位。  
   - 策略只进：ContextEngine / Session 持久化旁路 / 投影与 Ops / golden / 可选 profile 开关 / 导出与用户触发核查。  
   - 工具**集合与调用语义**默认不变；允许缩短 description 文案与 cache 布局（见 HM6），不允许为「省 token」改成另一套工具选择交互。

2. **不影响交互速率**（服从 [13](13-rate-redlines.md) R1–R5）  
   - 不挡 `turn.accepted`；首 token 前不加同步模型调用。  
   - 重活：Turn 间隙、outbox、投影 worker、用户 slash / 导出路径。  
   - 可测才合并：单测或 golden；延迟相关须有断言或 SLO 对照。

**杠杆排序**：契约与 Proof → **检索三层可观测（Q19/HM5）** → 异步预压缩 → 描述/cache 降本 → 交付门禁。  
**不用编排补洞**：不加节点、不加每问 router、不加 Turn 末 LLM judge。

---

## 1. 现状与完善点（工程事实）

| 面 | 已有（强） | 完善点（本模块已落地） |
|----|------------|--------------------------|
| **Context 压缩** | budget → microcompact → collapse@0.80 → snip@0.90 → autocompact@0.95；热区保留；`context.reported` | **HM1** 软阈值异步缓存；硬路径默认确定性 / 缓存，不同步 LLM |
| **Session 连续** | `session_transcripts` + `/compact`；无 transcript 时回退 `context_summary` | **HM2** append-only raw 仓（非模型面） |
| **长期记忆** | `remember` / `recall` 工具按需、非每轮注入 | **HM9** Intake hint（可选触发） |
| **工具 Token** | ScenarioProfile / Plan / late-stage ToolScope；结果字符预算 | **HM6** description hygiene + WT5/AQ1/WN3 cache 分家 |
| **RAG** | tool-mediated；hybrid；`retrieval.completed` | **HM5** 三层 audit → Ops |
| **幻觉 / 交付** | Turn 内 evidence + `unverified`；用户 `/verify` | **HM7** 导出 warn/block |
| **可观测** | 事件流、usage、assemble_ms、golden、ops 评测台 | **HM4** 模型信封抽样；HM5 Ops 检索页 |

结论与 [12](12-model-harness.md) 一致：**Loop 形状已对；Harness 厚度与可证明性已由本文 HM 票加厚到核心落地**。

---

## 2. 成熟度追问对照（问题 → 现状 → 优化）

> 下列问题编号对齐 [`question.txt`](../question.txt) 中的工程深挖题（略去算法题/闲聊）。  
> **现状**只写本仓库事实；**优化**指向本文 HM 票（已落地则写机制；历史提案语气保留在票详述）。  
> 标记：**已覆盖** = 工程上已能答清且有实现；**部分** = 有能力但缺契约/异步/Proof；**缺口** = 需 HM 补齐；**有意不做** = 与 R1–R5 / ADR 冲突，用替代方案。

### 2.1 总表

| # | 问题（工程表述） | 现状 | 判定 | 优化（如何解决） |
|---|------------------|------|------|------------------|
| Q2 | 短期记忆如何实现？ | 模型窗 = 组装后的 messages；多层压缩链；**HM1** 软阈值异步预压缩 | **已覆盖** | 机制见 [20](20-context-compaction-walkthrough.md) |
| Q3 | 「快到上限」如何定义？对话如何叠加？ | `fill_ratio` + 可配置 `fill_collapse/snip/autocompact`；Turn 内 messages **追加**后每步重新组窗 | **已覆盖** | 保持 |
| Q4 | 轮次过多如何优化？分层上下文？ | 热区 + 折叠/摘要；**HM3** 增量 merge；**HM8** 分层默认关 | **已覆盖** | HM8 仅超长会话 profile |
| Q5 | 何时触发总结？软/硬阈值？步数？ | **HM1**：软阈值 Turn 间隙异步备缓存；硬阈值优先缓存 + 确定性摘要，默认同步 LLM 关 | **已覆盖** | 禁止改成每轮总结（§5） |
| Q6 | 是否每轮都总结？ | **否**；仅过阈值或用户 `/compact` | **已覆盖** | 守住 |
| Q7 | 已总结后下一轮：增量还是全量重算？ | **HM3**：`next = merge(prev, delta)`；全量仅 `/compact` / 熔断；单测钉边界 | **已覆盖** | 见 [20](20-context-compaction-walkthrough.md) |
| Q8 | 前若干轮变摘要后，原始上下文还要吗？ | **HM2**：`session_raw_snapshots` append-only；Ops `GET /ops/raw/turns/{id}`；永不进模型窗 | **已覆盖** | transcript 仍可 trim 进窗 |
| Q9 | 长期记忆何时检索？ | `remember`/`recall` 按需；**HM9** Intake 启发式 hint（不自动注入） | **已覆盖** | 禁止每轮向量注入（§5） |
| Q10 | 每轮是否注入长短期记忆？是否同时注入？ | 短期 = 组窗；长期 = 工具按需 | **已覆盖** | HM9 只加 hint |
| Q11 | 如何降低工具过多带来的 Token？ | Profile / Plan / late ToolScope；description hygiene；稳定前缀 cache | **已覆盖** | 面试口述见 [21](21-agent-system-qa.md) Q12 §5；**有意不做**预循环 LLM 选工具 |
| Q12–Q16 | RAG 链路与相似度 | tool-mediated hybrid + lexical rerank；索引 Turn 外 | **已覆盖（架构更贴 Agent）** | 效果向实验；可观测 **HM5** |
| Q17 | 多模型分工？ | 主模型 + 可选 compact + embed；无路由小模型 | **部分** | 保持规则 Scope；**有意不做**热路径 router |
| Q18 | 如何控制幻觉？ | evidence + `unverified` + `/verify`；**HM7** 导出 warn/block | **已覆盖** | **有意不做** Turn 末 LLM judge |
| Q19 | 如何观察模型召回了哪些块？ | **HM5**：三层 `audit` + Ops `/ops/.../retrieval`；**HM4** 模型信封抽样 | **已覆盖** | 前台侧栏保持轻量 |
| — | Cancel / 超时 / 工具结果预算 | ADR-015/016；字符预算；stall watchdog | **已覆盖** | 不在本模块重做 |
| — | Harness / 规范工程 | [12](12-model-harness.md) 六面；golden；ops 评测台 + 检索/信封 | **已覆盖（核心）** | 细项持续加厚 |

### 2.2 深挖题展开（必须能讲清实现）

#### Q5 — 总结触发条件

| | |
|--|--|
| **对方要听的** | 软阈值提前准备、硬阈值才强制；触发后原子替换；不能改到一半就发给模型 |
| **我们现在** | **HM1 已落地**：软阈值异步写缓存；硬阈值优先缓存 / 确定性增量摘要；同步 compact LLM 默认关（见 [20](20-context-compaction-walkthrough.md)） |
| **优化后** | （同上，已交付）组窗与发模之间无「临时改一半」——仍一次 `assemble` 产出 `ContextEnvelope` |

#### Q7 — 第 10 轮已总结，第 11 轮怎么办？（增量 vs 全量）

| | |
|--|--|
| **对方要听的** | 第 11 轮用 `S_1-10 + D_11`，**不**把 1…11 全量重摘要；再触阈值时对 `S ⊕ 新片段` 做下一版（增量；极长会话可分层）；原始轮次持久化但不进模型窗；全量重算 ≈ O(n²) |
| **我们现在** | **HM3**：`merge(prev, delta)`；全量仅 `/compact`；单测钉 delta 边界（[20](20-context-compaction-walkthrough.md)） |
| **写作场景对照** | 摘要该保住：大纲进度、已写章节约束、用户否决、交付约定。素材/史实/人设正文应走 `search_sources`（语料库），**不要**指望摘要里塞语料 |
| **优化后** | （已交付）**HM2** 保原件；**HM1** 让再触阈值的摘要离开首 token；**HM8** 仅超长会话可选分层 |

#### Q8 — 原始上下文是否还要

| | |
|--|--|
| **对方常见方案** | 意图路由小模型；工具渐进披露（先目录后 schema） |
| **我们立场** | 路由 LLM / 每轮注入 = 打 R2 与 cache；Skills 见 [19](19-skills-layer.md) 近期末 |
| **优化后** | Q10 保持工具按需 + **HM9** hint；Q11 用 **HM6**（缩描述 + cache）+ 已有 ToolScope，而不是热路径再问一轮模型 |

#### Q18 — 幻觉分层防御

| | |
|--|--|
| **对方要听的** | 输入（检索质量）/ 推理（温度·CoT）/ 上下文（拒答纪律）/ 输出（引用校验） |
| **我们现在** | system 纪律；evidence；`unverified`；`/verify`；**HM7** 导出 warn/block |
| **优化后** | （已交付）检索质量靠 **HM5** 可观测，不加 Turn 末 LLM judge |

#### Q19 — 如何观察召回了哪些块？（检索可观测 · 重点加厚）

**前台**仍只看轻量 `RetrievalView`（最终 hits）。  
**生产可观测**已由 **HM5** 交付：事件三层 `audit` + Ops `/ops/<secret>/retrieval` 只读查看真实用户 Turn。

| 层 | 要回答的问题 | 本项目现状（✅） |
|----|--------------|-----------------|
| **L1 召回** | 融合/rerank 前召回了哪些 `chunk_id`？ | `audit.recall_pool` |
| **L2 排序** | rerank 后 Top-K？ | `audit.ranked` + `rank_method` |
| **L3 进窗** | 进 tool_result 的原文是否截断？ | `audit.entered_context`（`truncated` / `char_len`） |

**已有能力**

- 事件：`retrieval.completed.payload.audit`（契约已扩）；**不**进模型 tool_result  
- Ops：`GET /api/v1/ops/retrieval/turns/{turn_id}` · 页 `/ops/<secret>/retrieval`  
- 前台：`RetrievalView` 保持轻量  
- **HM4**：模型信封抽样（`/ops/<secret>/envelopes`）补生成侧归因  

**不做**：查询路径建索引；默认打开 CE；同步写大块全文进 SSE；把召回池默认灌前台。

### 2.3 追溯矩阵（问题 → 票）

| 票 | 主要关闭的问题 |
|----|----------------|
| **HM1** | Q5（软/硬阈值与阻塞体验）；巩固 Q2/Q3 |
| **HM2** | Q8（原始持久化） |
| **HM3** | Q7（增量 vs 全量）；加固 Q4/Q6 |
| **HM4** | Q19 生成侧（模型是否用上检索结果）；辅助坏例回放 |
| **HM5** | **Q19 检索侧三层归因（召回 / 排序 / 进窗）** — 本模块可观测主票 |
| **HM6** | Q11（工具 Token / cache） |
| **HM7** | Q18（交付层幻觉/诚实性） |
| **HM8** | Q7 延伸（摘要再摘要 / 分层） |
| **HM9** | Q9（召回触发时机提示） |

无 HM 票、且保持现状即可对外说清的：**Q6、Q10 主路径、Q12–Q16、Cancel/超时**。  
**Q19** 已由 HM5（检索三层）+ HM4（模型信封）覆盖：Ops 可只读查看真实用户 Turn。

---

## 3. 票状态

| 票 | 主题 | 优先级 | 状态 | 主要对应 |
|----|------|--------|------|----------|
| **HM1** | 软阈值后台预压缩（硬阈值不挡首 token） | P0 | ✅ | Q5 |
| **HM2** | 不可变原始 transcript（审计仓 · 异步） | P0 | ✅ | Q8 |
| **HM3** | 增量摘要契约 + 单测边界 | P0 | ✅ | Q7 |
| **HM5** | 检索三层审计 → **Ops 观测台看前台用户 Turn** | **P0** | ✅ | **Q19** · [29](29-ops-eval-console.md) §6 |
| **HM4** | Model request envelope 抽样落盘 | P1 | ✅ | Q19 生成侧 |
| **HM6** | 工具描述 hygiene + cache 稳定前缀（WT5 / AQ1 / WN3） | P1 | ✅ | Q11 · [30](30-quality-and-agility.md) |
| **HM7** | 写作交付确定性门禁（导出 / verify） | P1 | ✅ | Q18 |
| **HM8** | 分层摘要树（默认关 · 超长会话 profile） | P2 | ✅（默认 off · 薄实现） | Q7 延伸 |
| **HM9** | 长期记忆轻量召回提示（不自动注入） | P2 | ✅ | Q9 |

核验命令（合并前至少）：

```bash
# 本模块相关单测（环境有 pytest / docker 时）
pytest services/runtime/tests/test_hm_context_maturity.py \
       services/runtime/tests/test_hm_export_envelope_recall.py \
       services/runtime/tests/test_retrieval_audit.py \
       services/runtime/tests/test_session_raw.py \
       services/api/tests/test_ops_retrieval.py \
       services/api/tests/test_ops_envelope_raw.py -q
make gate   # 或仓库约定的全量 gate
```

---

## 4. 票详述

### HM1 — 软阈值后台预压缩

**落地摘要（2026-07-24）**  
- Settings：`context_fill_soft_precompact` · `precompact_cache_ttl_seconds` · `context_hard_autocompact_allow_llm=false`（默认）。  
- `precompact_cache.py`：Turn 尾异步写 `sessions.context_summary`；硬路径 `assemble_async` 优先 `autocompact_cached`，否则 `autocompact_deterministic`。  
- 单测：`test_hm_context_maturity.py`。文档：[20](20-context-compaction-walkthrough.md)。

**关闭问题**  
Q5（及 Q2 的速率侧）。

**问题**  
组装链在 `fill ≥ fill_autocompact`（默认 0.95）时可能走同步 LLM 摘要，落在「下一步模型调用」之前，直接冲击首 token / Cancel 体感（与 R2 精神冲突）。

**目标**  
- **软阈值**（建议与 collapse/snip 对齐，可配置，如 0.70–0.85）：在 **Turn 间隙**或上一步工具完成后，异步生成/刷新摘要缓存。  
- **硬阈值**：优先消费已缓存摘要 + 确定性 collapse/snip；仅在缓存未就绪时退回现有确定性摘要路径，**默认不再为组窗同步调用 compact LLM**。  
- 模型仍只看到组装后的窗；事件继续报 `compaction_trace` / `context.reported`。

**不做**  
预循环「先总结再思考」；改变 tool 调用顺序。

**验收**  
- 单测：软阈值触发后缓存命中，硬阈值路径无同步 gateway compact。  
- 延迟：相关 golden 或 `assemble_ms` / 首 token 对照不回退。  
- 文档：回写 [20](20-context-compaction-walkthrough.md) 顺序说明。

**触点（预期）**  
`context/engine.py` · `context/compact_summarizer.py` · `settings` 阈值 · 可选 Turn finalize 钩子（异步 task，失败可丢弃重试）。

---

### HM2 — 不可变原始 transcript（审计仓）

**落地摘要（2026-07-24）**  
- DDL `session_raw_snapshots` + Alembic `0014`；`session_raw.append_raw_snapshot` 在 assemble 前 `create_task`。  
- Ops：`GET /api/v1/ops/raw/turns/{turn_id}`。模型路径永不读该表。

**关闭问题**  
Q8。

**问题**  
`session_transcripts` 在持久化前会做确定性压缩（见 `session_transcript.prepare_messages_for_persist`），且后续会再进入模型窗。`turn_events` 是类型化事件流，**不能无损重建**「每步完整 messages」。审计、摘要重建、纠纷回放缺少权威原件。

**目标**  
- 新增 **append-only** 原始消息仓（独立表或 event 旁路 blob），在每步 assemble **之前**快照当前 messages（及可选 tools 指纹）。  
- 写入走 **outbox / 异步**；失败不阻塞流式与工具执行。  
- **永不**把该仓内容直接当作模型窗（模型路径仍只走 ContextEngine）。

**用途**  
审计溯源 · 摘要质量差时按原件重建 · 与 HM3 / HM4 联调。

**验收**  
- 契约/DDL + 迁移；写入失败可观测但不影响 Turn 终态。  
- 单测：压缩后 transcript ≠ raw；raw 可按 turn_id/step 读回。  
- R1/R4：热路径无同步大块 JSONB 等待。

**触点（预期）**  
`packages/contracts` DDL · runtime outbox worker · `turn_controller` / `agent_engine` 旁路钩子 · ops 只读 API（可后置）。

---

### HM3 — 增量摘要契约 + golden

**落地摘要（2026-07-24）**  
- `incremental_summary_from_messages` / `messages_since_last_summary` / `merge_structured_summary`。  
- 组窗与 soft precompact 共用；`/compact` 仍可全量。  
- 单测钉 delta 边界：`test_hm_context_maturity.py`。

**关闭问题**  
Q7（加固 Q4 / Q6）。

**问题**  
运行时已有 structured / LLM 摘要与 `/compact` 全量重算，但缺少明确产品契约：**续轮默认增量合并，禁止无条件全量重算**。压缩质量与「变短≈压缩」体感（[12](12-model-harness.md) §5.1.2）缺少可回归钉子。

**目标**  
定义 `SummaryRevision`（名称可调整）语义：

```text
next_summary = merge(prev_summary, new_turns_or_window_delta)
```

- **默认路径**：有 `prev_summary` 时只合并增量；复杂度近似随新片段增长，而非整段历史反复 O(n²) 全量摘要。  
- **全量重算**：仅用户 `/compact`、显式运维重建、或质量熔断（摘要损坏 / schema 失败）允许。  
- Proof：至少一条 golden 覆盖「多轮后再次组窗只增量合并、不重放全部原始轮次进 summarizer」。

**验收**  
- 契约字段或内部结构文档化（可进 [06](06-tools-and-context.md) / [20](20-context-compaction-walkthrough.md)）。  
- `eval/golden/...` + 单测断言 merge 输入边界。  
- 与 HM1 缓存摘要格式对齐，避免两套摘要方言。

**触点（预期）**  
`context/summary.py` · `compact_summarizer.py` · `session_compact.py` · golden。

---

### HM4 — Model request envelope 抽样落盘

**落地摘要（2026-07-24）**  
- DDL `model_request_envelopes` + Alembic `0015`；`maybe_persist_model_envelope`（哈希必写 · 全量采样/高 fill/debug）。  
- Ops API + 页：`/ops/<secret>/envelopes` · `GET /api/v1/ops/envelopes/turns/{turn_id}`。

**关闭问题**  
Q19（生成侧归因）。

**问题**  
线上坏例难回答：「那一步模型到底看见了什么？」事件流有分项，但缺少可选的完整请求信封。

**目标**  
- `assemble` 完成后异步落盘：messages + tools 的 **内容哈希** 必写；**全量信封**按采样率或仅失败 / 高 fill / 显式 debug 开关。  
- 不进 SSE 热路径；不进默认投影体积。  
- Ops / 评测台只读回放（可与 [29](29-ops-eval-console.md) 后续对接）。

**验收**  
- 默认采样配置安全（磁盘/隐私）；secret 扫描沿用现有写出前扫描纪律。  
- R4：异步；单测覆盖哈希稳定性。

---

### HM5 — 检索三层审计（召回 / 排序 / 进窗）→ **Ops 观测台**

**落地摘要（2026-07-24）**  
- Runtime：`retrieval/audit.py` + hybrid 分阶捕获；`search_sources` 挂 `audit`；`retrieval.completed` 带三层；**不**进模型 tool_result。  
- Contracts：`retrieval.completed.json` 增 `audit`。  
- API：`GET /api/v1/ops/retrieval/recent` · `…/turns/{turn_id}`（`ops_retrieval.py`）。  
- Web：`/ops/<secret>/retrieval`（先浏览最近 Turn，再点详情；`RetrievalAuditPage`）。  
- 测试：`test_retrieval_audit.py` · `test_ops_retrieval.py` · `test_two_level_recall.py`（ContextVar 传播）。  
- **坑（已修）**：`parallel_two_level` 在线程池跑 chunk 车道时，若未 `copy_context().run`，审计 ContextVar 写不上 → finalize 用最终 hits 合成三层（`rank_method=hybrid` 假象）。提交任务须显式传播上下文。

**关闭问题**  
**Q19**（如何观察召回了哪些块）— 本模块检索可观测主票。

**产品落点（先钉死）**  
主交付面是 **Ops 内部观测台**（[29](29-ops-eval-console.md) §6），**不是**前台 Web Agent / Writing 侧栏：

| 角色 | 看到什么 |
|------|----------|
| **前台用户**（工作台） | 保持轻量 `RetrievalView`（最终 hits）；**不**把召回池/rerank 默认塞给终端用户 |
| **后端 Ops**（`/ops/<OPS_TEST_SECRET>/…`） | 只读查看**真实前台用户**某次 Session/Turn 的三层检索审计；可导出 JSON |

鉴权沿用 Ops 密钥；数据来自用户 Turn 事件/审计落盘；**只读**；与 golden 私有 scratch、用户 `/workspace` **隔离**。

**判断**  
今日「能看见召回」**主要是前台 UI**（最终 hits 预览）≠ 生产可观测：

| 层 | 今日 | 目标 |
|----|------|------|
| **事件 / 契约（真源）** | 最终 Top hits + 短 excerpt | 三层 `RetrievalAudit` |
| **Ops 观测台（主 UI）** | 仅有 ci-proof / golden | **按用户 Turn 查看/导出检索审计**（本票主交付） |
| **前台 UI** | 侧栏最终 hits | **保持轻量**；非本票必过 |

完成定义：**契约 + 落盘 + Ops 只读查看/导出 + 单测**。

**问题**  
Ops / 研发无法对「某个真实用户 Turn」稳定回答召回率 / 排序坑 / 进窗截断三问。

**目标**  
```text
owner_user_id / work_id / session_id / turn_id / step_index / tool_call_id
query
→ recall_pool[]     # L1
→ ranked[]          # L2
→ entered_context[] # L3（truncated, char_len）
```

落地要点：

1. **写入（真源）**：检索工具路径组装审计；contracts 扩展。  
2. **异步落盘**：不阻塞 tool_result → 模型（R1/R4）。  
3. **Ops API + 页（主交付）**：见 [29](29-ops-eval-console.md) §6；与评测套件并列。  
4. **前台**：默认不改交互。  
5. **Proof**：三层 id 关联单测；Ops 鉴权单测。

**与 HM4**  
检索管线 vs 模型信封；均可挂 Ops 内部页，不进前台。

**不做**  
召回池灌前台 SSE；只改前台 `RetrievalView`；Ops 写用户 workspace；无密钥公开 debug。

**验收**  
- **必过**：契约 + 可查落盘 + **Ops 只读打开真实用户 Turn 审计** + 单测。  
- **非必过**：前台侧栏审计折叠。  
- 回写 [15](15-rag-and-sources.md) §3.3、[29](29-ops-eval-console.md) §6。

**触点（预期）**  
`retrieval/*` · `search_*` · `agent_engine` · contracts · `services/api/.../ops/` · Ops Web · [15](15-rag-and-sources.md) · [29](29-ops-eval-console.md)。

---

### HM6 — 工具描述 hygiene + cache 稳定前缀

**落地摘要**  
与 [30](30-quality-and-agility.md) **CQ2 / AQ1 / WN3** 同路径落地：工具 description hygiene + writing/agent 稳定前缀与易变段分家（WT5）。前缀稳定性单测已在 `test_agent_prefix_stability.py` / `test_writing_prefix_stability.py`。

**关闭问题**  
Q11。

**问题**  
工具过多时 schema/描述占用窗口；写作/agent 的 prompt cache 易因「稳定前缀与易变 messages 未分家」整段 miss（[12](12-model-harness.md) §5.1.1 · [24](24-writing-token-economy.md) WT5）。

**目标**  
- 持续砍冗余、过时、重复约束；**不改变工具名与参数契约**（破坏性改 schema 须走合约流程）。  
- 落实 WT5：稳定段（system / 工具表 / 少变场景块）与易变段（transcript / tool_result）布局分家，提高 cache hit。  
- 继续依赖已有 Profile / Plan / late ToolScope；**不**引入预循环 LLM 选工具。

**验收**  
- 前缀稳定性单测（参见 [30](30-quality-and-agility.md) AQ1 / WN3 已有模式）。  
- 窗口分项 `tools_tokens` 不无故回升；相关 golden 全绿。

**与 Skills**  
渐进式披露整表工具仍按 [19](19-skills-layer.md) **默认不开工**；HM6 不提前打开 Skills。

---

### HM7 — 写作交付确定性门禁

**落地摘要（2026-07-24）**  
- `writing_export_verify_mode`：`off|warn|block`（默认 `warn`）。  
- `export_document` 在结构 lint 后跑 `scan_text_citations`；block 不写文件。  
- 单测：`test_hm_export_envelope_recall.py`。

**关闭问题**  
Q18（交付边界）。

**问题**  
Turn completed 不等于导出物正确；`unverified` 目前以标注为主。合规向产品更关心交付诚实性。

**目标**  
- 在 **导出 / 用户确认交付** 路径：跑既有确定性 `/verify`（或等价扫描）；失败则标记交付风险或按配置阻断导出。  
- **不**在每轮流式末尾加 LLM judge（R2/R4）。  
- Turn 内 evidence / `unverified` 行为保持，供模型与 UI 提示。

**验收**  
- 开关默认保守（可先「仅标记」再「阻断」）。  
- 单测 + 写作相关 golden；不增加首 token 路径工作。

---

### HM8 — 分层摘要树（P2 · 默认关）

**落地摘要（2026-07-24）**  
- `StructuredSummary.layers` + `context_layered_summary_enabled`（默认 false）。  
- 启用时对过长 narrative 折叠进 L1 layer；默认路径零成本。

**关闭问题**  
Q7 延伸（摘要再摘要）。

**问题**  
单层 `StructuredSummary` 在极长会话上再次压缩会损失结构；需要可选的 L1→L2 分层，而不是默认复杂化。

**目标**  
- Profile 开关；默认 off。  
- 仅超长会话启用；合并仍在 Turn 间隙 / 软阈值路径（与 HM1/HM3 共用）。  
- 证明：专用 golden；默认路径零成本。

---

### HM9 — 长期记忆轻量召回提示（P2）

**落地摘要（2026-07-24）**  
- Intake regex → `metadata.recall_hint`；Turn 组 volatile 追加一行 `[memory_hint]`。  
- **不**自动 `recall`、**不**注入向量正文。单测覆盖触发/不触发。

**关闭问题**  
Q9。

**问题**  
`recall` 完全依赖模型选工具；部分用户表述（「上次」「记得」「之前说的」）可提高触发率。

**目标**  
- Intake / system 旁路：**毫秒级**启发式，追加一行 hint，**不**自动执行 `recall`，**不**注入向量命中正文。  
- 遵守「长期记忆按需」（[06](06-tools-and-context.md)）。

**验收**  
- 无额外模型调用；单测覆盖触发/不触发样例。

---

## 5. 明确否决（本模块不采纳）

| 做法 | 常被当作「标准答法」的问题 | 原因 |
|------|---------------------------|------|
| 预循环 LLM 意图路由选工具 / 选是否检索 | Q9 / Q11 | R2；热路径多一整轮模型；与 ADR-014 / [13](13-rate-redlines.md) 否决一致 |
| 每轮自动注入长期记忆或 RAG 向量 | Q10 | 涨 token、打 cache、干扰注意力；RAG 保持 tool-mediated |
| 每轮同步总结 | Q6 | 成本、延迟、摘要再摘要衰减 |
| Turn 末 LLM 幻觉法官 | Q18 | R2/R4；用 evidence + `/verify` + HM7 |
| 热路径精确 tokenizer | （窗口计量） | R3；继续启发式估 token |
| 改 while / 恢复 pipeline / 查询路径建索引 | （编排惯性） | 交互与速率红线；索引纪律见 [15](15-rag-and-sources.md) A9 |

---

## 6. 建议落地顺序

| 迭代 | 票 | 交付意图 | 优先关闭 |
|------|-----|----------|----------|
| **A — 可证明** | HM3 → HM2 → **HM5** → HM4（抽样可后置） | 增量契约、原件仓、**检索三层审计**、坏例可回放 | Q7 · Q8 · **Q19** |
| **B — 又厚又快** | HM1 → HM6 | 软阈值预压缩；cache/描述降本 | Q5 · Q11 |
| **C — 交付诚实** | HM7 | 导出门禁（检索可观测已由 HM5 支撑） | Q18 |
| **D — 可选** | HM8 · HM9 | 默认关或极低成本旁路 | Q7 延伸 · Q9 |

与 [12](12-model-harness.md) §5.1 的关系：  
- §5.1.1 WT5 ↔ **HM6**  
- §5.1.2 变短≈压缩 / 压缩质量 ↔ **HM1 + HM3**  
- §5.1.3 Proof 延迟盯梢 ↔ 既有 [28](28-proof-gate-and-ux-signals.md) + 本模块 golden；HM1 验收须带延迟对照  

不可逆契约（摘要 revision 字段、raw 表、envelope 采样语义）落地时抽 ADR 或扩写既有 ADR；不要平行再开 `*-execution` 文。

---

## 7. 完成定义（模块级）

本模块标「✅ 核心落地」（2026-07-24）满足：

1. **HM1–HM3 与 HM5** 已合并接线；约定单测路径见 §3（合并前跑 `make gate` / 子集）。  
2. [20](20-context-compaction-walkthrough.md) / [06](06-tools-and-context.md) 已反映增量摘要与预压缩顺序；  
3. 硬阈值默认路径 **不再**依赖同步 compact LLM 才能组窗（`context_hard_autocompact_allow_llm=false`）；  
4. 存在可查询的 raw 审计轨（HM2 · Ops `/ops/raw`），与模型窗分离；  
5. **Q19**：三层检索审计可经 Ops 查看/导出；HM4 信封抽样可查；  
6. 本文 §2 中 Q5 / Q7 / Q8 / **Q19** 已回写为「已覆盖」，并更新 [docs/README](README.md)。

HM4 / HM6 / HM7 / HM8 / HM9 已并行落地；后续只做细项加厚（golden 剧本、分层树产品化），不阻塞本模块状态。

---

## 8. 对照分析：教材式答法 vs 本仓（RAG · 写作记忆 · 第 10→11 轮）

> 目的：避免「对方链路更完整 → 我们应该照搬」的误判。结论：**Agent 交互与速率上本仓多数更成熟；对方在「默认 CE / 中文大 embedding / 口述三层审计」上有可借鉴点，应用实验轨吸收，不改交互默认。**

### 8.1 RAG 技术栈对照（Q12）

对方典型答法（`question.txt`）：

```text
语义切块(Recursive 512/64) → BGE-large-zh → Milvus IVF_FLAT
→ Top-20 余弦 → BGE-reranker → Top-5 原文拼进 LLM 上下文
```

本仓（[15](15-rag-and-sources.md)，生产裁判栈）：

```text
标题树/叶预算切块(+overlap) → embed(ST，默认 compose 可配；dev 常 hash)
→ BM25 ⊕ pgvector（RRF hybrid）→ lexical rerank（默认开）
→ （可选 CE，默认关，≤50ms）→ search_sources 工具按需回传
索引在 Turn 外（watch/startup/worker）；查询路径禁止 sync（A9）
```

| 维度 | 对方 | 本仓 | 谁更贴「成熟 Agent」 |
|------|------|------|----------------------|
| **何时进上下文** | 常隐含「检索结果拼进生成上下文」 | **tool-mediated**，模型决定搜不搜；polish/outline 可 0 搜 | **本仓**：省 token、保 cache、符合自主 Agent |
| **召回形态** | 偏纯向量 | **Hybrid** BM25+向量 | **本仓**：专名/标题/中文关键词更稳 |
| **切块** | 固定 char splitter | 标题树 + 叶预算 + path embed clue（RQ1） | **本仓**：更贴写作树状语料 |
| **Rerank** | 默认 CE（BGE-reranker） | 默认 **lexical**；CE 实验可选 | **对方**在难语义题上可能更高；**本仓**保 R3 延迟。应用 **prod-bench 实验**，不改默认 |
| **Embedding** | BGE-large-zh（中文强） | 默认 MiniLM / hash；可换 ST | **对方默认更贴中文写作**；本仓应在 compose/真相档坚持中文强模型，而非改架构 |
| **向量库** | Milvus | **pgvector**（与主库一体） | 运维上本仓更简单；规模到十万+ chunk 再评估专用引擎（[15] RQ1e） |
| **效果闸** | 口述链路 | `retrieval-bench-prod` / qrels / IX4 | **本仓**更可证明 |
| **可观测** | 强调审计日志（Q19） | **HM5** 三层 `audit` + Ops 检索页；**HM4** 信封抽样 | **已对齐**：Ops 只读看真实用户 Turn |

**总判**：对方描述的是「经典 RAG 流水线教材版」；本仓是「Agent 内的按需检索平面」。  
**不是对方整体更好**，而是：

- 架构默认：**本仓更优**（工具化、hybrid、Turn 外索引、速率红线）。  
- 组件选择：中文 embedding / 离线 CE A/B **可向对方看齐（实验轨）**。  
- 工程缺口：~~三层审计（HM5）~~ **已落地**；prod 默认模型勿停在 hash。

### 8.2 写作模式：长期记忆 ≠ 语料库（易混点）

对方把「长期记忆 = 向量库按需召回」；写作产品里用户体感上「资料库」确实像长期记忆，但本仓应**分槽**，不要合并成一个概念：

| 槽 | 本仓机制 | 存什么 | 进模型方式 |
|----|----------|--------|------------|
| **A. 语料 / 事实库** | `sources/**` + seed + `search_sources` | 人设、年代、剧情、既定事实 md | **按需工具**；可引用 / evidence |
| **B. 文风与规范** | writing cards pin | 文风、硬约束卡片 | **稳定前缀**（非每轮向量搜） |
| **C. 会话进度** | transcript / compact 摘要 / `context_summary` | 写到哪、用户否决、约定 | **短期窗 + 摘要**（HM1/HM3） |
| **D. Agent 便签** | `remember` / `recall` | 跨任务碎记忆 | **按需工具**，非语料正文 |

**结论**：写作下「看起来像长期记忆」的主力是 **A（语料库）**，不是 D。  
优化方向：

- 强化 A 的可观测与效果（**HM5** + 中文 embed / prod-bench），而不是把语料塞进 `remember`。  
- 摘要（C）只保留进度与约束；**禁止**用摘要替代语料检索（否则第 10→11 轮摘要会膨胀且不可引用）。  
- D 保持小而按需（**HM9** 最多加 hint）。

### 8.3 总结 / 摘要与第 10→11 轮（Q7）

对方正确点（本仓应对齐契约）：

1. **第 11 轮** = `已有摘要 S + 新轮 D`，不是重放 1…11 全量进 summarizer。  
2. **再触阈值** = 对 `S ⊕ 新片段` 出 `S'`（增量）；极长会话可分层（HM8）。  
3. **原始对话仍落盘**，但不进模型窗（HM2）。  
4. **绝非每轮总结**（本仓已遵守）。

本仓已接近「多层防线压缩」，但面试官会卡的三刀——增量还是全量、原件还在吗、软阈值是否挡用户——对应 **HM3 / HM2 / HM1**，写作长会话同样适用。

写作特化建议（实现时写入 summary schema / 提示，不改 loop）：

```text
摘要字段优先：goal / outline_progress / chapter_constraints / user_rejects / open_questions
摘要字段避免：大段素材原文、可 search_sources 找回的事实块
```

### 8.4 可吸收 vs 不吸收

| 吸收（不伤交互/速率） | 不吸收 |
|----------------------|--------|
| HM5 三层检索审计（学对方 Q19） | 每轮把 Top-5 原文预注入 user |
| prod 默认中文强 embedding（配置/镜像） | 热路径默认 CE |
| HM3 第 N+1 轮增量契约 + golden | 每轮同步总结 |
| HM1 软阈值异步备摘要 | 用 LLM 路由「要不要搜语料」 |
| 摘要字段与语料检索分家（§8.2/8.3） | 把 `sources` 与 `remember` 合成一个记忆系统 |

权威细节仍以 [15](15-rag-and-sources.md)、[20](20-context-compaction-walkthrough.md)、[14](14-writing-quality.md) 为准；本节只定对照结论与票映射。
