# Pull 分发运维手册（成熟度）

> 对应：`TURN_DISPATCH=pull`（默认）· lease · `run_commands` · 准入 429  
> 指标：`GET /metrics`（Bearer `INTERNAL_SERVICE_TOKEN`）· Ops 概览「容量 / 分发」卡

## 1. 正常扩缩

| 目标 | 动作 |
|------|------|
| 提高并发 | `make up-ha` 或增加 runtime 副本（同 PG） |
| 单机开发 | 默认单 runtime + pull；紧内存 `COMPOSE_PROFILES= make up`（跳过 bench-pg） |
| 回退推送制 | api/runtime 设 `TURN_DISPATCH=push` 后 recreate |

加副本**不必**改 `RUNTIME_URL_MAP`（ha 已删除该依赖）。

**Ops / L1 / golden（统一 pull + StartSpec）**：

- `create_turn(ops_eval=True, model_override=…)` → `runs.ops_eval` / `model_mode` + Fernet 密文进 `turn_model_secrets`
- 仍 `pull_eligible=true` + NOTIFY；runtime claim 读 StartSpec、**一次性解密** override 后 `start_turn`
- 密钥不进 NOTIFY、不进明文列；过期/已消费由 escrow 行清理
- `TURN_DISPATCH=push` 时仍 HTTP `start_turn`（兼容回退）
- 遗留：`dispatch_notify=False` → `pull_eligible=false`（仅紧急逃生，新代码勿用）

**Web `plan_phase`**：写入 `turns.plan_phase`；pull claim 读出后传给 `start_turn`。

**`__system` / `eval-openai`**：迁移 `0023` 停用占位激活资料。评测 key 走 escrow，不再依赖 `__system` 激活项。

## 2. 关键旋钮

| 变量 | 含义 | 常见值 |
|------|------|--------|
| `TURN_DISPATCH` | `pull` / `push` | `pull` |
| `TURN_CLAIM_TIMEOUT_SECONDS` | 无人 claim → `start_timeout` | 15 |
| `RUNNER_LEASE_SECONDS` | 心跳租约 | 60 |
| `RUNNER_HEARTBEAT_INTERVAL_SECONDS` | 心跳周期 | 10 |
| `DISPATCH_QUEUE_MAX` | 全局未领取帽（0→32） | 0/32 |
| `PER_TENANT_QUEUE_MAX` | 每用户未领取帽 | 2 |
| `RUNTIME_MAX_INFLIGHT_TURNS` | 每副本 inflight | 16 |
| `RUN_COMMANDS_CHANNEL_ENABLED` | DB 命令通道 | true |
| `EVENTS_STREAM_RETENTION_DAYS` | stream 事件保留 | 7 |
| `EVENTS_STRUCTURAL_RETENTION_DAYS` | 结构事件保留 | 90 |

## 3. 读指标 → 决策

| 信号 | 阈值建议 | 动作 |
|------|----------|------|
| `dispatch_wait_seconds`（最老未领取年龄）或 claim 直方图偏高 | 持续 > 平均 Turn 时长的 ~20% | **加 runtime** |
| `dispatch_queue_depth` / `unclaimed_accepted` 顶满 | 接近 `DISPATCH_QUEUE_MAX` | 加副本或暂提高帽；客户端会 429 |
| `dispatch_start_timeout_total` 上升 | 任意持续增长 | runtime 挂了或未起 LISTEN；查健康与日志 |
| `runner_lease_misses_total` 上升 | 杀副本后应出现 | 正常回收；若误杀慢 Turn → 加大 `RUNNER_LEASE_SECONDS` |
| `turn_ttfb_seconds` / `event_pipeline_lag_seconds` | 相对基线回退 | 查 DB/事件批窗，而非盲目加副本 |

## 4. 故障注入验收（人工）

```bash
# 无人领取 → start_timeout（停 runtime 后发 Turn，等 > claim timeout）
docker stop agent-runtime
# 发一条消息；SSE 应见 turn.failed(start_timeout)；再 docker start

# 租约回收 → runner_lost（ha 下 kill -9 持有 run 的副本）
# make up-ha 后对 owner 副本 kill -9；≤ lease+reclaim 周期应 failed(runner_lost)

# 准入 429：把 DISPATCH_QUEUE_MAX=1，堆未领取 Turn，下一条应 429 + Retry-After
```

自动化入口：`make pull-dispatch-maturity`（结构/指标/保留冒烟，不做 kill）。

## 5. 迁移与回滚

- Alembic head 应含 `0022_phase2_events_retention`（runners / run_commands / lease）。  
- 回滚分发：`TURN_DISPATCH=push`（命令通道可另关 `RUN_COMMANDS_CHANNEL_ENABLED=false`）。  
- **不要**在未演练时对生产 `turn_events` 做 PARTITION 改写。

## 6. 客户端契约

| 情况 | 期望 |
|------|------|
| 排队超帽 | HTTP **429** + `Retry-After`；文案区分全局/租户 |
| 无人 claim | 先 **202**，后 SSE `turn.failed` / `start_timeout` |
| 副本租约丢 | SSE `turn.failed` / `runner_lost` |
| 仅 push | runtime 不可达仍可能 **502** |
