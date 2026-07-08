# ADR-004: SSE 作为 Turn 流式传输协议

## 状态

已接受（2025-06-30）

## 背景

Turn 执行是长流程、多 Step、多工具调用的过程。客户端需要：

- 实时看到模型输出与工具进度
- 断线后按序号重连与回放
- 与 projection 兜底配合，不依赖前端本地推断状态

需在 WebSocket、SSE、gRPC stream 之间选定 Phase 0–2 的默认流式协议。

## 决策

1. **Server-Sent Events（SSE）** 作为 Turn 执行流的默认传输协议：
   - 对外：`GET /api/v1/turns/{id}/stream`（`text/event-stream`）
   - 内部：runtime 产出事件 → 持久化 `turn_events` → api 代理 SSE
2. 每个事件必须包含 **`event_id`**、**`sequence`**（单 `stream_id` 内严格递增）、**`type`**、**`turn_id`**、**`trace_id`**、**`ts`**。
3. 重连：客户端携带 `Last-Event-ID` 或 `since_sequence`；api 从 `turn_events` 回放；缺失窗口时回退 `GET /api/v1/turns/{id}/view`。
4. Phase 0 起事件写入 PostgreSQL，**禁止**仅依赖进程内内存 channel 作为唯一事实来源。
5. **WebSocket** 作为 Phase 3+ **可选双向通道**（`GET /api/v1/turns/{id}/ws` 升级）：高频审批场景；**不替代** SSE 作为主 Turn 流协议。

### 规范事件类型目录

命名规则：小写、点分、`{域}.{动作}`。  
**机器枚举**：`packages/contracts/schemas/events/types.json`（须与下表同步）。  
**人类索引**：[`contracts.md`](../contracts.md) §3。

| type | 说明 | Phase |
|------|------|-------|
| `turn.accepted` | Turn 已受理 | 0 |
| `step.started` | Step 开始 | 0 |
| `step.completed` | Step 结束 | 1 |
| `turn.thinking` | 模型思考流（可选展示） | 1 |
| `turn.token` | 模型文本 token 流 | 1 |
| `turn.plan` | 计划 / TODO 更新 | 2 |
| `tool.started` | 工具调用开始 | 0 |
| `tool.delta` | 工具流式输出增量 | 1 |
| `tool.completed` | 工具调用结束 | 0 |
| `approval.requested` | 等待人工审批 | 1 |
| `approval.resolved` | 审批已决 | 1 |
| `turn.cancelling` | 取消进行中（可选，UI「正在停止…」） | 1 |
| `subagent.started` | 子 agent 启动 | 2 |
| `subagent.completed` | 子 agent 结束 | 2 |
| `retrieval.completed` | 检索完成（可选细粒度事件） | 2 |
| `turn.cancelled` | Turn 已取消 | 1 |
| `patch.proposed` | diff 提案（写作/agent 改稿） | 1 |
| `patch.applied` | 用户接受并应用 patch | 1 |
| `patch.rejected` | 用户拒绝 patch | 1 |
| `outline.updated` | 大纲结构变更（写作） | 1 |
| `section.draft.delta` | 章节草稿流式增量（写作） | 1 |
| `turn.completed` | Turn 正常结束 | 0 |
| `turn.failed` | Turn 失败 | 0 |

### 最小事件 envelope

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
  "causation_id": "uuid|null",
  "ts": "iso8601",
  "payload": {}
}
```

## 理由

- SSE 基于 HTTP，与 gateway、鉴权、HTTP/2 基础设施一致，调试成本低
- 单向推送足够覆盖「执行进度 → 客户端」主路径；审批可用 REST 命令 + SSE 通知
- `sequence` + DB 持久化满足重连与审计，优于纯 WS 无状态推送
- 比 gRPC 更适合浏览器直连与 Phase 0 快速落地

## 后果

### 正面

- 前端可用标准 `EventSource` 或 fetch stream 消费
- 事件与 projection 共用同一事实链，便于 replay 与 debug
- api 可做 SSE 聚合与限流，runtime 不直接暴露公网

### 负面

- SSE 单向；高频双向交互需额外 REST 或未来 WS
- 部分代理对长连接超时需 gateway 配置 keep-alive
- 大 payload 事件需控制体积，避免带宽膨胀

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| WebSocket 作主协议 | Phase 0 复杂度高；重连与回放需自建更多语义 |
| 长轮询 | 延迟与服务器压力大 |
| 仅 REST 轮询 projection | 无法细粒度流式体验，工具进度滞后 |
| gRPC server stream | 浏览器与 gateway 集成成本高 |
