# 方案：后端架构全景（控制面 · 执行面 · 索引面 · Bench · 机型负载）

> **状态**：综合草案 **v0.3**（2026-08-13）· 以仓内代码与 compose 事实为准  
> **定位**：后端视角的**完整控制流、并发、机型与负载**说明；拓扑 + 时序 + 所有权 + 开发机画像  
> **冲突裁决**：实现与契约 > 六篇正文原则 > 本文措辞；**机型/并发数字以本文与 compose/settings 为准**  
> **回写**：主路径摘要已进入 [架构](../core/architecture.md) / [事件](../core/events.md) / [Runtime](../core/runtime.md)；本文保留全景与机型配方  
> **演进分册**：[backend-scaling-evolution.md](backend-scaling-evolution.md)（Phase 0–2 **已落地**；Phase 3 触发条件驱动）

本文写清：进程怎么连、请求怎么走、谁写什么表、两类索引如何隔离、Bench 怎么跑、**CPU/内存/GPU 如何调度、两台开发机上该怎么配负载**。

---

## 0. 一句话与读图顺序

**一个 Runtime（agentic loop）+ 多个 ScenarioProfile；api 是控制面与投影/SSE；runtime 是执行面；RAG 与 AST 是两条互不污染的索引旁路；Ops Bench 是效果温度计。水平扩缩靠 runtime 副本与旁路 indexer，不靠把冷启动塞进 Turn 进程。**

| 节 | 内容 |
|----|------|
| §1 | 部署拓扑 · 容器 mem/cpu 上限 |
| §2 | HTTP 平面 · 鉴权 · Web 契约 |
| §3 | StartTurn 写序 · 事件管道 · 写主权 |
| §4 | Runtime Intake / Engine / 审批 / 组窗 / 沙箱 / 模型 |
| §5 | RAG · AST · work_index · LSP |
| §6 | Bench / Eval / 证明分层 |
| §7 | 租户与 Work |
| §8 | **并发矩阵 · CPU 调度 · 失败 taxonomy** |
| §9 | 数据面 · Alembic vs `source_*` |
| §10 | **开发机画像（6C6G / 9800X3D+5080）与负载配方** |
| §11 | 「改 X 去哪」 |

---

## 1. 服务拓扑与资源上限

### 1.1 进程图

```text
Browser
  → Caddy :80/:443
       ├─ /api/* · /health/*  → api :8000
       └─ /                   → web :80
api ──（默认 TURN_DISPATCH=pull）INSERT + pg_notify(turn_dispatch) → runtime LISTEN/claim
api ──（可选 TURN_DISPATCH=push）HTTP + X-Internal-Token → runtime /internal/commands/start-turn
api ── approve/cancel/patch → run_commands + NOTIFY（可回退 HTTP）
api ── HTTP（可选 profile=bench）► bench :8002
runtime INSERT turn_events → Postgres NOTIFY → api LISTEN → SSE / turn_views
runtime/api enqueue work_ast_index_jobs → ast-indexer（FOR UPDATE SKIP LOCKED）
```

硬约束：

- 服务之间 **无 Python 互 import**。  
- 跨服务实时事实桥 = **Postgres**（`INSERT` + `NOTIFY` / `LISTEN`）。  
- 契约源：`packages/contracts`（OpenAPI、事件 schema、DDL）。

### 1.2 Compose 服务与默认资源（`deploy/docker-compose.yml`）

| 服务 | 容器 | 端口 | 默认 `mem_limit` | `cpus` | 职责 |
|------|------|------|------------------|--------|------|
| postgres | `agent-postgres` | 5432 内 | **1g** | — | 产品库 + 产品向量 |
| bench-postgres | `agent-bench-postgres` | 5432 内 | **1g** | — | Ops L1 / official 向量隔离 |
| runtime | `agent-runtime` | 8001 | **4g**（GPU overlay → **12g**） | — | Agent loop · RAG · LSP |
| ast-indexer | `agent-ast-indexer` | 无 | **768m**（`AST_INDEXER_MEM_LIMIT`） | **1.0**（`AST_INDEXER_CPUS`） | AST 冷启动/增量 parse |
| api | `agent-api` | 8000 | **1g** | — | 命令 · SSE · 投影 · Ops |
| bench | `agent-bench` | 8002 | **6g**（GPU → **12g**） | — | profile=`bench`；官方脚本 worker |
| web | `agent-web` | 80 内 | 未设硬限 | — | 静态工作台 |
| gateway | `agent-gateway` | 80/443 | 未设硬限 | — | Caddy |
| 发布台 | release-console | 9090 | 宿主机进程 | — | 分模块 dirty 重建 |

说明：

- `mem_limit` 是 **cgroup 上限**，不是预留；容器 RSS 之和仍可能打爆宿主机/虚拟机物理内存。  
- GPU 路径：`scripts/resolve_embedding_profile.sh` 在可用 NVIDIA 且 VRAM≥`EMBEDDING_GPU_MIN_MIB`（默认 **8192**）时写 `deploy/compose/gpu.auto.yml`，把 **runtime / bench** 的 `mem_limit` 抬到 **12g**，并 `gpus: all` + `TORCH_INDEX_URL=…/cu128`（Blackwell / RTX 50 系）。  
- CPU 路径（当前仓库生成的 `embedding.auto.env` 常见态）：`RUNTIME_GPU=0` → `gte-small@384` + CPU torch，`gpu.auto.yml` 为空 `services: {}`。

### 1.3 卷

| 挂载 | 用途 |
|------|------|
| 宿主 `workspace/` → `/workspace` | 默认 / 遗留 Work 根 |
| `agent_data` → `/data` | 模型、ops-eval、ops-official、AST heartbeat、`/data/works/{id}` |
| seed writing/intel → `sources/seed/*`（RO） | 站立语料 |
| `eval/official/.local-data` → `/data/ops-official/data` | 官方 Bench 数据 |

### 1.4 Overlay

| Overlay | 作用 |
|---------|------|
| `queue.yml` | `WORKER_MODE=outbox` + Redis + `agent-worker` |
| `ha.yml` | 双 runtime + **`TURN_DISPATCH=pull`**（无 `RUNTIME_URL_MAP`）；每副本 inflight 帽默认 16、`mem_limit: 4g` |
| `ops-eval.yml` | api 挂 `docker.sock`（SWE harness） |
| `runtime-lite.yml` | stub / 轻量评测 |
| `gpu.auto.yml` | 由 resolve 脚本生成；CUDA 透传 |
| `dev.override.yml` | 本地覆盖 |

起栈：`make up`（分模块脏重建）+ 发布台 `:9090`；全量 `make up-all`。模型供应商走 Web「设置 → 模型」。

### 1.5 发布模块 ↔ 路径

| 模块 | 脏前缀 | 重建 |
|------|--------|------|
| api | `services/api/` · `packages/contracts/` | `make up-api` |
| runtime | `services/runtime/` · contracts | `make up-runtime`（常 recreate ast-indexer） |
| ast-indexer | `workspace_index/` · compose | `make up-ast-indexer` |
| web | `services/web/` | `make up-web` |
| gateway | `deploy/caddy/` | compose recreate |

---

## 2. HTTP 平面 · 鉴权 · Web 契约

### 2.1 四层 + metrics

```text
公网（Caddy）     /api/v1/* · /health/* → api；/ → web
集群内            api → runtime :8001 /internal/*（X-Internal-Token）
可选              api → bench :8002（Bearer/INTERNAL）
旁路              Ops 路由仅当 OPS_TEST_SECRET 非空
观测              /metrics（api·runtime）Bearer = INTERNAL_SERVICE_TOKEN
```

Caddy（`deploy/caddy/Caddyfile`）：`/health` `/health/*` `/api/*` → api；其余 → web。  
**无 FastAPI CORS**：假定浏览器同源经 Caddy；跨域带 cookie 会挂。

### 2.2 产品 API（`services/api/app/main.py`）

默认 `uvicorn` **单进程**。Lifespan 顺序：

1. DB pool  
2. Alembic migrations  
3. `reconcile_stale_turns` / `reconcile_lagging_projections`  
4. 可选：ops eval orphan、official orphan reclaim  
5. `TurnEventListener`（LISTEN `turn_events_channel`）  
6. 约 **300s** 周期投影 reconcile 任务  

中间件：仅 `RequestContextMiddleware`（`X-Request-ID`、structlog、HTTP 延迟直方图）。

| Router | 职责 |
|--------|------|
| `auth` | register/login/logout/me/password |
| `sessions` | CRUD、**`POST .../turns`**、view、`/retrieval/warmup` |
| `works` | list/create/default/patch |
| `turns` | get / **view** / events / **SSE** / **WS** / cancel / approve·deny / patch |
| `runs` | `GET /runs/{id}` |
| `admin/workspace` | 浏览上传、sources sync、**ast-index status/rebuild/purge** |
| `admin/model_providers` | 供应商 CRUD + activate |
| Ops* | eval / official / retrieval audit / envelope / raw / ingestion（密钥门控） |

健康：

| 端点 | 语义 |
|------|------|
| api `/health/live` | 进程活 |
| api `/health/ready` | DB + **runtime `/health/ready`**（runtime 挂则 503） |
| runtime `/health/live` | 活（compose healthcheck 用这个，避免未配模型阻塞起栈） |
| runtime `/health/ready` | DB + `model_config_ready` + sandbox/structural 快照 |

`routers/health.py` 为空壳；live/ready/metrics 挂在 `main.py`。

### 2.3 Runtime 内部命令

前缀 `/internal/commands`，`hmac.compare_digest` 校验 token。

| 路径 | 要点 |
|------|------|
| `POST /start-turn` | **202**；`BackgroundTasks.add_task(start_turn)` — **先回包再跑 loop** |
| `cancel-turn` / `approve-tool-call` / `deny-tool-call` | 取消 / 审批（approve/deny 亦 BackgroundTasks） |
| `patch-accept` / `patch-reject` | diff 决策 |
| `sync-sources-index` / `cancel-sources-index` | RAG 索引面 |
| `verify-pass` / `warmup-retrieval` | 验证 / 预热 |

另：`/internal/workspace/*` 供 api admin 代理。

### 2.4 Web ↔ api 会话契约

| 机制 | 事实 |
|------|------|
| 终端用户 | httponly cookie `agent_end_user`，`SameSite=lax`，`secure`←`END_USER_COOKIE_SECURE` |
| 前端 | `credentials: "include"`（REST + SSE） |
| Admin | Basic `admin:` + localStorage；可与 end-user 并存；`ADMIN_SESSION_BYPASS` |
| CSRF | **无**独立 CSRF token；靠 SameSite + 同源 |
| 注册/登录 | `security/rate_limit.py` 限流 |
| WS | cookie / bearer / admin bypass |

### 2.5 鉴权分层

| 面 | 机制 |
|----|------|
| End user | cookie/token；`END_USER_AUTH_ENABLED` |
| Admin | `require_admin_or_end_user` |
| Ops | 路径密钥 `OPS_TEST_SECRET` |
| Internal | `X-Internal-Token` / Bearer |

错误体：统一 `ErrorResponse` + `meta.request_id`（422 与 HTTPException）。

---

## 3. StartTurn · 事件 · 写主权

### 3.1 StartTurn 写序（纠正：谁发 `turn.accepted`）

默认 **`TURN_DISPATCH=pull`**（WP9）；`push` 仍可回退。

```text
Client  POST /api/v1/sessions/{id}/turns
  → api 鉴权 · 校验 session / work / scenario
  →（pull）准入帽：全局 / 租户 unclaimed 队列满 → **429** + Retry-After
  → create_turn（同一事务）:
       INSERT turns(status=pending, client_request_id?)
       INSERT runs(status=accepted)
       INSERT turn_views(seed, last_event_sequence=0)
       （pull 且 pull_eligible）pg_notify('turn_dispatch_channel', run_id)
       （ops_eval）runs.ops_eval + 可选 turn_model_secrets 密文；与 Web 同走 pull claim
  → touch_session
  → pull：客户端 **202**（不等 HTTP 到 runtime）
  → push：POST runtime /internal/commands/start-turn
       ├─ 传输/受理失败 → mark_turn_start_failed → 客户端 **502**
       └─ 成功 → 客户端 **202**
  → 同 client_request_id 命中已有行 → **200**（幂等，非新建）

runtime（pull LISTEN/poll 或 push start_turn）:
  → 有空位才 claim（lease；仅 `runs.pull_eligible`）；满则不领（pull）/ 可 budget_exceeded（push）
  → claim 读 `turns.plan_phase`、`runs.ops_eval`/`model_mode`，消费 `turn_model_secrets`
  → turns/runs → running + lease_expires_at
  → append_event **turn.accepted**   ← 事件在这里，不在 api
  → Intake → should_query → Engine 或本地完结
  → claim 超时无人领（仅 pull_eligible）→ api reconcile → turn.failed(start_timeout)
```

**要点**：api「尽快」只做落库（+ NOTIFY）；**首个业务事件 `turn.accepted` 由 runtime 在 claim 成功后发出**。TTFB 看该事件经 NOTIFY→SSE 的到达时刻。

### 3.2 事件管道

```text
runtime BufferedEventWriter（默认窗口 EVENT_BATCH_WINDOW_SECONDS≈0.04）
  → INSERT turn_events（递增 sequence）
  → AFTER INSERT → pg_notify('turn_events_channel', turn_id)
api TurnEventListener
  → Queue → SSE GET /turns/{id}/stream + project_turn → turn_views
  → Queue 空闲约 2s 轮询兜底（防丢通知）
SSE：thinking.delta 只走流；~14s :ping；Last-Event-ID 重连
投影：thinking.delta 默认不进 view 快照
```

### 3.3 事件目录与发射方

| 事件 | 典型发射方 |
|------|------------|
| `turn.accepted` / `completed` / `failed` / `cancelling` / `cancelled` | `turn_controller` |
| `step.started` / `step.completed` | `agent_engine` |
| `turn.thinking` · `.delta` · `turn.token` · `tool.delta` | `agent_engine` |
| `tool.started` / `tool.completed` / `approval.requested` | `agent_engine` |
| `approval.resolved` · patch accept/reject 相关 | `turn_controller` |
| `retrieval.completed` · `patch.proposed` · `section.draft.delta` | 工具副作用经 engine |
| `turn.plan` · `outline.updated` | engine 映射 |
| `cards.pinned` | writing 路径（controller/engine） |
| `subagent.started` / `subagent.completed` | `delegate_runner` |
| `context.reported` / `usage.reported` | engine |

枚举契约：`packages/contracts/schemas/events/types.json`。

### 3.4 领域对象与写主权

```text
Principal → Work → Session* → Turn ↔ Run(1:1) → Step*（仅事件粒度）
pending → running ⇄ waiting_approval → completed|failed|cancelled
```

无 ResumeTurn；审批恢复 = **同一 `run_id` + checkpoint**。

| 所有者 | 写 |
|--------|-----|
| runtime | `turn_events`、执行态、`checkpoints`、transcript、RAG `source_*`（索引面）、AST 入队 |
| ast-indexer | `work_ast_*` 内容 |
| api | `turn_views`、SSE、Alembic、Ops 跑批元数据、orphan reclaim |
| bench | `/data/ops-official/*` 报告（不写产品 Turn 语义） |

---

## 4. Runtime 控制流细节

### 4.1 Intake → Engine 前置（`_run_turn`）

1. **本地短路**：`InputCompiler` 处理 slash / `@path` 预读；`/help` `/version` 等可零模型完结；`/compact` `/verify` 特殊路径；空消息 fail。  
2. **`should_query`**：否 → 本地响应 + `turn.completed`；是 → 进 Engine。  
3. **Profile / ToolScope**：按 `scenario_id` 装白名单与审批覆盖；**Engine 禁止 `if scenario ==` 改 while 形状**。  
4. **Volatile 注入**（进组窗 user 段，不进可缓存 system）：writing cards、`work_index`、work_surface、`plan_phase`、collab orchestrator 块、seed-off banner、recall hint 等。  
5. **`ops_eval`**：`writes_preapproved` + `exec_preapproved`；允许 per-Turn `model_mode` / `model_override`（非 ops 传入会被忽略并打日志）。  
6. **`plan_phase`**：`planning` 缩工具面；`executing` 可豁免清单内写盘审批。  
7. **Structural prewarm**：`asyncio.create_task`，**不挡** `turn.accepted` 受理。  
8. **Collab**：已接线（hints、delegate 类型限制、checkpoint gap hint），不是纯目标态。

### 4.2 AgentEngine 循环

```text
while true:
  ContextEngine.assemble
  ModelGateway.stream（可 abort；Cancel 轮询 ~50ms 级）
  解析 text / thinking / tool_use
  无 tool_use → final → 结束
  有 → 审批? → ToolExecutor → tool_result → checkpoint → 回 assemble
```

Guard（取消 / 分层超时 / Stall Watchdog）旁挂全程，不是 while 新节点。

### 4.3 审批 · 粘性 · stage 门

- 门在 `ToolExecutor`：`requires_approval`，除非 `ops_eval` 或 sticky / profile override。  
- **写盘 sticky**：`ON_WRITE` 工具 + `rename_file`；同 Turn 批准一次后同类可免再审。  
- **Exec sticky**：仅 `run_command` 集合；**Shell 仍逐步审**（与写盘粘性正交）。  
- Pending：内存 `pending_store` + PG `checkpoints`；TTL `pending_store_ttl_seconds`（默认 1800）。  
- Approve/deny：BackgroundTasks + `_inflight_commands` 防双提交。  
- **晚阶段**：默认 `stage_tool_scope_mutate_schema=false` → **schema 不变**（护 prompt cache）；执行期 `stage_tool_runtime_blocked` 挡住 `search_sources|delegate|remember|recall`。

### 4.4 ContextEngine 组窗布局与压力阶梯

消息布局：

```text
system（Scenario profile，可缓存前缀）
→ 可选 [project_context]
→ volatile user（cards / work_index / surface / plan / collab / …）
→ transcript（含 runtime_context）
→ tools schema（计入预算）
```

压力（相对 context window）：

| 阈值 | 动作 |
|------|------|
| ~0.78 | 软预压缩缓存（Turn 间） |
| 读折叠 / snip | tool_result 预算（如 4k；最新 read 可放宽） |
| 0.80 | collapse |
| 0.90 | snip |
| 0.95 | autocompact（优先预压缩；LLM compact 可选） |

写作：`format_work_index_block` 与 cards 在 **volatile**；可发 `cards.pinned`。

### 4.5 沙箱 · egress · secret_scan

| 层 | 行为 |
|----|------|
| 工具沙箱 | `sandbox.py`：landlock → bwrap → off；RW 限 work cwd |
| 评测断网 | `OPS_EVAL_DENY_NETWORK` → bwrap `--unshare-net`（无 bwrap 则 fail closed） |
| 模型出口 | `model_egress_enforce` 时 `ensure_model_egress_allowed`（allowlist） |
| 写盘隐私 | `gate_write_content` 正则 secret scan；超时先放行再异步；另有 PII redact 开关 |

### 4.6 模型网关

| 模式 | 用途 |
|------|------|
| `live` | 真实供应商 |
| `stub` / `recorded` | Golden / 回放 |
| `auto` | 按配置解析 |

配置优先级：ops_eval Turn override → DB 激活的 `model_provider_profiles`（按 owner，密钥解密）→ env `MODEL_*`。  
Cancel → abort event → provider 撕掉 httpx 流（`stream_abort`）。  
超时/重试：`MODEL_TIMEOUT_SECONDS` 等（compose 默认 600）。

### 4.7 Delegate

父 Turn 设 `DelegateRuntime` ContextVar；嵌套 `AgentEngine`；类型白名单（explore/edit/verify/shell/写作角色等）；深度帽约 2；默认 max_steps 约 12；共享父预算；发 `subagent.*` 事件。

### 4.8 工具注册（能力即工具）

入口 `tools/bootstrap.py`。代表：`search_sources`（RAG）、`search_codebase`（AST→LSP Locate）、FS 读写改、`run_command`/`run_tests`、LSP 工具、`delegate`、写作 draft/patch、intel `enrich_ioc` 等。

---

## 5. 索引四平面（硬隔离）

| 平面 | 生产进程 | 存储 | 热路径消费者 | 禁止 |
|------|----------|------|--------------|------|
| RAG | runtime 调度（单飞 sync） | `source_chunks/docs` + FTS | `search_sources` | Turn 内 sync；绑 AST |
| AST | **ast-indexer** | `work_ast_*` + 内存投影 | `search_codebase` / Locate | embedding；服务 writing RAG |
| writing work_index | runtime 拼装 | 无向量表 | Context volatile | 当 RAG |
| LSP | runtime 池 | 无持久符号库 | definition/refs/lints | 全仓冷启动占 Turn |

### 5.1 RAG

- **索引面**：启动延迟 sync、`sources_watch`（mtime poll ~2s / debounce ~1.5s；**不用 inotify**，适配 Docker/WSL bind）、上传、`sync-sources-index`；`_sync_lock` 单飞。  
- **交互面**：hybrid = embed 一次 → Chunk HNSW∥FTS(+Okapi) → Doc lane（默认 ON，0.3s）→ RRF(k=60) → lexical rerank（CE 默认 OFF）→ doc_boost → ACL → cover → keyword-fallback（不重建）。  
- 默认：`search_sources` limit 30、每 Turn≤3、chunk 4000/overlap 400。  
- Ops L1：`OPS_DATABASE_URL` → bench-postgres，schema `retrieval_ops` / `retrieval_ops_zh`。

### 5.2 AST（A6）

```text
runtime: enqueue cold_start|dirty|purge → work_ast_index_jobs
ast-indexer: claim SKIP LOCKED → walk/parse → upsert → 心跳 /data/ast_indexer_heartbeat
runtime: 只加载 IndexProjection；WORKSPACE_AST_INLINE 默认 false
```

- definitions-only JSONB / file；content-hash 失效。  
- dirty：写工具钩子 + `run_command` 轻扫 + poll（默认 ~45s）。  
- Admin：`GET/POST .../admin/workspace/ast-index/{status,rebuild,purge}`。  
- 默认 parse concurrency：settings 3；compose indexer 常 `WORKSPACE_AST_PARSE_CONCURRENCY=2`；受限机建议 **1**。

### 5.3 writing work_index / LSP

- `writing/work_index.py`：FS 大纲/章节元数据，硬字符帽。  
- `structural/pool.py`：Work 级 LSP，idle TTL 600s；AST 粗筛 + LSP 确认。

---

## 6. Bench · Eval · 证明

| 层 | 入口 | 挡合并？ |
|----|------|----------|
| Ops 官方 Bench | `/ops/<secret>/official` | **否** |
| Golden | `eval/golden` · `/test` | 否 |
| `make gate` / ci_proof | `scripts/ci_proof.sh` | **是** |

L1 **强制** `eval_path=agent`（真实 Session/Turn/工具）。套件：retrieval(BEIR) · retrieval_zh(C-MTEB) · context(LongBench) · coding(SWE)。  
L0 `agent-bench`：脚本 worker，与产品 Turn 解耦；向量在 bench-postgres。  
SWE resolve 需 harness + Docker（`ops-eval.yml`）；`OPS_EVAL_DENY_NETWORK` 防泄漏。

Bench 搜索并行（`scripts/official_bench/parallel.py`）：

- `BENCH_SEARCH_WORKERS` 未设 → `min(4, cpu_count)`  
- `BENCH_SEARCH_POOL`：`thread`（共享 ST，避免 ST×N RSS）或 `process`（轻量 BM25）  
- compose 注释：hybrid 用 thread，**不按 process 份数给 mem**

---

## 7. 租户与 Work

- `works`：`owner_user_id` · `work_root` · `visibility_seed`；个人租户 = owner。  
- 新 Work：`/data/works/{work_id}`；遗留可 claim `/workspace`。  
- StartTurn 冻结 `TenantContext`（ContextVar）。  
- 检索 ACL：seed OR 本 `work_id`；再租户过滤。  
- 工具路径沙箱：`current_work_root_path()`。

---

## 8. 并发 · CPU 调度 · 失败面

### 8.1 并发机制矩阵

| 机制 | 位置 | 行为 |
|------|------|------|
| Turn 分发 | `TURN_DISPATCH` · `turn_dispatch` LISTEN | **默认 pull** claim；push 保留回退 |
| Run claim + lease | `run_lock` · `lease_expires_at` | 一副本拥有一 Turn；过期 → `runner_lost` |
| 准入帽 | `admission` · `DISPATCH_QUEUE_MAX` | pull 饱和 → **429**（非 fail） |
| In-flight Turns | `_active_turns` · `RUNTIME_MAX_INFLIGHT_TURNS`（默认 **16**） | pull 满则不领；push 超限可 `budget_exceeded` |
| 控制命令 | `run_commands` + NOTIFY | approve/deny/patch/cancel（可关回 HTTP） |
| 周期任务单跑 | `pg_try_advisory_lock` | 投影 reconcile / lease / claim 超时 / 事件保留 |
| 事件批写 | `BufferedEventWriter` | ~40ms 合并 |
| RAG sync | `_sync_lock` + cancel gen | 单飞 |
| Embedding 车道 | `embedding_lanes` | query > index |
| AST 队列 | `SKIP LOCKED` | 可多 indexer |
| AST parse | ThreadPool + Semaphore | 与 Turn **跨进程**隔离 |
| Two-level RAG | 专用线程池 | chunk∥doc |
| Outbox | `outbox_jobs` SKIP LOCKED | 可选；默认 inline |
| LSP | per-work asyncio lock | idle 回收 |
| HTTP | 默认 1 uvicorn worker/容器 | 扩副本，勿盲目 `workers=N` |
| DB | 双池 hot≈5s / bypass≈120s | |
| Shutdown | `shutdown_drain_seconds≈25` | SIGTERM 排空 |

### 8.2 CPU / 线程调度原则（项目事实）

1. **Turn 热路径**只做毫秒级 CPU（组窗、事件批、工具编排）；重活（整库 embed、全仓 AST walk、SWE harness）必须旁路或独立容器。  
2. **Embedding**：CPU 上 gte-small batch 默认 64；CUDA 上 bge-m3 默认 batch 128、`max_seq=512`（避免 hub 默认 8192 在 16GiB 级显存 thrash）。  
3. **AST indexer**：compose 默认 **1.0 CPU + 768MiB**；parse concurrency 压到 1～2，避免与 runtime/Jedi 抢同一物理核导致 Turn `ReadTimeout` / DB `QueryCanceled`。  
4. **Bench**：thread pool 共享 ST；process pool 只给可 pickle 的轻索引；workers 帽 4。  
5. **sources_watch / AST poll**：轮询而非 inotify（WSL/Docker bind 可靠）。  
6. **HA**：多 runtime 靠 DB claim，不靠共享内存；每副本独立 inflight 计数。

### 8.3 失败 taxonomy

| 类 | 表现 | 备注 |
|----|------|------|
| 用户取消 | `turn.cancelling` → `cancelled` | ≠ failed；流 abort |
| orphan cancel | worker 静默 / stall 见 cancel 旗 | |
| stall | 无事件 ≥`STALL_THRESHOLD_SECONDS`（默认 180） | 可 auto-fail `step_timeout` |
| `budget_exceeded` | push 路径 inflight 满 | pull 优先排队/429，少见此码 |
| `start_timeout` | pull 无人 claim | 异步 `turn.failed`（非 502） |
| `runner_lost` | lease 过期回收 | api reclaim 循环 |
| `db_timeout` | 热池 statement 切断 | O10 |
| `model_timeout` / `model_error` / `fatal_error` | 模型/未捕获 | |
| `approval_state_lost` / `approval_resume_timeout` | 挂起态丢失 | O2 后显著减少 |
| `start_failed` | **仅 push** api→runtime 失败 | 502 |
| 429 准入 | `dispatch_queue_full` / `per_tenant_queue_full` | Retry-After |
| 启动回收 | ops eval force-cancel；official reclaim；投影/lease reconcile | |

### 8.4 容器预算加总（规划用）

默认 **非 GPU** 上限粗加（未起 bench）：

```text
postgres 1 + bench-pg 1 + runtime 4 + ast 0.75 + api 1 ≈ 7.75 GiB cgroup 上限
+ web/gateway/OS/page cache 另计
+ profile bench +6（或 GPU 路径 runtime/bench 各 12）
```

因此 **物理/虚拟机可用内存必须按 RSS 峰值规划**，不能只看「机器有 16G 主机内存」而忽略 VM 只分到 6G。

---

## 9. 数据面

### 9.1 Alembic（api / worker 启动）vs runtime `ensure_schema`

| 所有者 | 对象 |
|--------|------|
| **Api Alembic** | `sessions/turns/runs/turn_events/turn_views/checkpoints/works/end_users/...` · `work_ast_*` · `outbox_jobs` · NOTIFY trigger 等（`packages/contracts/schemas/ddl` → alembic `0001…`） |
| **Runtime `PgVectorStore.ensure_schema()`** | `source_files` / `source_chunks` / `source_docs` / `source_index_meta`（产品或 ops schema）；**维度变化可 DROP/重建 chunks** |
| Alembic 对检索 | 多为事件侧索引（如 `retrieval.completed`），**不建** RAG 表本体 |

### 9.2 FS 真相

```text
work_root/{outline,sections|manuscript,drafts,sources,.agent/}
/data/{models,ops-eval,ops-official,works,ast_indexer_heartbeat}
```

| 路径 | 类别 | 说明 |
|------|------|------|
| `/data/works/{id}` | **必须唯一**（节点本地亲和） | Work 沙箱根；工具/LSP/AST 要求本地 FS。多节点时走 `node_affinity`（演进 O8 方案 A），**不可**用 NFS 作为热路径 |
| `/workspace`（遗留） | **必须唯一** | 默认可 claim 的遗留 Work 根；与 works 同属工作区事实 |
| `/data/ops-eval` · `/data/ops-official` | **必须唯一** | Ops 报告与官方 Bench 产物；全集群一份 |
| `/data/models` · `HF_HOME` | **节点本地可再生** | embedding / HF cache；丢了可重新拉取或 bake |
| `/data/ast_indexer_heartbeat` | **节点本地可再生**（过渡） | 文件心跳；演进 O3 迁 `runners` 表后可弃 |
| `seed/sources/*`（RO 挂载） | 镜像/仓库只读语料 | 非节点状态 |

边界用途：任何共享存储 / 多 compose project 方案必须以本表为裁决清单（演进 O8）。

---

## 10. 开发机画像与负载配方（项目事实）

本节记录**当前开发环境**与推荐并发旋钮；Ops overview 也会从容器视角探测 WSL/VM（`services/api/.../ops/overview.py` 的 `_detect_virt`）。

### 10.1 机型 A — 日常轻量开发（受限）

| 项 | 事实 |
|----|------|
| 宿主 CPU | **Intel Core Ultra 7 155H** |
| 宿主内存 | **16 GiB** |
| 运行形态 | 虚拟机；分配给本项目环境 **6 vCPU + 6 GiB RAM** |
| GPU | 无（或未透传） |
| 预期 embedding | `RUNTIME_GPU=0` → **gte-small @384** + CPU torch（与仓库 `embedding.auto.env` 常见生成结果一致） |
| 典型用途 | 起产品栈、改 api/runtime、写文档、跑 stub Golden / 小流量 live Turn |

**6C6G 上的硬约束**

- 默认 cgroup 上限之和已 ≈ **7.75 GiB**（未计 web/OS），在 **6 GiB VM** 上若全拉满易 **OOM / 疯狂 swap**。  
- **不要**默认 `make up-bench` / 起 `agent-bench`（再 +6g 上限）。  
- **不要**开 GPU overlay（会把 runtime mem_limit 拉到 12g）。  
- AST 与 Turn **必须分进程**（保持 `WORKSPACE_AST_INLINE=false`）；indexer 限 1 CPU。  
- SWE harness + 多题并行在此机不现实。

**推荐 `.env` / 环境旋钮（机型 A）**

```bash
RUNTIME_GPU=0
EMBEDDING_PROFILE=small          # 或 auto（无 CUDA 也会落 small）
RUNTIME_MAX_INFLIGHT_TURNS=2     # 默认 16 对 6G 过猛
WORKSPACE_AST_INLINE=false
AST_INDEXER_MEM_LIMIT=512m       # 默认可 768m；更紧用 512m
AST_INDEXER_CPUS=1.0
WORKSPACE_AST_PARSE_CONCURRENCY=1
SWE_MAX_WORKERS=1
# 不要挂 compose profile bench；不要 ops-eval.yml 除非短时调试
SOURCES_STARTUP_SYNC_DELAY_SECONDS=5
```

**机型 A 可跑 / 应避**

| 可跑 | 应避 |
|------|------|
| `make up`（api+runtime+ast+pg+web+gateway） | `agent-bench` 常驻 |
| 单 Session 串行 Turn；偶发 2 inflight | inflight≥4 + 大仓 AST cold + sync 同时 |
| stub/`make eval-*` 轻量 | 官方 BEIR 全量 + ST 大 batch |
| AST rebuild 后台（concurrency=1） | `WORKSPACE_AST_INLINE=true` |
| 小资料 RAG sync | 同时起 HA 双 runtime |

**CPU 调度画像（A）**

```text
vCPU0-1  runtime（uvicorn + 模型等待 I/O + 少量工具线程）
vCPU2    ast-indexer（parse 串行）
vCPU3    postgres ×2（产品 + bench-pg 即使空闲也占缓冲）
vCPU4    api（LISTEN/SSE/投影）
vCPU5    突发：sources sync embed / web / 宿主机
```

6 核上 **embed 全量 + AST cold + 双 Turn** 会互相饿死事件循环与 DB；应时间片错开（先 sync 完再聊；cold 放空闲）。

### 10.2 机型 B — 重负载 / CUDA / Bench（主力评测）

| 项 | 事实 |
|----|------|
| CPU | **AMD Ryzen 7 9800X3D** |
| GPU | **NVIDIA GeForce RTX 5080**（Blackwell；项目默认 torch **cu128**） |
| 内存 | **32 GiB** |
| 运行形态 | **WSL2 · Ubuntu 22.04**；已配置 CUDA 加载与 GPU 使用 |
| Docker | 通常 Docker Desktop + WSL2 backend；注意 Windows cred helper 与 Linux 拉取（`scripts/ensure_docker_creds.sh`） |
| 发布台 | 须在**普通 WSL 终端**起监听（sandbox netns 会导致 Windows/WSL 浏览器 connection refused） |
| 预期 embedding | `nvidia-smi` VRAM≥8192 → auto：**BAAI/bge-m3 @1024** · `EMBEDDING_DEVICE=cuda` · batch≈128 · max_seq=512 · `gpu.auto.yml` 给 runtime/bench **gpus: all** + **mem_limit 12g** |

**推荐旋钮（机型 B）**

```bash
RUNTIME_GPU=1                    # 或 auto + 可见 GPU
EMBEDDING_PROFILE=auto           # → bge-m3
EMBEDDING_DEVICE=cuda
# TORCH_INDEX_URL 可由 resolve 脚本写为 cu128
RUNTIME_MAX_INFLIGHT_TURNS=4     # 32G 可到 4～8；与 SWE parallel 叠加时仍建议 ≤4
WORKSPACE_AST_INLINE=false
AST_INDEXER_CPUS=2.0             # 可高于默认 1.0
AST_INDEXER_MEM_LIMIT=2g
WORKSPACE_AST_PARSE_CONCURRENCY=2
BENCH_SEARCH_WORKERS=4
BENCH_SEARCH_POOL=thread         # hybrid + 共享 ST
SWE_MAX_WORKERS=1                # harness 仍建议 1；靠题间串行稳
# make up-bench；评测需要时叠加 ops-eval.yml
```

**机型 B 负载分层**

| 负载层 | 并发建议 | 说明 |
|--------|----------|------|
| 日常对话 | inflight 2～4 | 模型流为主，CPU 闲置给 indexer |
| RAG 建库 | sync 单飞 | CUDA embed；勿与 SWE 同时打满 VRAM |
| AST cold | indexer 2 CPU · parse 2 | 与 Turn 分进程；大仓仍错开高峰 |
| Ops L1 retrieval | bench 容器 12g + thread×4 | 产品 runtime 可并行轻 Turn |
| SWE L1 / harness | workers=1 · board tier n5 | 吃 Docker + 磁盘；勿叠满 Bench search process 池 |

**CPU/GPU 调度画像（B）**

```text
9800X3D 8C
  ├─ runtime：Turn + LSP(Jedi) + 轻工具线程
  ├─ ast-indexer：2C 解析
  ├─ postgres ×2 + api SSE
  └─ bench worker：thread 池查询（GIL 下仍受益于 I/O/DB）

RTX 5080
  └─ sentence-transformers / bge-m3 encode（runtime 索引面 + bench）
     注意：Turn 内 search_sources 也走同一 embedder —— 建库高峰时查询延迟上升属预期
```

**WSL2 注意**

- GPU：需 Windows 侧驱动 + WSL CUDA；`nvidia-smi` 在 Ubuntu 内可见才走 auto CUDA。  
- 内存：WSL2 默认可能不给满 32G；若 embed OOM，在 `.wslconfig` 提高 `memory=`，或临时 `EMBEDDING_BATCH_SIZE=64`、`RUNTIME_GPU=0` 回退。  
- Bind mount：资料 watch / AST poll 用 mtime，避免依赖 inotify。  
- 文件 IO：大仓 AST、SWE checkout 放在 Linux 文件系统侧（非 `/mnt/c/...`）显著更快。

### 10.3 两机对照速查

| 维度 | 机型 A（6C6G VM） | 机型 B（9800X3D+5080 / WSL） |
|------|-------------------|------------------------------|
| 目标 | 功能开发 · 文档 · 轻测 | Bench · CUDA 索引 · SWE |
| Embed | gte-small CPU | bge-m3 CUDA cu128 |
| runtime mem_limit | 4g | overlay **12g** |
| inflight | **2** | 4～8（谨慎） |
| ast-indexer | 1C · 512～768m · parse **1** | 2C · 2g · parse **2** |
| bench 容器 | **不起** | 可起 · search workers≤4 · thread |
| SWE parallel | 1 或免 | 1（稳） |
| 同时重活 | 禁止三线（sync∥AST∥多 Turn） | 允许两线，三线仍错峰 |

### 10.4 观测负载时看什么

| 信号 | 来源 |
|------|------|
| `dispatch_queue_depth` / `dispatch_wait_seconds` | api `/metrics` · Ops 概览「容量 / 分发」 |
| `dispatch_start_timeout_total` · `runner_lease_misses_total` | api `/metrics` · 同上 |
| `turn_ttfb_seconds` · `event_pipeline_lag_seconds` | api `/metrics`（SLO） |
| `runtime_inflight_turns` | runtime `/metrics` |
| runners 心跳 | `runners` 表 · Ops 容量卡 |
| 容器 mem / cgroup | `docker stats`；Ops overview 解析 `mem_limit_mib` |
| 宿主/WSL/VM 类型 · CPU model | Ops overview `_detect_virt` + `/proc/cpuinfo` |
| loadavg | overview `_loadavg` |
| AST 心跳 | `/data/ast_indexer_heartbeat`（过渡）+ `runners` |
| 索引进度 | admin sources index-status / ast-index status |
| embedding 解析结果 | `deploy/embedding.auto.env`（每次 `make up*` 重写） |
| 运维手册 | [`docs/ops/pull-dispatch-runbook.md`](../ops/pull-dispatch-runbook.md) · `make pull-dispatch-maturity` |

---

## 11. 「改 X 去哪」

| 改什么 | 落点 |
|--------|------|
| REST 字段/状态码 | `packages/contracts` → `services/api/app/routers/*` |
| StartTurn 写序/幂等 | `api/.../resource/turns.py` · `routers/sessions.py` |
| Intake / inflight / claim | `runtime/.../turn_controller.py` · `run_lock.py` |
| Engine / 审批粘性 | `engine/agent_engine.py` · `context/engine.py` ToolExecutor |
| 组窗阶梯 | `context/engine.py` · `context/policy.py` |
| 新工具 | `tools/bootstrap.py` + handler |
| 场景差 | `scenarios/profiles` + `system.md` |
| RAG | `retrieval/*` · compose EMBEDDING_* |
| AST | `structural/workspace_index/*` · ast-indexer compose |
| 沙箱/隐私 | `tools/core/sandbox.py` · `privacy/*` · `model/egress.py` |
| 模型配置 | Web admin providers · `model/factory.py` |
| Bench 并行 | `scripts/official_bench/parallel.py` · BENCH_* · compose bench |
| GPU/机型自动档 | `scripts/resolve_embedding_profile.sh` → `embedding.auto.env` + `gpu.auto.yml` |
| 合入门禁 | `scripts/ci_proof.sh`（勿把 Ops Bench 当 gate） |

---

## 附录 A · 产品 HTTP ↔ 内部命令

| 产品 | 内部 / 通道 |
|------|-------------|
| `POST /sessions/{id}/turns` | pull：`pg_notify(turn_dispatch)`；push：`POST /internal/commands/start-turn` |
| `POST /turns/{id}/cancel` | 默认 `run_commands`；可回退 `.../cancel-turn` |
| `POST /turns/{id}/approve-tool-call` | 默认 `run_commands`；可回退 HTTP |
| `POST /turns/{id}/deny-tool-call` | 默认 `run_commands`；可回退 HTTP |
| `POST /turns/{id}/patch/accept\|reject` | 默认 `run_commands`；可回退 HTTP |
| `POST /admin/workspace/sources/sync` | `.../sync-sources-index` |
| `POST /retrieval/warmup` | `.../warmup-retrieval` |
| AST rebuild/purge | AstIndexService → `work_ast_index_jobs` |

## 附录 B · 运维向环境变量（扩）

| 区域 | 变量 |
|------|------|
| 信任 | `INTERNAL_SERVICE_TOKEN` · `APP_SECRET_KEY` · `APP_ENV` · `AUTH_*` · `END_USER_*` · `ADMIN_*` · `OPS_TEST_SECRET` |
| DB | `DATABASE_URL` · `OPS_DATABASE_URL` · `BENCH_DATABASE_URL` |
| Worker | `WORKER_MODE` · `WORKER_POLL_*` |
| 模型 | `MODEL_MODE` · timeouts · `MODEL_EGRESS_*` |
| RAG | `RETRIEVAL_*` · `EMBEDDING_*` · `RUNTIME_GPU` · `TORCH_INDEX_URL` |
| AST | `WORKSPACE_AST_*` · `AST_INDEXER_*` |
| 并发 | `TURN_DISPATCH` · `RUNTIME_MAX_INFLIGHT_TURNS` · `DISPATCH_QUEUE_MAX` · `EVENT_BATCH_WINDOW_SECONDS`（`RUNTIME_URL_MAP` 仅 push 遗留） |
| Stall | `STALL_THRESHOLD_SECONDS` · `STALL_AUTO_FAIL` · `SHUTDOWN_DRAIN_SECONDS` |
| 沙箱 | `TOOL_SANDBOX` · `OPS_EVAL_DENY_NETWORK` · `SECRET_SCAN_*` |
| Bench | `BENCH_SEARCH_WORKERS` · `BENCH_SEARCH_POOL` · `SWE_MAX_WORKERS` |
| 观测 | `OTEL_*` · `RAW_SNAPSHOT_ENABLED` · `MODEL_ENVELOPE_*` |

完整默认值以 `services/*/app/settings.py` 与 compose 为准。

## 附录 C · 变更摘要

### v0.2 → v0.3（scaling WP0–WP9）

- 默认 **`TURN_DISPATCH=pull`**；`ha.yml` 无 `RUNTIME_URL_MAP`。  
- `run_commands` 通道；lease/`runner_lost`；准入 429；双池；embedding 车道；事件分级保留；advisory 单跑锁。  
- §3/§8/附录 B 与 compose 事实对齐。

### v0.1 → v0.2

- 纠正：**`turn.accepted` 由 runtime 在 claim 后发出**；api 只落库+202/200/502。  
- 补全：控制面 lifespan、Intake、审批粘性、组窗布局、沙箱/egress、事件发射表、失败 taxonomy、Alembic vs `source_*`、Web cookie 契约。  
- 新增 §10：机型 A/B 负载配方；§1/§8 compose mem/cpu 与 GPU overlay。
