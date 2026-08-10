# Runtime

TurnController 外壳与 AgentEngine 单循环：从 Intake 到工具执行、审批挂起、取消与模型网关。两张图是权威控制流。

## 图

1. [AgentEngine 单循环](../assets/harness/agent-engine-loop-zh.png) — assemble → model → tools → checkpoint  
2. [审批 · 取消 · 恢复](../assets/harness/approval-cancel-resume-flow-zh.png) — 同 `run_id` interrupt；Cancel ≠ failed；图内含与 Landlock/bwrap 正交说明（无外链断图）  

![AgentEngine 单循环](../assets/harness/agent-engine-loop-zh.png)

![审批 · 取消 · 恢复](../assets/harness/approval-cancel-resume-flow-zh.png)

## 1. 两层结构

```text
TurnController（不进 while）
  · 接收 StartTurn / 恢复上下文
  · 加载 ScenarioProfile → 组装 ToolScope
  · Intake：InputCompiler（slash、@path、附件）→ 规范化消息
  · shouldQuery：纯本地命令可零模型结束
  · 可选弱 hint（plan_hint / memory_hint，便签级，非新图节点）
  · 启动 run_id 进入 Engine；收尾写终态事件

AgentEngine while true:
  1. ContextEngine.assemble（卫生 + 80/90/95 阶梯）
  2. ModelGateway.stream（流中可 abort；Cancel 轮询约 50ms 级）
  3. 解析 text · thinking · tool_use
  4. 无 tool_use → final → 结束本 Turn
  5. 有 tool_use → 是否审批 → 执行工具 → tool_result 回灌 messages
  6. checkpoint（同 run_id）→ 回到 1
```

- Controller 管 **Turn 前后**；Engine 管 **推理循环**，不感知 scenario 名字。  
- Guard（取消 / 分层超时 / Stall Watchdog）**旁挂全程**，不是 while 里新节点。  
- Proof（`turn_events`、Golden/`make gate`）主在环外记账与证明。

放弃固定 13 节点 pipeline：加能力 = 注册工具，**不改 while 形状**。

## 2. Intake（确定性，非意图分类图）

```text
用户输入
  → InputCompiler（确定性）
  → shouldQuery
       ├─ 否：本地响应（/help、部分 /compact 等）+ turn.completed
       └─ 是：进入 Engine；首轮由模型决定直答或 tool_use
```

- `scenario_id` 由 API/会话指定，**不由 LLM 猜测**。  
- 不恢复旧项目那种 `event_classification_node` 意图大图。

## 3. 工具执行与审批

进入 `ToolExecutor` 后：

| 分支 | 行为 |
|------|------|
| 只读工具 | 可并行；结果经预算再进 messages |
| `run_command` / 写盘等 | 通常要审批；exec 再走沙箱（Landlock→bwrap，见「工具与上下文」图 2） |
| `read_file` | 先过 `read_registry` 硬闸（可 skipped）；降重复读 |

审批路径（与图 2 一致；图已自包含审批×沙箱正交说明）：

1. 需审 → `approval.requested` → `waiting_approval`，**同 `run_id` checkpoint 挂起**。  
2. Approve → 从 checkpoint 续跑；Deny → 写拒绝 `tool_result`（含原因），由模型/策略决定继续或收束。  
3. **写盘粘性**：同 Turn 内批准一次后，同类写盘可免再审；**Shell 仍逐步审**。  
4. **Plan `phase=executing`**：清单内写盘可按计划免审；普通 `update_plan` 进度清单 **≠** 已批准开工。  

正交关系：

- **审批门** = 允不允许跑  
- **bwrap / Landlock** = 跑起来能写哪（实现细节在工具文 bwrap 图）

## 4. 取消

| 模式 | 含义 |
|------|------|
| 软取消 `cancel_requested` | 协作式停下 |
| 硬取消 `cancel_force` | 可杀流 / 子进程 |

- 终态 `cancelled`；**Cancel ≠ failed**。  
- 继续对话：同 Session **新 Turn**，没有 ResumeTurn API。  
- 模型流：Cancel 必须能打断 backoff **与** provider HTTP 流（abort→`aclose`）；已请求取消时，transport 错误不得升成「流已开始后的 fatal」误报。

## 5. 模型网关

统一走 `ModelGateway`：

- **重试**：仅在尚未吐出 token 前；已开始流式则不按「可重试瞬断」乱重放。  
- **超时**：首字节快超时 + step/model/tool 分层超时；Stall Watchdog 防卡死。  
- **`GenerationParams`**：`max_output_tokens` 对齐 `output_reserve_tokens`、scenario temperature、`tool_choice`；thinking 默认策略按配置。  
- **reasoning**：映射为 `turn.thinking.delta` 进 SSE；默认不进投影正文快照。  

代码入口：`controller/` · `engine/` · `model/gateway.py` · `model/stream_abort.py`。
