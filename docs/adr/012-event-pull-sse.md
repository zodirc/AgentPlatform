# ADR-012: 事件 Pull 模型与 api 独占 SSE

## 状态

已接受（2025-07-01）

## 背景

`02-architecture` 数据流写「api 订阅或读取事件流」，未选定实现；`05` 曾写 TurnController「串接 SSE」，与「实时层在 api」冲突。多副本 runtime 下推送模型更复杂。

## 决策

1. **runtime** 将事实 **append-only 写入** `turn_events`（唯一写方）。
2. **api** 通过读 `turn_events`（轮询或 `LISTEN/NOTIFY`）向客户端提供 **唯一 SSE 端点**。
3. **禁止** runtime 直接向浏览器推流；**禁止** 仅以内存 channel 作为事件事实源。
4. projection 由 **api** 侧模块异步消费 `turn_events` 更新 `turn_views`；失败不阻断 Turn 执行。
5. Phase 0–2 默认 **单 runtime 副本**；多副本路由见 `docs/03-docker-runtime.md` §8.5。

详见 `docs/09-event-projection-pipeline.md`。

## 理由

- api 已承担鉴权与公网边界，SSE 集中于此
- 事件落库即可重连回放，与 ADR-004 一致
- runtime 无需维护客户端连接状态

## 后果

### 正面

- 实现路径单一，Phase 0 可 stub
- 日志、审计、replay 统一查 `turn_events`

### 负面

- SSE 延迟受轮询间隔影响（可用 NOTIFY 优化）
- `turn_events` 写入量增长需分区/归档策略（Phase 4）

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| runtime 直推 SSE | 破坏网关鉴权；多副本难路由 |
| Redis Stream 为主事实源 | Phase 0 组件过多；PG 已满足 |
| api 同步调用 runtime 流式转发 | runtime 与连接耦合，扩缩差 |
