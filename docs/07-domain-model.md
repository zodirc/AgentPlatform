# 07 — 领域模型与状态机

> 本文闭合 **Session / Run / Turn / Step** 的语义、生命周期与持久化归属。  
> 与 [`05-agent-runtime.md`](05-agent-runtime.md)（循环内核）、[`09-event-projection-pipeline.md`](09-event-projection-pipeline.md)（事件与投影）配套阅读。

## 1. 对象关系（权威定义）

```text
Session (1)
  └── Turn (N)          一次用户输入的受理闭环
        └── Run (1)       该 Turn 的唯一执行实例（与 Turn 1:1）
              └── Step (M)  循环内「一轮模型推理 + 工具执行」
```

| 对象 | 定义 | 与上下级关系 |
|------|------|--------------|
| **Session** | 用户对话连续性容器；跨 Turn 的记忆、策略、工作区绑定 | 包含多个 Turn |
| **Turn** | 一次用户输入从受理到终态的业务闭环 | 归属一个 Session；**恰好对应一个 Run** |
| **Run** | 一次 agentic loop 执行实例；持有 checkpoint 与 execution state | 归属一个 Turn；由 `StartTurn` 创建 |
| **Step** | Run 内一步：assemble → model → tools → checkpoint | 仅存在于事件与日志，无独立资源 API |
| **Artifact** | Turn 产生的文件或结构化产物引用 | 归属 Turn（及 Session） |

**关键约束**：

1. **禁止**一个 Turn 对应多个并发 Run；重试/恢复仍用同一 `run_id`。
2. **禁止**跨 Turn 共享未结束的 Run；用户每条新消息创建新 Turn + 新 Run。
3. `Step` 不暴露为 REST 资源；通过 `step_index` 字段出现在事件与日志中。

## 2. 状态机

### 2.1 Session

```text
active ──(归档策略)──> archived
active ──(删除)──────> deleted (软删除)
```

### 2.2 Turn（业务终态）

```text
pending ──> running ──> completed
              │
              ├──> waiting_approval ──> running ──> ...
              ├──> failed
              └──> cancelled
```

| 状态 | 含义 |
|------|------|
| `pending` | api 已受理命令，尚未被 runtime 执行 |
| `running` | runtime 正在执行 Run |
| `waiting_approval` | Run 在 interrupt 点等待审批 |
| `completed` | 正常结束 |
| `failed` | 不可恢复错误或 `fatal_error` 终止 |
| `cancelled` | 用户或系统取消 |

### 2.3 Run（执行终态）

```text
accepted ──> running ──> succeeded
                │
                ├──> interrupted (waiting_approval)
                ├──> succeeded | max_steps | budget_exceeded  (均属正常可解释终止)
                ├──> failed
                └──> cancelled
```

`Run.status` 与 `Turn.status` 同步更新，但 Run 额外记录 **终止原因**（`termination_reason`），供审计与 debug。

### 2.4 Run ↔ Turn 状态映射（权威）

runtime 在**同一事务或紧邻步骤**内同步更新 `runs` 与 `turns`；`termination_reason` 仅写在 `runs`。

| Run.status | Run.termination_reason（若有） | Turn.status | 说明 |
|------------|-------------------------------|-------------|------|
| `accepted` | — | `pending` | api 已建 Turn/Run；runtime 尚未受理 |
| `running` | — | `running` | loop 执行中 |
| `interrupted` | — | `waiting_approval` | checkpoint interrupt；等待审批命令 |
| `succeeded` | `final` | `completed` | 模型无 `tool_use` 正常结束 |
| `succeeded` | `max_steps` | `completed` | 达步数上限；可解释截断，**非** `failed` |
| `succeeded` | `budget_exceeded` | `completed` | 达 token/时长预算；可解释截断 |
| `failed` | `fatal_error`（等） | `failed` | 不可恢复错误 |
| `cancelled` | `cancelled` / `user_requested` | `cancelled` | 用户或系统取消 |

规则：

1. `shouldQuery` 短路（`/help` 等）：Run 直接 `succeeded` + `termination_reason: local_response` → Turn `completed`。
2. 审批恢复：`ApproveToolCall` 后 Run 回到 `running`，Turn 回到 `running`（自 `waiting_approval`）。**无** `ResumeTurn` 命令（ADR-009、ADR-015）。
3. **Cancel 非 Resume**：`CancelTurn` 后 Run/Turn 终态 `cancelled`；用户继续对话须 **新建 Turn + Run**。跨 Turn 记忆靠 `sessions.context_summary`，不靠恢复已取消的 checkpoint。
4. 投影与 API 读到的 `TurnView.status` 须与 `turns.status` 一致；若与事件终态不一致，以 **事件序列** 重建（见 `09` §5）。

### 2.5 Cancel 传播（domain 标志）

api 受理 `CancelTurn` 时，除转发 `cancel-turn` 命令外，须 **写入** `runs.cancel_requested_at`（及 `cancel_force`）。runtime 在执行全过程轮询该标志（与内存 `TurnState.cancelled` 并行，取先生效者）。详见 [ADR-015](adr/015-interrupt-cancel-resume.md)。

## 3. 一次对话的时序（闭环）

```text
1. POST /api/v1/sessions/{session_id}/turns  { message, client_request_id? }
2. api: 鉴权 → INSERT turn (pending) → INSERT run (accepted) → 转发 StartTurn
3. runtime TurnController:
     a. 加载 session_context（压缩摘要，非全量历史 messages）
     b. 编译输入 → 初始化 TurnState.messages
     c. AgentEngine.run → 每 Step 写 checkpoint + append turn_events
4. runtime: 更新 turn/run 终态 → 写 artifact 引用 → append 终态事件（`turn.completed` 等）
5. api: 经 `LISTEN/NOTIFY` 或轮询感知新事件 → projection 刷新 `turn_views`；终态 Turn 触发异步更新 `sessions.context_summary`（见 §5、§7）
6. 客户端: SSE 收事件；终态后 GET /turns/{id}/view 与事件一致
```

第二条用户消息：重复 1–6，**新建** `turn_id` 与 `run_id`，Session 仅注入更新后的 `session_context`。

## 4. Execution / Domain / Projection 三层对照

| 概念 | Execution（runtime 内存 + checkpoint） | Domain（PostgreSQL） | Projection（供 UI） |
|------|--------------------------------------|----------------------|---------------------|
| 会话 | — | `sessions` | `session_views`（Phase 1+） |
| 回合 | `TurnState.messages`, step 元数据 | `turns`, `runs` | `turn_views` |
| 步骤 | checkpoint 内 step 指针 | `turn_events`（事实） | `tool_timeline` 等嵌入 `turn_views` |
| 产物 | 工具输出缓冲 | `artifacts` | `artifact` 列表于 view |

三层对照与写主权见本文 §4、§7；契约字段见 [`contracts.md`](contracts.md)。

## 5. messages 与上下文：如何统一理解

**原则**：循环内演进状态以 `TurnState.messages` 为主；**不等于**把所有上下文都历史化进 messages。

| 内容 | 存放 | 何时注入 |
|------|------|----------|
| 当前 Turn 用户输入、assistant/tool 往返 | `TurnState.messages` | Turn 内每 Step 追加 |
| 跨 Turn 会话摘要 | `sessions.context_summary` 或 `session_views` | TurnController 启动时注入**首条 system 或 user 前缀** |
| system prompt 模板 | 配置 / 模板文件 | 每 Step 由 ContextEngine 组装，不逐条写入 messages 历史 |
| project / runtime context | 运行时采集 | 每 Step assemble 时合并，见 [`06-tools-and-context.md`](06-tools-and-context.md) §12 |
| 治理后的最终窗口 | `ContextEnvelope`（内存） | 仅本轮调模型用，可选 trace 采样 |

**跨 Turn 策略**：

1. Turn 结束后，runtime **仅** append 终态事件（如 `turn.completed`）；**不**写 `sessions` 表。
2. api 异步模块（`services/projection/` 或 Phase 1+ `memory/` worker）消费终态事件，生成摘要并 **UPSERT** `sessions.context_summary`（摘要 + 指针）。写主权归属 api，与 §7 一致。
3. 新 Turn 启动时，runtime **只读** `sessions.context_summary`，注入 `TurnState.messages` 首块。
4. 新 Turn 的 `TurnState.messages` **初始仅含**：`[session_context 块] + [本 Turn 用户消息]`。
5. 需要回溯的细节通过 `read_file` / `search_codebase` 等工具按需取回，而非无限堆历史。

## 6. Checkpoint 归属

| 项 | 规则 |
|----|------|
| **归属** | 每个 Run 一份 checkpoint 链 |
| **存储** | LangGraph checkpoint 表 + 可选 blob；`run_id` 为主键关联 |
| **写入方** | 仅 `runtime` / `AgentEngine` 每 Step 结束 |
| **读取方** | 仅 `runtime`（恢复、审批 resume、取消后查询） |
| **api** | **不**读 checkpoint；只读 domain + projection + events |

审批 interrupt：checkpoint 保存完整 `TurnState` + `interrupt_payload`（含 `tool_call_id`、待审批参数）；`ApproveToolCall` 命令携带 `run_id` 与 `turn_id`，runtime 按 `run_id` 恢复。

## 7. 持久化表与写主权

| 表 | 主写方 | 主读方 | 说明 |
|----|--------|--------|------|
| `sessions` | api | api, runtime（只读） | 会话元数据、context_summary |
| `turns` | api 创建 pending；runtime 更新执行态 | api | 业务终态 |
| `runs` | api 创建；api 写 cancel 标志；runtime 更新执行态 | api, runtime | 执行实例、termination_reason、`cancel_requested_at` |
| `turn_events` | **runtime** | api（SSE/replay）、projection | 事实日志，append-only |
| `turn_views` 等 | api projection 模块 | api, web | 可重建 |
| `artifacts` | runtime | api | 元数据；内容在 `/data` |
| `checkpoints` | runtime | runtime | 机制层 |
| `model_provider_profiles` | **api**（加密写） | api（脱敏读）、**runtime**（解密读） | Phase 1；ADR-019；`StartTurn` 加载 |

跨服务**无分布式事务**；顺序为：先写 `turn_events`，再更新 turn/run 终态，api 投影最终一致。

### 7.1 终态不一致与对账

若 runtime 在 append 终态事件后、更新 `turns`/`runs` 前崩溃：

1. **事实以 `turn_events` 为准**（含 `turn.completed` / `turn.failed` / `turn.cancelled`）。
2. api **对账任务**（与 projection 补偿同周期或独立）扫描：`turn_events` 已有终态事件，但 `turns.status` 仍为 `running` → 按 §2.4 映射回填 `turns`/`runs`。
3. 对账**不**改写或删除已有事件；仅修复 domain 行滞后。

`session_context` 更新仅由 api 在观察到终态事件后触发，runtime 不参与。

## 8. API 资源与 Phase 0 最小面

```text
POST   /api/v1/sessions
GET    /api/v1/sessions/{id}
GET    /api/v1/sessions/{id}/view          # SessionView（Phase 1+）

POST   /api/v1/sessions/{id}/turns         # 创建 Turn + 触发 StartTurn
GET    /api/v1/turns/{id}
GET    /api/v1/turns/{id}/view
GET    /api/v1/turns/{id}/stream           # SSE

GET    /api/v1/runs/{id}                   # Phase 1+；调试/审计
```

Phase 1 对外命令（Cancel、审批、patch 确认）见 [`contracts.md`](contracts.md) §2.1。  
内部命令（api → runtime）见 [`contracts.md`](contracts.md) §8。

## 9. 幂等与重试

`POST .../turns` 请求体：

```json
{
  "message": "string",
  "scenario_id": "writing | agent",
  "client_request_id": "uuid"
}
```

- `scenario_id` 省略时使用 Session 的 `default_scenario_id`（默认 `writing`）
- API 可接受 `mode` 作为 `scenario_id` 的兼容别名
- 幂等**仅当**请求体提供 `client_request_id` 时生效：`(session_id, client_request_id)` 唯一；重复请求返回同一 `turn_id`（HTTP 200），**不**二次执行。
- 省略 `client_request_id` 时每次创建新 Turn（PostgreSQL 对 `NULL` 不做唯一冲突）；**客户端应始终生成 UUID**。
- `StartTurn` 内部命令携带相同 `client_request_id`，runtime 检测到已有 Run 则 no-op 或返回进行中状态。

## 10. 与旧 agent-langraph 的差异

| 旧语义 | 新语义 |
|--------|--------|
| Run 可能跨多次交互 | **Run 与 Turn 1:1** |
| AgentState 大对象 | `TurnState.messages` + 少量控制字段 |
| 图节点产出阶段事件 | Step 粒度 `turn_events` |
| 节点间 dict / str 阶段字段 | 边界 Pydantic + 事件 payload schema（ADR-017） |
| 无界等待 provider/tool | model / tool / Step 超时 + Stall Watchdog（ADR-016） |

## 11. 相关 ADR

- [ADR-002](adr/002-postgresql-primary-store.md) — 存储
- [ADR-005](adr/005-agentic-loop-over-pipeline.md) — 循环内核
- [ADR-009](adr/009-protocol-four-layers.md) — 四层协议
- [ADR-011](adr/011-domain-run-turn-1-1.md) — Run 与 Turn 1:1 决策
- [ADR-013](adr/013-dual-product-modes.md) — `scenario_id` 与 Profile
- [ADR-015](adr/015-interrupt-cancel-resume.md) — Cancel / interrupt / resume
- [ADR-016](adr/016-execution-timeouts-and-stall-watchdog.md) — 超时与卡住检测
- [ADR-017](adr/017-contract-validation-and-event-payloads.md) — 边界校验与 payload schema
- [ADR-019](adr/019-model-provider-runtime-config.md) — 模型供应商 DB 热配置
