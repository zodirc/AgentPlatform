# ADR-013: Scenario 双场景与 Profile 扩展模型

## 状态

已接受（2025-07-01）

## 背景

平台定位为 **Agent Runtime**，默认特化 **写作**，同时提供 **Cursor 级通用 Agent**。需要：

1. 两种产品入口（写作 / Agent），工具与 UI 不同；
2. 未来可增场景，且**不**每加功能就改 loop 或拆服务。

若在实现中混为一套工具、或在引擎内写 `if scenario`，将重复 `agent-langraph` 的膨胀路径。

## 决策

### 产品层

1. 内置两个 **Scenario**：`scenario_id=writing`（写作模式）、`scenario_id=agent`（Agent 模式）。API 以 `scenario_id` 为准；`mode` 可为兼容别名。
2. Session 默认 `default_scenario_id=writing`；切换场景 = 新 Turn，不切换 runtime 服务。
3. 写作默认 **diff-first**（`propose_patch` → Accept → `apply_patch`）；Agent 允许直写与 `run_command`，审批更严。

### 扩展层（ScenarioProfile）

4. **ScenarioProfile** 为场景扩展的**唯一**入口：`tool_names`、子 agent 表、prompt、审批、`web_layout`。
5. `TurnController` 加载 Profile 并组装 `ToolScope`；**`AgentEngine` 不感知** `scenario_id`。
6. 工具实现在 **`tools/core/`**；Profile 只**登记**工具名。
7. 新场景 = 新 `profiles/*.yaml` +（可选）新 core 工具 + web 布局 + projection；**禁止**新 pipeline / 新 runtime。
8. 内核变更（`AgentEngine`、事件管道、`07`/`contracts` 领域模型）须新 ADR。

详见 `docs/10-product-modes.md`。

## 理由

- 一条 loop、多 Profile：符合 ADR-005/006 与成熟 agent 实践
- 开闭原则：扩展 Profile，封闭 loop
- 写作与 Agent 共享 ~70% 原语（patch、SSE、delegate）

## 后果

### 正面

- Phase 1 写作 golden；Phase 2 Agent；第三场景只增 Profile
- 审查规则：引擎 PR 不得出现 scenario 业务分支

### 负面

- 维护 ScenarioRegistry 与两套 web 布局
- 跨场景 Session 靠 `session_context` 衔接

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 仅写作 / 仅 Agent | 无法覆盖双产品期望 |
| 六种顶层 mode | 过重；写作内用 prompt 即可 |
| 两套 runtime | 违背 ADR-001 |
| 引擎内 if scenario | 不可扩展 |
| 仅 feature flag | 工具/UI 组合爆炸 |
