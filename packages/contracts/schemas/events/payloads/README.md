# Event payload schemas

每种 `turn_events.type` 的 `payload` 形状在此目录定义。外壳见 `../envelope.json`。

权威索引：`_index.json`  
人类索引：[`docs/contracts.md`](../../../../docs/contracts.md) §3.1  
决策：[ADR-017](../../../../docs/adr/017-contract-validation-and-event-payloads.md)

## 规则

1. runtime append 事件前校验 `payload` 符合对应 schema。
2. 新增 type：增 `*.json`、更新 `_index.json`、`types.json`、ADR-004、`contracts.md` §3。
3. payload **不得**重复 domain 枚举（如用 `phase: "running"` 代替读 `turns.status`）。

## Phase 1 最小集

| type | schema |
|------|--------|
| `turn.accepted` | `turn.accepted.json` |
| `turn.cancelling` | `turn.cancelling.json` |
| `turn.cancelled` | `turn.cancelled.json` |
| `turn.completed` | `turn.completed.json` |
| `turn.failed` | `turn.failed.json` |
| `step.started` | `step.started.json` |
| `tool.started` | `tool.started.json` |
| `tool.completed` | `tool.completed.json` |

其余 type 在首次实现该事件时追加 schema。

## 保留策略（O7 / WP3）

应用批删（`events_retention`），非强制分区：

| 类别 | types（示例） | 默认保留 |
|------|---------------|----------|
| Stream | `thinking.delta` · `turn.token` · `tool.delta` | 终态 Turn 后 **7d** |
| Structural | 其余 type（含 `turn.*` 终态、tool/approval 等） | 终态 Turn 后 **90d** |

旋钮：`EVENTS_STREAM_RETENTION_DAYS` / `EVENTS_STRUCTURAL_RETENTION_DAYS`。
DDL 注释见 `schemas/ddl/phase2_events_retention.sql`。
