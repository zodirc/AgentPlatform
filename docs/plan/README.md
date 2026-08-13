# 方案（Plan）

尚未升格为正文的设计草案。评审通过并落地后，应回写到 `docs/core/` / `docs/topics/` 或 ADR，并在本目录标注状态。

| 文档 | 状态 | 摘要 |
|------|------|------|
| [后端架构全景](backend-architecture.md) | 综合草案 **v0.3** | 后端控制流全文；**默认 pull 分发** · lease/run_commands/准入 · 机型 A/B 负载配方 |
| [后端并发架构演进](backend-scaling-evolution.md) | 优化草案 **v0.2** · Phase 0–2 **已落地** | 弱点 W1–W12 · O1–O11；WP10/Phase3 仍触发条件驱动 |
| [后端并发演进 · 开发方案](backend-scaling-implementation.md) | 实施计划 **v0.2** · **WP0–WP9 已落地** | 工程手册；WP10 门禁未开 |
| [Coding 结构智能（LSP · SWE/Ops）](coding-structural-intelligence.md) | 草案 | agent 写入链 **LSP** Locate/Impact/Verify 揉合、Wave 1/2、SWE-bench / Ops L1 评测主线 |
| [Agent 工作区异步 AST 索引](agent-workspace-ast-index.md) | 候选草案 | Cursor 式 codebase：按 Work 冷启动/增量、GUI 进度、多账号 DB 缓存；**不携带 RAG**；与评测主线分离 |
| [威胁情报 · 验证闭环](intel-closed-loop-verification.md) | 草案 v0.1 | `intel`：以攻促防；研判→验证闭环；**§5 Bench**（Golden/效果臂/CTIBench 对照；自建 Closed-Loop Suite） |

约定：

- Plan **不**替代六篇正文；冲突时以 `docs/core/*`、`docs/topics/*` 为准，直到回写完成。  
- 速率红线 R1–R5、能力即工具、Engine 禁止 `if scenario` 为硬约束。  
- 合入实现前须有 R5 验收（golden / 门禁 / 延迟对照）写进对应 Plan。
