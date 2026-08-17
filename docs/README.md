# 文档

Agent Platform：一个 Runtime，多个 Scenario。验证：`make gate` · `make smoke`。

## 分页导览（HTML）

```bash
make docs-tour
# http://127.0.0.1:8765/tour/
```

文件：[`tour/index.html`](tour/index.html)。导览是六篇的分页版；**现行流程以六篇正文为准**。

评测日记（含第 4/5 轮 coding 4/5）：[`eval/official/baseline/RESULTS.md`](../eval/official/baseline/RESULTS.md)。SCORECARD 机器栏只保留最近一次 `update-baseline` 指针，**不是**最新冒烟。

## 正文（6 篇 · 每篇配控制流图）

| 文档 | 图 1 | 图 2 |
|------|------|------|
| [架构](core/architecture.md) | [请求主路径](assets/architecture/request-path-zh.png) | [分模块发布台](assets/ops/release-modular-deploy-zh.png) |
| [Runtime](core/runtime.md) | [Engine 循环](assets/harness/agent-engine-loop-zh.png) | [审批·取消·恢复](assets/harness/approval-cancel-resume-flow-zh.png) |
| [工具与上下文](core/tools-and-context.md) | [组窗阶梯](assets/context/context-assemble-ladder-zh.png) | [exec 沙箱](assets/sandbox/bwrap-exec-flow-zh.png) · [Coding 揉合](assets/harness/coding-fuse-zh.png) |
| [事件与契约](core/events.md) | [事件·SSE·投影](assets/events/event-sse-zh.png) | [StartTurn 命令链](assets/events/start-turn-command-zh.png) |
| [RAG](topics/rag.md) | [hybrid 召回](assets/rag/search-sources-flow-zh.png) | [索引面](assets/rag/index-sync-zh.png) |
| [工作台](topics/workbench.md) | [写作主路径](assets/writing/writing-main-path-zh.png) | [Ops Bench 原理](assets/ops/ops-bench-principle-zh.png) |

起栈见仓库根 README。图范式是 **主链详流**（样板：[`StartTurn 命令链`](assets/events/start-turn-command-zh.png)）：左辅栏 · 中宽条带主链（编号圆 + 箭头脊柱 + 黄菱形是/否）· 右辅栏 · 底「要点」。整张手绘 1536×1024 RGB PNG；禁止脚本/卡片堆、禁止在旧图上涂改。

冲突时：**代码与契约 > 本目录六篇正文 > 导览（分页）**。数字以 [`RESULTS.md`](../eval/official/baseline/RESULTS.md) 为准。`docs/plan/` 是落地前的临时草稿，**不参与权威**；无用后删除即可。

## 契约

| 文档 | 说明 |
|------|------|
| [契约索引](contracts.md) | OpenAPI · 事件 · **Ops manifest schema** · L1 评测纪律 |

## 运维

| 文档 | 说明 |
|------|------|
| [Pull 分发运维手册](ops/pull-dispatch-runbook.md) | 默认 pull · lease · 准入 429 · 指标与故障注入 |

## 临时草稿（`plan/` · 可删）

落地前的诊断与机型草稿。**现行流程不要从这里读**；已回写六篇的条目随时可删。未落地的 intel 闭环仍只是草案，实施时直接改 Profile / 工具 / 正文，不必先扩 plan。

| 草稿 | 去向 |
|------|------|
| backend-architecture | 资源上限、改点表已进 [架构](core/architecture.md) |
| coding-structural-intelligence | 现行 Turn 已进 [工具与上下文](core/tools-and-context.md) · [Runtime](core/runtime.md) |
| quality-uplift-2026-08 | 诊断史；效果看 RESULTS |
| agent-workspace-ast-index | 旁路说明已进架构 ast-indexer 行 |
| intel-closed-loop-verification | 未实施；intel 场景以 Profile 现状为准 |
