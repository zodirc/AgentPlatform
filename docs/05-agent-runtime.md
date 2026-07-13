# 05 — Agent 运行时（核心循环）

> 本文定义 `runtime` 服务内部的核心执行模型：agent 如何思考、调工具、决定何时停止。
> 这是新项目相对 `agent-langraph` 最本质的改变。

## 0. 一句话总纲

> **agent 在受控循环内由模型编排工具**；平台护栏见 [`09-event-projection-pipeline.md`](09-event-projection-pipeline.md) §8。

`agent-langraph` 用一张 13 节点固定图把流程写死在代码里。我们放弃这种 workflow 形态，改用成熟编码 agent 共通采用的 **agentic loop**。这里的成熟参考对象是 Cursor、Claude Code、Copilot Agent 一类经过真实编码场景验证的系统，而不是继续延伸旧项目的大而全运行时。

## 1. 设计目标与反目标

### 1.1 设计目标

- 像成熟编码 agent 一样，在一个主 loop 内完成思考、调用工具、观察结果、继续行动
- 用最小必要状态驱动运行时，避免旧项目那种膨胀的 `AgentState`
- 支持长任务、长会话，但通过压缩、折叠、预算控制维持性能稳定
- 把能力增强集中在工具层，而不是把执行图越做越大
- 让 debug、重放、恢复、审批和错误定位成为架构内建能力

### 1.2 明确反目标

以下形态必须禁止回归：

- 回到 13 节点 pipeline 或任意固定阶段大图
- 为未来场景预埋多层 planner、router、dispatcher 常驻在主链路上
- 把工具、副作用、检索、投影、通知、评估都塞进单个大运行时
- 让一个 Step 里隐式做过多不可见工作，导致错误边界模糊
- 让长会话因为历史无限累积而性能持续恶化

## 2. 为什么不要固定 pipeline

| 固定 pipeline 旧 | agentic loop 新 |
|---|---|
| 人预先决定流程顺序 | 模型在循环中按需决定下一步 |
| 简单问题也跑完整链路 | 简单问题一轮即出，复杂问题自然多轮 |
| 每加一种场景就改图、加节点、加 router | 加能力等于注册一个工具，不动循环 |
| 多节点多 router 互相牵连 | 一个主循环加工具表 |
| 检索验证是强制阶段 | 检索验证是模型可选调用的工具 |

> 参考依据：Claude Code 的真实结构更接近 `QueryEngine` 加 `queryLoop` 的 while 循环。Anthropic《Building Effective Agents》也明确区分 workflow 与 agent，编码场景应优先选择后者。

## 3. 两层结构：Controller + Engine

借鉴成熟 agent 的分工方式，`runtime` 内部分两层。**不要**把它们重新拆回固定节点系统。

```text
┌──────────────────────────────────────────────────────────────┐
│ TurnController                                               │
│   · 接收 StartTurn 命令，加载恢复 Session 状态                │
│   · 按 scenario_id 加载 ScenarioProfile → 组装 ToolScope   │
│   · 输入编译：slash command、附件、文件引用 → 规范化消息        │
│   · 决定 shouldQuery：纯本地命令可直接返回                    │
│   · 写入 turn_events；更新 turn/run domain 终态              │
│   · Turn 结束后触发异步收尾（记忆、投影触发由 api 消费事件）   │
├──────────────────────────────────────────────────────────────┤
│ AgentEngine                                                  │
│   while true:                                                │
│     1. ContextEngine.assemble                                │
│     2. ModelGateway.stream                                   │
│     3. 解析 text thinking tool_use                           │
│     4. 无 tool_use → final                                   │
│     5. 有 tool_use → ToolExecutor 执行                       │
│     6. tool_result 回灌 messages → checkpoint → 下一轮       │
└──────────────────────────────────────────────────────────────┘
```

一句话总结：

> `TurnController` 负责 turn 启动前准备与结束后收尾（含加载 **ScenarioProfile**）；`AgentEngine` 负责推理循环，**不**感知 scenario 名称。

### 3.1 Turn Intake：输入编译与门控（非意图 Pipeline）

旧项目的 `event_classification_node` **不恢复**。任务理解拆为三层（[ADR-014](adr/014-turn-intake-over-intent-pipeline.md)）：

```text
用户输入
  → InputCompiler（确定性）
  → shouldQuery 门控（确定性）
  → [否] 本地响应 + turn.completed，结束
  → [是] AgentEngine：首轮 model 决定「直答 vs tool_use」
```

**产品模式（writing / agent）** 由 API `scenario_id` 指定，**不由 LLM 猜测**。

#### InputCompiler

将原始输入编译为规范 `Message`（`controller/input_compiler.py`）：

| 输入类型 | 处理 | 示例 |
|----------|------|------|
| 纯文本 | 原样进入 `user` content | `请改第二节` |
| Slash 命令 | 解析为结构化 intent（**非 LLM**） | `/help`、`/compact` |
| `@path` 引用 | 展开为文件指针块 + 可选预读摘要 | `@sections/02.md` |
| 附件 | 元数据 + `/data` 或 workspace 路径引用 | PDF、图片 |
| 选区上下文 | 编辑器传入 `selection` 块 | 写作模式改选中段 |

输出：`CompiledInput { messages: list[Message], metadata: dict }`。

#### shouldQuery 门控

以下情况 **不进入 AgentEngine**（零模型调用），直接写事件并结束：

| 条件 | 行为 | 事件 |
|------|------|------|
| 空消息 / 仅空白 | 400 或友好提示 | — |
| `/help`、`/version` | 返回静态帮助文本 | `turn.accepted` → `turn.completed` |
| `/compact`（若实现） | 触发 session 压缩任务，返回确认 | 同上 |
| 未配置 model key（dev） | 明确错误 | `turn.failed` |

实现为 **可测试的规则表** + 单元测试；禁止用 LLM 做此判断。

#### 快速首包

`StartTurn` 受理后 **立即** append `turn.accepted`（目标 TTFB ≤ 300ms，见 [`11-product-experience.md`](11-product-experience.md)）。  
旧 `acknowledge_node` 的职责在此，**不是**独立图节点。

#### 与「意图揣测」的分工

| 问题 | 谁负责 |
|------|--------|
| 写作还是 Agent 模式？ | 用户 / `scenario_id` |
| 是否值得调用模型？ | `shouldQuery` |
| 用户想改哪、要不要调工具？ | **首轮** `AgentEngine`（`tool_use` 或文本澄清） |
| 复杂多步规划？ | `update_plan`、`delegate` 工具（按需） |
验收：**[`12-eval-and-golden-turns.md`](12-eval-and-golden-turns.md) §5.2** 为能力融合阻断项（`06` §0.1）。

## 4. 核心状态：messages 即状态

这是理解整个系统最关键的一点，也是和旧 `AgentState` 最大的区别。

> **agent 的记忆、上下文、执行轨迹，主要编码在一个有序的 `messages` 序列里。**

```python
# 已实现：services/runtime/app/engine/state.py
@dataclass
class TurnState:
    turn_id: UUID
    session_id: UUID
    run_id: UUID
    trace_id: UUID
    scenario_id: str
    messages: list[dict[str, Any]]
    step_count: int = 0
    max_steps: int = 40
    usage: Usage = field(default_factory=Usage)
    cancelled: bool = False
    cancel_force: bool = False
```

```python
# Message 为 role + content blocks（TypedDict 或 dict）
MessageRole = Literal["user", "assistant", "tool"]
ContentBlock = dict[str, Any]  # text | tool_use | tool_result
```

规则：

- **消息序列是 Turn 内执行状态的主载体**（见 [`07-domain-model.md`](07-domain-model.md) §5）
- 跨 Turn 摘要、system 模板、runtime 采集层由 ContextEngine 每轮组装，不全部历史化进 messages
- LangGraph 在这里只承载 `loop + checkpoint + interrupt`，**不承载业务编排**
- 若未来裸 `while` 循环更可控，可以替换 LangGraph，但业务逻辑不应依赖框架特性

## 5. 运行时必须遵守的性能与复杂度约束

这是吸收旧项目教训后的强约束。

### 5.1 默认最短主路径

主路径只保留当前响应闭环真正需要的动作：

- 输入编译
- 上下文组装
- 模型调用
- 工具执行
- 终止判断
- 事件输出
- checkpoint 与最小持久化

以下内容不得阻塞主路径：

- 记忆写回
- 检索索引更新
- 评估采样
- 通知推送
- 历史全量补算
- 非必要统计聚合

### 5.2 默认最小状态集

除 `messages`、`step_count`、预算和取消位等少量控制字段外，禁止继续扩大运行时状态面。

尤其禁止：

- 把工具内部中间态长期塞进 `TurnState`
- 把 UI 结构直接塞进 execution state
- 为“也许以后用得上”的场景预留大量空字段

### 5.3 默认错误边界前置

错误越靠近输入和工具边界暴露越好。

必须优先在以下位置失败：

- command schema 校验
- tool schema 校验
- path sandbox 校验
- approval gate 校验
- provider 鉴权校验
- budget 上限校验

禁止把这些问题拖到 loop 深处才暴露。

### 5.4 默认长会话可压缩

长会话不是例外，而是编码 agent 的常态。运行时必须假设：

- 会读很多文件
- 会跑很多工具
- 会经历较长链路
- 会发生中断与恢复

所以 ContextEngine 的 budget、compact、collapse 不是优化项，而是生存机制。

### 5.5 长上下文编排是必须能力

长上下文编排不是可选增强，而是成熟 agent 的必须能力。

运行时必须支持：

- 在多轮执行中持续维护可工作的消息窗口
- 对历史进行预算控制、折叠、摘要和证据保留
- 区分当前任务强相关上下文与仅供回溯的弱相关上下文
- 在恢复、重连、追加任务和多 agent 协作时保持上下文可传递与可裁剪

长上下文编排的基本策略：

1. **热上下文**：当前几轮最相关消息、最近工具结果、当前约束，优先保留原文
2. **温上下文**：最近阶段性结论、文件摘要、验证结果，优先保留结构化摘要
3. **冷上下文**：久远历史、完整日志、大块输出，优先保留指针与可重读引用

规则：

- 任何大输出都不应长期停留在热上下文
- 子 agent 返回主循环时只能带回必要结论，不得把整个子会话倒灌回来
- 长上下文治理必须优先保证当前目标完成率，而不是机械追求保留更多历史

## 6. 一次 Turn 的完整时序

```text
1. api → runtime: POST /internal/commands/start-turn
2. TurnController:
   a. 加载 **ModelGateway 配置**（`model_provider_profiles` 激活行，或 env fallback；ADR-019）
   b. 加载 session_context + 恢复 run checkpoint（若 resume）
   c. InputCompiler 编译输入
   d. shouldQuery 否 → 写 turn.accepted + turn.completed，结束
   e. 写 turn.accepted（快速首包）
   f. 初始化 TurnState.messages；组装 system / runtime context
3. AgentEngine.run 进入 while true（**整轮 Turn 固定** §6 开头选定的 provider/model）
   ┌─ Step N ─────────────────────────────────────────────┐
   │ ContextEngine.assemble → 发 step.started             │
   │ ModelGateway.stream → 发 turn.thinking / turn.token（Phase 1+）│
   │ 解析 tool_use                                        │
   │ 若空 → 发 turn.completed，break                      │
   │ 否则 ToolExecutor.run → tool.started / tool.delta / tool.completed │
   │ append tool_result → 写 checkpoint                   │
   │ Phase 1+ 可补发 step.completed                       │
   └──────────────────────────────────────────────────────┘
4. TurnController: 落 transcript、更新最小 domain 状态
5. 异步收尾由 **api** 消费终态事件完成：更新 `sessions.context_summary`、projection 补算、评估采样（runtime 不直写 Session 行）
```

## 7. SSE 事件协议

loop 形态需要 Step 粒度的事件，而不是粗糙的阶段事件。**权威事件类型与 envelope** 见 [ADR-004](../adr/004-sse-turn-streaming.md)。

```jsonc
{
  "event_id": "uuid",
  "stream_id": "turn_uuid",
  "sequence": 12,
  "type": "step.started",
  "turn_id": "uuid",
  "run_id": "uuid",
  "step_index": 3,
  "trace_id": "uuid",
  "causation_id": null,
  "ts": "iso8601",
  "payload": {}
}
```

Phase 1 起逐步启用细粒度类型：`step.completed`、`turn.thinking`、`turn.token`、`tool.delta`、`approval.requested` 等（完整列表见 ADR-004）。Phase 0 最小链路不要求 `step.completed`。

规则：

- 事件必须足够细，方便 replay 和 debug
- 事件必须增量输出，禁止每步重复输出完整大快照
- 每个关键事件都应能与日志通过 `trace_id` 对齐
- 前端只消费事件和 projection，不本地推断执行事实

## 8. 终止与防失控

loop 最大的风险是停不下来、烧钱、反复失败。终止条件必须显式。  
**Cancel / interrupt / resume 权威语义**：[ADR-015](adr/015-interrupt-cancel-resume.md)。

| 终止原因 | 触发 | 行为 |
|---|---|---|
| `final` | 模型输出无 `tool_use` | 正常结束 |
| `max_steps` | `step_count >= max_steps` | 截断，提示继续或拆分 |
| `cancelled` | 用户或 api 发 `CancelTurn` | 见 §8.1；Run 终态，**无** ResumeTurn |
| `budget_exceeded` | token 或时长超配额 | 截断并记录审计 |
| `fatal_error` | 不可恢复错误 | 终止并告警 |

### 8.1 CancelTurn 与 abort 检查点

**禁止**仅在 Step 边界检查取消。runtime 必须在以下位置轮询 `TurnState.cancelled` 或 `runs.cancel_requested_at`（见 `07` §2.5）：

```text
1. ContextEngine.assemble 入口
2. ModelGateway.stream — 每 100–200ms 或每 N 个 token
3. ToolExecutor — 工具 handler 入口、流式输出循环、exec 子进程
4. delegate 子 AgentEngine — 与父 Run 共享 abort；父 cancel 级联子任务
5. Step 边界（兜底）
```

| `force` | 模型流式 | 工具执行 |
|---------|----------|----------|
| `false`（默认） | 下一检查点断开 provider 连接 | 优雅停（默认 500ms 超时） |
| `true` | 立即断连 | 立即 kill（`run_command` 用 process group） |

事件序列：`turn.cancelling`（可选）→ `turn.cancelled`（payload 含 `force`、`cancelled_at_phase`）。

**Cancel 后继续对话**：用户在同 Session 发 **新 Turn**；execution 上下文由 `context_summary` + 新用户消息衔接，**不是**恢复已 `cancelled` 的 Run。

**审批 interrupt 后继续**：仅 `ApproveToolCall` 从 checkpoint 恢复 **同一** `run_id`（`waiting_approval` → `running`）。

### 8.2 其他规则

- 长命令工具必须支持 cancel；`run_command` 必须可 kill 子进程
- 同类失败若连续发生，应触发更强约束而非无限重试

### 8.3 执行超时与卡住检测（ADR-016）

针对旧系统「单步挂起数百秒」，runtime 强制执行三层超时：

| 层级 | 默认 | 终止 |
|------|------|------|
| **Model 调用** | 120s | `turn.failed`，`termination_reason: model_timeout` |
| **工具** | `ToolSpec.timeout_s`（默认 60s） | `tool.completed(status=timeout)` |
| **Step 墙钟** | 300s（自 `step.started`） | `turn.failed`，`termination_reason: step_timeout` |

- Model 超时须断开 provider 连接。
- `CancelTurn` 与超时并行时，**cancel 优先**（终态 `cancelled`）。

**Stall Watchdog**（runtime 周期任务，默认 30s）：

```text
runs.status IN (running, interrupted)
  AND 最新 turn_events.ts 早于 now() - 120s
  → 日志 stall_detected + metric turn_stall_detected_total
  → Phase 1 默认仅告警；可配置 stall_auto_fail
```

默认值可在 `ScenarioProfile` / Settings 覆盖。Golden：`shared.07`（model timeout）。

## 9. Step 与 Run / Turn 的关系

权威定义见 [`07-domain-model.md`](07-domain-model.md)。摘要：

| 对象 | 职责 | 存储 |
|---|---|---|
| `Session` | 用户会话连续性 | PostgreSQL |
| `Turn` | 一次用户输入的受理闭环 | PostgreSQL |
| `Run` | **该 Turn 的唯一执行实例**（1:1） | PostgreSQL + checkpoint |
| `Step` | Run 内一轮模型推理加工具执行 | `turn_events` + checkpoint |
| `Artifact` | 产物元数据与内容引用 | `/data/artifacts` |

`Step` 让以下能力天然成立：

- 回放
- 审计
- token 成本定位
- 工具耗时定位
- 失败点定位

## 10. 子 Agent 委派

> **场景相关**：`agent_type` 白名单由 Turn 的 `scenario_id` 对应 Profile 限定，见 [`10-product-modes.md`](10-product-modes.md)。`delegate` 不得调用 Profile 外的角色。

复杂任务里，主 loop 可以派生隔离上下文的子 agent 处理子任务。

`delegate` 在工具协议中属于正式副作用类别 `delegate`，默认审批策略为 `always`，其预算、深度限制与事件审计要求以 [`06-tools-and-context.md`](06-tools-and-context.md) 的工具协议为准。

```python
class DelegateSubagentTool:
    name = "delegate"
```

规则：

- 子 agent 复用同一个 `AgentEngine`
- 只隔离消息窗口、工具集和预算
- 返回主循环的是摘要和关键产物引用，不是全部中间过程
- 子 agent 有自己的 `max_steps`
- 限制委派深度，默认不超过 `2`

这样做的目的不是增加炫技能力，而是避免主上下文爆炸，同时保持能力强度。

### 10.1 多 agent 协作

- 主 agent 可 `delegate(task, agent_type, context)`；`agent_type` 由 **ScenarioProfile** 限定
- **`writing`**：researcher、drafter、editor、fact_checker、stylist
- **`agent`**：explore、retrieve、verify、edit、planner
- 协作规则不变：只交换结论与引用；主编/主 loop 保留决策权；默认委派深度 ≤ 2

## 11. 日志与 debug 规范

为了让运行时真正可 debug，必须内建最小观测点。

### 11.1 必记日志点

- Turn 开始受理
- Step 开始与结束
- 模型请求开始与结束
- 工具开始、增量、结束
- 审批挂起与恢复
- 终止原因
- fatal error 边界

### 11.2 最小日志字段

| 日志类型 | 最小字段 |
|---|---|
| turn log | `trace_id`、`turn_id`、`session_id` |
| step log | `trace_id`、`turn_id`、`step_index`、`latency_ms` |
| model log | `trace_id`、`provider`、`model`、`token_usage`、`latency_ms` |
| tool log | `trace_id`、`tool_call_id`、`tool_name`、`status`、`latency_ms` |
| termination log | `trace_id`、`turn_id`、`reason` |

### 11.3 Debug 原则

- 先通过事件和日志定位在哪个 Step 失败
- 再判断是模型、工具、审批、上下文还是持久化问题
- 日志必须帮助缩小错误边界，而不是制造新的信息噪声

## 12. 从 agent-langraph 迁移

见 **[`appendix-migration.md`](appendix-migration.md)**（单一维护点）。

## 13. 目录落点

```text
services/runtime/app/
├── main.py
├── settings.py
├── controller/
│   ├── turn_controller.py
│   └── input_compiler.py
├── engine/
│   ├── loop.py
│   ├── state.py
│   ├── termination.py
│   └── subagent.py
├── scenarios/
│   ├── registry.py
│   └── profiles/           # writing.yaml, agent.yaml
├── tools/
│   └── core/               # 共享工具实现
├── model/
│   ├── gateway.py          # ModelGateway；配置自 model_provider_profiles（ADR-019）
│   └── provider_registry.py
├── graph/
└── ports/
```

## 14. 本文档对应的 ADR

- ADR-004：SSE 与事件类型目录
- ADR-005：采用 Agentic Loop 替代固定 pipeline
- ADR-006：能力以工具暴露
- ADR-007：子 agent 委派与上下文隔离
- ADR-008：上下文工程多层防线
- ADR-010：异步任务与投影层不阻塞主执行路径
- ADR-011：Run 与 Turn 1:1
- ADR-012：事件 Pull 与 api SSE
- ADR-013：Scenario 与 Profile 扩展
- ADR-014：Turn Intake 替代意图分类 Pipeline
- ADR-015：Interrupt / Cancel / Resume 语义
- ADR-016：执行超时与 Stall Watchdog
- ADR-019：模型供应商 Web 管理 + DB 热生效
- Agent Harness 成熟度总纲（AH1 已落地；Model/Context/Tools 子轨）：[`14-model-harness.md`](14-model-harness.md)
