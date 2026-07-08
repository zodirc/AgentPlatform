# ADR-017: 边界契约校验与事件 Payload Schema

## 状态

已接受（2025-07-02）

## 背景

旧 `agent-langraph` 频繁出现 **「某步 str 字段对不上对象」**：膨胀 `AgentState`、图节点间 dict 传参、阶段字符串与真实状态不一致、无统一 schema。新项目用 `TurnState.messages` + 有限状态机缓解，但若 **命令/事件/tool_result 在边界不校验**，同类错误会以 payload 漂移、运行时 `KeyError` 形式复发。

## 决策

### 1. 边界一律强类型（Pydantic v2）

下列边界 **禁止** 裸 `dict` 进入业务逻辑：

| 边界 | 校验 |
|------|------|
| api HTTP 请求/响应 | FastAPI + Pydantic models（与 OpenAPI 同步） |
| api → runtime 内部命令 | `packages/contracts/schemas/commands/*.json` → 共享 Pydantic |
| `turn_events` 写入前 | envelope + **按 type 的 payload schema** |
| `ToolCall` / `ToolResult` | `ToolSpec.input_schema` + 统一 `ToolResult` 模型 |
| Golden 回放 | eval runner 校验事件 payload |

`04-development-standards.md` §3.5 为实施检查项。

### 2. 事件 Payload 分类型 Schema

`envelope.json` 定义外壳；**每种** `type` 的 `payload` 形状由独立文件定义：

```text
packages/contracts/schemas/events/payloads/
  README.md
  _index.json              # type → payload schema 路径
  turn.accepted.json
  turn.cancelled.json
  step.started.json
  tool.started.json
  tool.completed.json
  ...
```

规则：

1. runtime **append 事件前**校验 payload；失败 → `turn.failed`，`termination_reason: schema_validation_error`。
2. 新增 `type` 须同时增 payload schema 并登记 `_index.json`。
3. **禁止** 在 payload 中用自由字符串表示本属 `turns.status` / `runs.status` 的枚举（避免双真相）。

### 3. 与旧 AgentState 字段迁移原则

| 旧模式 | 新模式 |
|--------|--------|
| `state["phase"]` 字符串 | `turns.status` + 事件 `type` |
| 节点间传递业务 dict | `tool_result` 标准结构 + messages |
| 隐式可选字段 | schema `required` 显式列出；省略用 `null` 不用缺键 |

### 4. Golden 断言扩展

`12` §1.2 支持：

```yaml
assertions:
  events:
    payload_validates: true   # 每条事件按 _index.json 校验
```

Phase 1 起 **管道类** golden 默认 `payload_validates: true`。

### 5. CI

- `packages/contracts`：jsonschema 单元测试（示例事件 fixture 过校验）。
- api/runtime：mypy/pyright 覆盖 `app/` 公开接口。

## 理由

- 将「字段对不上」从生产随机炸转为 **契约测试失败**。
- 事件 payload 分文件便于 codegen 与 Golden 共用。
- 与 ADR-009 四层协议一致：Event 层有机器真相。

## 后果

### 正面

- 重构时有 schema diff；replay 旧事件可版本化。
- 前端/codegen 可从 payload schema 生成类型。

### 负面

- 维护成本：每个事件 type 一个 schema。
- 严格校验可能拒绝「仅多一个字段」的向后兼容扩展 → 用 `additionalProperties` 策略显式管理。

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 仅 envelope 校验，payload 任意 object | 无法防止字段漂移 |
| 继续大图 AgentState | 重蹈旧系统覆辙 |
| 仅文档约定字段 | 无法 CI  enforcement |

## 关联文档

- [`04-development-standards.md`](../04-development-standards.md) §3.5
- [`contracts.md`](../contracts.md) §3.1
- [`07-domain-model.md`](../07-domain-model.md) §10
- [`12-eval-and-golden-turns.md`](../12-eval-and-golden-turns.md) §1.2
