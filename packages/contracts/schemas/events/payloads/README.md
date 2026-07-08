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
