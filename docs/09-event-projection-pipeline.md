# 09 — 事件、投影与 SSE 流水线

> 事件类型与 envelope 见 **[`contracts.md`](contracts.md)**。行为细节见本文。

## 1. 总览（Phase 0–2 权威路径）

采用 **事件表拉取（Pull）模型**，不用 runtime → api 内存推送。

```text
runtime AgentEngine / TurnController
    │ append-only INSERT turn_events
    │ NOTIFY turn_events_channel (payload: turn_id)
    v
PostgreSQL turn_events
    │ api: LISTEN turn_events_channel（主触发）
    │      + 300ms 轮询兜底（NOTIFY 丢失 / 连接断开）
    v
api GET /turns/{id}/stream  (SSE 至客户端)
    │
    │ 同进程 asyncio.Queue（由 LISTEN/轮询投递）
    v
api projection 模块 → UPSERT turn_views；终态 → 异步更新 sessions.context_summary
    v
web 消费 SSE（进行中）+ GET /view（重连/终态）
```

**Phase 0 默认触发机制**（以此为准，不另起规则）：

1. `turn_events` 表上 `AFTER INSERT` trigger → `pg_notify('turn_events_channel', turn_id::text)`。
2. api 进程启动时 `LISTEN turn_events_channel`；收到通知后将 `turn_id` 投入 `asyncio.Queue`。
3. SSE 长连接与 projection 消费者**共用**该 Queue（或各投一份），避免双套轮询逻辑。
4. 每连接 SSE 在 Queue 空闲时以 **300ms** 轮询 `turn_events` 作为兜底（与 §4.2 一致）。
5. runtime **不**调用 api HTTP 推送事件；跨服务边界仅经 PostgreSQL。

**禁止**：

- runtime 直接向浏览器暴露 SSE
- 仅靠内存 channel 作为事件唯一来源
- api 在执行路径中同步做重 projection 计算

## 2. 职责分界

| 组件 | 负责 | 不负责 |
|------|------|--------|
| **runtime** | 产生事实事件；写 `turn_events`、`runs`/`turns` 执行态、artifacts | 客户端 SSE；`turn_views` 计算 |
| **api realtime** | 读 `turn_events`；维护 SSE 连接；`since_sequence` 回放 | 执行 loop；写事件 |
| **api projection** | 消费事件增量更新 views；终态触发 `context_summary`；domain 对账 | 阻塞 Turn 主路径 |
| **web** | 渲染 SSE + view；不推断阶段 | 读 runtime 内部状态 |

### 2.1 修正：TurnController 与 SSE

`TurnController` **写入** `turn_events`，**不**向客户端串 SSE。  
对外 SSE 唯一入口：`api` 的 `services/realtime/`。

## 3. 事件写入规则

1. 每条事件在业务事实发生后**立即** INSERT（与 Step 边界对齐）。
2. `sequence` 由 DB 分配（`BIGSERIAL`  per `stream_id`）或事务内 `MAX+1`，保证单 `turn_id` 严格递增。
3. `stream_id` Phase 0–2 固定等于 `turn_id`。
4. 事件 payload 控制体积：大内容放 `artifacts`，事件只带引用与摘要。

### 3.1 Phase 0 最小事件子集

实现 stub 时至少产出：

`turn.accepted` → `step.started` → `tool.started` → `tool.completed` → `turn.completed`
（无真实工具时可合成 `tool.*` stub；但字段与时序必须兼容后续真实工具执行语义。）

说明：

- `step.completed` 从 Phase 1 起进入细粒度事件集合，Phase 0 最小链路不强制
- `turn.thinking`、`turn.token`、`tool.delta`、`approval.*`、`subagent.*` 同样按后续 Phase 逐步启用

## 4. SSE 消费（api）

### 4.1 连接

```http
GET /api/v1/turns/{turn_id}/stream
Accept: text/event-stream
Last-Event-ID: 12          # 可选，等价 since_sequence=12
```

### 4.2 回放算法

```text
1. 校验调用方对 turn 的访问权
2. since ← Last-Event-ID 或 query since_sequence 或 0
3. SELECT * FROM turn_events WHERE turn_id=? AND sequence>? ORDER BY sequence
4. 逐条写入 SSE data: {json}
5. 循环：每 300ms 或 LISTEN 通知后重复 3–4，直至 turn 终态且已发到最新 sequence
6. 发送可选 keep-alive 注释；终态后关闭或保持至客户端断开
```

### 4.3 重连兜底

| 情况 | 行为 |
|------|------|
| 缺口 sequence | `GET /turns/{id}/view` + 从 `last_event_sequence+1` 续流 |
| view 滞后 | 以 **事件** 为准更新本地缓存；view 用于列表与首屏 |
| turn 已终态 | 可仅拉 view，不必重连 SSE |

## 5. UI 以谁为准

| 场景 | 主数据源 | 辅助 |
|------|----------|------|
| 流式 token / tool 进度 | **SSE 事件** | — |
| 审批按钮展示 | SSE `approval.requested` | `GET /turns/{id}/view` |
| 对话列表、历史首屏 | **Projection** `TurnView` | 事件可后补 |
| 终态确认 | `turn.completed` 事件与 `TurnView.status` 一致 | 不一致以 **事件序列** 为准重建 view |

前端本地状态 = `projection 缓存` + `event cursor (sequence)`，**不**维护 Turn 阶段状态机。

## 6. Projection 流水线

### 6.0 触发与消费（Phase 0 权威）

见 §1 总览。实现落点：`services/api/app/services/realtime/`（LISTEN + SSE）与 `services/projection/`（Queue 消费者）。

```text
NOTIFY / 轮询
  → asyncio.Queue.put(turn_id)
  → 消费者 A: realtime 推送到已订阅的 SSE 连接
  → 消费者 B: projection 增量刷新 turn_views
  → 消费者 C（终态事件）: 排队更新 sessions.context_summary
```

规则：

- Queue 满 → 标记 `turn_id` 待补偿（§6.1.1），**不**阻塞 runtime。
- `sessions.context_summary` **仅**由 api 写；runtime 只读。路径见 [`07-domain-model.md`](07-domain-model.md) §5、§7。
- `session_views`（Phase 1+）与 `context_summary` 同源刷新，不另起写方。

### 6.1 增量刷新（Phase 0–1）

```text
turn_events INSERT（+ NOTIFY）
  → api LISTEN / 轮询 → asyncio.Queue
  → 按事件类型更新 turn_views 字段
  → 更新 last_event_sequence、updated_at
  → 终态事件：异步任务更新 sessions.context_summary
```

失败处理：记录 `projection_log`；**不**回滚 turn；由 api 进程内定时补偿任务按 `turn_id` 重算。

### 6.1.1 Phase 0 最小恢复机制

Phase 0 即要求最小可恢复投影链路，不等待 Phase 1 worker：

- `asyncio.Queue` 只负责低延迟触发，不是唯一恢复来源
- 若队列满、消费者报错、进程重启或 view 落后于事件序列，api 必须把该 `turn_id` 标记为待补偿
- api 进程内周期任务扫描 `turn_views.last_event_sequence < turn_events.max(sequence)` 的 turn，并按 `turn_id` 重放重算
- 补偿任务失败仅记录日志与重试计数，不影响 `turns` / `runs` 主状态
- 补偿范围包含 `turn_views` 滞后与 **domain 对账**（`turns`/`runs` 终态滞后于事件，见 `07` §7.1）
- Phase 1+ 若引入 `outbox_jobs` 或独立 worker，语义必须与该最小恢复机制保持一致，而不是另起一套规则

### 6.2 Outbox（Phase 1+）

```text
api 受理命令时可写 outbox_jobs { type: projection_refresh, turn_id }
worker 消费 → 重建 view
```

与 [ADR-010](adr/010-async-projection-layer.md) 一致。

### 6.3 最小 TurnView 字段

见 [`contracts.md`](contracts.md) §4（TurnView）；额外强制：

- `last_event_sequence` — 与 `turn_events` 对齐
- `status` — 与 `turns.status` 一致

## 7. 内部命令与事件的关系

| 命令（api → runtime） | 产生的事件 |
|----------------------|------------|
| `StartTurn` | `turn.accepted`, 随后 `step.*`, `tool.*`, `turn.completed/failed` |
| `CancelTurn` | `turn.cancelling`（可选）→ `turn.cancelled` |
| `ApproveToolCall` | `approval.resolved` → 继续 `tool.*` / `step.*` |
| `DenyToolCall` | `approval.resolved` → `tool.completed(denied)` |
| `PatchAccept` / `PatchReject`（对外命令） | `patch.applied` / `patch.rejected` |

`CancelTurn` 受理时 api 同时写 `runs.cancel_requested_at`（见 `07` §2.5、ADR-015）。  
命令 HTTP 202/200 仅表示**受理**；事实以 `turn_events` 为准。

## 8. 编排者表述（与 ADR-005 对齐）

- **模型**：在循环内决定调用哪些工具、何时结束文本输出。
- **平台**：决定何时 assemble 上下文、何时 interrupt、何时终止（max_steps、budget）、哪些工具可见。

文档中「模型编排工具」指前者；**平台护栏**由 ContextEngine、ToolRegistry、TurnController 强制执行，不视为违背 agentic loop。

## 9. 可观测交叉索引

| 排查目标 | 先看 | 再看 |
|----------|------|------|
| 客户端无流 | api access log | `turn_events` 是否有新 sequence |
| 有事件无 UI | projection_log | `turn_views.last_event_sequence` |
| 执行卡住 | runtime engine log、`stall_detected` 日志 | 最新 `step.started` 与 checkpoint；`turn_events` 最后 ts vs `stall_threshold`（ADR-016） |
| 审批无响应 | `approval.requested` 事件 | `ApproveToolCall` command log |

## 10. 契约文件

| 文件 | 内容 |
|------|------|
| `packages/contracts/schemas/ddl/phase0.sql` | Phase 0 表结构 |
| `packages/contracts/schemas/commands/*.json` | 内部命令体 |
| `packages/contracts/schemas/events/envelope.json` | 事件 envelope |
| `packages/contracts/schemas/events/types.json` | ADR-004 类型枚举 |
| `packages/contracts/schemas/events/payloads/*.json` | 按 type 的 payload（ADR-017） |
| `packages/contracts/schemas/projections/turn_view.json` | TurnView |
| `packages/contracts/openapi/public.yaml` | 含 `/turns/{id}/stream` |

索引：[`contracts.md`](contracts.md)。PR 变更须按 `packages/contracts/README.md` 同步规则更新。

## 11. 相关 ADR

- [ADR-004](adr/004-sse-turn-streaming.md) — SSE 与事件目录
- [ADR-009](adr/009-protocol-four-layers.md) — 四层协议
- [ADR-010](adr/010-async-projection-layer.md) — 异步投影
- [ADR-012](adr/012-event-pull-sse.md) — Pull 模型决策
- [ADR-015](adr/015-interrupt-cancel-resume.md) — Cancel / interrupt / resume
- [ADR-016](adr/016-execution-timeouts-and-stall-watchdog.md) — 超时与卡住检测
- [ADR-017](adr/017-contract-validation-and-event-payloads.md) — payload schema
