# 附录 — 从 agent-langraph 迁移映射

> 单一来源：旧模块 → 新归属。其他文档请链接本文，勿重复维护表格。

| 旧模块 | 新归属 | 优先级 |
|--------|--------|--------|
| `app/api/task_api` | `services/api` | P1 |
| `app/runtime/graph.py`、`app/nodes/*` | `services/runtime/engine` 单循环 | P1 |
| `app/services/writing_*` | `scenarios/profiles/writing.yaml` + `tools/core/` | P1 |
| `web/*` | `services/web` | P1 |
| `supervisor_decompose/worker/merge` | `delegate` 工具 + 写作/agent 子角色 | P2 |
| `app/services/retrieval_*` | `tools/core/search_*`；Agent:`search_codebase`；写作:`search_sources` | P2 |
| `app/services/prompt_context_gateway` | `services/runtime/context/` | P2 |
| `app/services/tool_*` | `tools/core/` + Scenario 登记 | P2 |
| `app/services/writing_*`（交付） | 写作 scenario 工具链 | P2 |
| `app/services/tenant_*` | `services/api/tenant` | P4 |

### 节点 → loop 对照（编排层面）

| 旧节点 | 新归属 |
|--------|--------|
| `event_classification_node` | 删除 → **Turn Intake**（`05` §3.1、ADR-014） |
| `acknowledge_node` | `turn.accepted` 快速首包（TurnController） |
| `retrieval_node` | `search_*` 工具 |
| `tool_node` | `ToolExecutor` |
| `context_governance_node` | `ContextEngine` 每轮 |
| `reasoning_or_writing_node` | 模型输出 |
| `verification_node` | `run_tests` / `check_citation` 等工具 |
| `policy_node` / `human_review_node` | 工具级审批门 |
| `supervisor_*` | `delegate` |
