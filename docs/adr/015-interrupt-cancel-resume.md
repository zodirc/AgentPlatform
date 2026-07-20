# ADR-015: Interrupt / Cancel / Resume 语义（对齐 Cursor 式可控性）

## 状态

已接受（2025-07-02）

## 背景

产品交互基线要求 **流式、可打断、过程可见**（`01`、`11`），参考 Cursor 类编码 agent。旧 `agent-langraph` 在「停不下来」「取消后状态乱」「UI 与执行不同步」上问题严重；新系统虽采用单 loop + Run:Turn 1:1，但早期文档将取消检查点仅写在 Step 边界，且混用「resume」表述，不足以保证实现后体验达标。

需明确三类用户动作的系统语义、传播路径与可测 SLO，避免与「暂停播放器」或「ResumeTurn」混淆。

## 决策

### 1. 三类动作（权威术语）

| 用户动作 | 系统机制 | Turn 终态？ | 继续方式 |
|----------|----------|------------|----------|
| **Stop / 取消本轮** | `CancelTurn` | 是 → `cancelled` | 同 Session **新发 Turn**（**无** `ResumeTurn`） |
| **审批工具** | Approval **interrupt** | 否 → `waiting_approval` | `ApproveToolCall` 从 checkpoint **续同一 Run** |
| **拒绝 diff（写作）** | `PatchReject` | 通常否（Turn 常已 `completed`） | 新发 Turn 或模型再改；**非**执行暂停 |

### 2. CancelTurn：软 / 硬取消

```json
{ "reason": "user_requested", "force": false }
```

| | `force: false`（默认） | `force: true` |
|--|------------------------|---------------|
| 模型流式 | 下一 abort 检查点断 provider 连接（目标 ≤500ms P95） | 立即断连 |
| 工具执行 | 优雅收尾（短超时，默认 500ms）后停 | 立即 kill（`run_command` 用 process group） |
| 副作用 | 已落盘不回滚；半写按工具事务边界 | 同左 |
| 事件 | `turn.cancelling`（可选）→ `turn.cancelled` | 同左 |

**禁止**仅在 Step 边界检查取消而不在 `ModelGateway.stream` / `ToolExecutor` 内检查。

### 3. 取消双通道（api ↔ runtime）

并行生效，取先到达者：

1. **Domain 标志**：api 受理 `CancelTurn` 时写 `runs.cancel_requested_at`（及 `cancel_force`）；runtime 在 assemble / stream / tool 轮询。
2. **内部命令**：`POST /internal/commands/cancel-turn`（202），与上互补。

### 4. Resume 边界

- **Cancel 后**：Run 终态 `cancelled`，**不可**恢复同一 Run。用户继续对话 = 新 `turn_id` + 新 `run_id`；跨 Turn 记忆靠 `sessions.context_summary`（`07` §5）。
- **审批 interrupt 后**：仅 `ApproveToolCall` / `DenyToolCall`；checkpoint 以 `run_id` 为主键；runtime 重启后须能从 DB checkpoint 恢复 interrupt（`03` §8.4）。

### 5. Web 乐观停止

用户点 Stop 时 Web **立即**停止本地渲染（≤50ms），并并行 `POST .../cancel`；**禁止**仅等 `turn.cancelled` 才停 UI（`11` §5.1）。

### 6. 写作 patch 审阅

`propose_patch` 后 Turn 正常进入 `completed`（模型无后续 tool 时）；用户在 **Turn 结束后** accept/reject patch。**不**引入 `waiting_patch_decision` 执行态。

### 7. delegate 级联

父 Run 收到 cancel 时，**级联 abort** 活跃子 `AgentEngine`（委派深度 ≤2）。

## 理由

- 与 Cursor 一致：Stop 结束当前生成，会话靠新消息延续，而非 ResumeTurn。
- Step 内模型流式可能持续数十秒，仅 Step 边界检查会导致「停不下来」回归。
- 双通道取消避免 runtime 繁忙时只靠 HTTP 命令延迟。
- 乐观 UI 是体感流畅的必要条件，不能全靠后端事件。

## 后果

### 正面

- 语义清晰，Golden 可分层断言（流式 cancel、工具 cancel、审批 resume）。
- 旧系统 cancel/interrupt 混乱根因被显式排除。

### 负面

- runtime 实现复杂度上升（stream abort、子进程 kill、delegate 级联）。
- `runs` 表增加取消相关列；`turn.cancelling` 可选事件需同步 schema。

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 通用 Pause / ResumeTurn | 与 Run:Turn 1:1 冲突；状态机膨胀 |
| 仅 Step 边界 abort | 模型长流式时体验差，复现旧系统痛点 |
| UI 等终态再停渲染 | 体感远差于 Cursor |
| patch 等待新 Turn 状态 `waiting_patch` | 不必要地扩展状态机 |

## 关联文档

- [`05-agent-runtime.md`](../05-agent-runtime.md) §8
- [`06-tools-and-context.md`](../06-tools-and-context.md) §5.4
- [`07-domain-model.md`](../07-domain-model.md) §2.5、§7
- [`10-product-experience.md`](../10-product-experience.md) §1、§5.1
- [`11-eval-and-golden-turns.md`](../11-eval-and-golden-turns.md) §5.1
- [`contracts.md`](../contracts.md) §2.1、§3、§3.1、§4
- [ADR-016](016-execution-timeouts-and-stall-watchdog.md)
