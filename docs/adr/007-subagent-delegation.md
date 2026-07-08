# ADR-007: 子 Agent 委派与上下文隔离

## 状态

已接受（2025-06-30）

## 背景

`agent-langraph` 用 `supervisor_decompose / supervisor_worker / supervisor_merge` 三个节点实现任务分解与合并，固化在图里。

长任务（大范围探索、并行尝试、跨多文件改动）会让主 agent 的 messages 窗口快速膨胀，触发频繁 compact，丢失关键上下文。成熟编码 agent（Claude Code、Cursor）用**子 agent**解决：派生隔离上下文的子任务，只把结论写回主循环。

## 决策

子 agent 以**一个工具** `delegate` 的形式提供（而非图节点）：

1. `delegate(task, agent_type, context)` 新建独立 `TurnState`（独立 messages 窗口），复用同一个 `AgentEngine` 执行。
2. 子 agent 工具集**可收窄**：如 `explore` 型只读、`edit` 型可写。
3. 子 agent 有独立 `max_steps`，**委派深度受限**（默认 ≤ 2，禁止无限递归）。
4. 返回主循环的只有**摘要 + 关键产物引用**，不把子 agent 的全部中间消息倒回主窗口。

详见 [`docs/05-agent-runtime.md`](../05-agent-runtime.md) §10 与 [`docs/06-tools-and-context.md`](../06-tools-and-context.md) §4。

## 理由

- 主窗口保持紧凑，长任务上下文不爆。
- 子任务可用收窄的工具集与独立预算，更安全、更聚焦。
- 复用同一引擎，无需为分解/合并单独建节点和 router。

## 后果

### 正面

- 长任务可持续推进；探索类子任务的噪音不污染主对话。
- 天然支持并行子任务（多个 `delegate` 并发）。

### 负面

- 调试更复杂：需要把子 agent 的 transcript 也纳入可观测（按 `parent_turn_id` 关联）。
- 委派深度/数量需要护栏，避免成本失控。

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 保留 supervisor 三节点 | 与 ADR-005 矛盾；分解策略写死在图里 |
| 不做子 agent，全部塞主窗口 | 长任务必然爆上下文，质量崩塌 |
