# 方案：后端并发架构演进（双机开发 → 可扩容部署）

> **状态**：优化草案 **v0.2**（2026-08-13）· Phase 0–2 / WP0–WP9 **已落地**（见 [`backend-scaling-implementation.md`](backend-scaling-implementation.md)）  
> **定位**：不改交互语义的前提下，把当前"单机 compose 架构"演进为"同构可扩容架构"的**优化清单与分阶段执行方案**  
> **红线**：本方案所有优化项必须满足 —— ① Turn 热路径 TTFB / 事件延迟不回退；② 客户端契约（202/200/502、SSE、审批流）不破坏（O4 饱和态除外）；③ 机型 A（6C6G）仍能跑完整产品栈

---

## 0. 目的 · 原则 · 非目标

### 0.1 目的

一句话：**让"单机双副本"和"多节点多副本"跑同一套机制**——扩容时只加节点、不改架构。

当前架构（v0.2 全景文档）在单机 compose 下工作良好，但向"真正并发部署"演进时有一组结构性弱点（§1.2）。本方案将它们分级，逐项给出"现状 → 问题 → 方案 → 延迟影响 → 落点 → 验收"，并映射到两台开发机的分阶段执行计划（§4）。

### 0.2 原则（对应用户约束）

| # | 原则 | 落实方式 |
|---|------|----------|
| P-1 | **不影响 agent 交互速率与交互逻辑** | 每个优化项单列「延迟影响」分析；涉及契约变化的（仅 O4 饱和态语义）显式标注并给开关 |
| P-2 | **成熟后端并发视角：同构扩展** | 核心判断见 §2：分发从"静态推送"转"声明式领取"，控制命令统一走 DB 通道，状态从 FS/内存收敛到 PG |
| P-3 | **先裁决后实施** | 本文定架构；工程包见 implementation 方案 |

### 0.3 非目标（明确不做，见 §5 详述）

- **不**引入 Kubernetes / 服务网格 / 独立消息中间件（Kafka/NATS）——PG 在当前量级下是足够的事实桥与队列。
- **不**拆微服务——runtime 仍是单体 agentic loop，只把"资源竞争者"（embedding、投影）旁路化。
- **不**重写事件管道——`BufferedEventWriter → NOTIFY → LISTEN → SSE` 保留原样。

---

## 1. 现状评估

### 1.1 值得保留的设计（本方案的地基，不动）

| 设计 | 为什么好 |
|------|----------|
| PG 作为唯一跨服务事实桥（INSERT + NOTIFY/LISTEN） | 无额外中间件；事件有序、可回放（`Last-Event-ID`）；天然支持多消费者 |
| 服务间无 Python 互 import，契约收敛在 `packages/contracts` | 副本化 / 异构部署的前提已具备 |
| AST 走 `work_ast_index_jobs` + `FOR UPDATE SKIP LOCKED` | **已经是"领取制"**——加 indexer 副本即扩容，这正是 O1 要推广到 Turn 分发的模式 |
| cancel 意图落 `runs.cancel_requested_at`（`run_lock.py`） | **已经是"DB 命令通道"**——HA 安全、全副本可见，O2 直接复用该先例 |
| `_active_turns` + `RUNTIME_MAX_INFLIGHT_TURNS` 副本级准入 | 每副本独立计数、不靠共享内存，横向扩展友好 |
| 重活旁路原则（AST 独立容器、Bench 独立容器、prewarm 不挡受理） | CPU 调度原则 §8.2 已经内化，扩容后依然成立 |
| `outbox_jobs`（`services/api/app/services/outbox.py`） | 通用 job 表 + SKIP LOCKED + 退避重试已实现，只是尚未承载主链路 |

### 1.2 扩展性弱点清单（分级）

| 级 | 编号 | 弱点 | 证据（代码/文档） | 对应优化 |
|----|------|------|-------------------|----------|
| **P0** | W1 | Turn 分发靠**静态 URL 表 + 盲轮询**：`RUNTIME_URL_MAP` 是 env 里的 JSON；加副本要改 env + 重启 api；轮询不感知副本 inflight 水位 | `services/api/app/services/command/runtime_router.py`：`url_for_new_turn()` 纯 round-robin | O1 |
| **P0** | W2 | 轮询可把 Turn 推给已满副本 → 明明集群有空位却报 `budget_exceeded` fail | 同上 + `turn_controller` inflight 检查在**受理后** | O1 |
| **P0** | W3 | run claim **无租约/心跳**：副本崩溃后其 running Turn 无人接管，只能等 stall watchdog（默认 180s，且 `STALL_AUTO_FAIL` 可选）或该副本重启 reconcile | `run_lock.py` B4 注释："Crashed 'running' runs are failed by the startup reconcile" | O3 |
| **P1** | W4 | 审批挂起态**副本亲和**：approve/deny 走 `url_for_runner(runner_id)` HTTP 直达 + 内存 `pending_store`；owner 副本死亡 → `approval_state_lost` | `runtime_router.url_for_runner` · 失败 taxonomy §8.3 | O2 |
| **P1** | W5 | 饱和态**报错而非排队**：inflight 满 → Turn 直接 fail `budget_exceeded`，对用户是错误而非等待 | §8.1 并发矩阵 | O4 |
| **P1** | W6 | Embedding **进程内共享**：Turn 内 `search_sources` 查询 embed 与建库批量 embed 同一实例；建库高峰查询延迟上升（文档已自认"属预期"）；多 runtime 副本 = 每副本一份模型 RSS/VRAM | §10.2 CPU/GPU 调度画像 B 的注释 | O5 |
| **P1** | W7 | `turn_events` 无保留/归档策略：`thinking.delta`、`turn.token` 等高频事件全量落表，长期膨胀拖慢投影兜底轮询与 `Last-Event-ID` 回放 | §3.2 · §9.1 | O7 |
| **P1** | W8 | 多节点硬阻塞：Work 数据在**节点本地 FS**（`/data/works/{id}`、`/workspace`）；AST 心跳是**文件**（`/data/ast_indexer_heartbeat`）；models 卷每节点一份 | §1.3 卷 · §5.2 | O8 |
| **P2** | W9 | api 单进程身兼四职（REST、SSE fanout、LISTEN→投影、周期 reconcile）：SSE 长连接数是单进程天花板；投影多副本竞争语义未定义 | §2.2 lifespan | O6 |
| **P2** | W10 | 机型配方停留在文档：§10 的 env 旋钮靠手抄 `.env`，机器间切换易错；bench-postgres 在机型 A 上常驻占 1g cgroup | §10.1 · §1.2 | O9 |
| **P2** | W11 | DB 连接面未规划：多副本 × asyncpg pool 直连 PG；`statement_timeout≈30s` 一刀切（热路径与索引/投影混用） | §8.1 | O10 |
| **P2** | W12 | 扩容缺"何时扩"的量化信号：有 `/metrics` 但无 SLO 口径（TTFB、事件管道 lag、排队深度） | §10.4 | O11 |

---

## 2. 目标架构：一个核心判断

### 2.1 判断：分发从「推」转「领」，控制从「HTTP 直达」转「DB 通道」

现状与目标的对照：

```text
【现状 · 推送制】
api ──静态URL表·轮询──► runtime-a  /internal/commands/start-turn（202 或 502）
api ──runner_id反查──► runtime-b  /internal/commands/approve-tool-call
        问题：路由表=拓扑硬编码；盲轮询；owner 死则审批丢

【目标 · 领取制】（AST 队列模式的推广）
api：INSERT turns(pending)+runs(accepted) ──同事务──► pg_notify('turn_dispatch')
runtime-a/b/…：LISTEN 唤醒 → 有空位（inflight<cap 且 work 可服务）才 claim
               （复用 run_lock 原子 UPDATE，加租约列）
api：审批/取消/patch 决策 ──INSERT run_commands + NOTIFY──► owner 副本 LISTEN 消费
        收益：加节点=起容器；容量感知天然负载均衡；无路由表；命令不怕 owner 迁移
```

**为什么这是唯一需要下的架构决心**：领取制之后，"单机双副本（ha.yml）"与"三节点九副本"在机制上完全同构——扩容动作退化为「新节点起 runtime 容器 + 指向同一 PG」。而 AST indexer（SKIP LOCKED）与 outbox worker 已经证明这套模式在本项目内可行。

### 2.2 延迟论证（P-1 红线）

| 路径 | 现状 | 领取制 | 差值 |
|------|------|--------|------|
| api 受理 | INSERT 事务 + HTTP push（~1–3ms）+ 202 | INSERT 事务（NOTIFY 挂在同事务，免费）+ 202 | api 侧**更快**（少一次同步 HTTP） |
| runtime 拿到 Turn | HTTP handler → BackgroundTasks | LISTEN 唤醒（亚 ms）+ claim UPDATE（~1ms） | +1ms 级 |
| 首事件 `turn.accepted` 到达浏览器 | 上述之和 + `EVENT_BATCH_WINDOW≈40ms` + NOTIFY→SSE | 同 | **被 40ms 批窗淹没，不可观测** |

结论：领取制对 TTFB 的影响在毫秒级、低于现有事件批窗粒度，满足 P-1。唯一语义变化是**失败面**：现状"api push 失败 → 同步 502"；领取制下 push 失败不存在，取而代之是"超时无人 claim → 异步 `turn.failed(start_timeout)`"。处理见 O1 的契约小节。

### 2.3 目标拓扑（Phase 3 形态，向下兼容单机）

```text
                    ┌──────────── 节点 1（或唯一节点）────────────┐
Browser → Caddy ──► │ api ×N（REST+SSE fanout；无状态）           │
                    │ projection-worker（LISTEN→turn_views·单写者）│
                    └──────────────────────────────────────────────┘
                              │  全部只连 ▼
                    ┌──────  Postgres（+pgbouncer, Phase 3）──────┐
                    │ turns/runs(+租约) · turn_events · run_commands│
                    │ work_ast_index_jobs · outbox_jobs · runners   │
                    └──────────────────────────────────────────────┘
                              ▲ LISTEN/claim         ▲ claim
        ┌─────────────────────┴─────────┐   ┌────────┴────────┐
        │ runtime ×M（各节点若干副本）    │   │ ast-indexer ×K   │
        │ 领 Turn·领命令·心跳续租        │   │ （现状已同构）    │
        │ work 亲和：只领本节点有的 work  │   └─────────────────┘
        └───────────────────────────────┘
        embedding sidecar（每 GPU 节点 1 个，O5 Phase 3 可选）
```

单机开发时 N=M=K=1，与今天的 `make up` 完全一致——**同一套代码，规模由 compose 副本数决定**。

---

## 3. 优化项详解

每项格式：现状 → 问题 → 方案 → 延迟影响 → 落点 → 验收。

### O1 · Turn 分发：静态推送 → 声明式领取（P0，核心项）

**现状**：`RuntimeRouter.url_for_new_turn()` 对 `RUNTIME_URL_MAP` 做纯轮询；单副本时走 `RUNTIME_URL` 直推。api push 失败 → `mark_turn_start_failed` → 502。

**问题**：W1（拓扑硬编码）+ W2（盲轮询打满副本）。轮询在两副本、`RUNTIME_MAX_INFLIGHT_TURNS=2`（机型 A 推荐值）下极易复现：副本 a 满、副本 b 空，轮询恰好指到 a → 用户吃 `budget_exceeded`，而集群实际有 50% 空闲容量。

**方案**：

1. 新增分发模式开关 `TURN_DISPATCH=push|pull`，**默认已转正为 `pull`**（WP9；设 `push` 可回退）。
2. `pull` 模式下：
   - api `create_turn` 事务尾部 `pg_notify('turn_dispatch_channel', run_id)`，不再调 runtime HTTP；照常回 202/200（幂等）。
   - **StartSpec（0024）**：`runs.ops_eval` / `model_mode` + `turn_model_secrets`（Fernet 一次性密钥托管）。Ops/L1 与 Web **同一 pull 队列**；claim 还原 `start_turn(ops_eval, override)`，不再靠 `pull_eligible=false` + HTTP push 分叉（后者仅作 `TURN_DISPATCH=push` 回退）。
   - runtime 增加 `TurnDispatchListener`：LISTEN 唤醒后，仅当 `len(_active_turns) < RUNTIME_MAX_INFLIGHT_TURNS` 时尝试 claim（复用 `ensure_run_owned_by_runner` 的原子 UPDATE，`status='accepted'` 谓词不变）；claim 成功进入现有 `start_turn` 后台流程，**Intake 之后的一切不动**。
   - 兜底轮询：LISTEN 连接抖动时，副本每 ~2s 扫一次 `runs WHERE status='accepted'`（与 sources_watch 同款 poll 兜底哲学）。
   - 无人认领超时：api 侧 300s reconcile 循环（已存在）追加一条规则——`accepted` 超过 `TURN_CLAIM_TIMEOUT_SECONDS`（建议 15s）→ `turn.failed(start_timeout)`。
3. `RUNTIME_URL_MAP` 与 `RuntimeRouter` 在 pull 模式下仅保留给 O2 迁移完成前的命令路由；O2 落地后整体退役。

**契约变化（显式声明）**：pull 模式下"runtime 全灭"从**同步 502** 变为**202 + 异步 `turn.failed(start_timeout)`**。评估：前端本就订阅 SSE 终态事件，`turn.failed` 渲染路径已存在；502 分支保留在 push 模式。此变化只发生在故障态，不触碰正常交互逻辑，符合 P-1 的精神但需在 `packages/contracts` 事件枚举里补 `start_timeout` 失败码并知会前端。

**延迟影响**：见 §2.2，净变化 ±1ms 级，低于事件批窗。

**落点**：`services/api/app/services/resource/turns.py`（NOTIFY）· `services/runtime/app/controller/turn_controller.py`（listener）· `run_lock.py`（不变）· `packages/contracts`（失败码）· `deploy/compose/ha.yml`（改用 pull，删 URL_MAP）。

**验收**：
- Golden：push/pull 双模式跑同一 stub 会话集，事件序列 diff 为空。
- 延迟对照（R5 式）：pull 模式 TTFB p95 相对 push 回退 ≤ 5ms。
- 故障注入：双副本杀掉一个，新 Turn 100% 由存活副本领取，零 `budget_exceeded`（在集群总容量内）。

### O2 · 控制命令统一走 DB 命令通道（P0.5，O1 的姊妹项）

**现状**：cancel 已落库（`runs.cancel_requested_at`，全副本可见）；但 approve/deny/patch-accept/patch-reject 走 `url_for_runner(runner_id)` HTTP 直达 owner，挂起态在内存 `pending_store`（PG `checkpoints` 只作恢复底稿）。

**问题**：W4。owner 副本重启/死亡 → `approval_state_lost`；且命令路由依赖 O1 要退役的 URL 表。

**方案**：把 cancel 的模式推广为通用 `run_commands` 表：

```text
run_commands(id, run_id, type[approve|deny|patch_accept|patch_reject|cancel],
             payload jsonb, status[pending|consumed|expired], created_at, consumed_at)
INSERT + pg_notify('run_commands_channel', run_id)
owner 副本 LISTEN：只消费自己 claim 的 run 的命令（WHERE runner_id = self）
非 owner 副本忽略；owner 死亡 → 命令滞留 → 与 O3 租约回收联动：
  新的 reclaim 逻辑可读到未消费命令，恢复挂起审批（同 run_id + checkpoint，契约不变）
```

- api 侧路由 handler 从"转发 HTTP"改为"写命令行 + 202"，响应码语义不变（本就是异步受理）。
- `_inflight_commands` 防双提交逻辑平移为 `run_commands` 上的唯一性约束（`run_id + type + pending` 部分唯一索引），比内存去重更强。
- cancel 可保留现有专列（已工作良好），或并入统一表——建议 Phase 2 并入，减少两套心智。

**延迟影响**：审批本身是人机交互（秒级），+1 次 DB 写 + NOTIFY（毫秒级）完全无感。审批恢复路径反而**更快更可靠**（不再依赖 owner 存活）。

**落点**：`packages/contracts/schemas/ddl`（新表）· api `routers/turns.py` · runtime `turn_controller.py` 命令消费 · 退役 `runtime_router.py`。

**验收**：审批挂起中杀 owner 副本 → O3 回收后另一副本恢复并正确消费 approve；`approval_state_lost` 在故障注入测试中不再出现（除 TTL 过期）。

### O3 · Runner 注册表与租约（P0，故障恢复的地基）

**现状**：claim 是一次性原子 UPDATE，无续租；ast-indexer 心跳写**文件** `/data/ast_indexer_heartbeat`（healthcheck <45s）。

**问题**：W3 + W8 的一半。副本崩溃后 running Turn 悬挂；文件心跳在多节点下不可见。

**方案**：

1. 新表 `runners(runner_id, kind[runtime|ast_indexer|bench], node, last_heartbeat_at, capacity, inflight)`；各副本每 ~10s UPSERT 心跳（一次亚毫秒级 UPDATE，可与 metrics 采集共线程）。
2. `runs` 增加 `lease_expires_at`；runtime 在 Turn 存续期随心跳续租（建议租约 60s）。
3. api 的 300s reconcile 循环增强为 ~30s 的**租约回收**：`running AND lease_expires_at < now()` → 按类型处置：
   - 无未消费命令、无 checkpoint → `turn.failed(runner_lost)`（比现状 stall 180s 快 3 倍以上，且不依赖 `STALL_AUTO_FAIL` 开关）；
   - 有 `waiting_approval` checkpoint → 置回可恢复态，等 O2 命令通道驱动另一副本接手。
4. ast-indexer 心跳从文件迁到同一 `runners` 表；compose healthcheck 改查 DB（或过渡期双写）。Ops overview 的负载探测（§10.4）顺带获得全集群副本视图。

**延迟影响**：心跳/续租是旁路低频写，不在 Turn 热路径；回收循环在 api 后台。零影响。

**落点**：contracts DDL · runtime `turn_controller.py`（心跳任务）· api `session_projector.py` reconcile 扩展 · `workspace_index` 心跳改写。

**验收**：kill -9 runtime 副本，其 running Turn 在 ≤90s（租约 60s + 回收周期 30s）内转 `failed(runner_lost)` 或被接手；对照现状的 180s+。

### O4 · 准入与背压：饱和态从「报错」到「排队」（P1）

**现状**：inflight 超限 → `budget_exceeded` fail。这是把**容量问题转嫁为用户错误**。

**问题**：W5。机型 A inflight=2，第三个并发用户直接失败；扩容前后用户体验断崖。

**方案**（依赖 O1 pull 模式，天然获得）：

1. pull 模式下副本满载就是"不领"，Turn 停在 `pending/accepted` 排队——**排队深度与等待时长成为一等指标**（O11）。
2. api 层准入替代 runtime 层报错：
   - 全局帽：`pending 且未 claim` 的 Turn 数 > `DISPATCH_QUEUE_MAX`（建议 = 集群总 inflight 容量 × 2）→ 新 StartTurn 返 **429 + Retry-After**（新契约码，饱和态才出现）。
   - 租户公平：单 principal 排队中 Turn ≥ `PER_TENANT_QUEUE_MAX`（建议 2）→ 429。防止一个用户/一个脚本刷满队列饿死他人（Ops eval 批跑正是这种负载）。
3. 前端可选增强（非必须）：SSE 已有 `turn.accepted` 事件，排队期间 view 状态即 `pending`，UI 可显示"排队中"。
4. `budget_exceeded` 保留为 push 模式语义，pull 模式下自然消亡。

**延迟影响**：非饱和态零变化（队列长度为 0 时 claim 即刻发生）。饱和态从"立即失败"变"短暂排队"，这是**交互体验的改善**而非破坏；429 仅在超过排队帽时出现。

**落点**：api `routers/sessions.py` 准入检查（一次 count 查询，可用近似缓存）· contracts（429 语义）。

**验收**：并发 2×容量 的 StartTurn 风暴下：零 `budget_exceeded`，p95 排队时长 < 单 Turn 平均时长，超帽请求收到 429 而非 5xx。

### O5 · Embedding 资源竞争：车道分级 → 服务化（P1）

**现状**：runtime 进程内单例 embedder；`search_sources` 的查询 embed 与建库（sources sync）的批量 embed 共享实例。机型 B 上 bench 容器又是一份模型副本。

**问题**：W6。三层：① 建库高峰打高查询延迟（直接违反 P-1 的方向）；② CPU 机上批量 embed 与事件循环抢核；③ 未来 M 个 runtime 副本 = M 份模型 RSS（gte-small 数百 MB）/ VRAM（bge-m3 数 GB）——**副本化的主要边际成本**。

**方案**（三步走，前两步单机即受益）：

1. **Phase 1 · 优先级车道**：embedder 前加两级 asyncio 队列——`query` 车道（`search_sources`，单条、小 batch）严格优先于 `index` 车道（sync 批量）；index 批之间强制 yield（如每 batch 后 `await sleep(0)` + 检查 query 队列）。批大小已有 `EMBEDDING_BATCH_SIZE` 旋钮，车道只是调度顺序。
2. **Phase 1 · CPU 亲和**：机型 A 上建库批量 embed 用 `asyncio.to_thread` + 单线程池并压 torch 线程数（`torch.set_num_threads(2)`），避免抢占 uvicorn 事件循环核（§10.1 画像里 vCPU5 的"突发"变可控）。
3. **Phase 3 · embedding sidecar（可选）**：每 GPU 节点起一个轻量 embedding 服务（HTTP/UDS，batch 聚合），runtime 副本与 bench 共用——N 副本 1 份模型。仅当决定在机型 B 跑 ≥2 runtime 副本 + bench 并存时才值得做；单副本时期**不做**（额外一跳 ~1ms 反而是纯开销）。

**延迟影响**：车道分级**降低**建库高峰的查询 p95（目标：sync 进行中 `search_sources` p95 恶化 ≤ 20%，对照现状的无界恶化）；sidecar 引入 +1ms/查询，仅在多副本 VRAM 收益成立时启用。

**落点**：`services/runtime/app/retrieval/`（embedder 封装处加队列）· settings 新增 `EMBEDDING_QUERY_PRIORITY=true`。

**验收**：机型 B 上触发全量 sync 同时跑 20 次 `search_sources`：车道开启前后查询 p95 对照，恶化幅度收敛到 20% 内。

### O6 · api 面的可扩展性：先定义竞争语义，后拆 worker（P2）

**现状**：api 单 uvicorn 进程承担 REST、SSE fanout、LISTEN→`turn_views` 投影、周期 reconcile。

**问题**：W9。SSE 长连接受单进程 FD/事件循环限制；若简单起 api ×2，投影会双写 `turn_views`，语义未定义；reconcile 会双跑。

**方案**（顺序重要，先语义后拆分）：

1. **定义投影幂等**：核实 `project_turn` 是否严格按 `last_event_sequence` 单调推进（`turn_views.last_event_sequence` 已在 seed 里）。若是，双副本投影只是重复幂等写（可接受）；若否，给投影加 `pg_advisory_xact_lock(turn_id)`——每 Turn 串行、跨 Turn 并行，锁粒度最小。
2. **reconcile 单跑**：所有周期任务（投影 reconcile、O3 租约回收、O1 claim 超时）套 `pg_try_advisory_lock(常量)`——抢到的副本干活，抢不到的跳过。约 10 行的成熟模式。
3. **拆 projection-worker（触发条件驱动，非立即）**：当 SSE 并发连接 > ~1k 或投影 lag 指标（O11）持续超阈时，把 LISTEN→投影搬进 `queue.yml` 已有的 `agent-worker` 容器（`projection.refresh` job 类型已存在），api 退化为纯 REST+SSE。在此之前**不拆**——单机开发期多一个常驻容器违反机型 A 内存预算。
4. api 副本化后 SSE 天然正确：每副本各自 LISTEN，NOTIFY 广播给所有 listener，客户端连哪个副本都能收到全量事件。Caddy 加 `lb_policy` 即可。

**延迟影响**：advisory lock 在无竞争时为亚毫秒；投影本就异步于 SSE 推流（SSE 直接消费 listener 队列），用户可见延迟零变化。

**落点**：api `session_projector.py` · `main.py` lifespan · `deploy/compose/queue.yml`。

**验收**：api ×2 + 事件风暴下 `turn_views.last_event_sequence` 无回退、无丢投影；reconcile 日志确认单副本执行。

### O7 · turn_events 治理：保留策略与分区（P1）

**现状**：全量事件（含 `thinking.delta`、`turn.token` 高频流事件）永久落 `turn_events`；投影兜底 2s 轮询 + `Last-Event-ID` 回放都要扫这张表。

**问题**：W7。表无界增长 → 索引膨胀 → 兜底轮询与回放变慢 → 最终反噬热路径（DB 共享 buffer 被冷数据挤占）。这是"现在不痛、扩容后必痛"的典型。

**方案**：

1. **分级保留**：终态 Turn 的流式细粒度事件（`thinking.delta` / `turn.token` / `tool.delta`）在 N 天后（建议 7）归档删除——它们只服务实时流与短期回放，转写/审计事实在 transcript 与 `turn_views` 里已固化。结构性事件（accepted/completed/tool.started…）保留期更长（建议 90 天）。
2. **按月分区**（`PARTITION BY RANGE (created_at)`）：删除退化为 `DROP PARTITION`，不产生 vacuum 债。Alembic 迁移一次到位，对上层 SQL 透明。
3. 归档任务挂 outbox（`events.retention` job 类型），复用 O6.2 的单跑锁。
4. 顺带核查：`retrieval.completed` 等被 Ops 审计依赖的事件，保留期与 Ops 报告生成周期对齐（避免报告要用时已删）。

**延迟影响**：零（后台 DDL/删除在低峰窗口）；长期是**正收益**（回放与兜底轮询的表更小更热）。

**落点**：alembic 迁移 · api 后台任务 · `packages/contracts` 标注各事件保留级别。

**验收**：灌 30 天模拟负载后表尺寸曲线封顶；`Last-Event-ID` 回放 p95 不随历史总量增长。

### O8 · 存储与 Work 亲和：多节点的真正硬点（P1 决策 / P3 实施）

**现状**：Work 文件在节点本地卷（`/data/works/{id}`、遗留 `/workspace`）；models、ops 数据同在 `agent_data` 卷。

**问题**：W8。**这是多节点扩容唯一绕不过去的状态问题**——Turn 的工具（FS 读写、run_command、LSP、AST）都要求 work_root 在本地。领取制（O1）解决了"谁来跑"，但没解决"在哪能跑"。

**方案**（决策矩阵，建议先 A 后 B）：

| 选项 | 机制 | 优点 | 代价 | 建议 |
|------|------|------|------|------|
| **A · work→节点亲和 claim** | `works.node_affinity` 列；O1 的 claim 谓词加 `AND (work 在本节点 OR work 未落位)`；新 Work 落在首个 claim 它的节点 | 零基础设施；FS 性能原生；与领取制天然融合 | 节点间负载可能不均；节点死则其 works 上的 Turn 不可跑（数据仍在，需人工/脚本迁移） | **Phase 3 首选** |
| B · 共享存储（NFS/virtiofs） | 所有节点挂同一 works 卷 | 任意副本跑任意 work | LSP/AST/git 在 NFS 上延迟劣化明显（违反 P-1）；锁语义坑多 | 仅作 A 的补充评估 |
| C · 对象存储 + checkout | Turn 前拉取、后回传 | 云原生 | 冷启动秒级延迟进热路径，当前形态不可接受 | 排除（现阶段） |

近期（Phase 1，单机也受益）先做三件小事：
1. AST 心跳文件 → `runners` 表（并入 O3）。
2. 盘点 `/data` 里"节点本地可再生"（models、HF cache）vs"必须唯一"（works、ops 报告）的目录，写进 §9.2 的 FS 真相表——这是未来任何存储方案的边界清单。
3. 新 Work 创建路径记录 `node` 归属列（先只写不读），为亲和 claim 铺数据。

**延迟影响**：选项 A 零影响（本地 FS 不变）；这正是排除 B/C 的理由。

**落点**：contracts DDL（works 加列）· O1 claim 谓词 · 运维文档。

**验收**：双节点模拟（同机两套 compose project + 共享 PG）下,work 固定由归属节点副本领取；未落位新 work 被任一节点认领后归属固化。

### O9 · 机型配方：文档画像 + bench 门控（P2，纯配置）

**现状**：§10 的机型 A/B 旋钮是文档里的 `.env` 抄写建议；bench-postgres 无条件常驻。

**问题**：W10。手抄易错；bench-postgres 在内存紧的开发机上常驻占 1g cgroup。**机型 A/B 是负载画像说明，不是部署枚举**——不引入 `MACHINE=a|b` 类开关。

**方案**：

1. **不**新增按机型命名的 compose overlay / Make 参数。§10 推荐值继续写在全景文档与 `.env` 手调；已有 `resolve-embedding` / `gpu.auto.yml` 机制不变。
2. bench-postgres 挂 compose `profiles: [bench]`，与 bench 容器同门控——默认 `COMPOSE_PROFILES=bench` 行为与今日一致；内存紧时 `COMPOSE_PROFILES= make up` 不起 bench 栈，回收 1g。需同步检查产品栈无隐性依赖（Ops L1 路由仅在密钥门控下访问它）。
3. 文档-配置可追溯：§10 注释引用本文；compose 注释引用 O9。

**延迟影响**：零（纯部署面）。

**落点**：`deploy/docker-compose.yml`（bench-pg profile）· `scripts/release/release.sh` · Makefile 注释。

**验收**：无 bench profile 时产品栈可起且不拉 bench-postgres；`make up-bench` 仍起全套 bench。

### O10 · DB 连接与超时分级（P2，随副本数触发）

**现状**：各服务 asyncpg 直连；`statement_timeout≈30s` 一刀切。

**问题**：W11。副本化后连接数线性增长（PG 默认 `max_connections=100`，每连接有内存成本）；30s 超时对热路径太宽（掩盖慢查询）、对索引/归档太紧。

**方案**：

1. **超时分级**：热路径池（Turn/事件/投影）`statement_timeout` 收紧到 5s；旁路池（RAG sync、AST、归档、Ops）放宽到 120s。runtime/api 各自维护双池即可，无需新组件。
2. **pgbouncer 引入阈值**：当 `Σ(副本数 × pool_size) > 60` 时在 PG 前加 pgbouncer（transaction pooling）。注意 LISTEN/NOTIFY 连接必须**绕过** pgbouncer 直连（session 语义），压力本就极小（每副本 1–2 条）。
3. 每副本 pool_size 显式进 settings（紧内存主机：api 5 / runtime 5；资源充足可加倍），替代 asyncpg 默认值。

**延迟影响**：热路径超时收紧是保护而非开销；pgbouncer 在阈值前不引入。

**落点**：`services/*/app/db/pool.py` · settings · Phase 3 compose。

**验收**：故障注入慢查询在热路径 5s 被切断且计入失败 taxonomy（新码 `db_timeout`）；副本压测下 PG 连接数曲线符合预算。

### O11 · SLO 口径与扩容信号（P2，贯穿各阶段的度量地基）

**现状**：有 `/metrics` 与 §10.4 的观察清单，但无 SLO 定义，"何时该扩容/该降载"靠人肉感觉。

**方案**：定义五个一等指标 + 阈值，作为所有优化项的验收标尺与扩容触发器：

| 指标 | 定义 | 采集点 | 参考阈值（触发动作） |
|------|------|--------|---------------------|
| `turn_ttfb_seconds` | StartTurn 202 → SSE 收到 `turn.accepted` | api（listener 侧打点） | p95 > 1s 持续 5min → 查分发/claim |
| `event_pipeline_lag_seconds` | `turn_events.created_at` → SSE flush | api | p95 > 0.5s → 查 LISTEN 队列/投影 |
| `dispatch_queue_depth` / `dispatch_wait_seconds` | 未被 claim 的 accepted 数量与等待时长 | api（O1 后有意义） | wait p95 > 平均 Turn 时长的 20% → **加 runtime 副本**（这就是扩容信号） |
| `runner_lease_misses_total` | 租约过期回收次数 | api reconcile | >0 即告警（副本不稳定） |
| `embed_query_wait_seconds` | query 车道排队时长 | runtime | 建库期 p95 > 200ms → 压 index 车道 batch |

落地形式：五个指标全部走现有 prometheus `/metrics`；Ops overview 页加一块"容量"卡片（排队深度 + 各 runner 心跳 + inflight/capacity 比）。

**延迟影响**：打点为内存计数器，零影响。

**落点**：api/runtime metrics 模块 · `services/api/.../ops/overview.py`。

---

## 4. 分阶段执行计划

原则：每阶段独立可交付、可回滚；双机在每阶段都保持可用；延迟对照（R5 式）是每阶段的合入门槛。

### Phase 0 · 双机整备（纯配置 + 文档，无代码风险） — **已落地**

| 动作 | 对应 | 产出 |
|------|------|------|
| ~~`dev-a.yml` / `MACHINE=`~~ | O9 | 已裁决：机型画像不固化为 Make 参数 |
| bench-postgres 挂 `profiles: [bench]` | O9 | **已落地** · `COMPOSE_PROFILES=` 可跳过 |
| `/data` 目录盘点表回写 §9.2 | O8 | **已落地** · architecture §9.2 |
| TTFB / 事件 lag 指标 | O11 | **已落地** · `turn_ttfb_seconds` / `event_pipeline_lag_seconds` |

**回滚**：去掉 bench-postgres 的 `profiles: [bench]` 并恢复 runtime `depends_on`（不推荐）。

### Phase 1 · 单机健壮化（不改分发拓扑） — **已落地**

| 动作 | 对应 | 状态 |
|------|------|------|
| `runners` + lease + 回收 | O3 | **已落地** |
| AST 心跳双写 DB | O3/O8 | **已落地**（过渡期双写） |
| Embedding 优先级车道 | O5 | **已落地** |
| `turn_events` 分级保留（分区改写另开维护窗） | O7 | **已落地**（应用批删） |
| DB 双池 | O10 | **已落地** |

**回滚**：各项独立 feature flag / 迁移可逆（分区迁移除外，需一次性演练）。

### Phase 2 · 领取制转正（单机双副本 = ha.yml 毕业） — **已落地**

| 动作 | 对应 | 状态 |
|------|------|------|
| `TURN_DISPATCH=pull` + `start_timeout` | O1 | **已落地** · 默认 pull |
| `run_commands` 命令通道 | O2 | **已落地** |
| api 准入 429 | O4 | **已落地** |
| advisory lock + reconcile 单跑 | O6 | **已落地** |
| `ha.yml` pull · 删 `RUNTIME_URL_MAP` · 默认转正 | O1/WP9 | **已落地** |

**回滚**：`TURN_DISPATCH=push` 一键回退（保留至 Phase 3 结束）。

### Phase 3 · 多节点（架构已同构，扩容 = 部署动作）

| 动作 | 对应 | 触发条件 |
|------|------|----------|
| work→节点亲和 claim（方案 A） | O8 | 决定加第二台"生产"节点时 |
| pgbouncer + 连接预算 | O10 | Σpool > 60 连接 |
| projection-worker 拆分 | O6 | SSE >1k 并发或投影 lag 超阈 |
| embedding sidecar（每 GPU 节点） | O5 | 单节点 ≥2 runtime 副本 + bench 并存 |
| 双节点演练：同机双 compose project + 共享 PG 先行模拟 | 全部 | Phase 2 完成后即可在机型 B 上演练 |

### 阶段 × 机型映射

| 机型 | Phase 0–1 | Phase 2 | Phase 3 |
|------|-----------|---------|---------|
| A（6C6G VM） | 主要受益者：预算回收、车道、保护性超时 | 单副本跑 pull 模式（机制同构，容量不变） | 不参与多节点（容量不够），继续做功能开发机 |
| B（9800X3D+5080） | GPU 车道验证、事件分区演练 | 双 runtime 副本 + 故障注入主战场 | 双 compose project 模拟双节点；embedding sidecar 试点 |

---

## 5. 明确不做（与理由）

| 不做 | 理由 |
|------|------|
| Kubernetes / Nomad | 两台开发机 + 领取制 compose 已满足同构扩容；编排系统的运维成本在此规模为纯负债。留待节点数 >3 且有专职运维时再评估 |
| Kafka / NATS / Redis Streams 事件总线 | PG NOTIFY + SKIP LOCKED 在 <数百 Turn/分钟 量级下毫无压力；换总线破坏"事件有序落表可回放"的现有优势。O1/O2 刻意把接口收敛在"表 + NOTIFY"，未来若真要换，seam 已留好 |
| 拆分 runtime 为微服务（工具执行器/模型网关独立进程） | Turn 热路径的进程内函数调用是速率红线的朋友；拆分引入的序列化与网络跳违反 P-1。唯一例外是 embedding（O5），因为它是被证实的资源竞争者 |
| Turn 迁移/续跑（副本间接管 running 中的 Turn） | 需要完整执行态快照，复杂度极高；租约回收 + checkpoint 恢复审批态（O2/O3）已覆盖最痛的场景。running 中段崩溃就 fail，由用户重试——诚实且简单 |
| 提前上 pgbouncer / sidecar / worker 拆分 | 均已定义量化触发条件（O5/O6/O10），条件未到即为过度设计 |

---

## 6. 与现有文档的关系

- 本文是 [`backend-architecture.md`](backend-architecture.md)（现状全景）的**演进分册**：那边写"现在是什么"，本文写"往哪改、为什么、何时"。
- 弱点编号 W1–W12 ↔ 全景文档章节的映射见 §1.2 表内"证据"列。
- 各优化项落地后：现状描述回写全景文档对应章节（§3 分发写序、§8 并发矩阵、§10 机型配方），本文对应项标注「已落地 → 见 xxx」。
- 「改 X 去哪」补充：

| 改什么 | 落点 |
|--------|------|
| 分发模式 / claim 谓词 | `turn_controller.py` · `run_lock.py` · `TURN_DISPATCH` |
| 命令通道 | `run_commands` DDL · api `routers/turns.py` |
| 租约与回收 | `runners` DDL · api reconcile 循环 |
| 准入帽 | api `routers/sessions.py` · `DISPATCH_QUEUE_MAX` / `PER_TENANT_QUEUE_MAX` |
| 机型 overlay | ~~取消 `dev-{a,b}` / `MACHINE=`~~ · bench-pg `profiles: [bench]` · `.env` 手调 §10 |
| 事件保留 | alembic 分区迁移 · outbox `events.retention` |
