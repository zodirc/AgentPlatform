# ADR-014: Turn Intake 替代意图分类 Pipeline

## 状态

已接受（2025-07-01）

## 背景

旧 `agent-langraph` 用 `event_classification_node` 在 loop 前做意图分类并路由到不同图路径。新项目采用 agentic loop（ADR-005），但若完全不管「用户输入如何进入 loop」，会出现：

1. 简单 meta 输入（`/help`、空消息）也触发完整模型调用，浪费成本；
2. 产品误以为需要恢复「意图揣测节点」才能成熟；
3. 与 Cursor 类产品的实际结构不符——它们用 **确定性 Intake + 首轮模型**，而非固定分类图。

同时，平台需要 **自用好用**（低延迟首包、可预期行为）和 **可长期运行**（成本可控、行为可回归）。

## 决策

1. **不恢复** `event_classification_node` 或任何常驻主链路的 LLM 意图分类节点。
2. 在 **`TurnController`（Turn Intake）** 内完成 loop 前处理，分三层：
   - **确定性**：`InputCompiler`（slash、`@path`、附件 → 规范化 `Message`）
   - **确定性门控**：`shouldQuery`（meta/本地命令 → 不进 `AgentEngine`）
   - **产品入口**：`scenario_id` 由用户/API 指定，**不由 LLM 猜测** writing/agent
3. **任务级意图理解**交给 `AgentEngine` **首轮**：无 `tool_use` 则直接回答，有则进入工具链；复杂规划用 `update_plan` / `delegate` 工具，非常驻阶段。
4. **快速首包**：受理后立即写 `turn.accepted`；Phase 1 起目标 TTFB ≤ 300ms（见 [`10-product-experience.md`](../10-product-experience.md)）。
5. **Phase 2+ 可选**：廉价小模型产出 **intent_tags** 仅用于日志/eval，**不参与路由**。

详见 [`05-agent-runtime.md`](../05-agent-runtime.md) §3.1。

## 理由

- 与 ADR-005/006 一致：能力增长在工具层，不在图节点
- 确定性 Intake 可测、可回归；LLM 分类难 golden
- `scenario_id` 显式选择避免模式误判，符合双产品设计（ADR-013）
- 成熟 agent 的「意图」多数是 **首轮 tool_use 决策**，不是独立 microservice

## 后果

### 正面

- 成本：meta 输入零模型调用
- Debug：Intake 与 loop 边界清晰
- 面试可讲清「为什么删掉 classification 节点」

### 负面

- `InputCompiler` / `shouldQuery` 规则需维护表（文档 + 测试）
- 极模糊输入依赖主模型澄清，可能多一轮对话

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 恢复 event_classification 节点 | 违背 ADR-005；每加场景改图 |
| LLM 自动猜 scenario_id | 与产品入口设计冲突；难回归 |
| 独立 intent 微服务 | Phase 0–2 过重；延迟与运维成本高 |
| 仅依赖主模型、无 shouldQuery | meta 输入浪费成本；首包慢 |
