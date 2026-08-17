# Runtime

TurnController 外壳与 AgentEngine 单循环：从领取/Intake 到工具执行、审批挂起、取消与模型网关。两张图是权威控制流。

## 图

1. [AgentEngine 单循环](../assets/harness/agent-engine-loop-zh.png) — assemble → model → tools → checkpoint（模型想收工却还没验完时再跑一轮，见正文，未改海报骨架）  
2. [审批 · 取消 · 恢复](../assets/harness/approval-cancel-resume-flow-zh.png) — 同 `run_id` interrupt；Cancel ≠ failed  

![AgentEngine 单循环](../assets/harness/agent-engine-loop-zh.png)

![审批 · 取消 · 恢复](../assets/harness/approval-cancel-resume-flow-zh.png)

## 1. 两层结构

api 把一次提问落库之后**并不把任务推到 runtime**。runtime 自己来领活：有空位才领，领了之后用租约心跳续约；心跳断了这题作废，控制面可以收回给别的副本。满负荷时不领，压力挡在 api 准入（队列满回 429）而不是把 runtime 撑爆。超过领取时限仍无人领，记为 `failed(start_timeout)`；租约丢失且无法安全续跑，记为 `failed(runner_lost)`。取消、审批、接受补丁这类控制命令，默认走同一条命令通道，送给**当前持有租约**的那份 runtime。

```text
TurnController（不进 while）
  · 入口：runtime 自己领取（默认）或 api HTTP 推送 start-turn（回退）
  · 持有 runner 租约（心跳续约）；丢失可由控制面回收
  · 加载 ScenarioProfile → 组装 ToolScope
  · Intake：InputCompiler（slash、@path、附件）→ 规范化消息
  · shouldQuery：纯本地命令可零模型结束
  · 可选弱 hint（便签级，非新图节点）
  · 发 turn.accepted 后进入 Engine；收尾写终态事件

AgentEngine while true:
  1. ContextEngine.assemble（卫生 + 80/90/95 阶梯）
  2. ModelGateway.stream（流中可 abort；Cancel 轮询约 50ms 级）
  3. 解析 text · thinking · tool_use
  4. 有 tool_use → 是否审批 → 执行工具 → tool_result 回灌 → checkpoint → 回到 1
  5. 无 tool_use → 若模型写完就收工、但还欠验证 → 塞一条用户口吻提醒再跑一轮
                 → 否则 final → 结束本 Turn
```

第 5 步那条提醒**不是新工具名**，菜单里点不到，对话记录里也不是 `tool_result`：平台把它写成一条用户消息打进窗，同时落一条带 `verify_receipt=true` 的 `tool.completed` 事件，然后 `continue`。两类欠账会触发：成功改过代码却还没跑过测试类命令；仓库测试已经绿了，但 `problem.md` 里写过的例子还没在**最新一次编辑之后**被成功命令覆盖。不挡取消/失败；每类每 Turn 至多一次；剩下步数不够（默认还要留 10 步）则省略。这两类「还欠什么」写进 checkpoint，审批挂起后再续跑不能丢。

- Controller 管 **Turn 前后**；Engine 管 **推理循环**，不感知 scenario 名字。  
- Guard（取消 / 分层超时 / Stall Watchdog）**旁挂全程**，不是 while 里新节点。  
- 加能力 = 注册或增强工具 / 结果契约，**不改 while 形状**（想收工却还欠验证时的再跑一轮，是第 5 步的旁路 continue，不是新图节点）。

## 2. 分发与租约

细节与指标见 [Pull 分发运维手册](../ops/pull-dispatch-runbook.md)。上面已经说明领取、租约、无人领和控制命令怎么配合；手册里是旋钮、指标和故障注入。

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
| 只读工具 | 连续只读可并行；结果经预算再进窗 |
| `run_command` / 写盘等 | 通常要审批；过门后再进沙箱（见「工具与上下文」） |
| `read_file` | 先过已读登记（覆盖区间可 skipped）；每 Turn 有次数帽 |
| 编码改完再验 | 每条工具结果更新「还欠测试 / 还欠 issue 例子」；checkpoint 必须能恢复 |

执行前 handler 可能整条改道（仍是同一工具名）：纯翻页读文件 → `read_file`；裸符号 grep → 找定义；官方编码评测下 pytest/`|tail` → 进该题 Docker 镜像跑完整测试。详见 [工具与上下文 §2](tools-and-context.md)。

审批路径：

1. 需审 → 发审批请求 → `waiting_approval`，**同 `run_id` checkpoint**（含「还欠测试 / 还欠 issue 例子」）。  
2. 批准 → 续跑；拒绝 → 把原因写进 `tool_result`，由模型决定改方案或结束。  
3. **写盘粘性**：同 Turn 内批准一次后，同类写盘可免再审。  
4. **shell 粘性**：`run_command` **第一次仍要审**；通过后本 Turn 后续同类 shell 可免再审。Plan `executing` 只预授权清单内写盘，**不等于** shell 免审。普通进度清单更新 **≠** 已批准开工。  
5. **官方评测无人值守**：这次提问带评测标记时，StartTurn 即置写盘/exec 预批准，不拦人审。  

正交：

- **审批门** = 允不允许跑  
- **沙箱门** = 跑起来能写哪  
- **解题改道** = 官方编码评测下，测/探针进该题 Docker 镜像，与上面两门都正交  

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
- **`GenerationParams`**：对齐输出预留、scenario temperature、`tool_choice`。OpenAI 兼容路径：GPT-5.x 默认带 `reasoning_effort=high`，DeepSeek 带 `thinking` + `reasoning_effort`；中转 400/422 则剥掉未知字段重试。  
- **reasoning**：映射为 `turn.thinking.delta`；默认不进投影正文快照。
