# ADR-008: 上下文工程多层防线（budget / compact / collapse）

## 状态

已接受（2025-06-30）

## 背景

编码 agent 的长会话会累积大量 messages（文件内容、grep 结果、命令输出、多轮工具结果）。`agent-langraph` 的 `prompt_context_gateway` 与 token budget 分散在多处，且与固定 pipeline 阶段耦合。

若不每轮主动治理上下文，将导致：

- 模型调用延迟与费用失控
- 关键约束被历史噪音淹没
- 子 agent 返回大段中间态倒灌主窗口

## 决策

1. 引入 **`ContextEngine`**，在**每一轮 Step 调模型之前**执行 `assemble(state) → list[Message]`，不是一次性预处理阶段。
2. 采用多层防线，按顺序执行（详见 `docs/06-tools-and-context.md`）：

   ```text
   取消息窗口
   → apply_tool_result_budget
   → snip
   → microcompact
   → collapse
   → autocompact（兜底）
   → 调模型
   ```

3. **budget**：按类别限制 token 占比（工具结果、thinking、输出等）；超大 tool result 截断并保留重读指针。
4. **collapse / autocompact**：将冷历史折叠为摘要 + 引用；热上下文保留原文。
5. **检索结果**只能通过工具 `tool_result` 进入窗口，禁止每轮预注入 RAG 包。
6. 子 agent 回流主循环时**只带回摘要与产物引用**，禁止全量 messages 合并。
7. 每轮组装必须记录压缩前后 token 估计与触发策略，便于 debug（见 06 §13.2）。

## 理由

- 与 Cursor、Claude Code 等成熟 agent 的上下文治理方向一致
- 将治理从「图节点」抽离为每轮基础设施，与 ADR-005 agentic loop 正交
- 多层策略比单一「全量摘要」更可控，降低信息丢失与行为抖动
- 性能：整理成本应显著低于不整理带来的模型成本

## 后果

### 正面

- 长任务可持续执行，主路径不依赖无限上下文窗口
- 压缩策略可独立测试与调参
- 与工具截断、RAG 预算形成统一防线

### 负面

- 过度压缩可能导致模型「遗忘」关键细节，需 eval 与指针机制
- 实现复杂度高于「直接塞全历史」
- 各层策略需版本化，避免 silent behavior change

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 依赖模型超长上下文硬撑 | 成本与延迟不可控 |
| 仅在 Turn 开始压缩一次 | 多 Step 后仍膨胀 |
| 固定 pipeline 的 context_governance 节点 | 与 ADR-005 矛盾；非每轮执行 |
| 无预算，靠工具自觉截断 | 错误边界后置，不可审计 |
