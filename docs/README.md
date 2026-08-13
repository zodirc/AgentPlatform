# 文档

Agent Platform：一个 Runtime，多个 Scenario。验证：`make gate` · `make smoke`。

## 正文（6 篇 · 每篇 2 张控制流图）

| 文档 | 图 1 | 图 2 |
|------|------|------|
| [架构](core/architecture.md) | [请求主路径](assets/architecture/request-path-zh.png) | [分模块发布台](assets/ops/release-modular-deploy-zh.png) |
| [Runtime](core/runtime.md) | [Engine 循环](assets/harness/agent-engine-loop-zh.png) | [审批·取消·恢复](assets/harness/approval-cancel-resume-flow-zh.png) |
| [工具与上下文](core/tools-and-context.md) | [组窗阶梯](assets/context/context-assemble-ladder-zh.png) | [bwrap exec](assets/sandbox/bwrap-exec-flow-zh.png) |
| [事件与契约](core/events.md) | [事件·SSE·投影](assets/events/event-sse-zh.png) | [StartTurn 命令链](assets/events/start-turn-command-zh.png) |
| [RAG](topics/rag.md) | [hybrid 店内召回](assets/rag/search-sources-flow-zh.png) | [索引面](assets/rag/index-sync-zh.png) |
| [工作台](topics/workbench.md) | [写作主路径](assets/writing/writing-main-path-zh.png) | [Ops Bench 原理](assets/ops/ops-bench-principle-zh.png) |

起栈见仓库根 README。图对齐 [`assets/harness/agent-engine-loop-zh.png`](assets/harness/agent-engine-loop-zh.png)（大字号中文 · 编号步骤 · 菱形 · 虚线边界 · 侧注 · 图例）。旧材料见 [archive/](archive/)（仅指针；正文以本目录六篇为准）。契约包：`packages/contracts`。

## 运维

| 文档 | 说明 |
|------|------|
| [Pull 分发运维手册](ops/pull-dispatch-runbook.md) | 扩缩、回退、指标阈值、故障注入、429/租约语义 |

## 方案（草案）

尚未升格正文的设计稿见 [plan/](plan/)（例如 [后端架构全景](plan/backend-architecture.md)、[Coding 结构智能 · LSP/SWE](plan/coding-structural-intelligence.md)、[Agent 工作区异步 AST](plan/agent-workspace-ast-index.md)、[威胁情报 · 验证闭环](plan/intel-closed-loop-verification.md)）。冲突时以本目录六篇为准。
