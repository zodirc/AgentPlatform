# 契约索引（Contracts）

> **接缝文档单一入口**：领域字段、事件 envelope、最小 API、内部命令、DDL、schema 路径。  
> 行为细节见 [`07-domain-model.md`](07-domain-model.md)、[`08-event-projection-pipeline.md`](08-event-projection-pipeline.md)。  
> 机器真相来源：`packages/contracts/` 下 JSON/SQL/OpenAPI；本文与之保持同步。

## 1. 领域（摘要）

```text
Session (1) ── Turn (N) ── Run (1:1) ── Step*（仅事件）
```

| 字段 | 说明 |
|------|------|
| `Turn.scenario_id` | `writing` \| `agent` \| `interview`（`mode` 为兼容别名） |
| `Session.default_scenario_id` | 默认 `writing` |

全文：[`07-domain-model.md`](07-domain-model.md)

## 2. 对外 API（Phase 0 最小）

```text
POST   /api/v1/sessions
GET    /api/v1/sessions                # 我的会话列表（登录用户）
GET    /api/v1/sessions/{id}
DELETE /api/v1/sessions/{id}           # 硬删除本人会话（turns/events/transcript；不动 workspace）
POST   /api/v1/sessions/{id}/turns     # body: CreateTurnRequest
GET    /api/v1/turns/{id}
GET    /api/v1/turns/{id}/view
GET    /api/v1/turns/{id}/stream       # SSE
WS     /api/v1/turns/{id}/ws            # WebSocket（已实现，审批双向；SSE 仍为默认）
GET    /health/live
```

### CreateTurnRequest

```json
{
  "message": "string",
  "scenario_id": "writing",
  "client_request_id": "uuid",
  "plan_phase": "planning"
}
```

- `scenario_id` 省略 → Session.`default_scenario_id`
- `mode` 可作为 `scenario_id` 兼容别名
- `plan_phase` 可选：`planning`（硬只读 ToolScope）| `executing`（全工具 + status 纪律）；省略 = 普通 Agent（docs/25）
- 幂等：提供 `client_request_id` 时 `(session_id, client_request_id)` 唯一；省略则每次新建 Turn。见 [`07-domain-model.md`](07-domain-model.md) §9

OpenAPI：`packages/contracts/openapi/public.yaml`

## 2.2 管理面 API（Phase 1：模型供应商）

Phase 1 起交付；用于 Web 设置页，**无需重启 runtime** 即可切换供应商。权威语义：[ADR-019](adr/019-model-provider-runtime-config.md)。

前缀 `/api/v1/admin/model-providers`；须 admin 鉴权（`AUTH_ENABLED`）。

```text
GET    /api/v1/admin/model-providers              # 列表（api_key 脱敏）
POST   /api/v1/admin/model-providers              # 新增
PUT    /api/v1/admin/model-providers/{id}         # 更新（省略 api_key = 不轮换）
PUT    /api/v1/admin/model-providers/{id}/activate # 设为当前生效
DELETE /api/v1/admin/model-providers/{id}         # 删除（不可删唯一 active）
```

### CreateModelProviderRequest

```json
{
  "label": "Claude 日常",
  "provider": "anthropic",
  "model_name": "claude-sonnet-4-20250514",
  "api_key": "sk-...",
  "base_url": null,
  "activate": true
}
```

- `activate: true` 时同事务内置为唯一 `is_active` profile
- **禁止**在 `GET` 响应中返回完整 `api_key`；仅 `api_key_hint`（如后四位）

### ModelProviderProfile（响应摘要）

```json
{
  "id": "uuid",
  "label": "Claude 日常",
  "provider": "anthropic",
  "model_name": "claude-sonnet-4-20250514",
  "base_url": null,
  "is_active": true,
  "api_key_hint": "••••abcd",
  "config_version": 3,
  "updated_at": "iso8601"
}
```

规则：

1. **api** 加密写入 `api_key_ciphertext`；**runtime** 在 `StartTurn` 解密并构造 `ModelGateway`。
2. 配置变更在**下一 Turn** 生效；进行中的 Turn 不换 provider。
3. DB 无激活行时，runtime fallback 至 env `MODEL_*`（Bootstrap）。
4. **禁止** web → runtime 直连写密钥。

## 2.1 对外 API（Phase 1 命令）

Phase 0 可不实现；Phase 1 起与写作 diff、审批、取消体验一并交付。均为 **Command 层**：HTTP 202/200 仅表示受理，事实以 `turn_events` 为准。

```text
POST   /api/v1/turns/{id}/cancel              # CancelTurn
POST   /api/v1/turns/{id}/approve-tool-call # ApproveToolCall（含审批后 resume）
POST   /api/v1/turns/{id}/deny-tool-call    # DenyToolCall
POST   /api/v1/turns/{id}/patch/accept        # 写作：接受 propose_patch
POST   /api/v1/turns/{id}/patch/reject        # 写作：拒绝 propose_patch
```

> **无独立 `ResumeTurn`**：审批 interrupt 后的恢复由 `ApproveToolCall` 完成（见 [ADR-009](adr/009-protocol-four-layers.md)）。

### CancelTurnRequest

```json
{
  "reason": "user_requested",
  "force": false
}
```

- Query `?force=true` 与 body `force: true` 等价（**硬取消**）
- api 校验 Turn 归属与状态 → 写 `runs.cancel_requested_at`（及 `cancel_force`）→ 转发内部 `cancel-turn` → 产生 `turn.cancelling`（可选）→ `turn.cancelled`
- **语义权威**：[ADR-015](adr/015-interrupt-cancel-resume.md)

#### 软 / 硬取消

| | `force: false`（默认） | `force: true` |
|--|------------------------|---------------|
| 模型流式 | 下一 abort 检查点断 provider（目标 ≤500ms P95） | 立即断连 |
| 工具执行 | 优雅停（默认 500ms） | 立即 kill |
| Run 终态 | `cancelled`（**不可** ResumeTurn） | 同左 |
| 用户继续 | 同 Session **新发 Turn** | 同左 |

### ApproveToolCallRequest / DenyToolCallRequest

```json
{
  "tool_call_id": "string",
  "client_request_id": "uuid"
}
```

- `client_request_id` 可选；提供时对 `(turn_id, client_request_id)` 幂等
- api 转发内部 `approve-tool-call` / `deny-tool-call`
- `ApproveToolCall` 使 Run 自 `interrupted` 恢复为 `running`（Turn：`waiting_approval` → `running`）

### PatchDecisionRequest（写作场景）

```json
{
  "patch_id": "string",
  "client_request_id": "uuid"
}
```

- `accept` → api 转发 runtime 执行 `apply_patch`（或等效内部命令）→ `patch.applied`
- `reject` → 记录拒因 → `patch.rejected`；**不**修改工作区文件

## 3. 事件 envelope

```json
{
  "event_id": "uuid",
  "stream_id": "turn_uuid",
  "sequence": 1,
  "type": "step.started",
  "turn_id": "uuid",
  "run_id": "uuid",
  "step_index": 0,
  "trace_id": "uuid",
  "causation_id": null,
  "ts": "2025-07-01T00:00:00Z",
  "payload": {}
}
```

Schema：`packages/contracts/schemas/events/envelope.json`

### 3.1 事件 Payload（按 type）

每种 `type` 的 `payload` 须符合 `packages/contracts/schemas/events/payloads/{type}.json`；索引见 `payloads/_index.json`。  
决策：[ADR-017](adr/017-contract-validation-and-event-payloads.md)。

规则：

1. runtime **append 前**校验 payload；失败 → `turn.failed`（`schema_validation_error`）。
2. payload **不得**用自由字符串重复 `turns.status` / `runs.status`（避免双真相）。
3. 新增 type 须同时增 payload schema 并登记 `_index.json`。

Phase 1 最小 payload schema：`turn.accepted`、`turn.cancelling`、`turn.cancelled`、`turn.completed`、`turn.failed`、`step.started`、`tool.started`、`tool.completed`。

### Phase 0 最小 `type`

`turn.accepted` · `step.started` · `tool.started` · `tool.completed` · `turn.completed` · `turn.failed`

### Phase 1（流式、审批、写作 diff）

`turn.cancelling` · `step.completed` · `turn.thinking` · `turn.thinking.delta` · `turn.token` · `tool.delta` · `approval.requested` · `approval.resolved` · `turn.cancelled` · `patch.proposed` · `patch.applied` · `patch.rejected` · `outline.updated` · `section.draft.delta`

### Phase 2

`turn.plan` · `subagent.started` · `subagent.completed` · `retrieval.completed`

**完整目录**（含 Phase 标注）：[ADR-004](adr/004-sse-turn-streaming.md) · 机器枚举：`packages/contracts/schemas/events/types.json`

变更事件类型须同时改 ADR-004、`types.json` 与本节。

## 4. TurnView（投影最小）

```json
{
  "turn_id": "uuid",
  "session_id": "uuid",
  "scenario_id": "writing",
  "status": "pending | running | waiting_approval | completed | failed | cancelled",
  "user_input": "string",
  "latest_output": null,
  "tool_timeline": [],
  "artifacts": [],
  "last_event_sequence": 0,
  "updated_at": "iso8601",
  "cancellable": true,
  "cancel_requested_at": null,
  "interrupt": null
}
```

- `cancellable`：`status` 为 `pending` \| `running` 时为 `true`（projection 填充）
- `cancel_requested_at`：api 已受理 Cancel、runtime 尚未终态时非 null
- `interrupt`：仅 `waiting_approval` 时 `{ "kind": "approval", "tool_call_id": "..." }`

> **派生字段口径**：`cancellable`、`cancel_requested_at`、`interrupt` **不落 `turn_views` 列**，由 api 读时从 `turns.status` / `runs.cancel_requested_at` / checkpoint interrupt 派生填充。`turn_views` 表结构（[`packages/contracts/schemas/ddl/phase0.sql`](../packages/contracts/schemas/ddl/phase0.sql)）仅存可重建的投影主体字段。

Schema：`packages/contracts/schemas/projections/turn_view.json`

## 5. 数据流（谁写谁读）

| 表/流 | 写 | 读 |
|-------|----|----|
| `turn_events` | **runtime** | api SSE、projection |
| `turns` / `runs` | api 创建；runtime 更新执行态 | api |
| `turn_views` | api projection | web |
| `sessions.context_summary` | api（终态事件触发） | api, runtime（只读，transcript 空时兜底） |
| `session_transcripts` | **runtime** | runtime（跨 Turn 滚动 messages） |

全文：[`08-event-projection-pipeline.md`](08-event-projection-pipeline.md)

## 6. 错误响应

```json
{
  "data": null,
  "error": { "code": "TURN_NOT_FOUND", "message": "...", "details": {} },
  "meta": { "request_id": "uuid" }
}
```

Schema：`packages/contracts/schemas/errors.json`

## 7. 持久化（Phase 0 最小 DDL）

权威 SQL：`packages/contracts/schemas/ddl/phase0.sql`

| 表 | 关键字段 | 写主权 |
|----|----------|--------|
| `sessions` | `id`, `default_scenario_id`, `context_summary`, `status` | api |
| `turns` | `id`, `session_id`, `scenario_id`, `status`, `user_input`, `client_request_id` | api 创建；runtime 更新态 |
| `runs` | `id`, `turn_id` **UNIQUE**, `status`, `termination_reason`, `cancel_requested_at`, `cancel_force` | api 创建；api 写 cancel 标志；runtime 更新态 |
| `turn_events` | `event_id`, `turn_id`, `sequence`, `type`, `payload`… | **runtime** append-only |
| `turn_views` | `turn_id` PK, `last_event_sequence`, `tool_timeline`… | api projection |

约束：

- `UNIQUE (session_id, client_request_id)` on `turns`（幂等）
- `UNIQUE (turn_id, sequence)` on `turn_events`
- `runs.turn_id` 唯一 → Run : Turn = 1:1

`checkpoints`（LangGraph）、`artifacts` 元数据表、`session_transcripts`（跨 Turn 滚动 messages）Phase 1+ 追加；字段主权见 [`07-domain-model.md`](07-domain-model.md) §7。 DDL：`phase1c_session_transcripts.sql`。

### 7.1 Phase 1：`model_provider_profiles`（ADR-019）

权威 SQL：`packages/contracts/schemas/ddl/phase1_provider_configs.sql`

| 表 | 关键字段 | 写主权 |
|----|----------|--------|
| `model_provider_profiles` | `provider`, `model_name`, `api_key_ciphertext`, `base_url`, `is_active`, `config_version` | **api** 加密写；**runtime** 解密读（`StartTurn`） |

约束：`UNIQUE (is_active) WHERE is_active = true`（恰好一条生效配置）。

## 8. 内部命令（api → runtime）

传输：`POST http://runtime:8001/internal/commands/{name}`  
鉴权：Header `X-Internal-Token: ${INTERNAL_SERVICE_TOKEN}`  
响应：HTTP **202 Accepted**（仅表示命令入队/受理；事实以 `turn_events` 为准）

| 路径 | Schema |
|------|--------|
| `start-turn` | `schemas/commands/start_turn.json` |
| `cancel-turn` | `schemas/commands/cancel_turn.json` |
| `approve-tool-call` | `schemas/commands/approve_tool_call.json` |
| `deny-tool-call` | `schemas/commands/deny_tool_call.json` |

### start-turn（摘要）

```json
{
  "turn_id": "uuid",
  "run_id": "uuid",
  "session_id": "uuid",
  "scenario_id": "writing",
  "message": "string",
  "client_request_id": "uuid",
  "trace_id": "uuid"
}
```

runtime 幂等：相同 `client_request_id` 且 Run 已存在 → no-op 或返回进行中。

### cancel-turn（摘要）

```json
{
  "turn_id": "uuid",
  "run_id": "uuid",
  "trace_id": "uuid",
  "reason": "user_requested",
  "force": false
}
```

- api 须在转发前写 `runs.cancel_requested_at` / `cancel_force`（见 ADR-015）

### approve-tool-call / deny-tool-call（摘要）

```json
{
  "turn_id": "uuid",
  "run_id": "uuid",
  "tool_call_id": "string",
  "trace_id": "uuid"
}
```

产生事件见 [`08-event-projection-pipeline.md`](08-event-projection-pipeline.md) §7。

## 9. Eval（Golden Turn）

人类规范：[`11-eval-and-golden-turns.md`](11-eval-and-golden-turns.md)  
Schema：`packages/contracts/eval/golden_turn.schema.json`  
用例目录：`eval/golden/*.yaml`

Phase 1 最小集：`12` §5.1（管道）。  
能力融合（Phase 1b，进 Phase 2 前必绿）：`12` §5.2。

## 10. 工具命名与语义约束（补充）

以下名称作为文档、schema、事件、日志、审批与 Golden 的**权威工具名**。其中分为**跨场景共享工具**与**场景专属工具**；二者都属于正式一等公民，均不得在新文档中再引入漂移别名。

### 10.1 跨场景共享工具

- `read_file`
- `list_dir`
- `glob`
- `grep`
- `propose_patch`
- `apply_patch`
- `write_file`
- `edit_file`
- `run_command`
- `run_tests`
- `read_lints`
- `search_sources`
- `search_codebase`
- `delegate`
- `update_plan`

### 10.2 场景专属工具

#### writing

- `update_outline`
- `draft_section`
- `check_citation`
- `export_document`

约束：

- 写作场景的正式文稿修改以 `propose_patch` / `apply_patch` 为准
- `draft_section` 属于场景写作工具，不替代正式 patch 提交流程
- `delegate` 为正式副作用类别，审批默认 `always`
- `glob`、`grep`、`run_tests`、`read_lints` 为正式工具名；若被上层能力复用，不视为别名
- `update_plan` 归类为低风险元操作：可更新受管计划投影或 TODO 展示，但不直接修改工作区文件、执行命令或访问外网；在当前协议中仍归入 `read` 类处理
- Phase 1b 时 `search_codebase` 允许以 `grep` + 小索引退化实现，但对外工具名不变
- Phase 1b 时 `search_sources` 允许以 workspace 文档库关键词检索或轻量索引退化实现，但对外工具名不变
- `search_sources` 可选参数 `path_prefix`（RE0 冻结）：相对路径，可省略 `sources/` 前缀；禁止 `..` / 绝对路径；非法时返回空 hits + `hint`；合法时命中限制在该前缀下（见 `docs/15`）

## 11. 文件布局

```text
packages/contracts/
├── openapi/public.yaml
├── eval/golden_turn.schema.json
├── schemas/
│   ├── ddl/phase0.sql
│   ├── commands/
│   │   ├── start_turn.json
│   │   ├── cancel_turn.json
│   │   ├── approve_tool_call.json
│   │   └── deny_tool_call.json
│   ├── events/envelope.json
│   ├── events/types.json
│   ├── events/payloads/              # 按 type 的 payload schema（ADR-017）
│   ├── projections/turn_view.json
│   └── errors.json
└── python/                          # 可选：共享 Pydantic 模型

eval/golden/                         # 用例 YAML
```
