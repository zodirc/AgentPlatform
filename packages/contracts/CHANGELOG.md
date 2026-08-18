# 契约变更日志

版本规则见 [README.md](README.md) §版本化。每次改动 `schemas/`、`openapi/`、
`python/agent_contracts` 时,在此追加一条并按规则调整版本号。

## 0.3.4 — 2026-08-18

- `python/agent_contracts/command_allowlist.py`：`run_command` 审批前缀匹配
  （`normalize_command_prefix` / `command_matches_prefix`）。向后兼容新增模块。

## 0.3.3 — 2026-08-13

- `schemas/ddl/phase2_run_commands.sql` + alembic `0021`：`run_commands` 表
  （approve/deny/patch/cancel）+ partial unique + NOTIFY 通道（O2 / WP6）。
- `schemas/ddl/phase2_events_retention.sql` + alembic `0022`：`turn_events`
  分级保留注释；应用侧 stream 7d / structural 90d 批删（O7 / WP3；分区改写另开维护窗）。
- 默认分发：`TURN_DISPATCH=pull`（WP9）；push 仍可一键回退。

## 0.3.2 — 2026-08-13

- `events/payloads/turn.failed.json`: `termination_reason` 枚举新增 `runner_lost`
  （副本租约过期回收，O3 / WP1）、`db_timeout`（O10）、`start_timeout`
  （pull 分发无人 claim，O1 / WP5）。向后兼容。
- `schemas/ddl/phase2_runners_lease.sql`: `runners` 表 + `runs.lease_expires_at`。

## 0.3.1 — 2026-08-04

- `events/payloads/tool.completed.json`: 新增可选 `chars_read` / `file_chars` /
  `offset` / `end_line` / `total_lines` / `next_offset`（CTX-9 可视覆盖探针；
  不在事件总线携带全文 content）。向后兼容。

## 0.3.0 — 2026-08-02

- `events/payloads/retrieval.completed.json`: `audit.lane_depth`（RET-10：vector/bm25/union/top_k/over_fetch/two_level 真计数）
  （≤100 条 path/score/chunk_id，供 Ops / official L1 计 nDCG@10 / R@100）。
  向后兼容；写侧先升 runtime schema，旧消费者忽略未知字段即可。

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
