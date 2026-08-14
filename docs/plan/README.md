# 方案（Plan）

设计详册与说明。原则与主路径以 `docs/core/` · `docs/topics/` 为准；数字、机型配方、评测日记可留在本目录。

| 文档 | 状态 | 摘要 |
|------|------|------|
| [后端架构全景](backend-architecture.md) | 详册 **v0.3** | 控制流全文；机型负载配方 |
| [Coding 结构智能](coding-structural-intelligence.md) | **已收敛** | 流程 / 已优化 / 观测定位 / harness 方案 |
| [Agent 工作区异步 AST](agent-workspace-ast-index.md) | A6 **已接线** | 旁路 indexer；双轨 n5 数字待复跑 |
| [威胁情报 · 验证闭环](intel-closed-loop-verification.md) | 草案 · **未实施** | intel 验证闭环与 Bench 对照 |

约定：

- 速率红线 R1–R5、能力即工具、Engine 禁止 `if scenario` 为硬约束。  
- 分发默认 pull；运维手册见 `docs/ops/pull-dispatch-runbook.md`。  
- 合入实现须有可测验收；正文已覆盖的主路径勿只改 plan 不改 core。  
- 冲突时：代码与契约 > 六篇正文 > plan 措辞。
