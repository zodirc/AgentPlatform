# 契约变更日志

版本规则见 [README.md](README.md) §版本化。每次改动 `schemas/`、`openapi/`、
`python/agent_contracts` 时,在此追加一条并按规则调整版本号。

## 0.2.0 — 2026-07-27

- `events/payloads/turn.failed.json`:`termination_reason` 枚举新增
  `approval_resume_timeout`、`approval_state_lost`(审批恢复失败路径,docs/35 I10)、
  `budget_exceeded`、`runner_restart`(崩溃恢复,docs/35 B2)。向后兼容(仅新增枚举值);
  消费者按未知原因兜底展示即可。
- `schemas/ddl/phase1k_retrieval_event_index.sql`:`turn_events` 上
  `retrieval.completed` 部分索引(docs/35 A13)。
- `schemas/ddl/phase1l_audit_log.sql`:新增 `audit_log` 表(docs/35 B17)。

## 0.1.0

- 初始契约:Phase 0/1 REST(`openapi/public.yaml`)、事件信封与 payload schema、
  内部命令体(`python/agent_contracts`)、领域 DDL。
