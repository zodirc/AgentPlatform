# 37 — 多 Agent 协作 Scenario（`collab`）

> **状态：已实施（CL1–CL5）· 历史 interview 只读降级沿用 RETIRED_SCENARIOS**（2026-07-31）  
> **产品意图：** 在 `writing` / `agent` / `intel` 之外增加 **编排型多 Agent 协作** 入口 `collab`（`interview` 已退役）。  
> **硬约束：**  
> 1. **不影响** Agent 交互速率与交互逻辑（服从 [13](../core/13-rate-redlines.md) R1–R5）  
> 2. **不改** `AgentEngine` while / Intake / 审批门 / Plan 相位 / 事件契约形状  
> 3. **对齐** 成熟做法：协作 = 现有 `delegate` 产品化（[ADR-007](../core/05-agent-runtime.md)），禁止 supervisor 图回潮  
> **关联：** [09](../core/09-product-modes.md) · [05](../core/05-agent-runtime.md) §10 · [06](../core/06-tools-and-context.md) · [25](writing/runway.md) · [contracts.md](../core/contracts.md)

---

## 0. 一句话

**多 Agent 协作不是新内核**：同一 `AgentEngine` + 按需 `delegate`；差异只在 `ScenarioProfile` 与 Web **团队板**只读投影。

```text
writing  = 成稿 / diff / RAG
agent    = 全能助手，按需委派
intel    = 威胁情报研判
collab   = 编排者优先：update_plan + 多次 delegate，自己少下场
```

## 编排加厚（相对软 Prefer）

- `scenarios/collab/system.md`：**Must orchestrate / Must NOT**（绿场多交付物首工具必须 `update_plan` 或 `delegate`；禁 `list_dir(".")` / 广域 `glob` 开场）
- 每 Turn `volatile_context` 注入 `[collab_orchestrator]` 短提醒（不改 Engine）
- Plan 建议阈值：`collab` = 2（比 agent/writing 的 4 更敏感）
- Profile：`delegate: never`（编排免审）；`run_command` 仍首次审批，同 Turn 后续粘性免批（`exec_preapproved`）


## 协作形态（编排型，非对等网）

成熟口径：**真协作 = 共享目标 + 分工 + 可验证上下文传递**；不是 agent 互聊总线。

| 模式 | 何时 | 机制 |
|------|------|------|
| 并行 fan-out | 子任务无依赖 | 多次 `delegate` → 摘要回主编 |
| 依赖 handoff | 后步需要前步产物 | 上游写 `artifacts/collab/`；下游带 `context_refs`；工具结果可含 `artifact_refs` |
| 黑板 | 跨工人共享 | 路径 + 短笔记；禁全文 transcript |

硬约束不变：不改 Engine / 审批门 / 事件形状；无 peer DM；深度 ≤ 2。

**角色白名单（收紧）：** `edit` · `verify` · `shell` · `explore`。绿场常见 edit+verify；retrieve/researcher/planner 不挂 collab（写作/intel 另有）。

**Harness：** 无事件 stall 默认自动收尾；edit 后未 verify 时注入 `[collab_gap]` 提醒（不改 Engine）。

**子 agent 写盘：** 嵌套 worker 免工具审批（审批挂在主编 Turn）；避免子 `write_file` 挂起却无法 resume。

**verify：** 工具表含 `run_command`（冒烟 CLI）；`delegate` 整段超时 ≥300s（避免 edit 60s 被掐）。

## Web 差异

- 路由 `/collab`；主区以主编时间线为主
- **团队 / 子任务** = 浮层子窗口（同文件预览），入口仅在左侧产物侧栏；不占主列
- 侧栏 Plan；不复制 SSE；首 token 前不调模型组队

## 证明

| Golden | 意图 |
|--------|------|
| `collab.01_delegate_explore` | ≥1 delegate / subagent |
| `collab.02_simple_no_delegate` | 无 delegate |
| `collab.03_handoff_refs` | explore→verify 接力（refs） |

## 实施票

| ID | 状态 |
|----|------|
| CL0–CL6 | ✅（interview 退役沿用 RETIRED_SCENARIOS） |

## 非目标

第二套 runtime / supervisor 图 / Agent Teams 总线 / 改 Cancel·审批语义。
