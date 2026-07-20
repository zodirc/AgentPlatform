# ADR-016: 执行超时与卡住检测（Stall Watchdog）

## 状态

已接受（2025-07-02）

## 背景

旧 `agent-langraph` 除「难取消」外，常见 **单步挂起数百秒**：provider 无响应、工具未设 `timeout`、pipeline 节点等待错误状态、无 Step 级看门狗。新项目去掉 13 节点强制链后，**单次 model 调用或工具 hang** 仍可能导致 Turn 长期 `running` 且无新 `turn_events`。

ADR-015 解决取消传播；本文闭合 **超时终止** 与 **卡住可观测**，针对「流程卡几百秒」类故障。

## 决策

### 1. 三层超时（runtime 强制执行）

| 层级 | 默认上限 | 触发 | 终止 |
|------|----------|------|------|
| **Model 调用** | 120s | `ModelGateway` 单次 stream/complete | `turn.failed`，`termination_reason: model_timeout` |
| **工具** | `ToolSpec.timeout_s`（默认 60s） | `ToolExecutor` | `tool.completed(status=timeout)` → 模型改道或终态 |
| **Step 墙钟** | 300s | 自 `step.started` 起无 Step 完成 | `turn.failed`，`termination_reason: step_timeout` |

Profile 可覆盖（`ScenarioProfile` / env）；默认值写入 `runtime` Settings。

规则：

- **Model 超时**须断开 provider 连接，禁止无限 await。
- **Step 墙钟**覆盖「model + tools 合计」；与 `max_steps` 正交。
- 超时与 `CancelTurn` 并行：cancel 优先于 timeout 时以 `cancelled` 为准。

### 2. Stall Watchdog（卡住检测）

runtime 内周期任务（默认每 30s）扫描活跃 Run：

```text
条件：runs.status IN (running, interrupted)
  AND turn_events 最新 sequence 的 ts 早于 now() - stall_threshold
  AND 无 cancel_requested_at
动作：结构化日志 stall_detected + metric；可选自动 fail（Phase 1 默认仅告警，Phase 2+ 可配置 auto_fail）
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `stall_threshold` | 120s | 无新 `turn_events` sequence 视为卡住 |
| `stall_auto_fail` | `false`（Phase 1） | `true` 时写 `turn.failed` + `step_timeout` |

排查入口：`09` §9「执行卡住」。

### 3. 与旧 pipeline 的对比

| 旧系统 | 新系统 |
|--------|--------|
| 多节点串行，每节点可 hang | 单 loop；hang 定位到 Step / tool / model |
| 无统一 Step 超时 | Step 墙钟 + tool timeout + model timeout |
| 用户只见「一直转」 | `stall_detected` 日志/metric + 终态 `failed` |

### 4. Golden 与 SLO

| 项 | 要求 |
|----|------|
| `shared.07` | mock provider 延迟 > model_timeout → `turn.failed` |
| metrics | `turn_stall_detected_total`、`turn_step_duration_seconds` |
| Phase 1 | 禁止无超时配置的 `run_command` handler |

## 理由

- 取消（ADR-015）解决用户主动停；超时解决 **外部依赖 hang**。
- 旧项目「卡几百秒」大量来自无界等待，非单纯 pipeline 长。
- Stall metric 使「假活」可告警，不依赖用户点取消。

## 后果

### 正面

- Turn 最长可预期等待有上界（Step 墙钟 + cancel）。
- 运维可基于 `stall_detected` 告警。

### 负面

- 合法长任务（大测试套件）需调 `timeout_s` 或 Profile 覆盖。
- Watchdog 误报需调 `stall_threshold`（流式 token 稀疏场景）。

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 仅依赖用户 Cancel | hang 时用户未操作则无限等 |
| 仅 tool timeout 无 model timeout | provider hang 仍卡死 |
| 全局进程 watchdog 杀 runtime | 误杀其他 Turn；Phase 0–2 单副本可接受粒度是 Run 级 |

## 关联文档

- [ADR-015](015-interrupt-cancel-resume.md)
- [`05-agent-runtime.md`](../05-agent-runtime.md) §8.3
- [`06-tools-and-context.md`](../06-tools-and-context.md) §5.1
- [`08-event-projection-pipeline.md`](../08-event-projection-pipeline.md) §9
- [`11-eval-and-golden-turns.md`](../11-eval-and-golden-turns.md) §5.1、`§3.3`
