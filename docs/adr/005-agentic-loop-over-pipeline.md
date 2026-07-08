# ADR-005: 采用 Agentic Loop 替代固定 Pipeline

## 状态

已接受（2025-06-30）

## 背景

`agent-langraph` 的执行内核是一张固定的 LangGraph 状态图（`app/runtime/graph.py`），脊柱为：

```text
event_classification → acknowledge → interrupt_control → incremental_planning
→ retrieval / tool / engineering → context_governance → reasoning_or_writing
→ verification → policy → output → END
```

共 13 个节点、8 个 router 文件。这是一种 **workflow**（路径由人预先编排）。它带来的问题：

- 简单输入也要穿过完整链路（分类→规划→检索→验证），延迟与成本浪费。
- 每加一种场景就要改图、加节点、加 router，改一处牵动全图。
- 检索/验证是**强制阶段**，模型无法跳过或按需多次调用。
- 业务逻辑与编排耦合在图里，难以测试和演进。

对照成熟编码 agent（Cursor / Claude Code / GitHub Copilot Agent），它们的内核都不是固定图，而是一个 **agentic loop**：模型在带工具的循环里自主决定下一步。Claude Code 的真实结构仅为 `QueryEngine`（控制器）+ `queryLoop()` 的 `while(true)`（引擎）。

## 决策

新项目 `runtime` 采用 **agentic loop** 作为唯一编排内核：

1. **模型是唯一编排者**：要不要检索/规划/验证，由模型在循环里调对应工具决定，不预设阶段。
2. **两层结构**：`TurnController`（turn 启动与收尾）+ `AgentEngine`（`while(true)` 推理循环）。
3. **messages 即核心状态**：执行轨迹编码在有序消息序列里，而非几十个业务 state 字段。
4. **LangGraph 降级为机制层**：仅承载 `loop + checkpoint + interrupt`，图退化为单循环 `agent ⇄ tools`，不承载业务编排。
5. **显式终止条件**：`final | max_steps | cancelled | budget_exceeded | fatal_error`。

详见 `docs/05-agent-runtime.md`。

## 理由

- 简单任务一轮即出，复杂任务自然多轮，成本与延迟自适应。
- 加能力 = 注册工具，不动循环（见 ADR-006），演进成本极低。
- 与 Anthropic《Building Effective Agents》关于 *agent vs workflow* 的结论一致：编码这类开放式任务应选 agent。
- 核心状态收敛到 messages，可观测/回放/计费有统一载体。

## 后果

### 正面

- 编排逻辑从 13 节点图收敛到一个循环，认知与维护成本大幅下降。
- 业务不绑定 LangGraph，未来可替换为裸循环。

### 负面

- 失控风险（停不下来/烧钱）转移到运行时，必须用 `max_steps`、token 预算、abort token 等显式护栏（见 05 §6）。
- 行为可预测性下降：路径由模型决定，需要更强的 eval 与回放体系来保证质量回归。
- 对 prompt（system prompt、工具 description）质量更敏感。

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 原样 port 13 节点固定图 | 复制旧债，违背重写初衷 |
| 混合（默认 loop + 少量固定 workflow） | Phase 0/1 暂不需要；保留为后续可选，不进内核 |
| 纯裸 while 循环（不用 LangGraph） | 放弃现成 checkpoint/interrupt 设施；保留 LangGraph 作机制层更稳 |
