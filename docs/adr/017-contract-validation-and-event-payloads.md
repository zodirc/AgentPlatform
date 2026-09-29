# ADR-017 契约校验与事件 payload

状态：已实施。

## 决策

跨服务契约放在 `packages/contracts`，服务里不先发明字段。

事件 `payload` 按 `turn_events.type` 分文件，目录是 `schemas/events/payloads/`。`_index.json` 把类型名映射到 schema 文件。外壳在 `schemas/events/envelope.json`，不在 payload schema 里重复。

runtime 追加耐久事件前调用 `maybe_validate_event_payload`：

- `event_payload_validation` 默认开。校验的是 payload，不是整封信封。
- 已进索引的类型用 JSON Schema（Draft 2020-12）校验。索引里没有的类型放行。
- 高频 `turn.token`、`tool.delta`、`turn.thinking.delta`、`section.draft.delta` 默认只检查存在 `delta` 或 `text`。完整 schema 由 `event_payload_validation_strict_deltas` 打开，用于 CI 和调试。
- 不合法时抛 `EventPayloadValidationError`，不写入该行。

api 与 runtime 之间的命令体是 `packages/contracts/python` 里的 Pydantic 模型：`StartTurnCommand`、`ApproveToolCallCommand`、`DenyToolCallCommand`、`CancelTurnCommand`。

## 改契约时

1. 新事件类型：加 payload schema、更新 `_index.json` 和 `schemas/events/types.json`。若校验面变了，改本 ADR。
2. 对外 REST：改 `openapi/public.yaml`，再跑 codegen。
3. 内部命令：改 `schemas/commands/` 与 python 模型。
4. 版本号与兼容性记在 `packages/contracts/CHANGELOG.md`。

人类入口是导览「契约位置」页。
