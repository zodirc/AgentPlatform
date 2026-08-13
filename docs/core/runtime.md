# Runtime

TurnController 外壳与 AgentEngine 单循环：从领取/Intake 到工具执行、审批挂起、取消与模型网关。两张图是权威控制流。

## 图

1. [AgentEngine 单循环](../assets/harness/agent-engine-loop-zh.png) — assemble → model → tools → checkpoint  
2. [审批 · 取消 · 恢复](../assets/harness/approval-cancel-resume-flow-zh.png) — 同 `run_id` interrupt；Cancel ≠ failed  

![AgentEngine 单循环](../assets/harness/agent-engine-loop-zh.png)

![审批 · 取消 · 恢复](../assets/harness/approval-cancel-resume-flow-zh.png)

## 1. 两层结构

```text
TurnController（不进 while）
  · 入口：pull claim（默认）或 push start-turn（回退）
  · 持有 runner lease（心跳续约）；丢失可由控制面回收
  · 加载 ScenarioProfile → 组装 ToolScope
  · Intake：InputCompiler（slash、@path、附件）→ 规范化消息
  · shouldQuery：纯本地命令可零模型结束
  · 可选弱 hint（便签级，非新图节点）
  · 发 turn.accepted 后进入 Engine；收尾写终态事件

AgentEngine while true:
  1. ContextEngine.assemble（卫生 + 80/90/95 阶梯）
  2. ModelGateway.stream（流中可 abort；Cancel 轮询约 50ms 级）
  3. 解析 text · thinking · tool_use
  4. 无 tool_use → final → 结束本 Turn
  5. 有 tool_use → 是否审批 → 执行工具 → tool_result 回灌
  6. checkpoint（同 run_id）→ 回到 1
```

- Controller 管 **Turn 前后**；Engine 管 **推理循环**，不感知 scenario 名字。  
- Guard（取消 / 分层超时 / Stall Watchdog）**旁挂全程**，不是 while 里新节点。  
- 加能力 = 注册或增强工具，**不改 while 形状**。

## 2. 分发与租约

| 项 | 行为 |
|----|------|
| **领取** | 有空位才 claim；满则不领（背压在 api 准入 / 等待领取） |
| **租约** | running 期间心跳续约；副本异常 → 回收 → 可 `failed(runner_lost)` |
| **无人领** | 超过 claim 时限 → `failed(start_timeout)` |
| **控制命令** | 取消 / 审批 / patch 等默认经 `run_commands` 送达持有 lease 的副本 |

细节与指标见 [Pull 分发运维手册](../ops/pull-dispatch-runbook.md)。

## 3. Intake（确定性，非意图分类图）

```text
用户输入
  → InputCompiler（确定性）
  → shouldQuery
       ├─ 否：本地响应（/help、部分 /compact 等）+ turn.completed
       └─ 是：进入 Engine；首轮由模型决定直答或 tool_use
```

- `scenario_id` 由 API/会话指定，**不由 LLM 猜测**。

## 4. 工具执行与审批

| 分支 | 行为 |
|------|------|
| 只读工具 | 可并行；结果经预算再进 messages |
| `run_command` / 写盘等 | 通常要审批；exec 再走沙箱（见「工具与上下文」） |
| `read_file` | 先过 `read_registry` 硬闸（可 skipped） |

审批路径：

1. 需审 → `approval.requested` → `waiting_approval`，**同 `run_id` checkpoint**。  
2. Approve → 续跑；Deny → 拒绝 `tool_result`（含原因）。  
3. **写盘粘性**：同 Turn 内批准一次后，同类写盘可免再审；**Shell 默认仍逐步审**（可有粘性策略，以实现为准）。  
4. **Plan `phase=executing`**：清单内写盘可按计划免审；普通进度清单 **≠** 已批准开工。  

正交：

- **审批门** = 允不允许跑  
- **沙箱门** = 跑起来能写哪  

控制面送达：默认 `run_commands` 通道（与 StartTurn 领取制配套）。

## 5. 取消

| 模式 | 含义 |
|------|------|
| 软取消 `cancel_requested` | 协作式停下 |
| 硬取消 `cancel_force` | 可杀流 / 子进程 |

- 终态 `cancelled`；**Cancel ≠ failed**。  
- 继续对话：同 Session **新 Turn**。  
- 模型流：Cancel 必须能打断 backoff **与** provider HTTP 流。

## 6. 模型网关

- **重试**：仅在尚未吐出 token 前。  
- **超时**：首字节快超时 + step/model/tool 分层超时；Stall Watchdog 防卡死。  
- **`GenerationParams`**：对齐输出预留、scenario temperature、`tool_choice`。  
- **reasoning**：映射为 `turn.thinking.delta`；默认不进投影正文快照。
