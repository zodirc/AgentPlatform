# 文档

Agent Platform：一个 Runtime，多个 Scenario。验证：`make gate` · `make smoke`。

## 正文（6 篇 · 每篇配控制流图）

| 文档 | 图 1 | 图 2 |
|------|------|------|
| [架构](core/architecture.md) | [请求主路径](assets/architecture/request-path-zh.png) | [分模块发布台](assets/ops/release-modular-deploy-zh.png) |
| [Runtime](core/runtime.md) | [Engine 循环](assets/harness/agent-engine-loop-zh.png) | [审批·取消·恢复](assets/harness/approval-cancel-resume-flow-zh.png) |
| [工具与上下文](core/tools-and-context.md) | [组窗阶梯](assets/context/context-assemble-ladder-zh.png) | [exec 沙箱](assets/sandbox/bwrap-exec-flow-zh.png) · [Coding 揉合](assets/harness/coding-fuse-zh.png) |
| [事件与契约](core/events.md) | [事件·SSE·投影](assets/events/event-sse-zh.png) | [StartTurn 命令链](assets/events/start-turn-command-zh.png) |
| [RAG](topics/rag.md) | [hybrid 召回](assets/rag/search-sources-flow-zh.png) | [索引面](assets/rag/index-sync-zh.png) |
| [工作台](topics/workbench.md) | [写作主路径](assets/writing/writing-main-path-zh.png) | [Ops Bench 原理](assets/ops/ops-bench-principle-zh.png) |

起栈见仓库根 README。图风格：大字号中文 · 编号步骤 · 菱形 · 虚线边界 · 侧注 · 图例。正文以本目录六篇为准。

## 运维

| 文档 | 说明 |
|------|------|
| [Pull 分发运维手册](ops/pull-dispatch-runbook.md) | 默认 pull · lease · 准入 429 · 指标与故障注入 |

## 方案（详册 / 历史）

| 文档 | 状态 |
|------|------|
| [后端架构全景](plan/backend-architecture.md) | **现行详册**（机型/并发数字）；摘要已回写六篇正文 |
| [后端并发演进](plan/backend-scaling-evolution.md) | Phase 0–2 **已落地**；Phase 3 触发条件驱动 |
| [后端并发 · 开发方案](plan/backend-scaling-implementation.md) | WP0–WP9 **已落地**；WP10 未开 |
| [Coding 结构智能](plan/coding-structural-intelligence.md) | Wave 1 + 写入链揉合 **已落地**；长文日记保留作对照 |
| [工作区异步 AST](plan/agent-workspace-ast-index.md) | A6 旁路 indexer **已接线**；双轨 n5 数字待复跑 |
| [威胁情报 · 验证闭环](plan/intel-closed-loop-verification.md) | 草案 |

冲突时：**代码与契约 > 六篇正文原则 > plan 措辞**。plan 不再当作「尚未实现」的待办清单。
