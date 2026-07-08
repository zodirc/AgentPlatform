# ADR-011: Run 与 Turn 1:1 绑定

## 状态

已接受（2025-07-01）

## 背景

文档从 `agent-langraph` 继承了 `Session`、`Run`、`Turn` 概念，但未闭合现代 agentic loop 下的关系，导致：

- checkpoint 挂在 Run 还是 Turn 不明确
- 用户第二条消息是否复用 Run 存疑
- API 有 `TurnView` 却无 `Run` 资源定义

## 决策

1. **每个 Turn 恰好对应一个 Run**（1:1）；`StartTurn` 同时创建 `turn_id` 与 `run_id`。
2. 用户每条新消息创建**新 Turn + 新 Run**；禁止跨 Turn 共享执行实例。
3. **checkpoint 归属 Run**；`run_id` 为恢复与审批 resume 的主键。
4. **Step** 为 Run 内循环粒度，仅出现在事件与日志，不作为 REST 资源。
5. 跨 Turn 上下文通过 **session_context 摘要**注入，而非无限追加历史 messages。

详见 `docs/07-domain-model.md`。

## 理由

- 与「一次用户输入 = 一次受理闭环」的产品语义一致
- 简化取消、审计、计费边界
- 避免 LangGraph checkpoint 跨多轮输入的复杂合并

## 后果

### 正面

- api/runtime 表结构与命令语义清晰
- 审批与 cancel 命令可强制携带 `run_id`

### 负面

- 极长「单轮」多 Step 任务仍受单 Run 预算约束（靠 delegate 子 agent 缓解）

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| Session 级单 Run 多 Turn | checkpoint 与取消边界模糊 |
| 无 Run，仅 Turn + checkpoint | 丢失「执行实例」与图/checkpoint 机制层对接 |
