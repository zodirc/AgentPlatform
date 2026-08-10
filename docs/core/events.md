# 事件与契约

事实事件如何从 runtime 到达 Web，以及 api 如何用内部命令启动/取消/审批 Turn。两张图覆盖管道与 StartTurn 链。

## 图

1. [事件 · SSE · 投影](../assets/events/event-sse-zh.png) — INSERT → NOTIFY → LISTEN → SSE / views  
2. [StartTurn 命令链](../assets/events/start-turn-command-zh.png) — POST turns → 内部 start-turn  

![事件 SSE 投影](../assets/events/event-sse-zh.png)

![StartTurn 命令链](../assets/events/start-turn-command-zh.png)

## 1. 事实管道（Pull 模型）

采用 **事件表拉取**，不用 runtime→api 内存推送，也不让 runtime 对浏览器开 SSE。

```text
runtime（TurnController / AgentEngine）
  · 关键节点 append-only INSERT turn_events（递增 sequence）
  · 大正文进 artifacts；事件行带摘要/指针
  · AFTER INSERT → pg_notify('turn_events_channel', turn_id)

Postgres

api
  · 启动时 LISTEN turn_events_channel
  · 收到 turn_id → asyncio.Queue（SSE 与 projection 共用触发）
  · Queue 空闲约 2s 轮询 turn_events 兜底（防丢通知/断连）

分流：
  · SSE  GET /api/v1/turns/{id}/stream
        按 sequence 回放增量；thinking.delta 只走 SSE
        约 14s 发 :ping；客户端可用 Last-Event-ID 重连
  · Projection
        同批事件 UPSERT turn_views
        列表 / 首屏 / 重连 / 终态确认 → GET /view（可 ETag/304）
        thinking.delta 默认不进 view 快照
```

禁止：

- runtime 直连浏览器 SSE  
- 仅靠进程内 channel 当事唯一源  
- 在 Turn 热路径上同步做重投影计算  

UI **不推断**阶段：只跟事件流与 `turn_views`。

## 2. 写主权

| 所有者 | 写什么 |
|--------|--------|
| **runtime** | `turn_events`、runs/turns 执行态、checkpoint、transcript 真源、工具产物引用 |
| **api** | `turn_views`、对外 SSE、触发/更新 `sessions.context_summary`（常异步） |

无分布式事务：领域表若短暂落后，用事件序 **reconcile** 修。  
派生字段（如 `cancellable`、interrupt 视图）可读时计算，不必全部落成 `turn_views` 列——以 `packages/contracts` DDL 与 api 实现为准。

## 3. 命令与资源

### 3.1 StartTurn（主路径）

1. 客户端 `POST /api/v1/sessions/{id}/turns`（input、附件、scenario 等）。  
2. api 鉴权，校验 session · `work_id` · `scenario_id`。  
3. 落库：插入 `turns` + `runs`；尽快发出 **`turn.accepted`**（服务 TTFB）。  
4. 内部 HTTP：`POST runtime /internal/commands/start-turn`，头带 `INTERNAL_SERVICE_TOKEN`。  
5. runtime `TurnController`：Intake → Profile → shouldQuery → Engine 或本地完结。  

### 3.2 同族内部命令（同一 token）

| 命令 | 用途 |
|------|------|
| `cancel-turn` | 软/硬取消 |
| `approve-tool-call` / `deny-tool-call` | 审批续跑或拒绝 |
| `patch-accept` / `patch-reject` | diff 接受/拒绝 |
| `sync-sources-index` / `cancel-sources-index` | 索引面 |
| `verify-pass` · `warmup-retrieval` 等 | 验证/预热类 |

### 3.3 只读资源（不触发 loop）

`GET /turns/{id}` · `/view` · `/stream` · `GET /runs/{id}` · Sessions/Works/健康检查等。

公开契约与版本：`packages/contracts`（OpenAPI ⊆ api 测试；事件 schema；DDL；changelog）。改字段先改契约包，再改实现与 web 生成类型。

## 4. 常见事件形态（概念）

不必背全表，但主链上会反复见到：

| 阶段 | 例 |
|------|-----|
| 受理 | `turn.accepted` |
| 模型 | `turn.thinking.delta` · 文本增量 |
| 工具 | `tool.started` / `tool.completed` · `approval.requested` |
| 检索旁路 | `retrieval.completed`（audit，给 Ops L1/L2/L3；见[工作台](../topics/workbench.md)） |
| 终态 | `turn.completed` / `turn.failed` / `turn.cancelled` |

完整枚举与 payload 以契约包事件 schema 为准，并与投影消费逻辑对齐。
