# 方案（Plan）

设计详册与落地记录。原则与主路径以 `docs/core/` · `docs/topics/` 为准；数字、机型配方、评测日记可留在本目录。

| 文档 | 状态 | 摘要 |
|------|------|------|
| [后端架构全景](backend-architecture.md) | 详册 **v0.3** | 控制流全文；默认 pull · lease · 准入；机型负载配方 |
| [后端并发架构演进](backend-scaling-evolution.md) | **历史 + Phase3** | Phase 0–2 / O1–O11 主项已落地；WP10/Phase3 触发条件驱动 |
| [后端并发演进 · 开发方案](backend-scaling-implementation.md) | **历史手册** | WP0–WP9 已落地；勿再当未开工待办 |
| [Coding 结构智能](coding-structural-intelligence.md) | Wave1+揉合 **已落地** | Locate/Impact/Verify；SWE/Ops 日记与 Wave2 收尾项 |
| [Agent 工作区异步 AST](agent-workspace-ast-index.md) | A6 **已接线** | 旁路 indexer + 队列；双轨 n5 数字待 A6 拓扑复跑 |
| [威胁情报 · 验证闭环](intel-closed-loop-verification.md) | 草案 v0.1 | intel 验证闭环与 Bench 对照 |

约定：

- 速率红线 R1–R5、能力即工具、Engine 禁止 `if scenario` 为硬约束。  
- 分发默认 pull；运维手册见 `docs/ops/pull-dispatch-runbook.md`。  
- 合入实现须有可测验收；正文已覆盖的主路径勿只改 plan 不改 core。
