# 方案（Plan）

尚未升格为正文的设计草案。评审通过并落地后，应回写到 `docs/core/` / `docs/topics/` 或 ADR，并在本目录标注状态。

| 文档 | 状态 | 摘要 |
|------|------|------|
| [Coding 结构智能（LSP / AST）](coding-structural-intelligence.md) | 草案 | agent 写入链的 LSP/AST：场景隔离、R1–R5、交互逻辑、分阶段与情况总表 |

约定：

- Plan **不**替代六篇正文；冲突时以 `docs/core/*`、`docs/topics/*` 为准，直到回写完成。  
- 速率红线 R1–R5、能力即工具、Engine 禁止 `if scenario` 为硬约束。  
- 合入实现前须有 R5 验收（golden / 门禁 / 延迟对照）写进对应 Plan。
