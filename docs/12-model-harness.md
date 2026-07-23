# 12 — Agent Harness（成熟度总纲）

> **状态**：部分落地（2026-07-13）— **AH1 ✅**；**AH2–AH4 / AH-obs 已落地核心路径**。**下一刀口径（2026-07-21）见 §5.1**：① cache 布局（WT5）② 变短≈压缩 ③ Proof 延迟盯梢——设计/纪律已定，实现按排期。  
> **范围**：**广义 Agent Harness**——包住 frontier model、决定「好不好用」的整层工程：Intake · Context · Tools 执行纪律 · Model · Cancel/超时/watchdog · Eval/SLO 与可观测。  
> **不在范围**：改写 `AgentEngine` while 语义；恢复固定 pipeline；K8s / MCP / 多租户模型市场；**写作去 AI 腔**（走 writing `system.md`，见 [`14`](14-writing-quality.md)，不塞进 Harness 引擎）。

关联：[`05-agent-runtime.md`](05-agent-runtime.md)（loop 细则）· [`06-tools-and-context.md`](06-tools-and-context.md)（工具与 Context 契约）· [`20`](20-context-compaction-walkthrough.md)（压缩演练）· [`24` §4.6](24-writing-token-economy.md)（WT5）· [ADR-014](adr/014-turn-intake-deterministic.md)（Intake）· [ADR-015](adr/015-interrupt-cancel-resume.md)（Cancel）· [ADR-016](adr/016-execution-timeouts-and-stall-watchdog.md)（超时/watchdog）· [ADR-019](adr/019-model-provider-runtime-config.md)（供应商配置）· [`10-product-experience.md`](10-product-experience.md)（体验 SLO）· [`11-eval-and-golden-turns.md`](11-eval-and-golden-turns.md)（延迟门禁）。

> **命名说明**：早期文稿称「Model Harness」，仅覆盖模型调用外围。本文升格为 **Agent Harness 总纲**；原 Model 面仍是子轨之一（AH1–AH2、AH4 部分）。细则不合并进本文——`05`/`06`/`11`/`12` 仍是各面权威。

各期合并后更新本文「状态」与 `docs/README`；若引入不可逆契约（重试语义、cache 前缀、envelope 字段），再抽 **ADR-020**，否则扩写既有 ADR / 专文。

**AH1 落地摘要（Model 子轨）**：`ModelGateway` 统一重试（仅尚未吐 token）+ 首字节快超时 + Cancel 可打断 backoff **与** provider HTTP 流（abort → `aclose`，含长 thinking 间隙）；已请求取消时 transport 错误 **不得**升成「after streaming started」fatal；`ModelTransientError` / `ModelFatalError` / `ModelProviderTimeout`；`GenerationParams`（`max_output_tokens` 对齐 `output_reserve_tokens`、scenario temperature、`tool_choice`、thinking 默认关）；reasoning → `turn.thinking.delta`（不进投影）。见 `model/gateway.py`、`model/stream_abort.py`、providers、`tests/test_gateway_retry.py`。

---

## 0. 一句话

> **Loop 形状已经对；成熟度差在 Agent Harness 厚度**（看见什么、调得稳不快拖、工具跟手、可打断、可证明）。  
> 「厚」不能牺牲「快」：每一项能力增强都要通过热路径成本审视，不得回归 [`11` §1](10-product-experience.md) 的 TTFB / 首 token / Cancel SLO。

**两条主线并重**：

| 主线 | 手段 | 风险 | 兜底 |
|------|------|------|------|
| **能力**（少猜、少失败、少劣化） | 可见上下文、生成策略、错误分类、工具 hygiene | 上下文变厚 → 更慢更贵 | §4 延迟预算 |
| **性能**（跟手、可打断） | 快超时、prompt cache、只读并行、assemble 复用 | 为省时牺牲正确性 | 每期 golden + 延迟门禁 |

---

## 1. Harness 是什么、不是什么

广义 Agent Harness = 下列**六面**的策略厚度与可观测；**不是**换模型，也不是加 workflow 节点。

| 面 | 是 | 细则文档 |
|----|----|----------|
| **Intake** | 确定性输入编译与门控；`@path` 预读（预算内） | `05`、ADR-014 |
| **Context** | `ContextEnvelope`、compact、assemble 复用、热文件指针 | `06` §6 |
| **Tools** | ToolScope、审批、超时；只读 `tool_calls` 并行；description hygiene | `06` |
| **Model** | 配置注入、生成策略、重试/错误分类、prompt cache、usage | 本文 Model 子轨、ADR-019 |
| **Guard** | Cancel 贯串 backoff/assemble/预读；model/tool/step 超时；stall watchdog | ADR-015、ADR-016 |
| **Proof** | Golden / 延迟门禁；`retry_count`、cache、`assemble_ms` 等可观测字段 | `11`、`12` |

| 不是 |
|------|
| 改写 `AgentEngine` 的 while / 终止条件（只读工具并发是**执行层**并发） |
| 13 节点 / 意图分类 / 强制 retrieval·verify pipeline |
| 在 `AgentEngine` / `ToolExecutor` 内 `if scenario == …` 塞策略 |
| 每个 scenario 复制一套 gateway |
| 把业务编排塞回 LangGraph（ADR-005：机制层单节点） |
| K8s / MCP / 多租户模型市场 |

```text
TurnController
  → Intake（InputCompiler / shouldQuery）     ← Intake 面
  → ContextEngine.assemble → ContextEnvelope ← Context 面（assemble_ms）
  → Model：GenerationParams + Gateway.stream ← Model 面（首 token / retry）
  → Tools：串行写 | 并行只读                 ← Tools 面
  → Guard：abort / timeout / watchdog        ← Guard 面
  → Proof：events + golden + SLO             ← Proof 面
AgentEngine while 语义冻结（ADR-005）
```

**原则**：新能力进 Profile / Intake / ContextEngine / ModelGateway / 工具执行层；**冻结** while；热路径新增工作必须归入 §4 并可度量。

---

## 2. 六面成熟度（代码事实，2026-07）

| 面 | 已有 | 缺口 | 分期 |
|----|------|------|------|
| **Model** | Provider + factory；ADR-019；**AH1** 重试/策略；**AH2** `cache_control` + usage cache 字段 | **WT5 稳定/易变分家**（写作组装仍易整段 miss）；多 provider failover（延后） | AH1–AH2 ✅；WT5 ⏸ |
| **Context** | compact；**AH3a** project/runtime + `assemble_ms`；**session transcript**（≥80/90/95% 才 collapse/snip/autocompact） | 压缩**质量**（到点折干净）；对齐「变短≈压缩」体感 | AH3a ✅；§5.1.2 |
| **Intake** | InputCompiler；**AH3b** `@path` 预算预读 | — | AH3b ✅ |
| **Tools** | 审批、超时；**AH3c** 只读并行 | description 持续 hygiene | AH3c ✅ |
| **Guard** | ADR-015/016；AH1 Cancel 打断 backoff；预读/assemble 可中止钩子 | — | 持续 |
| **Proof** | Golden + SLO；**AH-obs** `retry_count` / cache / `assemble_ms` 进事件契约 | 默认盯 assemble/TTFB/usage；UI 可后置 | AH-obs ✅；§5.1.3 |

结论：**不要用加节点/加 router 补洞**。用 harness 各面策略层补；**先 cache 布局（WT5）→ 压缩到点质量 → Proof 延迟盯梢**（§5.1），避免性能倒退与「无压缩暗削窗」。

---

## 3. 对照：旧项目 vs 成熟 agent

| 维度 | agent-langraph | 本平台现状 | Cursor / Claude Code 类 | 本文取向 |
|------|----------------|------------|-------------------------|----------|
| 编排 | 13 节点 workflow | 单 loop + 工具 | 单 loop + 工具 | **保持**，不回头 |
| 强制检索/验证阶段 | 有 | 无（工具可选） | 无 | **保持** |
| 调用可靠性 | 混在节点里 | **AH1 厚网关** | 厚：重试、分类、快超时 | **AH1 已对齐** |
| 交互速率 | 整链空跑、串行 | 有流式，待 cache / 只读并行 | cache、只读并行、快超时 | **AH2/AH3** |
| 模型看见什么 | 大 AgentState / 强制包 | compact 强、envelope 未齐 | 项目针脚、@ 预读 | **AH3** |
| 成本 | 常整链空跑 | 摘要占主模型 | cache + 小模型摘要 | **AH2/AH4** |
| 可证明 | 弱 | golden + SLO | eval 门禁 | **Proof 面加厚** |

成熟度定级：**设计正确的早期平台**。目标是把「偶发失败 / 乱选工具 / 长会话劣化 / 不跟手」压到可自用，而不是功能清单追平 IDE 内嵌 agent。

---

## 4. 延迟预算与热路径纪律（一等约束）

> 任何 AH 期改动**先过这里**，否则不合并。

### 4.1 继承 SLO（权威定义见 [`11` §1](10-product-experience.md)）

| 指标 | 目标（P95） | 本文相关杠杆 |
|------|-------------|--------------|
| TTFB（`turn.accepted`） | ≤ 300ms | 重试/assemble 不得挡在受理反馈之前 |
| 首模型 token | ≤ 800ms | 快超时、prompt cache、assemble 复用 |
| 流式 Cancel | ≤ 500ms | **Cancel 必须打断 backoff sleep、assemble、预读** |
| 长会话 | 50 Turn 后无线性恶化 | cache、collapse、token 估计不炸 |

### 4.2 热路径成本清单

| 成本项 | 来自 | 度量 | 约束 |
|--------|------|------|------|
| `assemble_ms` | AH3 project/runtime 注入、预读 | `context.reported` | 软上限；预读超时降级为纯指针 |
| 输入 token 增量 | AH3 上下文加厚 | `context.reported` 分区 | 硬上限；优先 AH2 cache 抵消 |
| 重试墙钟 | AH1 backoff | 日志 + `usage.reported.retry_count` | ≤ `model_timeout_seconds` |
| tokenizer CPU | AH4 估计升级 | 采样计时 | 估高优于估低；禁止每步重 tokenizer |
| compact 额外调用 | AH4 summarizer | `usage.reported` | 独立 timeout/budget |

### 4.3 铁律

1. **受理优先**：`turn.accepted` 在任何重试/assemble 之前发出。
2. **快失败**：首次尝试较短 connect/首字节超时。
3. **可打断压倒可靠**：Cancel 打断 backoff、assemble、预读（ADR-015）。
4. **加厚必先能抵消**：显著增大输入 → 命中 cache，或硬上限 + 降级。
5. **可测才算数**：性能改动挂 [`12`](11-eval-and-golden-turns.md) 延迟门禁。
6. **策略不进引擎分叉**：不在 `AgentEngine` / `ToolExecutor` 写 `if scenario`。

---

## 5. 目标形态

```text
┌─────────────────────────────────────────────────────────┐
│ TurnController                                          │
│   turn.accepted 先发（保 TTFB）                          │
│   ModelConfig + ScenarioProfile + Intake                 │
├─────────────────────────────────────────────────────────┤
│ ContextEngine  →  ContextEnvelope                       │
│   system_blocks · project_context · runtime_context     │
│   message_window · included_tools · budget_report       │
│   assemble 跨 Step 复用；预读可降级                      │
├─────────────────────────────────────────────────────────┤
│ Model（GenerationParams + Gateway）                     │
│   retry / 快超时 / cache_control / usage（含 retry）     │
├─────────────────────────────────────────────────────────┤
│ Tools：只读并行 · 写/exec 串行 · 审批                   │
└─────────────────────────────────────────────────────────┘
```

与 [`06` §6.1](06-tools-and-context.md) 对齐：`ContextEnvelope` 为 assemble 权威输出；`system_blocks` **不**回写 `TurnState.messages`。

### 5.1 下一刀优化思路（2026-07-21）

> 三条线**分开推进**，都服从 [`13`](13-rate-redlines.md) R1–R5；**不改** `AgentEngine` while / 发送路径 / Plan 同意门。  
> **不混入**：写作去 AI 腔 → writing [`system.md` Prose defaults](../services/runtime/app/scenarios/writing/system.md) / [`14`](14-writing-quality.md)；资料库 RAG → [`15`](15-rag-and-sources.md)（下一刀 RQ1 见 [`15` §9](15-rag-and-sources.md)）。

排期建议：`① cache 布局 WT5` → `② 变短≈压缩` → `③ Proof 延迟盯梢`。

#### 5.1.1 Cache 布局（WT5 · Model × writing 组装）

**问题：** 写作常把 `system.md` + cards + work index + focus/prev **焊成一整段 system** 再打 `cache_control`。换章/换话 → **整段 miss**，稳定正文陪葬。仪表盘命中率 ~10–15% 多半正常（messages / tool_results 本就不会进稳定前缀）。细则权威：[`24` §4.6](24-writing-token-economy.md)。

**思路：只改位置，不删内容。**

| 层 | 放什么 | cache |
|----|--------|--------|
| **稳定前缀** | `system.md`（含 Prose defaults）+ tools 定义 | 打标；跨 Turn 尽量命中 |
| **易变后置** | cards / work index / focus+prev | **照样送给模型**；挂 runtime 或靠后 user，不焊进稳定块 |

| 做 | 不做 |
|----|------|
| KPI = **cache miss / 总 input 绝对量** | 以命中率 % 为唯一目标 |
| 先靠 WT1–WT4 缩小 miss 分母 | 为刷命中丢掉 focus / cards |
| 同内容重组 + provider 打标 | 更勤 collapse 专为 cache；每步同步 LLM 摘要 |

**落地：** `prepare_writing_system_prompt` / assemble 分块；稳定段末 `cache_control`。验收：同任务「写一章」miss/总 input 下降；TTFB/首 token/质量不回归。状态：**设计 ✅ · 实现 ⏸**。

#### 5.1.2 变短 ≈ 压缩（Context）

**产品体感（对齐 Cursor / Claude Code 自用观察）：** 平时上下文**一路涨或持平**；**明显变短**应对得上自动压缩链或用户 `/compact`。单条进窗 `budget` 截断是「这条没那么肥」，不是整段对话暗中变短。机制教学见 [`20`](20-context-compaction-walkthrough.md)。

**思路：加厚到点压缩质量，不日常暗削。**

| 做 | 不做 |
|----|------|
| 满闸 collapse / snip / autocompact 时，旧大块 tool 折干净（path + 可重读） | **无压缩事件**却整窗 40K→30K（曾议「提前 pointerize」——**否决为默认**） |
| `/compact` 写作书签保住「写到哪」（WT2） | 每轮同步 LLM 摘要（R2） |
| Usage / `compaction_trace` 可读 | 调阈值刷分区 % 好看 |

**读表：** 压缩前 `tool_results` / `assistant` 偏高多为正常作业面。成功 = **压缩触发后**仍能续写，且 input 绝对量下来。

**落地优先级：** ① 现链 + 观测可读 → ② 仅当已有 compact 轨迹时强化冷 tool 折叠 → ③ 写作按章装载（少灌窗 ≠ 暗收窗）。

#### 5.1.3 Proof · 延迟盯梢

**已有：** SLO（[`10` §1](10-product-experience.md)）TTFB≤300ms / 首 token / Cancel≤500ms；事件 `context.reported`（`assemble_ms`）、`usage.reported`（retry/cache）；golden `latency.*`（[`11`](11-eval-and-golden-turns.md)）。

**思路：把「能测」变成「默认盯着」，不加裁判模型。**

| 层 | 做什么 |
|----|--------|
| **契约** | 事件继续带齐 assemble / usage / cache；UI 面板可后置 |
| **Golden** | stub 路径保住 TTFB / cancel 断言；勿用 live 抖动当 PR 硬闸 |
| **对照** | WT5 / 压缩改动前后：同剧本 `assemble_ms`、首 token、input 绝对量 |
| **语义** | 分清受理慢（TTFB）vs 模型慢（首 token）vs 组窗贵（assemble） |

| 做 | 不做 |
|----|------|
| 改动挂延迟相关断言或抽样对照（R5） | 每轮同步 LLM「证明延迟」 |
| `make runtime-test` + 相关 golden | 指望 `make eval-all` 单独覆盖全部延迟/RAG/Plan 建议（见 eval 分层） |

**说明：** `eval-all` = stub Golden Turn 行为回归；Harness 单测 → `runtime-test`；RAG 真效果 → `eval-retrieval` / `retrieval-bench*`；Plan 建议 → `eval-plan-suggest`。Proof 加厚 = 盯对命令与字段，不是一条 makefile 万能。

---

## 6. 分期（AH1 → AH4 + AH-obs）

> 排序：先稳（AH1）→ 先便宜且更快（AH2 cache）→ 再加厚（AH3）→ 成本精修（AH4）。**AH-obs 自 AH2 起穿插**。缓存先于加厚。

### AH1 — Model：调用可靠性 + 快失败 + 生成策略 ✅

见文首落地摘要。验收：`tests/test_gateway_retry.py`；失败路径终态 ≠ completed。

### AH2 — Model：Prompt Cache

1. 稳定前缀（system + 工具定义）打 Anthropic `cache_control` / 兼容 OpenAI-compat  
2. assemble 保证可缓存前缀跨 Step/Turn **字节稳定**（易变内容后置）— **写作侧完整分家 = WT5（§5.1.1 / `24` §4.6），实现⏸**  
3. **AH-obs**：`usage.reported` 含 cache 读写 token / hit 指示  

**主改**：providers、`context/engine.py`；WT5 另动 writing 组装。  
**验收**：cache 字段可观测；长会话首 token 门禁不回归；WT5 以 miss/总 input 绝对量为准。

### AH3 — Context × Intake × Tools

**AH3a** ContextEnvelope 最小集 + assemble 复用（`project_context` / `runtime_context`；`assemble_ms`）  
**AH3b** `@path` 预读 + Session 热文件指针（超时降级）  
**AH3c** 只读 `tool_calls` 并行；工具 description hygiene  

**验收**：分区与 `assemble_ms`；只读并行时序用例；writing/agent 预读或 project 注入；延迟门禁不回归。

### AH4 — 成本精修

1. Autocompact 独立小模型 + 独立 timeout；失败回退确定性摘要  
2. Token 估计升级（估高、便宜）  

### AH-obs — 可观测（穿插）

| 字段 | 事件 | 自何时 |
|------|------|--------|
| `retry_count` | `usage.reported` | AH2（也可回填 AH1） |
| cache 命中相关 | `usage.reported` | AH2 |
| `assemble_ms` + 分区 | `context.reported` | AH3a |

UI 面板可后置；**事件契约先落地**。

### 延后（原 H5）

多 provider failover、`ModelGatewayRegistry` + `pg_notify`、动态裁剪工具表、JSON mode。

---

## 7. 明确不做

1. 重写或分叉 `AgentEngine` loop  
2. 恢复意图分类图、强制 retrieval/verify 节点  
3. 引擎内 `if scenario` 塞 harness 策略  
4. 每 scenario 复制 gateway  
5. 业务编排塞回 LangGraph  
6. 为省延迟牺牲正确性（流后重放、跳过审批、静默截断未标记）  
7. 未落地前宣称「已完全对齐」  
8. 无压缩事件时悄悄整窗变短（「压缩外收窗」）— 见 §5.1.2  
9. 以 prompt cache 命中率 % 或 Usage 单分区 % 为唯一优化目标 — 见 §5.1.1 / §5.1.2

---

## 8. 文档与实现纪律

| 规则 | 说明 |
|------|------|
| 总纲 vs 专文 | 本文只定六面、分期、预算；loop/工具/契约细节在 `05`/`06`/`11`/`12` |
| 每期可证明 | 单测 + golden；性能挂延迟门禁 |
| 状态回写 | 合并后更新本文状态与 `docs/README` |
| ADR | 不可逆约束再抽 ADR-020 |
| 与 `06` | Envelope 字段以 `06` §6.1 为契约；本文定优先级与预算 |

---

## 9. 建议落地顺序

| 顺序 | 主题 | 主路径 | 主线 |
|------|------|--------|------|
| AH0 | 本文升格 + 索引交叉引用 | `docs/*` | 口径 |
| AH1 ✅ | Gateway 重试 + 生成策略 | `model/*` | Model |
| AH2 | Prompt cache + usage cache/retry 字段 | providers, context | Model + Proof |
| AH3a–c | Envelope / 预读 / 只读并行 | context, input_compiler, agent_engine | Context/Intake/Tools |
| **下一刀** | **§5.1** WT5 → 变短≈压缩 → Proof 延迟 | writing 组装 / context / golden·观测 | Model+Context+Proof |
| AH4 | summarizer + token 估计 | compact_summarizer, context | 成本 |

验证：`make runtime-test` · 相关 `make eval-*`（勿把 `eval-all` 当全能闸）· `context.reported` / `usage.reported` · [`10`](10-product-experience.md) / [`11`](11-eval-and-golden-turns.md) 延迟门禁。

---

## 10. 成功标准（产品语言）

**能力**

1. 供应商短暂抖动时少无意义 Turn 失败（AH1）  
2. 改稿/引用更少「该读却空转」（AH3）  
3. 事件能区分「模型挂了」与「交付失败」（AH1 + AH-obs）

**性能**

4. 抖动不拖满超时；首 token 稳定在 `11` §1（AH1+AH2）  
5. 长会话延迟/费用不线性炸裂（AH2+AH3+AH4）  
6. agent 多步只读墙钟下降（AH3c）  
7. Cancel 在 backoff/assemble/预读中 ≤500ms（§4）

**可证明**

8. `retry_count` / cache / `assemble_ms` 可在事件中核对（AH-obs）  
9. 窗变短可归因于压缩（或单条 budget）；无「无压缩暗削」（§5.1.2）  
10. WT5 后同任务 miss/总 input 绝对量可降，不以命中率 % 冒充成功（§5.1.1）

北极星服从 [`11`](10-product-experience.md)：愿意连续自用数周，不因模型层不可预期或不跟手而弃用。
