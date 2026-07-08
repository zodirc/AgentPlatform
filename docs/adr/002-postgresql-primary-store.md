# ADR-002: PostgreSQL 作为唯一关系型存储

## 状态

已接受（2025-06-30）

## 背景

`agent-langraph` 的持久化对象（Session、Run、Turn、事件日志）与多种辅助状态混用，部分能力依赖隐式文件或内存结构，导致：

- 多副本部署时状态不一致
- 事件回放与投影重建缺少统一事实来源
- 运维备份策略分散

新项目需要为 domain state、event log、projection、outbox 选定单一关系型存储基座。

## 决策

1. **PostgreSQL 16** 作为唯一关系型数据库，承载：
   - domain tables：`sessions`、`turns`、`runs`、`artifacts`
   - event log：`turn_events`
   - projection tables：`turn_views`、`session_views`、`approval_views` 等
   - outbox：`outbox_jobs`（Phase 1 起）
   - LangGraph checkpoint 元数据（或与 checkpoint blob 联合存储）
2. **Redis** 仅作 Phase 2+ 可选组件（队列、限流、多副本协调），**不**替代 PostgreSQL 作为事实存储。
3. 向量索引与 embedding 模型缓存放在 `/data` 卷（`vectorstore/`、`models/`），关系型库只存元数据与引用。
4. Schema 迁移由 `api` 服务主权管理（Alembic）；`runtime` 只读写，不擅自建表。

## 理由

- Session / Turn / Event / Projection 天然适合事务与追加日志模型
- Outbox 模式需要可靠的关系型存储保证 at-least-once 派发
- 单库降低 Phase 0–2 运维复杂度；备份策略统一（`pg_data` 卷快照）
- 团队已有 PostgreSQL 经验，与 FastAPI + SQLAlchemy 生态匹配

## 后果

### 正面

- 事件、投影、domain 可在同一事务边界内保持一致性策略
- 重连回放（`since_sequence`）有稳定查询面
- 为后续读写分离、只读副本预留标准路径

### 负面

- 高吞吐事件写入可能成为瓶颈（Phase 4 前可接受）
- checkpoint 大 payload 需评估是否外置对象存储
- 单库故障影响全栈（Phase 0–2 用 compose 单实例可接受）

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| SQLite（仅本地） | 无法支撑多容器、多副本与标准备份 |
| MongoDB 作主库 | 事件与投影的增量更新、事务语义更复杂 |
| 事件仅内存 + SSE | 无法重连回放，违背架构目标 |
| PostgreSQL + 每服务独立库 | Phase 0 过度拆分，跨服务查询与迁移成本高 |
