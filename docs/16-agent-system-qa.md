# 16 — Agent 系统问答：现状对照、改进方案与速率影响评估

> **定位**：对照本仓库真实实现，回答 21 个 Agent 系统设计问题（Q0–Q20）。每个改进方案都经过**交互速率审视**：会明显拖慢 Agent 的方案已被改写为速率安全版，或明确否决。  
> **读法**：先看 [总览](#总览) 和 [速率红线](#速率红线所有改进方案的前置约束)；单题按 **结论 → 现状 → 缺口 → 方案** 扫读；只想抄结论看 [附录 C](#附录-c--一句话答案卡)。  
> **口径**：2026-07。  
> **执行排期（由本文附录 A 导出）**：[17-execution-plan.md](17-execution-plan.md) — S0～S3 冲刺、票粒度与否决项。  
> **落地后的现状重答**：[19-agent-system-qa-current.md](19-agent-system-qa-current.md) — 同一套 Q0–Q20，按 2026-07 已实现能力重写。  
> **关联专文**：[05 运行时](05-agent-runtime.md) · [06 工具与上下文](06-tools-and-context.md) · [11 体验 SLO](11-product-experience.md) · [12 评估](12-eval-and-golden-turns.md) · [14 Harness](14-model-harness.md) · [15 全景](15-highlights-vs-legacy.md)

---

## 图例

**问题状态**

| 标记 | 含义 |
|------|------|
| ✅ 已解决 | 主路径有明确机制，且可观测、可回归 |
| 🔸 部分解决 | 有缓解手段，缺口仍可感知 |
| ❌ 未解决 | 设计未覆盖，或规模不够 |

**方案速率影响**（相对人机交互体感）

| 标记 | 含义 | 处置 |
|------|------|------|
| 🟢 可忽略 | 不挡受理与首 token；纯离线，或热路径增量在毫秒级 | 可直接采纳 |
| 🟡 可控 | 热路径有成本，但可预算、可缓存、可降级 | 采纳，但必须挂延迟 golden 门禁 |
| 🔴 高风险 | 会加整轮模型调用、同步重计算、或阻塞受理 | **本文一律改写为安全版或否决**，不作推荐 |

**交互 SLO 基准**（权威定义见 [11 §1](11-product-experience.md)）：

| 指标 | 目标（P95） |
|------|-------------|
| TTFB（`turn.accepted`） | ≤ 300ms |
| 首模型 token | ≤ 800ms |
| 流式 Cancel | ≤ 500ms |
| 长会话 | 50 Turn 后无线性恶化 |

---

## 总览

| # | 问题 | 状态 | 推荐方案速率 |
|---|------|------|--------------|
| [0](#q0-agent-的落地场景是什么是否真的有用) | 落地场景 / 是否真有用 | ✅ | —（定位问题） |
| [1](#q1-agent-是否经常幻觉或乱调工具如何缓解) | 幻觉 / 乱调工具 | 🔸 | 🟢 |
| [2](#q2-如何设计评价-agent-系统好坏的指标体系) | 评价指标体系 | ✅ | 🟢（离线） |
| [3](#q3-主-agent-任务规划怎么保证拆解合理用什么-prompt-策略) | 任务规划 | 🔸 | 🟢 |
| [4](#q4-子-agent-之间的上下文怎么传递) | 子 Agent 上下文传递 | ✅ | 🟢 |
| [5](#q5-是否使用-reactreact-是什么优缺点) | ReAct 范式 | ✅ | — |
| [6](#q6-大模型捏造工具参数怎么处理) | 捏造工具参数 | 🔸 | 🟢 |
| [7](#q7-多-agent-协作常见模式有哪些) | 多 Agent 协作模式 | 🔸 | 🟢（重活转离线） |
| [8](#q8-一万个长文档构建-rag-知识库怎么解决) | 万级长文档 RAG | ❌ | 索引🟢 / 查询🟡 |
| [9](#q9-当前项目的-context--prompt--harness-engineering) | 三层工程 | ✅ | — |
| [10](#q10-tool-与-memory-怎么设计长短时记忆) | Tool 与记忆 | 🔸 | 🟢～🟡 |
| [11](#q11-隐私消息怎么防止泄漏) | 隐私防泄漏 | 🔸 | 🟢 |
| [12](#q12-保证效果的前提下怎么加速推理) | 加速推理 | 🔸 | 改善向 |
| [13](#q13-rag-为什么混合召回chunk-怎么切太大太小的问题) | 混合召回 / chunk | ✅ | 现路径🟡 |
| [14](#q14-harness-讲解) | Harness | ✅ | — |
| [15](#q15-多数据表多内容下怎么设计稳定召回链路) | 多表稳定召回 | ❌ | 🟡（含降级） |
| [16](#q16-动态-prompt-与静态-prompt) | 动/静 prompt | ✅ | — |
| [17](#q17-模型如何决定长期记忆是否需要召回) | 记忆召回决策 | 🔸 | 🟢 |
| [18](#q18-为什么要静态长期记忆和动态长期记忆) | 静/动态长记 | 🔸 | 🟢 |
| [19](#q19-整个链路的运转) | 端到端链路 | ✅ | — |
| [20](#q20-function-calling-在当前项目怎么运作) | Function calling | ✅ | — |

---

## 速率红线：所有改进方案的前置约束

本项目的第一体验目标是**跟手**（[11 §0](11-product-experience.md)、[14 §4](14-model-harness.md)）。任何改进方案先归位到热路径的哪一段，再按红线裁决：

```text
受理段（TTFB）      → 必须极轻：先发 turn.accepted，再做别的
首 token 前         → 最敏感：assemble + 首次 model 调用，不许塞新工作
逐步执行段          → 可并行、可截断、可缓存
Turn 结束后 / 离线  → 投影、索引、评分、审计的正确归宿
```

**红线 R1–R5**（本文所有方案按此改写；违反即否决）：

| # | 红线 |
|---|------|
| R1 | 不得推迟 `turn.accepted`：任何校验、检索、脱敏不挡受理反馈 |
| R2 | 首 token 前**不新增模型调用**：路由、反思、打分不得抢在首次生成之前 |
| R3 | 热路径新增同步 CPU 工作控制在毫秒级：schema 校验、正则、集合比对可以；重 tokenizer、交叉编码不行 |
| R4 | 重计算一律**异步 / 离线 / 抽样 / 用户触发**：索引重建、质量评分、二次验证不占用户等待时间 |
| R5 | 每项改动挂 [12](12-eval-and-golden-turns.md) 延迟门禁 golden，可测才算数 |

由此形成的通用「安全化手法」，后文反复引用：

| 手法 | 含义 |
|------|------|
| **转离线** | 从 Turn 同步尾移到 CI / 夜间 / 后台 worker |
| **转确定性** | 用规则、正则、集合比对替代「再问一次模型」 |
| **转按需** | 从「每轮必做」降为「模型经工具主动调用」 |
| **转提示词** | 用静态 system 文案引导行为，代替运行时强制拦截 |
| **转用户触发** | 高成本验证做成按钮 / 命令（如 `/verify`），用户要才跑 |

---

## Q0. Agent 的落地场景是什么？是否真的有用？

**结论：✅ 场景明确——「智能写作」为主、「沙箱通用 Agent」为辅；按自用北极星衡量已过「真实使用」门槛。不是万档企业知识库，也不宣称追平 Cursor 全功能。**

### 落地场景

| 场景 | `scenario_id` | 用户真实任务 | 交付物 |
|------|---------------|--------------|--------|
| **智能写作**（默认） | `writing` | 长文大纲、按章起草、依据资料改稿、引用核对、导出 | `outline.md`、`sections/`、diff、`exports/` |
| **通用 Agent** | `agent` | 沙箱内探索文件、检索、改代码、跑命令、多步任务 | patch、文件变更、工具时间线 |
| 面试演练 | `interview` | 最小闭环占位 | 非主力 |

两场景共用同一 Runtime（[10](10-product-modes.md)），差异只在 ScenarioProfile（工具白名单、system prompt、子 agent 角色、UI 布局）。仓库 `workspace/` 内的真实产物（小说素材卡、章节、导出文档、代码练习）可以佐证这不是空跑 demo。

### 「真的有用」怎么判定

项目自设北极星（[11 §0](11-product-experience.md)）：**自己愿意每天用它完成真实任务，连续数周不因卡顿、丢状态、不可预期而放弃**。逐维度诚实对照：

| 维度 | 现状 |
|------|------|
| 跟手 | SSE 流式 + TTFB/首 token/Cancel SLO 有设计有门禁；stub 路径已验收 |
| 可控 | 随时 Stop；改稿必 diff（`propose_patch` → Accept）；写/exec 工具强审批 |
| 有据 | 写作强制 `search_sources` 主路径 + 素材卡 pin；零命中要求明说，禁止编引用 |
| 可回归 | 37 条 golden；Context / RAG / delegate 必须被真实调用（Phase 1b 阻断项） |
| 长期 | session transcript 滚动 + 分层压缩；重装栈不丢会话 |

**诚实边界**：模型路径质量依赖 Frontier 模型本身；万级文档库、多租户、内容级隐私是已知未做项（见 Q8/Q11）。

### 一句话

> 它解决的是「**长文写作要证据、要 diff、要可打断**」和「**沙箱任务要过程可见、变更可审**」这两类真实需求；判据不是功能清单，而是自用留存 + golden 全绿。

**速率影响：** 无（产品定位问题，不涉热路径）。

---

## Q1. Agent 是否经常幻觉或乱调工具？如何缓解？

**结论：🔸 幻觉是模型固有问题，本项目不宣称消灭，而是用「缩小空间 + 入口拦截 + 证据链」三层把危害压到可自用。**

### 现状（三层防线，均已在代码）

**① 缩小可胡说的空间**

- ToolScope 白名单：模型每步只看见 Profile 允许的工具（`scenarios/profiles/*.yaml`）；写作场景没有 `run_command` / `grep`，从源头砍掉误用面。
- 提示词纪律：`scenarios/writing/system.md` 明文规定「`search_sources` 零命中不得捏造 citation」「pin 卡优先级最高」；`scenarios/agent/system.md` 规定「禁止猜路径，读写前先 `list_dir`/`glob` 确认」。
- 工具描述即产品文案：如 `search_sources` 描述里写明「已知路径优先 `read_file`，同一主题最多搜 2–3 次」。

**② 错误在工具入口失败，不留给模型下一轮猜**

| 拦截点 | 实现位置 | 行为 |
|--------|----------|------|
| 未知工具名 | `context/engine.py` `ToolExecutor.run` | 返回 `Tool not available` |
| 路径越权 | `tools/core/tools.py` `_resolve_path` | `..` 逃逸 → `PermissionError` |
| 写/exec 未审批 | `ToolSpec.requires_approval` | interrupt → `waiting_approval`，人审后续跑 |
| 检索刷限 | `search_sources_max_per_turn` | 超限直接报错并给出改用 `read_file` 的指引 |
| 重复只读调用 | `agent_engine.py` `_lookup_tool_cache` | 相同参数第二次起返回 `_cached` + 「不要再调」的劝停语 |

**③ 写作证据链**

检索结果只经 `tool_result` 进下一轮（Tool-mediated RAG）；改稿走 `propose_patch` diff，禁止静默覆盖；`check_citation` 可核对引用来源。

### 缺口

- 工具 arguments **没有统一 JSON Schema 预校验**（捏造参数靠 handler 抛异常兜底）。
- 没有事实 grounding 评分：模型仍可能把「像真的」写进正文。

### 改进方案（已按红线安全化）

| 方案 | 做法 | 速率 |
|------|------|------|
| **Schema 校验门** | `ToolExecutor.run` 内 `jsonschema.validate(arguments, spec.parameters)`，失败返回结构化 `invalid_arguments` + 缺字段清单，不调 handler | 🟢 微秒级 CPU；且省掉失败后的整轮纠错，**净提速** |
| **引用溯源校验** | Turn 内维护本轮检索命中的 `citation_id` 集合；`draft_section` / `export_document` 落盘前做**集合比对**（纯确定性），未命中的引用打 `unverified` 标记进事件，不阻断输出 | 🟢 集合运算；不打断流式 |
| **工具误用可观测** | 从既有 `tool.completed` 事件离线聚合「同 Turn 重复调用率 / 参数校验失败率」，超阈值加 golden | 🟢 离线 |
| ~~Turn 末强制 verify 子 Agent~~ | ❌ 原始形态多跑一整段子 loop（🔴 违反 R2/R4）。**安全化**：改为 (a) 用户触发 `/verify` 命令，或 (b) 夜间对已完成 Turn 抽样跑 fact_checker，结果写报告不改正文 | 🟢 用户触发 / 离线 |

---

## Q2. 如何设计评价 Agent 系统好坏的指标体系？

**结论：✅ 本项目已落地一套「行为契约 × 体验 SLO × 可观测」三位一体的体系；弱项是开放式内容质量分。**

### 现状：指标分五层

| 层 | 测什么 | 本项目落地 |
|----|--------|------------|
| 正确性 | 终态、事件子序列、workspace 文件内容 | Golden YAML：`turn.status` / `events.sequence_contains` / `workspace.matches` |
| 能力真实性 | Context / RAG / delegate 是否真的被 loop 调用 | Phase 1b 阻断 golden：`shared.04`（压缩）、`writing.05`（检索→引用）、`agent.05`（委派） |
| 体验 | TTFB ≤300ms、首 token ≤800ms、Cancel ≤500ms | `latency.*_ms_max` 断言（[11 §1](11-product-experience.md)） |
| 成本 | 步数、token、检索次数 | `metrics.max_steps` / `max_total_tokens` |
| 可观测 | 每步上下文占用、usage、重试次数 | `context.reported` / `usage.reported` 事件 + structlog `trace_id` |

分层执行：`make smoke`（L0 栈活）→ `make eval-all`（31 条 stub）→ `eval-retrieval` / `eval-queue`（能力剖面）→ `eval-live`（真模型抽样，容忍 flaky 看趋势）。

**设计要点（可迁移到任何 Agent 项目）**：先锁「行为契约」（同输入必须出现哪些事件、落什么终态），再锁「体验上界」（延迟 SLO），最后才是「智力质量」——顺序反了就会出现「评分很高但没法用」的系统。

### 改进方案

| 方案 | 做法 | 速率 |
|------|------|------|
| Rubric judge 质量分 | 小模型按忠实度/结构/风格打分，**只跑在 CI / 夜间**，对生产 Turn 抽样 ≤5% | 🟢 离线（R4） |
| 工具误用率 / 空转率 | 由既有事件流离线聚合 | 🟢 |
| 用户行为指标 | patch accept/reject 比、Cancel 率、二次修订轮次——从 `turn_events` 统计 | 🟢 |

---

## Q3. 主 Agent 任务规划怎么保证拆解合理？用什么 prompt 策略？

**结论：🔸 规划是可选工具而非强制阶段：`update_plan` 写计划、`delegate(planner)` 深度规划、多数任务在 ReAct 循环内隐式规划。平台不校验计划合理性——这是明确取舍：宁可偶尔拆解欠佳，也不给每个简单任务加规划税。**

### 现状

| 机制 | 实现 | 说明 |
|------|------|------|
| `update_plan` 工具 | `tools/core/tools.py`，schema 带 `status: pending/in_progress/done` 枚举 | 发 `turn.plan` 事件供 UI 展示；不强制执行 |
| `delegate(planner)` | `tools/delegate_runner.py`，工具限 `read_file`/`list_dir`/`update_plan`/`grep`，≤8 步 | 复杂任务先派专职规划子 agent，摘要回灌 |
| 隐式规划 | `AgentEngine` while 内模型自主决策 | 简单任务零规划开销，直接干活 |

Prompt 策略：**静态 Scenario system + 工具描述引导**，没有 CoT/ToT 模板强制、没有「先意图分类再分派」的 LLM pipeline（ADR-014 明确否决）。

### 缺口

计划与执行不绑定（计划项没完成也能 `completed`）；无依赖图。

### 改进方案（已安全化）

| 方案 | 做法 | 速率 |
|------|------|------|
| **提示词级 plan 引导** | 在 agent system.md 增加一段：「任务含 3 个以上独立目标时，先调用一次 `update_plan`」——**转提示词**，不做运行时强制拦截 | 🟢 静态文本，可进 prompt cache |
| **终态一致性回填** | Turn 结束时（终态事件之后、不挡用户）扫描最后一次 `turn.plan` 的 pending 项，写入 session summary 的 `open_items`，下一 Turn 自然可见 | 🟢 Turn 尾异步 |
| **planner 输出结构化** | `delegate(planner)` 子 prompt 要求给出 goal/steps/risks/done_criteria；`update_plan` 对字段做**确定性校验**（缺字段返回提示，不重跑模型） | 🟢 校验是 CPU 级 |
| ~~Intake 强制 plan gate~~ | ❌ 原始形态「复杂任务必须先 plan 再执行」= 强制多一轮模型（🔴 违反 R2）。**安全化**：仅在 Intake 检测到多目标关键词时往 runtime_context 里塞一行 hint 文本，由模型自行决定 | 🟢 一行文本注入 |
| ~~规划专用图节点~~ | ❌ 否决：回到固定 pipeline，简单任务也吃满链路 | — |

---

## Q4. 子 Agent 之间的上下文怎么传递？

**结论：✅「摘要委派」模型——task + 可选 context 字符串进，concise summary 出；刻意不共享完整消息历史。这本身就是为速率与窗口健康设计的。**

### 现状（`tools/delegate_runner.py` + `delegate_context.py`）

```text
主 Agent → delegate(task, agent_type, context?)
  → 子 TurnState.messages = [user_message(task + context)]   # 干净窗口
  → 子 AgentEngine 独立跑：专属 system prompt + 角色工具白名单 + max_steps=8
  → 子过程事件大部分被压制（_SUPPRESSED_SUB_EVENTS），仅 subagent.started/completed 上浮
  → 返回 {summary, status} 作为主 Agent 的 tool_result
```

| 传递 | 不传递 |
|------|--------|
| task + context 文本 | 主 Agent 的 messages 全量 |
| 同一 `turn_id`/`run_id`/取消信号（Cancel 级联） | 子的 thinking / token 流 |
| 完成后的 summary（截 500 字进事件） | 子完整 messages 倒灌 |

硬约束：`MAX_DELEGATE_DEPTH = 2`；角色→工具映射表 `SUBAGENT_TOOL_NAMES`（writing：researcher/drafter/editor/fact_checker/stylist；agent：explore/retrieve/verify/edit/planner/shell）。子↔子无直接总线，协作必须经主 Agent 再派——标准 supervisor 形态。

### 改进方案

| 方案 | 做法 | 速率 |
|------|------|------|
| `context_refs` 传路径指针 | 主 Agent 传 `sources/x.md` 等 path 而非贴大段文本，子按需 `read_file` | 🟢 **减** token，通常更快 |
| 注入 hot_files 指针 | 把主 session 的热文件列表（≤12 条路径）拼进子 system | 🟢 短文本 |
| ~~整包 messages 共享~~ | ❌ 否决：爆窗、信息串染、子首 token 恶化 | — |

注意区分：`delegate` **本身**就是一段完整子 loop，墙钟成本天然高——这是功能代价，控制手段是「模型按需少派 + depth ≤2 + 事件压制」，而不是改传递方式。

---

## Q5. 是否使用 ReAct？ReAct 是什么？优缺点？

**结论：✅ 等价使用。`AgentEngine` 的 while 循环就是 ReAct 族实现，Act 由 function calling 承载，不依赖「Thought/Action/Observation」文本协议。**

**ReAct（Reason + Act）**：每步让模型「推理 → 选动作（工具）→ 观察结果 → 再推理」，交替进行直到产出最终答案。

本项目对应（`engine/agent_engine.py`）：

```text
while step < max_steps:
    ContextEngine.assemble          # 组装模型这一步看见什么
    model.stream(messages, tools)   # Reason：模型内部推理，产出 tool_calls 或最终文本
    if tool_calls: 执行 → tool_result 回灌 messages   # Act + Observe
    else: 终止（final）
```

LangGraph 仅作单节点薄包装（`graph/runner.py`，ADR-005），业务不在图里。

| 优点 | 缺点 | 本项目的抑制手段 |
|------|------|------------------|
| 按需调工具，简单任务一步完 | 依赖模型选工具的质量 | ToolScope 白名单 + 工具描述纪律 |
| 天然适配流式与取消 | 可能空转打转 | 只读结果缓存 + 劝停语 + `max_steps` |
| 加能力 = 加工具，不改内核 | 缺全局最优规划 | `update_plan` / `delegate(planner)` 可选 |
| — | 成本随步数线性涨 | Turn token budget + step 超时 + Stall Watchdog |

无改进方案需评估——若反向改成固定 pipeline 反而 🔴（简单任务也跑全链）。

---

## Q6. 大模型捏造工具参数怎么处理？

**结论：🔸 现状靠「handler 异常 → error 回灌 → 模型下一轮自纠」+ 局部硬校验；缺统一 schema 门。补上它不但不伤速率，还能省掉纠错轮次。**

### 现状处理链

```text
Provider 解析 tool_calls JSON
  → ToolExecutor.run：未知工具 / 审批 / asyncio.wait_for(handler(**arguments))
  → 参数错 → handler 抛异常 → {"error": str(exc)} 以 is_error 回灌 messages
  → 模型下一轮看到错误自行修正
```

已有的点状硬校验：路径参数过 `_resolve_path` 沙箱；`export_document` 强制显式 `section_ids`（写作交付事故后加的，见 [13](13-writing-delivery-issues.md)）；`update_plan.status` schema 带枚举（但执行前未 validate）。

### 缺口

捏造字段名 / 缺 required / 类型错，全靠 Python `TypeError` 兜底——错误信息对模型不友好，往往多消耗一轮才纠正。

### 改进方案（全部 🟢，建议最先落地）

| 方案 | 做法 | 速率 |
|------|------|------|
| **统一 schema 门** | `ToolExecutor.run` 调 handler 前 `jsonschema.validate`（Draft 2020-12，复用 `packages/contracts` 已有依赖）；失败返回 `{"error":"invalid_arguments","missing":[...],"expected":<字段摘要>}` | 🟢 微秒～毫秒；**净提速**（省一轮纠错的完整模型调用，约数秒） |
| 高频工具 Pydantic 化 | `read_file`/`propose_patch` 等入参转 Pydantic 模型，错误消息更结构化 | 🟢 |
| path 预检 | 校验通过后对 path 类参数做一次 `stat`，不存在直接带候选提示返回 | 🟢 一次系统调用，远比读错文件再兜圈便宜 |
| 失败熔断 | 同一工具连续 3 次参数校验失败 → 计入 budget，提前明确终止而不是烧步数 | 🟢 早停即省钱省时 |

---

## Q7. 多 Agent 协作常见模式有哪些？

**结论：🔸 行业有七类常见模式；本项目主形态是「单 Agent + 工具」，协作只做了 supervisor→delegate 一种，这是**刻意收敛**——每多一个子 Agent 就多一段完整 loop 的墙钟。**

### 行业常见模式速查

| 模式 | 一句话 | 本项目取舍 |
|------|--------|-----------|
| Single agent + tools | 单循环按需调工具 | ✅ 主形态 |
| Supervisor / Router | 主派专家子 agent，摘要汇总 | ✅ 唯一多 Agent 入口（`delegate`） |
| Pipeline / Sequential | A→B→C 固定接力 | ❌ 内核层否决（旧项目 13 节点之痛） |
| Debate / Critique | 生成者 vs 批评者对抗 | 未做；见下方安全化 |
| Hierarchical | 多层 manager | 深度限 2，事实上不成层级 |
| Blackboard | 共享工作区，各自读写 | 弱形态：workspace 文件即黑板 |
| Swarm / Peer | 对等消息总线 | ❌ 协调成本爆炸，否决作默认 |

### 本项目实现要点

`delegate` 是唯一入口；角色白名单按场景（见 Q4）；子事件压制防止 UI 与窗口被刷爆；父 Cancel 级联子。

### 改进方案（已安全化）

| 方案 | 做法 | 速率 |
|------|------|------|
| 子 prompt 加 done_criteria | 委派时带明确完成标准，减少子 agent 空转步数 | 🟢 静态文本，且缩短子 loop |
| ~~默认 critique 链（写完必派 fact_checker）~~ | ❌ 每次交付多一整段子 loop（🔴 违反 R2/R4）。**安全化**：(a) 转提示词——写作 system 建议「引用密集章节可考虑 `delegate(fact_checker)`」，模型按需；(b) 转用户触发——UI 提供「事实核查」按钮；(c) 转离线——夜间对导出文档批量核查出报告 | 🟢 |
| ~~Peer 总线~~ | ❌ 否决 | — |

---

## Q8. 一万个长文档构建 RAG 知识库，怎么解决？

**结论：❌ 当前索引是单 JSON 文件 + 内存线性扫（`retrieval/vector_index.py`），面向写作场景百级小库绰绰有余；一万长文档会在内存、扫描、重嵌三处同时爆。方案分两阶段，且索引路径必须先异步化。**

### 现状能力边界

| 环节 | 现实现 | 万档下的问题 |
|------|--------|--------------|
| 存储 | `vector_index.json`：chunks + 向量整体载入内存 | 千万级 chunk 内存放不下 |
| 检索 | 逐 chunk cosine（线性扫）+ BM25 + RRF | 查询延迟随库线性涨 |
| 索引 | `sync()` 按 mtime 增量；**默认在 `search_sources` 调用里同步跑** | 大库首查会把索引墙钟算进用户等待 ← 最伤交互 |
| Embedding | sentence-transformers（retrieval 镜像）或 hash 降级 | 万档全量重嵌需专门流水线 |
| 权限 | 无 ACL / 多租户 | 企业场景必需 |

### 改进方案（阶段化，索引先行）

**第 0 步（不换存储也应先做）：索引彻底出热路径。**

- `index_via_worker=true` 成为默认：上传/变更 → outbox 任务异步嵌入；`search_sources` **只查不建**，索引落后时返回旧结果 + `index_lag` 提示。  
- **速率：** 🟢 这一步是纯减法，消除「首查卡索引」的最大隐患（R1/R4）。

**阶段 A：单租户库放大（千～万档）**

| 措施 | 速率 |
|------|------|
| 存储迁 pgvector / Qdrant，ANN 索引（HNSW） | 查询 🟡→通常**快于**现线性扫；写入异步 |
| 两级召回：文档摘要层先选 doc，段落层再取 chunk | 🟡 两跳查询——**并行发出 + 单跳超时降级**（超时只用段落层） |
| 切分保持「标题优先 + 400 字 / 80 重叠」，超长节换语义切分器（离线跑） | 🟢 离线 |

**阶段 B：企业万档**

| 措施 | 速率 |
|------|------|
| namespace + metadata ACL 过滤（在 ANN 查询谓词里做，不做召回后全量过滤） | 🟡 |
| BM25 侧换 Elastic/OpenSearch，与向量双路 RRF | 🟡 双路并行取 max，设单路超时 |
| ~~交叉编码 rerank~~ → **安全化**：默认用现有 lexical rerank（轻量）；cross-encoder 仅离线评估或对 top-20 小池 + 50ms 预算 + 超时跳过 | 🟢～🟡 |

**对当前写作交互的忠告**：库小时现状够用；**任何扩库动作之前先做第 0 步**，否则用户第一次搜索会替你付索引账单。

---

## Q9. 当前项目的 Context / Prompt / Harness Engineering

**结论：✅ 三层职责清晰，且都有代码落点；Harness 是总纲（见 Q14）。**

### Context Engineering — 「模型这一步看见什么」

每步 `ContextEngine.assemble`（`context/engine.py`）产出 `ContextEnvelope`：

| 分区 | 内容 |
|------|------|
| system_blocks | Scenario 模板 + 写作 pin 卡（稳定前缀，利 prompt cache） |
| project_context | `AGENT.md` 等项目针脚 |
| runtime_context | 步数、预算等运行时拼装块 |
| message_window | session transcript + 本 Turn messages |
| included_tools | Scoped 工具表 |
| budget_report | tokens_before/after、fill_ratio、assemble_ms → 发 `context.reported` 事件 |

**多层防线**（`context/policy.py`，阈值可配）：工具结果先按约 4k 字符预算截断；fill ≥80% collapse 旧工具历史 → ≥90% snip 最老消息组 → ≥95% autocompact 摘要。铁律：**未达阈值禁止整窗 LLM 摘要**；落库 trim 必须确定性无 LLM（`session_transcript.py`）。

### Prompt Engineering — 「静态话术 + 动态组装」

| 类型 | 载体 |
|------|------|
| 静态 | `scenarios/*/system.md`、`ToolSpec.description` + JSON parameters（描述即产品文案） |
| 动态 | pin 卡、`@path` 预读、session summary / hot_files、tool_result |
| Intake | `InputCompiler` / `shouldQuery` 确定性门控（`/help` 类零模型调用短路） |

### Harness Engineering — 「包住模型的六面厚度」

Intake · Context · Tools · Model · Guard · Proof，详见 Q14 与 [14](14-model-harness.md)。三层的共同纪律：**策略进 Profile / Gateway / ContextEngine，不进 `AgentEngine` 的 `if scenario` 分支。**

---

## Q10. Tool 与 Memory 怎么设计？长短时记忆？

**结论：🔸 Tool 协议完整（注册 → Scope → 审批 → 超时 → 截断）；记忆没有独立「Memory 服务」，而是按寿命分六层落在 transcript / summary / 文件 / RAG 上——短时靠截断保速，长时靠指针与按需检索防爆窗。**

### Tool 设计（已落地）

```text
ToolRegistry.register(ToolSpec)          # tools/registry.py
  name / description / parameters(JSON Schema) / handler / requires_approval / timeout_s
ScenarioProfile.tool_names → ToolScope   # 模型只见白名单
执行：连续只读并行（asyncio.gather）；写/exec 串行 + 审批（ON_WRITE_TOOLS）
结果：统一回 messages，再过 Context 预算截断
```

新能力 = 新工具 + Profile 登记，不改 loop（扩展宪法，[10 §0](10-product-modes.md)）。

### 记忆分层（对照代码）

| 层 | 载体 | 寿命 | 注入方式 | 保速手段 |
|----|------|------|----------|----------|
| 短时工作记忆 | `TurnState.messages` | 单 Turn | 每步 assemble | 工具结果 4k 截断；fill 阈值压缩 |
| 会话滚动记忆 | `session_transcripts`（PG） | 跨 Turn | 新 Turn 开头加载 | 落库前确定性 trim，读取无 LLM |
| 会话长时摘要 | `sessions.context_summary` | 跨 Turn | transcript 缺失时兜底；含 hot_files 指针 | 摘要短小 + 指针化 |
| 外部知识 | `workspace/sources/` + 向量索引 | 持久 | **模型按需调 `search_sources`** | 按需检索，不每轮预灌 |
| 写定约束 | `sources/cards/*` pin | 持久 | Turn 级钉进 system 前缀（`writing/cards.py`） | 稳定前缀利 cache；卡片不进 RAG 防噪 |
| 产物记忆 | sections / exports / `.agent/revisions` | 文件 | `read_file` 按需 | — |

### 改进方案（已安全化）

| 方案 | 做法 | 速率 |
|------|------|------|
| 显式 `remember` / `recall` 工具 | 作为**按需工具**注册（带 namespace / 重要性）；recall 走小向量库 | 🟡 与一次检索同级；**禁止每轮强制召回**（那是 🔴，见 Q17） |
| 偏好库与资料库分仓 | 「用户偏好/决策」单独 namespace，不混进写作资料 RAG | 🟢 治理性改动 |
| 记忆可见化 | UI 面板展示本 Turn 注入了哪些卡/摘要/hot_files（读投影即可） | 🟢 投影层 |

---

## Q11. 隐私消息怎么防止泄漏？

**结论：🔸 结构性边界齐全（沙箱、内网、token、key 加密）；内容级防护（PII 脱敏、egress 管控）尚缺。补齐方案全部可以做到 🟢。**

### 已有边界

| 面 | 机制 |
|----|------|
| 文件 | 工具路径必须落在 `WORKSPACE_ROOT`（`_resolve_path` 拒逃逸） |
| 服务 | runtime 不暴露公网；api→runtime 走 `X-Internal-Token` |
| 凭据 | 模型 API key Fernet 加密存 DB（`model/crypto.py`）；`.env` 不进镜像 |
| 行为 | 写/exec 工具默认审批；`run_command` 输出截断 |
| 管理 | admin 接口 Basic 认证 |

### 缺口

进出模型的 prompt / 日志无 PII 脱敏；无「只允许把数据发往已配置 provider」的强制；无多租户隔离。

### 改进方案（已安全化）

| 方案 | 做法 | 速率 |
|------|------|------|
| Egress allowlist | `ModelGateway` 出站前比对已配置 base_url 集合 | 🟢 一次集合查找 |
| 正则脱敏中间件 | 手机号/身份证/密钥模式的**预编译正则**，仅对出站 prompt 与日志字段跑；~~LLM 判别脱敏~~ ❌（🔴 多一轮模型） | 🟢 大 prompt 上毫秒级；预编译 + 只扫新增增量可再压 |
| 写入前 secret 扫描 | 仅 `write_file`/`export_document` 路径；同步版设 50ms 预算超时放行 + 异步补扫告警 | 🟢～🟡 |
| at-rest 加密 | PG 字段级或磁盘级 | 🟢 不占交互墙钟 |
| 日志脱敏 | structlog processor 里对 `arguments` 字段套同一套正则 | 🟢 |

---

## Q12. 保证效果的前提下，怎么加速推理？

**结论：🔸 加速是 Harness 的并行主线（[14 §4](14-model-harness.md)），已有八类杠杆在代码；纪律是「加厚必先能抵消」。**

### 已落地杠杆

| 杠杆 | 实现 | 效果 |
|------|------|------|
| 首字节快超时 | `ModelGateway`：connect / 首字节短超时，快失败快重试 | 避免第一次就干等 120s |
| Prompt cache | Anthropic `cache_control` 标记稳定前缀（system+tools） | 长会话输入 token 费用与延迟同降 |
| 只读工具并行 | `_run_tool_batch`：连续 `_CACHEABLE_TOOLS` 用 `asyncio.gather` | 探索类步骤墙钟降 |
| 工具结果缓存 | 相同参数只读调用直接回缓存 + 劝停 | 消除重复 IO 与空转步 |
| Assemble 复用 | fingerprint 未变则跳过重组 | 减每步 CPU |
| Intake 短路 | `/help` 等确定性回复，零模型调用 | meta 输入秒回 |
| Cancel 打断 backoff | 重试等待期可被取消 | Cancel SLO 不被重试拖累 |
| 检索预算 | `search_sources_max_per_turn` | 防刷搜烧步数 |

### 进一步方案（已安全化）

| 方案 | 做法 | 速率 |
|------|------|------|
| 小模型分流 | compact 摘要 / 简单分类用便宜小模型，**独立超时 + 只在 Turn 尾或后台跑**，失败降级为确定性摘要 | 🟡 不挡 TTFB（R1） |
| 预热 | 用户打字时异步 warm embedding / 索引载入 | 🟢 完全异步 |
| 阶段化 ToolScope | 交付期收窄工具表 → tools JSON 变小 → 输入 token 降 | 🟡 切换逻辑必须是简单规则，不引入 LLM 判断 |
| 工具 DAG 并行 | 静态标注 side_effect 后无依赖工具并行 | 🟢～🟡 做对了纯加速；依赖分析宁可保守 |
| 供应商侧投机解码 | 若 API 支持则开启 | 🟢 平台无成本 |

---

## Q13. RAG 为什么混合召回？Chunk 怎么切？太大太小的问题？

**结论：✅ 写作 sources 已实现 BM25 + 向量 + RRF 融合，可选 lexical rerank；chunk 按 Markdown 标题切节，超长节 400 字窗 / 80 重叠。**

### 为什么混合（`retrieval/vector_index.py` `search_hybrid`）

| 单路 | 强 | 弱 |
|------|-----|-----|
| 纯向量 | 语义改写、同义表达 | **专名、编号、短术语**常丢（如「张白鹿」「§4.2」） |
| 纯 BM25 | 精确词命中稳 | 换个说法就搜不到 |

融合：双路各取 top-k → `reciprocal_rank_fusion`（k=60 可配）→ 可选 lexical rerank。硬规则：**禁止「向量有结果就丢关键词路」**；命中分低时返回 hint 引导模型改 `read_file`，防止低质量刷搜。降级链：向量不可用 → keyword 全文扫兜底。

### Chunk 策略（`retrieval/chunking.py`）

```text
1. 按 #/##/### 切 Markdown 节（语义边界优先）
2. 节内超长 → CHUNK_SIZE=400 字滑窗，CHUNK_OVERLAP=80
3. 每 chunk 带 path / section_title / line_start~end / citation_id / vector
4. sources/cards/ 不进索引（素材卡走 pin，防 RAG 噪声）
```

### 太大 / 太小的代价

| 维度 | 太大 | 太小 |
|------|------|------|
| 召回 | 一 chunk 混多主题，相似度被稀释，难定位 | 语境破碎，指代断裂 |
| 窗口 | 命中几条就吃掉几千 token，**直接拖慢首 token** | 要拼很多条才够语境，条数失控 |
| 引用 | 行号范围太宽，核对困难 | 引用过碎 |

400/80 + 标题边界是「段落级证据」的折中；overlap 缓解边界切断。

**速率视角的关键既有决策**：Tool-mediated RAG（检索只经工具按需进入，绝不每轮预灌向量包）——这是保护首 token 的最重要设计，任何改进不得破坏。

---

## Q14. Harness 讲解

**结论：✅ Harness = 包住 frontier model、决定「好不好用」的整层工程。本项目的判断：loop 形状已对，成熟度差在六面厚度，不在换模型或加 pipeline 节点。**

### 六面（[14](14-model-harness.md)，AH1–AH4 核心已落地）

| 面 | 管什么 | 代表实现 |
|----|--------|----------|
| **Intake** | 确定性输入编译、shouldQuery 门控、`@path` 预算内预读 | `controller/input_compiler.py` |
| **Context** | Envelope 分区、budget、collapse/snip/autocompact、assemble 复用 | `context/engine.py` |
| **Tools** | Scope、审批、超时、只读并行、description hygiene | `tools/` + `_run_tool_batch` |
| **Model** | 供应商热配置（ADR-019）、重试分类、首字节快超时、prompt cache、usage | `model/gateway.py` |
| **Guard** | Cancel 贯穿 backoff/assemble/预读、三层超时、Stall Watchdog | ADR-015/016 |
| **Proof** | Golden、延迟门禁、`context.reported`/`usage.reported`/`retry_count` | `eval/` + 事件契约 |

### 铁律（[14 §4](14-model-harness.md)）

1. `turn.accepted` 先于任何重试/assemble 发出。
2. 加厚上下文必须被 cache 抵消或设硬上限——**「厚」不许牺牲「快」**。
3. Cancel 必须能打断 backoff、assemble、预读。
4. 策略不进 `AgentEngine` / `ToolExecutor` 的 scenario 分支。

**Harness 不是**：换模型；再加 workflow 节点；每场景复制一套 gateway。

---

## Q15. 多数据表、多内容下，怎么设计稳定召回链路？

**结论：❌ 现有 RAG 面向 workspace 文件，不是多表业务库。以下是目标架构草案——设计时每一环都预置了速率约束，可作下阶段蓝图。**

### 分层召回总线（草案）

```text
Query
  → 查询理解：规则/词典抽实体、时间窗（❌ 不用「每问一次 LLM 路由」）
  → 多通道并行召回（各通道独立超时，取 max 而非串行相加）：
      Structured：参数化 SQL（带租户 ACL 谓词）
      Lexical：BM25/ES（工单号、专名）
      Vector：pgvector ANN（语义段落）
  → RRF / 加权合并
  → ACL 过滤（谓词内置于各通道查询，避免召回后大集合过滤）
  → 轻量 rerank（lexical；cross-encoder 仅离线）
  → 预算打包：evidence blocks（带来源主键 + 权限标签），按 token 预算截断
  → 只经 search_records 类工具返回 Agent（Tool-mediated，不预注入）
  → 生成后确定性校验：引用主键 ∈ evidence 集合
```

### 稳定性要点与速率标注

| 要点 | 做法 | 速率 |
|------|------|------|
| 查询理解 | 规则 + 实体词典 + 结果缓存；LLM 路由仅作离线兜底实验 | 🟢（LLM 每问路由为 🔴，否决） |
| 通道降级 | 向量挂 → BM25 顶上；DB 挂 → 明确报错，**禁止编造** | 🟢 降级即保速 |
| 并行 + 超时 | 通道并行，单通道 300ms 级超时放弃 | 🟡 墙钟 = 最慢存活通道 |
| 索引流水线 | 幂等任务 + 死信队列，全部异步 | 🟢 离线 |
| 引用校验 | 生成后集合比对 | 🟢 |
| ~~预注入多表 join 进 system~~ | ❌ 否决：又慢（每轮大 payload）又易越权 | — |
| 回归 | golden：专名召回、跨表关联、ACL 拒绝、空结果诚实声明 | 🟢 离线 |

本仓库演化路径：先把 `sources` 索引迁 pgvector（Q8 第 0 步、阶段 A）→ 再加 `search_records` 工具接业务库——**仍走同一 loop，不为多表召回加图节点**。

---

## Q16. 动态 Prompt 与静态 Prompt？

**结论：✅ 明确两分：静态部分版本化、可缓存；动态部分经 ContextEngine 组装、可截断。**

| | 静态 Prompt | 动态 Prompt |
|--|-------------|-------------|
| **内容** | Scenario `system.md`；工具 name/description/parameters；子 agent 角色前缀；产品宪法（禁静默覆盖、禁编引用） | 用户消息与历史；pin 卡内容；`@path` 预读；session summary / hot_files；tool_result；runtime 拼装块 |
| **变更频率** | 随版本发布 | 每 Turn / 每 Step |
| **速率意义** | 稳定前缀命中 **prompt cache** → 输入延迟与成本双降 | 必须可截断，否则窗口失控拖慢首 token |
| **治理** | 进 git、code review | 进 `ContextEnvelope` 预算防线 |

原则：**能静不动**（约束尽量固化进静态层换 cache 收益）；动态膨胀必截断，但 pin 卡与安全条款优先保留。把频繁变动的内容误塞进 system 前缀会破坏 cache 命中——这是最常见的隐性劣化。

---

## Q17. 模型如何决定长期记忆是否需要召回？

**结论：🔸 分两条路：外部资料由**模型自主选工具**（prompt 规则引导）；会话记忆由**系统策略**默认加载。没有独立「记忆路由器」——这恰是速率友好的选择。**

### 现状决策矩阵

| 记忆 | 谁决定召回 | 机制 |
|------|-----------|------|
| sources 资料 | 模型 | writing system.md 列明何时 `search_sources` / 何时 `read_file` / 何时跳过（纯改写、无证据需求就不搜） |
| session transcript | 系统 | 新 Turn 默认加载（`turn_controller.py`）；满窗才压缩 |
| context_summary | 系统 | transcript 缺失时兜底 |
| 素材卡 | 系统强制 | 匹配即 pin，不经模型选择（`cards.pinned` 事件可观测） |

### 改进方案（已安全化）

| 方案 | 做法 | 速率 |
|------|------|------|
| `recall_memory(query, namespace)` 工具 | 与 `search_sources` 同级的**按需工具**，模型判断该不该调 | 🟡 调了才花一次检索 |
| Intake 召回提示 | 检测「还记得/上次/之前说过」类模式 → runtime_context 加一行 hint，**只是提示不是强制** | 🟢 文本注入 |
| ~~每 Turn 自动向量召回记忆~~ | ❌ 等价每轮预检索（🔴 违反 R2）。**安全化**：召回权交给模型工具选择 + 上述 hint | 🟢 |
| 召回质量评估 | 错召率 / 漏召率离线统计 | 🟢 离线 |

---

## Q18. 为什么要静态长期记忆和动态长期记忆？

**结论：🔸 概念上必须区分：混在一起要么「窗死」（全钉）要么「漂移」（全动态）。本项目已有对应物，缺的是显式命名与分仓。**

| | 静态长期记忆 | 动态长期记忆 |
|--|--------------|--------------|
| **本质** | 低频变更的**权威约束** | 随任务演进的**事实与情节** |
| **例子** | 人设卡、风格卡、禁忌红线、工具使用宪法 | 会话摘要、hot_files、大纲变更史、检索命中 |
| **注入** | 钉进 system 前缀，高优先级 | 滚动窗口 / 按需工具召回 |
| **全用此类的后果** | 窗口被占死，新信息进不来 | 角色漂移、前后矛盾、约束被稀释 |
| **本项目对应** | `sources/cards` pin、`system.md`、工具 schema | `session_transcripts`、`context_summary`、sources 索引 |

**速率视角**：这个区分本身就是性能设计——静态层稳定 → prompt cache 命中；动态层可截断 → 窗口不失控。把「情节」误当「约束」钉进 system，等于同时破坏 cache 和挤占窗口，双输。

改进（🟢 纯治理）：产品层显式命名 constraints 仓 vs episodes 仓，配不同的写入与淘汰策略，避免「什么都进 RAG / 什么都想 pin」。

---

## Q19. 整个链路的运转？

**结论：✅ 控制面（api）与执行面（runtime）分离；`turn_events` 是唯一事实源；UI 只消费 SSE + 投影，从不猜阶段。**

```text
① Web 工作台 POST /api/v1/sessions/{id}/turns   （scenario_id + message + client_request_id 幂等）
② api：INSERT Turn(pending) + Run(accepted)（1:1）→ 内部命令 StartTurn → runtime
③ runtime TurnController：
     加载 ScenarioProfile / DB 热模型配置（ADR-019）/ session transcript
     Intake：InputCompiler + shouldQuery（meta 输入零模型短路）
     写作：匹配素材卡 → pin 进 system → cards.pinned 事件
     先发 turn.accepted（保 TTFB ≤300ms）
④ AgentEngine while（每步）：
     ContextEngine.assemble → context.reported
     ModelGateway.stream（function calling；turn.token 流式）
     工具执行：只读并行 / 写+exec 串行审批 → tool.started/completed
     checkpoint + turn_events 追加（append-only 事实）
⑤ 终态：completed / failed / cancelled / waiting_approval
     → session_transcripts UPSERT（确定性 trim，无 LLM）
⑥ Postgres NOTIFY → api TurnEventListener（LISTEN + 300ms 轮询兜底）
     → SSE /turns/{id}/stream（断线 Last-Event-ID 重放）
     → project_turn 折叠 turn_views
⑦ Web 渲染 timeline / diff / 文稿；Accept patch、Approve tool、Cancel 走命令通道回到 ③
```

机制级完整时序见 [15 §26](15-highlights-vs-legacy.md)。

---

## Q20. Function Calling 在当前项目怎么运作？

**结论：✅ 主路径就是原生 function calling，不做「Action: xxx」文本解析。**

### 六步流程

| 步 | 内容 | 位置 |
|----|------|------|
| 1 注册 | `ToolSpec.parameters` 即 JSON Schema | `tools/bootstrap.py` |
| 2 暴露 | 转 provider 中立 `{name, description, input_schema}` | `agent_engine.py` |
| 3 下发 | OpenAI 兼容：`tools:[{type:"function", function:{...}}]` + `tool_choice`；Anthropic：tools 块 + `cache_control` | `model/openai_provider.py` / `anthropic_provider.py` |
| 4 回流 | 流式聚合 `tool_calls`（id/name/arguments 增量拼接）→ `ModelResponse.tool_calls` | providers |
| 5 执行 | `assistant_tool_uses` 入 messages → `_run_tool_batch`（只读并行）→ `tool_result_message` 回灌 | `agent_engine.py` |
| 6 终止 | 无 `tool_calls` 的响应视为最终答案；或 max_steps / budget / cancel | loop 终止条件 |

stub / recorded 模式可回放固定 `tool_calls` 序列，支撑 golden 回归而不烧真模型。

与「文本 ReAct」的差别：协议层就是 FC，参数错误走结构化 error 回灌（配合 Q6 的 schema 门），不靠正则抠文本——更稳也更快。

---

## 附录 A — 改进方案速率总表（安全化后）

> 原则重申：**🔴 原始形态一律不采纳**；下表列出的都是改写后的推荐形态。  
> **如何落地排期**：见 [17-execution-plan.md](17-execution-plan.md)（S0 → S2 → S3）。  
> **落地状态（2026-07）**：A1–A21 最小可合并切片均已提交；细节与开关见 17。部分项默认关或为 stub（A10 默认 json、A20 stub、A5 启发式），合入前仍需跑 `make runtime-test` / `eval-*`。

| ID | 方案（安全版） | 速率 | 安全化手法 | 建议 | 状态 |
|----|----------------|------|------------|------|------|
| A1 | 工具参数 JSON Schema 校验门 | 🟢 净提速 | 确定性 CPU 校验 | 立即做（Q1/Q6） | **已落地（2026-07）** |
| A2 | 引用 ∈ evidence 集合比对 + unverified 标记 | 🟢 | 转确定性；不阻断输出 | 立即做（Q1/Q13） | **已落地（2026-07）** |
| A3 | 工具误用 telemetry | 🟢 | 转离线聚合 | 立即做 | **已落地（2026-07）** |
| A4 | 事实核查：`/verify` 用户触发 + 夜间抽样 | 🟢 | 转用户触发 / 转离线（原「Turn 末强制 verify」🔴 已否决） | 按需 | **已落地（2026-07）** |
| A5 | Rubric judge 质量分 | 🟢 | 转离线（CI/夜间，抽样 ≤5%） | 按需 | **已落地（2026-07）**（启发式 `make eval-rubric`；非 Turn 尾） |
| A6 | plan 引导：提示词 + Intake 一行 hint | 🟢 | 转提示词（原「强制 plan gate」🔴 已否决） | 可做 | **已落地（2026-07）** |
| A7 | plan-execute 一致性回填 open_items | 🟢 | Turn 尾异步 | 可做 | **已落地（2026-07）** |
| A8 | delegate 传 path 指针 / hot_files | 🟢 | 减 token | 可做 | **已落地（2026-07）** |
| A9 | 索引出热路径（worker 化，search 只查不建） | 🟢 | 转异步 | 扩库前必做（Q8 第 0 步） | **已落地（2026-07）** |
| A10 | pgvector/Qdrant + ANN | 查询🟡 | 写入异步；ANN 常快于线性扫 | 扩库时做 | **已落地（2026-07）**（默认 `json`；`RETRIEVAL_BACKEND=pgvector` 启用） |
| A11 | 两级 doc→chunk 召回 | 🟡 | 并行 + 单跳超时降级 | 扩库时做 | **已落地（2026-07）** |
| A12 | rerank：lexical 默认；cross-encoder 仅离线或 top-20+50ms 预算 | 🟢～🟡 | 转离线 / 硬预算（原「默认 cross-encoder」🔴 已否决） | 按需 | **已落地（2026-07）**（姿态确认） |
| A13 | `remember`/`recall` 按需工具 | 🟡 | 转按需（原「每轮自动召回」🔴 已否决） | 按需 | **已落地（2026-07）** |
| A14 | egress allowlist | 🟢 | 集合查找 | 立即做 | **已落地（2026-07）** |
| A15 | 预编译正则 PII 脱敏（禁 LLM 脱敏） | 🟢 | 转确定性 | 可做 | **已落地（2026-07）** |
| A16 | secret 扫描：50ms 预算 + 异步补扫 | 🟢～🟡 | 硬预算 + 转异步 | 可做 | **已落地（2026-07）** |
| A17 | 小模型分流 compact | 🟡 | 独立超时；Turn 尾/后台；降级确定性摘要 | 可做 | **已落地（2026-07）** |
| A18 | 打字期预热 embed / 索引 | 🟢 | 转异步 | 可做 | **已落地（2026-07）** |
| A19 | 阶段化 ToolScope 缩 tools JSON | 🟡 | 规则切换，无 LLM 判断 | 可做 | **已落地（2026-07）** |
| A20 | 多表召回：规则路由 + 通道并行超时 + ACL 谓词 | 🟡 | 转确定性路由（原「LLM 每问路由」🔴 已否决） | 蓝图 | **已落地（2026-07）**（`docs/18` + `search_records` stub） |
| A21 | critique：提示词建议 + 用户按钮 + 夜间批量 | 🟢 | 三重转移（原「默认 critique 链」🔴 已否决） | 按需 | **已落地（2026-07）** |

**被彻底否决（无安全版可言）**：恢复固定 pipeline；子 Agent 整包 messages 共享；peer 多 Agent 总线；每轮预注入向量包 / 多表 join；未达阈值整窗 LLM 摘要。

---

## 附录 B — 关键代码索引

| 主题 | 路径 |
|------|------|
| Agentic loop | `services/runtime/app/engine/agent_engine.py` |
| Context 引擎 / 压缩策略 | `services/runtime/app/context/engine.py` · `policy.py` |
| 工具注册 / 实现 | `services/runtime/app/tools/bootstrap.py` · `tools/core/tools.py` |
| 委派 | `services/runtime/app/tools/delegate_runner.py` · `delegate_context.py` |
| RAG（切分/BM25/向量/融合/重排/两级召回） | `services/runtime/app/retrieval/`（含 `pgvector_store.py` · `two_level.py`） |
| 隐私 / secret 扫描 | `services/runtime/app/privacy/` |
| `/verify` / 事实核查 | `controller/verify_pass.py` · slash `/verify` · web「事实核查」 |
| 记忆工具 | `tools/core/memory.py`（`remember`/`recall`） |
| 多表召回 stub | `tools/core/records.py` · [18](18-a20-multitable-recall.md) |
| 离线 rubric | `app/offline/rubric.py` · `scripts/eval_rubric.py` · `make eval-rubric` |
| 会话记忆 | `controller/session_transcript.py` · `session_context.py` · `session_compact.py` |
| 素材卡 pin | `services/runtime/app/writing/cards.py` |
| 模型网关 / FC | `services/runtime/app/model/gateway.py` · `openai_provider.py` · `anthropic_provider.py` |
| 场景 Profile / system prompt | `services/runtime/app/scenarios/` |
| Golden / 评估 | `eval/golden/` · `scripts/eval_run.py` · [12](12-eval-and-golden-turns.md) |
| Harness 总纲 | [14-model-harness.md](14-model-harness.md) |

---

## 附录 C — 一句话答案卡

| # | 一句话 |
|---|--------|
| 0 | 落地 = 智能写作 + 沙箱 Agent；判据是自用留存 + golden 全绿，不是功能清单。 |
| 1 | 幻觉只能压不能灭：ToolScope 缩空间、入口先失败、证据链兜底；schema 门还能净提速。 |
| 2 | 先锁行为契约，再锁体验 SLO，最后才谈质量分；质量分永远离线跑。 |
| 3 | 规划是可选工具不是强制阶段；引导用提示词，不用运行时拦截加规划税。 |
| 4 | 子 Agent：task+指针进、summary 出；整包共享历史被否决。 |
| 5 | while + function calling ≡ ReAct；缺点用 budget/缓存/watchdog 抑制。 |
| 6 | 假参数：调 handler 前 schema 校验，失败结构化回灌——省一整轮纠错。 |
| 7 | 只做 supervisor-delegate；critique 转提示词/按钮/夜间，不默认多派子 loop。 |
| 8 | 万档 RAG：第一步是索引出热路径，再迁 ANN 向量库；同步重嵌是大忌。 |
| 9 | Context 管每步看见什么；Prompt 管静态话术+动态组装；Harness 管六面厚度。 |
| 10 | 短时记忆靠截断保速，长时记忆靠指针+按需检索防爆窗。 |
| 11 | 结构边界已齐（沙箱/token/加密）；内容防护用预编译正则，禁 LLM 脱敏。 |
| 12 | 加速八杠杆：快超时、cache、只读并行、复用、短路、预算、缓存、可断重试。 |
| 13 | 混合召回补专名盲区；chunk 标题优先 400/80；Tool-mediated 保首 token。 |
| 14 | Harness = Intake/Context/Tools/Model/Guard/Proof 六面；厚不许牺牲快。 |
| 15 | 多表召回：规则路由 + 通道并行超时 + ACL 谓词 + 引用校验；禁预注入。 |
| 16 | 能静不动：静态换 cache，动态可截断。 |
| 17 | 资料召回交给模型选工具，会话记忆交给系统策略；不做每轮盲召。 |
| 18 | 约束钉静态、情节走动态——既防漂移也保 cache。 |
| 19 | api 收命令、runtime 跑 loop、events 是事实、SSE+投影出 UI。 |
| 20 | FC：Schema 下发 → 流式聚 tool_calls → 校验执行 → tool_result 回灌。 |
