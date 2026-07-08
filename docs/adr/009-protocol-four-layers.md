# ADR-009: Resource / Command / Event / Projection 四层协议模型

## 状态

已接受（2025-06-30）

## 背景

`agent-langraph` 中 HTTP 路由、SSE 推送、内部 graph 状态与前端展示混用同一数据结构，导致：

- `/tasks` 与 `/api/...` 语义不清
- 前端靠实现细节拼 Turn 阶段
- api 与 runtime 之间仅有「下游 HTTP」关系，缺少稳定语义分层

需要明确对外与跨服务协议的职责划分。

## 决策

系统协议分为四层，**禁止**同一接口同时承担多种语义：

### 1. Resource（资源）

- 稳定业务对象的 CRUD 与查询：`Session`、`Turn`、`Run`、`Artifact`、`ApprovalRequest`
- 对外前缀：`/api/v1/...`
- 适合：列表、分页、管理面、幂等更新
- 返回 envelope：`{ data, error, meta }`（见 `docs/04-development-standards.md`）

### 2. Command（命令）

- 表达**意图**，不是事实结果：`StartTurn`、`CancelTurn`、`ApproveToolCall`、`DenyToolCall`、`PatchAccept`、`PatchReject`
- 对外：`POST /api/v1/sessions/{id}/turns`、`POST /api/v1/turns/{id}/cancel` 等（完整列表见 `docs/contracts.md` §2.1）；对内：`POST /internal/commands/*`
- **无独立 `ResumeTurn`**：审批 interrupt 后的恢复由 `ApproveToolCall` 从 checkpoint 继续执行
- 规则：命令受理成功 ≠ 业务完成；结果通过 Event 与 Projection 体现
- 必须支持幂等键或可推导幂等语义

### 3. Event（事件）

- 已发生事实的追加日志，用于 SSE、重连、审计、投影构建
- 规范见 **ADR-004**；持久化于 `turn_events`
- runtime 生产，api 代理，web 消费

### 4. Projection（投影）

- 供 UI 与管理面直接消费的展示模型：`TurnView`、`SessionView`、`TimelineView` 等
- 可由事件增量刷新，**必须可重建**
- 字段以消费稳定性优先，不暴露 execution state 内部字段

### 跨层规则

| 层 | 消费者 | 禁止 |
|----|--------|------|
| Execution state（messages 等） | runtime 内部 | 直接暴露给前端 |
| Domain model | api / runtime 持久化 | 等同 UI 状态 |
| Projection | web / 管理面 | 由前端本地推断 |

契约落地位置：`packages/contracts/`（OpenAPI、JSON Schema、共享 Pydantic 模型）。

## 理由

- 分离「读资源 / 发命令 / 收事件 / 看投影」使前后端协作边界清晰
- 与 CQRS / event sourcing 轻量实践一致，无需引入重量级 ES 框架
- 支持重连：Event + Projection 双兜底
- 防止 api 退化为「BFF 杂物间」或 runtime 泄漏 UI 结构

## 后果

### 正面

- 契约可版本化、可 codegen（TypeScript 类型从 schema 生成）
- 测试可分层：命令受理、事件序列、投影重建独立验证
- 异步任务层可订阅事件，不侵入主 loop

### 负面

- 初期需维护多套 schema，文档与实现需同步
- 投影延迟一致需产品层接受（最终一致）
- 开发者需学习四层区分，避免偷懒混用

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 仅 REST + 轮询 Turn 状态 | 流式体验差；状态对象过重 |
| Graph state 直接 SSE 推送 | 泄漏 execution 细节；不可重建投影 |
| 单一 BFF 聚合一切 | api 臃肿，违背 ADR-001 |
| gRPC 统一四类语义 | Phase 0 浏览器与工具链成本高 |
