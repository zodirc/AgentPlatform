# 12 — Agent Harness（成熟度总纲）

> **状态**：部分落地（2026-07-13）— **AH1 ✅**；**AH2–AH4 / AH-obs 已落地核心路径**（prompt cache 打标、envelope project/runtime、@path 预读、只读并行、compact 独立超时、usage/context 可观测字段）。细调与 golden 加固可继续。  
> **范围**：**广义 Agent Harness**——包住 frontier model、决定「好不好用」的整层工程：Intake · Context · Tools 执行纪律 · Model · Cancel/超时/watchdog · Eval/SLO 与可观测。  
> **不在范围**：改写 `AgentEngine` while 语义；恢复固定 pipeline；K8s / MCP / 多租户模型市场。

关联：[`05-agent-runtime.md`](05-agent-runtime.md)（loop 细则）· [`06-tools-and-context.md`](06-tools-and-context.md)（工具与 Context 契约）· [ADR-014](adr/014-turn-intake-deterministic.md)（Intake）· [ADR-015](adr/015-interrupt-cancel-resume.md)（Cancel）· [ADR-016](adr/016-execution-timeouts-and-stall-watchdog.md)（超时/watchdog）· [ADR-019](adr/019-model-provider-runtime-config.md)（供应商配置）· [`10-product-experience.md`](10-product-experience.md)（体验 SLO）· [`11-eval-and-golden-turns.md`](11-eval-and-golden-turns.md)（延迟门禁）。

> **命名说明**：早期文稿称「Model Harness」，仅覆盖模型调用外围。本文升格为 **Agent Harness 总纲**；原 Model 面仍是子轨之一（AH1–AH2、AH4 部分）。细则不合并进本文——`05`/`06`/`11`/`12` 仍是各面权威。

各期合并后更新本文「状态」与 `docs/README`；若引入不可逆契约（重试语义、cache 前缀、envelope 字段），再抽 **ADR-020**，否则扩写既有 ADR / 专文。

**AH1 落地摘要（Model 子轨）**：`ModelGateway` 统一重试（仅尚未吐 token）+ 首字节快超时 + Cancel 可打断 backoff；`ModelTransientError` / `ModelFatalError` / `ModelProviderTimeout`；`GenerationParams`（`max_output_tokens` 对齐 `output_reserve_tokens`、scenario temperature、`tool_choice`、thinking 默认关）。见 `model/gateway.py`、`model/generation.py`、providers、`tests/test_gateway_retry.py`。

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
| **Model** | Provider + factory；ADR-019；**AH1** 重试/策略；**AH2** `cache_control` + usage cache 字段 | 多 provider failover（延后） | AH1–AH2 ✅ |
| **Context** | compact；**AH3a** project/runtime + `assemble_ms`；**session transcript** 滚动历史（≥80/90/95% 才 collapse/snip/autocompact） | 更细 session 指针产品化 | AH3a ✅ |
| **Intake** | InputCompiler；**AH3b** `@path` 预算预读 | — | AH3b ✅ |
| **Tools** | 审批、超时；**AH3c** 只读并行 | description 持续 hygiene | AH3c ✅ |
| **Guard** | ADR-015/016；AH1 Cancel 打断 backoff；预读/assemble 可中止钩子 | — | 持续 |
| **Proof** | Golden + SLO；**AH-obs** `retry_count` / cache / `assemble_ms` 进事件契约 | UI 面板后置 | AH-obs ✅ |

结论：**不要用加节点/加 router 补洞**。用 harness 各面策略层补；**先 cache（AH2）再加厚上下文（AH3）**，避免性能倒退窗口。

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

---

## 6. 分期（AH1 → AH4 + AH-obs）

> 排序：先稳（AH1）→ 先便宜且更快（AH2 cache）→ 再加厚（AH3）→ 成本精修（AH4）。**AH-obs 自 AH2 起穿插**。缓存先于加厚。

### AH1 — Model：调用可靠性 + 快失败 + 生成策略 ✅

见文首落地摘要。验收：`tests/test_gateway_retry.py`；失败路径终态 ≠ completed。

### AH2 — Model：Prompt Cache

1. 稳定前缀（system + 工具定义 + pinned 卡）打 Anthropic `cache_control` / 兼容 OpenAI-compat  
2. assemble 保证可缓存前缀跨 Step/Turn **字节稳定**（易变内容后置）  
3. **AH-obs**：`usage.reported` 含 cache 读写 token / hit 指示  

**主改**：providers、`context/engine.py`。  
**验收**：cache 字段可观测；长会话首 token 门禁不回归。

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
| AH4 | summarizer + token 估计 | compact_summarizer, context | 成本 |

验证：`make runtime-test` · 相关 `make eval-*` · `context.reported` / `usage.reported` · `12` 延迟门禁。

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

北极星服从 [`11`](10-product-experience.md)：愿意连续自用数周，不因模型层不可预期或不跟手而弃用。
