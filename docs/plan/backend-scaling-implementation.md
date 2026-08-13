# 开发方案：后端并发架构演进落地

> **状态**：实施计划 **v0.2**（2026-08-13）· **WP0–WP9 已落地**；WP10 仍为触发条件驱动  
> **上游**：[backend-scaling-evolution.md](backend-scaling-evolution.md) v0.2 · [backend-architecture.md](backend-architecture.md) v0.3  
> **定位**：把演进文档的 O1–O11 / Phase 0–3 转成**可排期、可验收、可回滚**的工程包；以仓内代码核实为准  
> **红线**：① Turn 热路径 TTFB / 事件延迟不回退；② 客户端契约（202/200/502、SSE、审批流）不破坏（O4 饱和态除外，显式开关）；③ 机型 A（6C6G）仍能跑完整产品栈

---

## 0. 一句话与交付物

**同一套「表 + NOTIFY + claim」机制同时服务单机双副本与多节点多副本；扩容只加容器/节点，不改交互语义。**

| 交付物 | 说明 |
|--------|------|
| 本方案 | 工作包、依赖、落点、测试、双机分工、合入门槛 |
| 演进文档 | 架构「为什么」；落地后回写状态 |
| 全景文档 | 落地后回写「现在是什么」对应章节 |

本方案**写代码时的执行手册**；演进文档仍是架构裁决源。冲突时：contracts / 代码事实 > 本方案 > 演进草案措辞。

---

## 1. 现状基线（代码核实，2026-08-13）

### 1.1 已具备（可复用，勿重造）

| 能力 | 落点 | 落地用途 |
|------|------|----------|
| PG 事实桥 + NOTIFY | `0005_notify_trigger` · `TurnEventListener` | O1/O2 同款通道 |
| AST `FOR UPDATE SKIP LOCKED` | `structural/workspace_index/queue.py` | O1 claim 模板 |
| Outbox SKIP LOCKED + 退避 | `services/api/app/services/outbox.py` | O7 归档任务 |
| Cancel 已落库 | `runs.cancel_requested_at` · `run_lock.persist_cancel_request` | O2 命令通道先例 |
| 副本级 inflight | `_active_turns` + `RUNTIME_MAX_INFLIGHT_TURNS` | O1「满则不领」 |
| 投影序列单调 | `turn_views` upsert `WHERE last_event_sequence <= EXCLUDED...` | O6 幂等已基本成立 |
| `projection.refresh` outbox | `queue.yml` + worker handlers | O6 拆 worker 时复用 |
| Checkpoint 审批底稿 | runtime checkpoint store | O2/O3 恢复态 |

### 1.2 关键路径（必须改的热区）

```text
【分发 · 推送制】
POST /sessions/{id}/turns
  → turns.create_turn（pending + accepted）
  → RuntimeRouter.url_for_new_turn（RUNTIME_URL_MAP 盲轮询）
  → POST /internal/commands/start-turn
  → start_turn：inflight 满 → budget_exceeded（在 claim 前 fail）
  → ensure_run_owned_by_runner（accepted→running）

【审批 · HTTP 亲和】
approve/deny/patch → runtime_client_for_turn(runner_id) → 内存 pending_store
owner 死 → approval_state_lost

【故障 · 无租约】
running 悬挂 → 同 runner 重启 reconcile_runner_orphans，或 stall≈180s
```

### 1.3 关键缺口对照

| 演进项 | 代码现状 | 缺口摘要 |
|--------|----------|----------|
| O1 | 仅 push；无 `TURN_DISPATCH` | LISTEN claim、claim 超时、`start_timeout` |
| O2 | cancel 半 DB；approve 纯 HTTP | `run_commands` 表与消费 |
| O3 | 无 lease；AST 文件心跳 | `runners`、`lease_expires_at`、回收 |
| O4 | 满则 `budget_exceeded` | 排队 + 429 帽 |
| O5 | 单例 embedder 共享 | query/index 车道 |
| O6 | 投影已单调；无单跑锁 | advisory lock；条件拆 worker |
| O7 | `turn_events` 无界 | 分区 + 分级保留 |
| O8 | work 本地 FS | `node_affinity`；盘点表 |
| O9 | `COMPOSE_PROFILES?=bench`；bench-pg 曾常驻 | bench-pg 挂 profile（**无** MACHINE=） |
| O10 | 单池 30s | 双池超时 |
| O11 | 有通用 metrics，无 SLO 五件套 | 打点 + Ops 容量卡 |

### 1.4 契约注意（实施时易踩坑）

1. **`budget_exceeded` 双义**：`turn.failed` = inflight 满；`turn.completed` = token 预算。O4 只消前者。
2. **`start_failed`**：api push 失败只写 `runs.termination_reason` + **502**，**不发** `turn.failed`。pull 的 `start_timeout` 必须走 SSE 终态。
3. **`turn_events` 时间列是 `ts`**，不是 `created_at`——分区键用 `ts`。
4. **B4 不变式**：`running` 不可被 `ensure_run_owned_by_runner` 再 claim；O3 回收必须显式改状态后再交给接手逻辑。
5. **机型 A 预算陷阱**：默认 cgroup ≈7.75GiB（含常驻 bench-pg），VM 仅 6G；O9 是 Phase 0 硬前置。

---

## 2. 目标架构（实施视角）

```text
Browser → Caddy → api×N（REST + SSE；周期任务抢 advisory lock）
                      │
                 Postgres（turns/runs+lease · turn_events · run_commands
                           · runners · work_ast_index_jobs · outbox_jobs）
                      ▲
     runtime×M LISTEN/claim Turn + 命令 + 心跳续租
     ast-indexer×K（已同构）
     （Phase 3 可选）embedding sidecar / projection-worker / pgbouncer
```

核心开关：

| 开关 | 默认 | 转正时机 |
|------|------|----------|
| `TURN_DISPATCH=push\|pull` | **pull**（WP9 转正） | `push` 可回退至弃用期结束 |
| `EMBEDDING_QUERY_PRIORITY` | true（Phase 1） | 可关对照 |
| `DISPATCH_QUEUE_MAX` / `PER_TENANT_QUEUE_MAX` | 仅 pull | 与 O4 同发 |
| `RUN_COMMANDS_CHANNEL_ENABLED` | true | false → 遗留 HTTP |

---

## 3. 工作包（WP）总览

依赖图（实线 = 硬依赖；虚线 = 软依赖/同阶段并行）：

```text
WP0 bench profile 门控 + 基线指标
  ├─► WP1 runners/租约/回收（O3）
  ├─► WP2 embedding 车道（O5）          ┐
  ├─► WP3 turn_events 分区/保留（O7）    ├─ Phase 1 可并行
  └─► WP4 DB 双池超时（O10）            ┘
        │
        ▼
WP5 Turn pull 分发（O1）◄── 依赖 WP1（lease 列可同迁）
WP6 run_commands（O2）◄── 依赖 WP5（退役 URL 路由）
WP7 准入排队 429（O4）◄── 依赖 WP5
WP8 投影/reconcile 锁（O6）  可与 WP5–7 并行
        │
        ▼
WP9 ha.yml 转 pull + 默认切换
        │
        ▼
WP10 多节点（O8 亲和 / O10 pgbouncer / O5 sidecar / O6 worker）— 触发条件驱动
```

| WP | 演进 | 优先级 | 预估 | 主战场机型 | 状态 |
|----|------|--------|------|------------|------|
| WP0 | O9+O11 基线+O8 盘点 | P0 | 2–3d | A+B | **已落地** |
| WP1 | O3 | P0 | 3–5d | B（kill 注入） | **已落地** |
| WP2 | O5 Phase1 | P1 | 2–3d | B（sync 对照） | **已落地** |
| WP3 | O7 | P1 | 3–4d | B | **已落地**（批删；分区维护窗另开） |
| WP4 | O10 双池 | P2 | 1–2d | A+B | **已落地** |
| WP5 | O1 | P0 | 5–7d | B + ha | **已落地** |
| WP6 | O2 | P0.5 | 4–6d | B + ha | **已落地** |
| WP7 | O4 | P1 | 2–3d | B | **已落地** |
| WP8 | O6 | P2 | 1–2d | B（api×2） | **已落地** |
| WP9 | 转正 | P0 | 1–2d | B | **已落地** |
| WP10 | Phase3 | 条件 | 按触发 | B 模拟双节点 | 未开 |

合计 Phase 0–2 约 **3.5–5 人周**（单人串行）；WP2/3/4/8 可与 WP1/5 并行压缩。

---

## 4. 分 WP 详案

### WP0 · Phase 0：双机整备与度量基线

**目标**：机型一键可复现；后续每阶段有 TTFB/lag 对照基线。

#### WP0-a · bench-postgres 与 bench 同门控（O9 收敛）

| 项 | 内容 |
|----|------|
| 改 | `deploy/docker-compose.yml`：`bench-postgres` 挂 `profiles: [bench]`；产品 runtime **不** `depends_on` bench-pg |
| 改 | `scripts/release/release.sh`：infra 仅在 profile 含 `bench` 时起 bench-postgres |
| **不**做 | `MACHINE=a\|b` / `dev-a.yml` / `dev-b.yml`——全景 §10 机型画像是**负载说明**，不是部署枚举；旋钮继续用手调 `.env` / 既有 compose overlay |
| 瘦身 | 内存紧的机器用 `COMPOSE_PROFILES= make up`（跳过 bench + bench-postgres） |
| 验收 | 无 bench profile 时产品栈可起；`make up-bench` 仍起 bench-pg + bench |
| 回滚 | 去掉 profile、恢复 runtime depends_on（不推荐） |

#### WP0-b · SLO 基线打点（O11 先行子集）

| 指标 | 采集点 | Phase 0 必做 |
|------|--------|--------------|
| `turn_ttfb_seconds` | api：StartTurn 受理时刻 → listener 见 `turn.accepted` | ✅ |
| `event_pipeline_lag_seconds` | api：event `ts` → SSE flush | ✅ |
| 其余三者 | 依赖 O1/O3/O5 | Phase 1–2 补齐 |

落点：`services/api/app/observability/metrics.py` · listener / SSE 路径。  
验收：stub Turn 能刮到直方图；记入「push 基线」报告（机型 A/B 各一份）。

#### WP0-c · `/data` 边界盘点（O8 文档）

回写全景 §9.2：区分「节点本地可再生」（models、HF cache）vs「必须唯一」（works、ops 报告）。**只写文档+表结构预留，不改挂载。**

---

### WP1 · runners 表与租约回收（O3）

**目标**：副本崩溃后 ≤90s 处置；AST 心跳进 DB。

#### 数据模型

```sql
-- runners
runner_id TEXT PK
kind TEXT  -- runtime | ast_indexer | bench
node TEXT
last_heartbeat_at TIMESTAMPTZ
capacity INT
inflight INT

-- runs 增列
lease_expires_at TIMESTAMPTZ NULL
```

contracts DDL + Alembic；`turn.failed` 枚举新增 **`runner_lost`**。

#### 行为

1. runtime / ast-indexer 每 ~10s UPSERT `runners`；Turn 存续期续租（租约 **60s**）。
2. api reconcile 从 300s 收紧出一条 **~30s** 租约回收（与投影 reconcile 可同任务、不同规则）：
   - `running AND lease_expires_at < now()`：
     - 无 checkpoint / 无待恢复审批 → `failed(runner_lost)`
     - 有 `waiting_approval` checkpoint → 置可恢复态（与 WP6 衔接；WP1 可先 fail-safe 为 `runner_lost` + 日志，WP6 补接手）
3. AST：过渡期 **文件+DB 双写**；healthcheck 切 DB 或 api 探活后再弃文件。

#### 落点

| 模块 | 文件 |
|------|------|
| DDL | `packages/contracts/schemas/ddl/` + alembic |
| 心跳 | `turn_controller.py` lifespan 任务 |
| 续租 | `run_lock.py` 或 turn 循环旁路 |
| 回收 | `session_projector.py` / `main.py` reconcile |
| AST | `workspace_index/worker.py` |
| 契约 | `turn.failed.json` |

#### 验收

- `kill -9` runtime 副本 → ≤90s 转 `failed(runner_lost)`（或 WP6 后接手）。
- 对照：现状 stall 180s / 仅同 runner 重启 `runner_restart`。
- 热路径：心跳不进 Turn 关键事件序列；Golden 无回归。

#### 回滚

feature flag `RUNNER_LEASE_ENABLED=false`：停心跳与回收；列可留空。

---

### WP2 · Embedding 优先级车道（O5 Phase 1）

**目标**：建库高峰时 `search_sources` p95 恶化 ≤20%。

| 步骤 | 内容 |
|------|------|
| 1 | embedder 前双车道 asyncio 队列：`query` > `index`；index batch 间 `await sleep(0)` + 抽空 query |
| 2 | CPU：`to_thread` + `torch.set_num_threads(2)`（机型 A overlay） |
| 3 | 指标：`embed_query_wait_seconds`（O11） |
| 4 | **不做** sidecar（Phase 3 触发条件未到） |

落点：`services/runtime/app/retrieval/embedder.py` · `index_embed.py` · settings `EMBEDDING_QUERY_PRIORITY`。

验收（机型 B）：全量 sync 同时 20× `search_sources`，开/关车道对照。

---

### WP3 · turn_events 分区与分级保留（O7）

| 步骤 | 内容 |
|------|------|
| 1 | 按月 `PARTITION BY RANGE (ts)`（注意：列名是 **`ts`**） |
| 2 | 分级：流式细粒度（`thinking.delta` / `turn.token` / `tool.delta`）终态 Turn **7 天**；结构事件 **90 天**；`retrieval.completed` 对齐 Ops 报告周期 |
| 3 | outbox job `events.retention` + advisory 单跑（与 WP8 共用锁模式） |
| 4 | contracts 标注各事件保留级别 |

验收：灌 30 天模拟数据后表尺寸封顶；`Last-Event-ID` 回放 p95 不随总量线性恶化。

**风险**：分区迁移需维护窗口与演练环境；**不可轻易逆迁移**——先在机型 B 空库/bench 库演练。

---

### WP4 · DB 双池与超时分级（O10 Phase 1）

| 池 | timeout | 用途 |
|----|---------|------|
| hot | **5s** | Turn / 事件 / 投影 / claim |
| bypass | **120s** | RAG sync、AST、归档、Ops |

落点：`services/{api,runtime}/app/db/pool.py` + settings；`.env` / settings 写明 `pool_size`（紧内存主机建议 api 5 / runtime 5）。  
taxonomy：热路径超时 → `db_timeout`（contracts 增补）。  
**暂不**上 pgbouncer（Σpool>60 再开）。

---

### WP5 · Turn 分发领取制（O1）★ 核心

**目标**：`TURN_DISPATCH=pull` 下加副本即扩容；满副本不领，不误杀空闲容量。

#### 行为规格

| 角色 | push（默认） | pull |
|------|--------------|------|
| api `create_turn` | INSERT + HTTP start-turn | INSERT + `pg_notify('turn_dispatch_channel', run_id)`，**不** HTTP |
| 响应 | 202/200；push 失败 502 | 202/200；无同步 502 |
| runtime | HTTP → BackgroundTasks | `TurnDispatchListener`：有空位才 claim |
| 满载 | `_fail_turn(budget_exceeded)` | **跳过 claim**（排队） |
| 无人领 | N/A | `accepted` > `TURN_CLAIM_TIMEOUT_SECONDS`（15s）→ `turn.failed(start_timeout)` |
| 兜底 | N/A | 每 ~2s 扫 `status='accepted'` |

**Intake 之后零改动**：claim 成功后进入现有 `_run_turn`。

#### 落点

| 改动 | 路径 |
|------|------|
| NOTIFY | `services/api/app/services/resource/turns.py` |
| 开关跳过 HTTP | `routers/sessions.py` |
| Listener + 空位判断 | `turn_controller.py` |
| claim | `run_lock.py`（谓词保持 `accepted`） |
| 超时规则 | api reconcile |
| 失败码 | `turn.failed.json` → `start_timeout` |
| 部署 | `ha.yml` 可先可选 pull |

#### 验收（合入门槛）

1. **Golden**：push/pull 同一 stub 会话集，事件序列 diff 为空（终态码在故障注入集另测）。
2. **R5 延迟**：pull 相对 push，TTFB p95 回退 ≤ **5ms**（同机对照）。
3. **故障**：双副本杀一，新 Turn 100% 被存活副本领取；集群容量内 **零** `budget_exceeded`。

#### 回滚

`TURN_DISPATCH=push` 一键回退；保留至 Phase 3 结束。

---

### WP6 · run_commands 命令通道（O2）

**目标**：approve/deny/patch/cancel 不依赖 owner HTTP；owner 死后可接手。

#### 数据模型

```sql
run_commands(
  id, run_id, type,  -- approve|deny|patch_accept|patch_reject|cancel
  payload jsonb,
  status,  -- pending|consumed|expired
  created_at, consumed_at
)
-- 部分唯一：同一 run 上同 type 仅一条 pending
```

#### 行为

1. api 路由：写命令行 + `pg_notify('run_commands_channel', run_id)` + **202**（语义不变）。
2. owner runtime LISTEN：仅消费 `runs.runner_id = self` 的命令。
3. 与 WP1：lease 回收发现 `waiting_approval` → 新副本可 claim 恢复路径 + 消费滞留命令。
4. cancel：Phase 2 并入表；过渡期可双写 `cancel_requested_at`。
5. 退役：`runtime_router.py` / `RUNTIME_URL_MAP` 在 pull+commands 稳定后删除。

#### 验收

审批挂起中杀 owner → 另一副本恢复并消费 approve；故障注入中 **不再**出现 `approval_state_lost`（TTL 过期除外）。

#### 延迟

人机交互秒级；+1 DB 写可忽略。

---

### WP7 · 准入与背压（O4）

**依赖**：WP5 pull。

| 规则 | 行为 |
|------|------|
| 排队 | 副本满则不领；Turn 停在 accepted |
| 全局帽 | `pending/accepted 未 claim` > `DISPATCH_QUEUE_MAX`（≈ 总 inflight×2）→ **429 + Retry-After** |
| 租户帽 | 单 principal ≥ `PER_TENANT_QUEUE_MAX`（建议 2）→ 429 |
| push 模式 | 保留 `budget_exceeded` |

落点：`routers/sessions.py` 准入 count；contracts 文档化 429。  
指标：`dispatch_queue_depth` / `dispatch_wait_seconds`。  
验收：2×容量风暴 → 零 `budget_exceeded`；超帽 429 非 5xx。

---

### WP8 · 投影幂等与 reconcile 单跑（O6）

| 项 | 动作 |
|----|------|
| 核实 | 已有 `last_event_sequence` 单调 upsert → 记入测试，双投影可接受 |
| 可选加固 | 争议时加 `pg_advisory_xact_lock(turn_id)` |
| 必做 | 周期任务（投影 reconcile、租约回收、claim 超时、事件保留）套 `pg_try_advisory_lock(常量)` |
| 不拆 worker | 除非 SSE>~1k 或投影 lag 持续超阈 |

验收：api×2 + 事件风暴 → `last_event_sequence` 无回退；reconcile 日志单副本执行。

---

### WP9 · ha 转正与默认切换

1. `ha.yml`：`TURN_DISPATCH=pull`；删除 `RUNTIME_URL_MAP`。
2. 机型 B 常态双 runtime + 全套故障注入（WP5/6/7）。
3. **通过后**：默认 `TURN_DISPATCH=pull`；push 进弃用期（文档 + settings 注释）。
4. 回写全景文档 §3/§8/§10 与演进文档「已落地」标记。

---

### WP10 · Phase 3（触发条件驱动，不提前做）

| 项 | 触发条件 | 方案摘要 |
|----|----------|----------|
| Work 节点亲和 | 加第二生产节点 | `works.node_affinity`；claim 谓词只领本节点 work |
| pgbouncer | Σ(副本×pool) > 60 | transaction pooling；LISTEN **直连**绕过 |
| projection-worker | SSE>1k 或 lag 超阈 | 搬 LISTEN→投影到 queue worker |
| embedding sidecar | 单节点 ≥2 runtime + bench | 每 GPU 节点 1 服务 |
| 演练 | Phase 2 完成后 | 同机双 compose project + 共享 PG |

**明确不做**（演进 §5）：K8s、Kafka/NATS、拆 runtime 微服务、Turn 热迁移。

---

## 5. 测试与合入策略

### 5.1 分层

| 层 | 用途 | 命令/资产 |
|----|------|-----------|
| 单元 | claim 谓词、车道调度、准入 count | `services/*/tests` |
| Golden | 交互语义不回归 | `eval/golden` · push/pull 双跑 |
| 故障注入 | kill 副本、满载、审批挂起 | 机型 B + `up-ha` |
| R5 延迟 | TTFB / pipeline lag 对照 | WP0 基线 vs 各阶段 |
| 门禁 | 合入主线 | `scripts/ci_proof.sh`（**不**把 Ops Bench 当 gate） |

### 5.2 每阶段合入检查单

- [ ] 相关 WP 验收项全绿  
- [ ] Golden 无新增 flaky  
- [ ] 无 bench profile 时产品栈仍可起（内存紧主机用 `COMPOSE_PROFILES=`）  
- [ ] 延迟：TTFB p95 相对上一阶段基线回退 ≤5ms（分发相关）或有书面豁免  
- [ ] contracts CHANGELOG 已记枚举/HTTP 语义  
- [ ] 回滚开关已验证  
- [ ] 全景/演进文档状态回写（或开 follow-up issue）

### 5.3 建议新增/扩展用例

| 用例 | 覆盖 |
|------|------|
| `eval/golden/...` pull 镜像集 | O1 事件序列 |
| 故障：kill owner + approve | O2/O3 |
| 风暴：并发 StartTurn = 2×cap | O4 |
| sync∥search_sources | O5 |
| api×2 投影 | O6 |

---

## 6. 双机分工与排期建议

| 周 | 机型 A（6C6G） | 机型 B（9800X3D+5080） |
|----|----------------|------------------------|
| W0 | WP0 overlay 验证、内存账 | WP0 指标基线、GPU 栈确认 |
| W1 | WP4 双池；文档/契约辅助 | WP1 租约 + kill 注入；WP2 车道 |
| W2 | 功能开发不挡主线 | WP3 分区演练；WP5 pull 实现 |
| W3 | pull 单副本冒烟 | WP5/6/7 + ha 故障全套 |
| W4 | — | WP8/9 转正；开 WP10 演练（可选） |

原则：**B 做破坏性与性能对照；A 验证「瘦身配方仍能开发」。**

---

## 7. 契约与前端影响清单

| 变化 | 模式 | 前端/客户端 |
|------|------|-------------|
| `start_timeout` | pull 故障态 | 已有 `turn.failed` 渲染；补文案 |
| `runner_lost` | 租约回收 | 同上 |
| 502 `start_failed` | 仅 push | 保留 |
| 429 + Retry-After | pull 超排队帽 | **需**处理重试/提示（可先最小：展示错误码） |
| 排队中 view=`pending` | pull | 可选「排队中」UI（非必须） |
| `approval_state_lost` 减少 | O2 后 | 监控告警下调预期 |

`packages/contracts` 变更必须先合、再服务、再 Golden。

---

## 8. 风险登记

| 风险 | 等级 | 缓解 |
|------|------|------|
| pull 故障语义 202+异步 fail 被误认为回归 | 中 | 文档+契约+前端文案；Golden 分「正常集/故障集」 |
| 分区迁移锁表/耗时 | 高 | B 演练；维护窗口；保留策略可先软删后分区 |
| bench-pg profile 化破坏 Ops L1 | 中 | L1 文档改为显式 `profile bench`；CI 评测 job 显式开 |
| lease 误杀慢 Turn | 中 | 租约 60s + 心跳 10s；续租挂在事件循环旁路；监控 `runner_lease_misses_total` |
| 双池漏切导致热路径仍 30s | 低 | 代码审 + 慢查询注入测 `db_timeout` |
| 过早做 sidecar/pgbouncer | 低 | 严格按触发条件；本方案 WP10 门禁 |

---

## 9. 「改 X 去哪」速查（实施用）

| 改什么 | 落点 |
|--------|------|
| 分发模式 | `TURN_DISPATCH` · `turns.py` · `sessions.py` · `turn_controller.py` |
| claim / 租约 | `run_lock.py` · `runs.lease_expires_at` |
| 命令通道 | `run_commands` DDL · `routers/turns.py` · runtime 命令 listener |
| 准入帽 | `sessions.py` · `DISPATCH_QUEUE_MAX` |
| runners 心跳 | runtime/ast lifespan · `runners` |
| 投影/回收单跑 | `main.py` · `session_projector.py` · advisory lock |
| embedding 车道 | `retrieval/embedder.py` |
| 事件保留 | alembic 分区 · outbox `events.retention` |
| 机型 | `deploy/docker-compose.yml` · bench `profiles: [bench]`（**无** MACHINE=/dev-a/b） |
| 指标 | api/runtime `observability/metrics.py` · `ops/overview.py` |
| 失败码 | `packages/contracts/schemas/events/payloads/turn.failed.json` |

---

## 10. 建议的首个 PR 切片（降低一次性风险）

按「可独立合并」切，避免巨型 PR：

1. **PR-0**：bench-postgres → `profiles: [bench]` + release infra 同步（**不**引入 `MACHINE=`）  
2. **PR-0.1**：`turn_ttfb_seconds` + `event_pipeline_lag_seconds`  
3. **PR-1**：`runners` + `lease_expires_at` + 心跳 + `runner_lost` 回收（flag 默认开，可关）  
4. **PR-2**：embedding 车道  
5. **PR-3**：DB 双池  
6. **PR-4**：`TURN_DISPATCH=pull` 实现（默认仍 push）+ `start_timeout`  
7. **PR-5**：`run_commands` + 审批改写库  
8. **PR-6**：准入 429 + dispatch 指标  
9. **PR-7**：advisory 单跑锁 +（可选）事件分区  
10. **PR-8**：ha 改 pull + 默认切换 + 文档回写  

事件分区若风险高，可从 PR-7 拆成独立维护窗口 PR。

---

## 11. 与上游文档的维护约定

- 每完成一个 WP：演进文档对应 O# 标「已落地 → 见 commits/PR」；全景文档改「现在是什么」。  
- 本方案版本随大阶段 bump（Phase 0 完成 → v0.2）。  
- 新发现的代码事实若否定演进假设：先改演进文档裁决，再改本方案，避免实施漂移。

---

## 附录 A · 环境变量清单（落地后应存在）

| 变量 | 阶段 | 默认建议 |
|------|------|----------|
| （无 `MACHINE=`） | 0 | 机型用 `.env` / §10 手调；bench-pg 靠 `COMPOSE_PROFILES` |
| `TURN_DISPATCH` | 2 | **`pull`**（`push` 回退） |
| `TURN_CLAIM_TIMEOUT_SECONDS` | 2 | 15 |
| `RUN_COMMANDS_CHANNEL_ENABLED` | 2 | true |
| `RUNNER_LEASE_SECONDS` | 1 | 60 |
| `RUNNER_HEARTBEAT_INTERVAL_SECONDS` | 1 | 10 |
| `RUNNER_LEASE_ENABLED` | 1 | true |
| `DISPATCH_QUEUE_MAX` | 2 | 0→默认 32 |
| `PER_TENANT_QUEUE_MAX` | 2 | 2 |
| `EMBEDDING_QUERY_PRIORITY` | 1 | true |
| `DB_HOT_STATEMENT_TIMEOUT_SECONDS` | 1 | 5 |
| `DB_BYPASS_STATEMENT_TIMEOUT_SECONDS` | 1 | 120 |
| `EVENTS_STREAM_RETENTION_DAYS` | 1 | 7 |
| `EVENTS_STRUCTURAL_RETENTION_DAYS` | 1 | 90 |

## 附录 B · 失败码增量

| 码 | 何时 | 通道 |
|----|------|------|
| `start_timeout` | pull 下无人 claim | SSE `turn.failed` |
| `runner_lost` | 租约过期且不可恢复 | SSE `turn.failed` |
| `db_timeout` | 热路径 statement_timeout | 计入 taxonomy（路径依调用点） |
| 429 | 排队超帽 | HTTP StartTurn |
| `budget_exceeded`（inflight） | **仅 push** | 保持 |
| `start_failed` + 502 | **仅 push** | 保持 |
