# 35 — 全仓优化审查（2026-07）

> 对 `services/api`（~8.1k 行）、`services/runtime`（~18.7k 行）、`services/web`（~17.4k 行 TS）与工程基建（deploy / Makefile / contracts / eval / CI / DB 迁移）的一次深度代码审查。
> 每项标注 **[高]/[中]/[低]** 严重度与文件位置。高严重度条目均经过人工复核确认。
> 落地顺序建议见 §9；本文只记录问题与建议，不代表已修复。

---

## 0. 总体判断

架构方向是健康的：三服务边界清晰、事件溯源 + 投影 + SSE 的链路完整、golden/gate 可证明、文档与 ADR 纪律好。主要债务集中在五处：

1. **检索热路径同步阻塞事件循环**（runtime 最痛，会放大为整机卡顿）；
2. **事件 → 投影 → SSE → 前端** 这条主链路两端各有正确性缺陷（通知被抢、读路径全量投影、前端不去重/断流不重连）；
3. **安全默认值宽松**（docker.sock + root、弱默认密钥、Ops 密钥进 URL、沙箱默认联网）；
4. **千行级巨石文件**积累（runtime 5 个、web 2 个、api 2 个、scripts 1 个）；
5. **契约同步靠人工纪律**（JSON Schema 与 Pydantic 已漂移、codegen 无 CI 门禁、api/web 测试基本不进 CI）。

---

## 1. Runtime 执行面（`services/runtime/`）

### 1.1 检索 / RAG（最高优先）

**[高] R1 — 检索热路径在 async 事件循环上同步阻塞**
`app/tools/core/tools.py` 978–979 行：`search_sources` 是 `async def`，却直接调用 `store.load()` / `store.search()`；内部（`app/retrieval/pgvector_store.py` 70、220–248、480–536、592–696；`two_level.py` 78–110）用同步 `psycopg.connect`、全表 SELECT、临时 `ThreadPoolExecutor`、embedding encode，全部占用事件循环。并发 Turn 时一次 hybrid 检索可以卡住整个 runtime（模型流、取消轮询、其它工具全部停摆）。
**建议**：热路径统一 `await asyncio.to_thread(...)` 或改 asyncpg；线程池进程级复用，不要每次 search 新建。

**[高] R2 — store 无单例 + 每次查询全表 `load()`**
`app/retrieval/store.py` 70–90：每次 `get_sources_store()` 新建 store 并 `ensure_schema()`；`search_sources` 再把 `source_chunks` 全部行拉进内存缓存。查询复杂度 ≈ O(全库 chunk 数)，与 ANN 设计目标相反。
**建议**：按 schema/DSN 键控的进程级单例；`load()` 仅在启动/sync 后刷新；BM25 改增量或 DB 侧 FTS。

**[高] R3 — `HashEmbedder` 使用不稳定的内置 `hash()`**
`app/retrieval/embedder.py` 47 行：`bucket = hash(token) % self.dimensions`。CPython 字符串 hash 默认随机种子，**进程重启后查询向量与库内向量空间不一致**，hash 后端召回静默失效（已复核确认）。
**建议**：改 `hashlib.blake2b` 等稳定哈希并强制 reindex；文档标明 hash 后端仅限测试。

**[中] R4 — Hybrid 双倍 ANN 查询**：`pgvector_store.py` 601–609、667–669，chunk lane 与 doc lane 各打一次相似查询。可一次宽召回同时服务两个 lane，或 SQL `DISTINCT ON (path)`。

**[中] R5 — pgvector 过滤 + HNSW 退化风险**：`pgvector_store.py` 182–185、493–516，`WHERE work_id = … ORDER BY embedding <=> …` 在大租户下 HNSW 收益下降。评估 partial index / 分区，或先 ANN 后应用层过滤（`fetch_limit` 下推到 SQL）。

**[中] R6 — 双数据库客户端割裂**：主路径 asyncpg（`app/db/pool.py`，`max_size=10` 硬编码）、检索/索引走 psycopg 无上限短连接（`pgvector_store.py` 70、`index_scheduler.py` 88–90）。统一驱动或给检索专用池；池参数配置化。

### 1.2 模型网关（`app/model/gateway.py`，1059 行）

**[高] G1 — 流超时/重试时未关闭 provider 异步生成器**
`_stream_attempt`（917–972 行）对 `agen = provider.stream(...)` 在 first-byte timeout 和异常路径只 `attempt_abort.set()`，没有 `finally: await agen.aclose()`。若 abort 竞态失败会留下挂起连接/半开 SSE，加重连接池压力与假超时。
**建议**：`try/finally` 中始终 `aclose()`；重试前确保上一 attempt 清理完成。

**[中] G2 — Stub 占文件 2/3，职责混杂**
122–800 行是 `StubModelProvider` + 几十个 `_wants_*` golden 路由启发式；真正的生产 harness（超时/重试/错误分类）只有 803 行以后约 250 行。**建议**：拆为 `stub_provider.py` / `errors.py` / `gateway.py`；生产镜像可排除或延迟导入 stub。

**[中] G3 — liveness 信号会禁止重试**：`StreamActivity`（59–68 行）解除假超时是对的，但仅发出 liveness、尚无用户可见 token 时失败，`emitted=True` 会升级为 `ModelFatalError` 禁止重试（845–857 行）。应区分 `emitted_user_visible` 与 `emitted_liveness`。

**[低] G4 — 公开类型与实现不一致**：814 行标注 `AsyncIterator[str | ModelResponse]`，实际会透传 `StreamActivity`。

**[低] G5 — stub 默认应答 `[stub] Acknowledged` 可能让未覆盖的 golden 假绿**（462–465 行）；CI 模式建议 fail-fast。

### 1.3 Turn 控制与引擎

**[高] E1 — 审批恢复路径丢失 step checkpoint**
`app/controller/turn_controller.py`：首跑 `_run_turn`（1058–1124 行）传入 `on_step_checkpoint`，`_resume_after_approval`（1309–1317 行）构造 `AgentEngine` 时**没传**。用户批准后若进程崩溃，checkpoint 停在中断点，HA/恢复链断裂。
**建议**：引擎装配抽成公共工厂，两条路径复用同一份回调。

**[高] E2 — 并行只读工具并发写共享状态**
`app/engine/agent_engine.py` 506–521、1014–1020：`asyncio.gather` 并行 `_run_tool`，各自 `state.messages.append` 并更新 read registry（728–750）。tool_result 顺序可能相对 tool_use 乱序，registry 交错更新导致冗余读误判。
**建议**：并行只做 I/O，结果按 `tool_calls` 原序串行合并；registry 收集后统一更新。

**[中] E3 — `turn_controller.py`（1485 行）上帝对象 + 恢复异常处理大段复制**：`_run_turn`（848–1247）与 `_resume_after_approval`（1253–1441）的异常处理几乎重复（E1 正是这种复制漏改的产物）。拆 `turn_runner` / `approval_resume` / `turn_finalize`。

**[中] E4 — 内存 `PendingTurn` 持有完整 Gateway/Tools**（`app/controller/pending_store.py` 13–37）：长期 pending 占内存且与 runner sticky 假设耦合。只存 interrupt 元数据，恢复一律从 checkpoint 重建，加 TTL。

**[中] E5 — 事件序号写放大**：`app/controller/events.py` 16–70，每条事件 advisory lock + `MAX(sequence)` + INSERT 两次往返；token 流密集时放大 DB 压力。改 `turns.event_seq` 原子 `UPDATE … RETURNING`。

**[中] E6 — fire-and-forget `create_task` 无监督**（`agent_engine.py` 168–177、198–207；`turn_controller.py` 721–734）：统一 `spawn_background(coro, name=…)`，记录异常与指标。

**[中] E7 — Context 组装重复估算 token + 指纹偏弱**（`app/context/engine.py` 353–440、485–496）：`_build_envelope` 多次全量 `json.dumps` 估 token；指纹用 `hash()` + 消息条数，同长度替换内容可能误复用。缓存中间计数、指纹改内容 digest。

**[中] E8 — 沙箱默认联网 + bind 宿主 `/proc`**（`app/tools/core/sandbox.py` 74–75、107–125）；无 bwrap 时完全 unsandboxed（36–38 行）。生产应强制 bwrap 就绪检查、网络按工具白名单、评估 `--proc` 替代全量 bind。（对齐 docs/31 待办 E4/SB4。）

**[低] E9 — `app/graph/runner.py` 单节点 LangGraph 封装无实质编排**（18–31 行），徒增依赖；要么真图化要么标注 compat shim。
**[低] E10 — 多处 `except Exception: pass` 静默**（`model_envelope.py` 69–86、`session_raw.py` 46、`precompact_cache.py` 43–54 等）：至少 debug 日志 + counter。
**[低] E11 — `tools.py`（1585 行）巨石 + `grep`/keyword fallback 同步扫整个 sources 树**（734–761、821+）：按域拆分，FS 扫描 `to_thread`，grep 限深度/大小。

---

## 2. API 控制面（`services/api/`）

### 2.1 事件 → 投影 → SSE 链路

**[高] A1 — SSE 与 projection 共用同一个队列，互相抢通知**（已复核确认）
`app/services/realtime/listener.py` 51–66：`wait_for_turn` 从全局 `asyncio.Queue` `get()` 通知，不匹配的 turn 就地 `project_turn`；`_consumer_loop`（102–111）消费同一队列。多路 SSE 并发时投影消费者可能永远收不到某 turn 的通知，投影延迟且唤醒语义不稳定。
**建议**：LISTEN 回调改扇出——per-turn `asyncio.Event` + 独立投影队列；`wait_for_turn` 只等自己的信号，不消费全局队列。

**[高] A2 — `GET /turns/{id}/view` 在请求路径同步全量投影**
`app/services/projection/projector.py` 561–562（`build_turn_view` → `project_turn`），每次读 view 重放该 turn **全部** `turn_events` 再 UPSERT——违反 docs/08 自身的禁止项。Token 流密集时 view 轮询会打爆 CPU/DB。
**建议**：默认只读 `turn_views`；仅当 `max(sequence) > last_event_sequence` 时才投影；`?refresh=1` 兜底。同理修 `build_session_view`（`session_projector.py` 66–67）与 SSE 空闲路径每 ~0.9s 的全量投影（`events.py` 90–94）。

**[高] A3 — SSE 流期间无周期 keep-alive**
`app/services/realtime/sse.py` 10–14：只在整段结束后发一次 `: keep-alive`；空闲等待期间不发注释帧，反代/LB 容易按读超时掐长连接。对齐 `ops_eval.py` 136–138 已有的 `: ping` 做法，每 15–30s 发一次。

**[高] A4 — LISTEN 回调队列满时抛异常丢通知**
`listener.py` 68–74：`call_soon_threadsafe(self._queue.put_nowait, …)` 在队列满时于事件循环回调里抛 `QueueFull`，通知静默丢失（`notify()` 45–49 反而有处理）。统一吞掉 + 打点，或改 dirty-set 强制 reconcile。

**[高] A5 — 投影无单调性/互斥，并发可写回旧视图**
`projector.py` 485–529 UPSERT 无 `WHERE last_event_sequence <= EXCLUDED…`、无 advisory lock；两个 `project_turn` 交错时旧事务可能覆盖新视图。加 `pg_advisory_xact_lock(hash(turn_id))` 或单调条件更新；投影改增量（只读 `sequence > last_event_sequence`）。

**[中] A6 — LISTEN 长期占用连接池 1/10**（`listener.py` 76–100 + `pool.py` `max_size=10`）：LISTEN 改池外独立连接；池大小配置化。

### 2.2 安全与鉴权

**[高] A7 — Ops 密钥进 URL 且不止只读**
产品入口 `/ops/<OPS_TEST_SECRET>/…` 把密钥放路径（浏览器历史、Referer、access log 全泄露）；同一密钥还能 `POST /ops/eval/runs`、经 docker.sock 重建 runtime、跑 proof 容器（`ops_eval.py` 62–71、`restart.py`、`proof.py`）。
**建议**：URL 无密钥 + HttpOnly cookie / 一次性兑换；拆 `OPS_READ_SECRET` / `OPS_EVAL_SECRET`；生产不挂 docker.sock。

**[高] A8 — 默认弱密钥与可关闭鉴权**
`app/settings.py` 10–17：`internal_service_token="change-me-internal"`、`app_secret_key="change-me"`、`admin_password="admin"`、`auth_enabled=False`、`admin_session_bypass=True`。生产启动应校验拒绝默认值。

**[中] A9 — `owner_user_id IS NULL` 的 session 所有登录用户可读写**（`end_user/auth.py` 91–93）：无主应视为 403，迁移回填 owner。

**[中] A10 — `/metrics` 无鉴权**（`main.py` 155–163）。

### 2.3 其它

**[中] A11 — Runtime HTTP 客户端每请求新建、无重试、错误传播不一致**（`runtime_client.py` 68–74；`turns.py` cancel/approve/deny 无 httpx 捕获）：进程级共享 `AsyncClient`；幂等命令有限重试；统一映射 502/504。
**[中] A12 — 删除 session 残留 envelope 孤儿**（`model_request_envelopes.turn_id` 无 FK）：删除事务内显式清理或补 CASCADE。
**[中] A13 — Ops `retrieval.completed` 聚合查询缺 type 部分索引**（`ops_retrieval.py` 39–64）。
**[中] A14 — 周期 reconcile 无 LIMIT**（`session_projector.py` 97–136，每 300s 全量），需分批。
**[中] A15 — WebSocket 审批失败静默 return**（`ws.py` 61–75），前端表现为"点了没反应"；应 `send_json` 错误。
**[低] A16 — `projector.py`（654 行）按 event type 注册 handler 重构**；子代理分支（202–270）与主路径（272–448）大量重复。
**[低] A17 — `TERMINAL_EVENTS` 在 `listener.py` 与 `events.py` 重复定义**。
**[低] A18 — session 列表每行两个 turns 子查询**（`sessions.py` 75–126），物化到 session_views。

---

## 3. Web 前端（`services/web/`）

### 3.1 事件流正确性

**[高] W1 — 事件无去重，重连可能重复累积 token**（已复核确认）
`TurnStreamClient.ts` 90–97：只推进 `lastSequence`，不跳过 `sequence <= lastSequence` 的事件；`useWorkbench.ts` 268–272 的 `setEvents`/`setStreamText` 无条件追加。重连重叠时出现重复 token / 重复 timeline。
**建议**：传输层 `if (data.sequence <= this.lastSequence) return;`；应用层按 sequence 应用而非盲目拼接。

**[高] W2 — SSE"干净断流"不重连，误走终态路径**
`TurnStreamClient.ts` 106–108：reader `done` 且未收到终态事件时直接 `onClose`（重连只在 `catch` 分支）。代理 idle timeout 常表现为干净结束 → 活跃 turn 静默丢流、UI 误清 busy。
**建议**：非终态断流用 `lastSequence` 指数退避重连；仅终态事件（或 view 已终态）才 `onClose`。

**[高] W3 — WebSocket `onerror` 在可重连时立即报错清 busy**（`TurnWebSocketClient.ts` 73–76）：抖动即显示失败，虽然随后 `onclose` 还会重连。`onerror` 只记日志，耗尽重试次数再上报。

### 3.2 长会话性能

**[高] W4 — 单体 Context + 每 token 多处 setState → 整树重渲染**
`workbenchProvider.tsx` 9–11 直接 `value={wb}`；`useWorkbench.ts`（1040 行）每事件多次 setState、每次 render 新建返回对象（970–1032）。长 agent turn 大量 `turn.token` 时全部订阅者跟着刷。
**建议**：流式文本 rAF/50–100ms 批量；Context 拆分（session / liveStream / actions）或 Zustand + selector；列表行 `memo`。

**[高] W5 — `events` 数组无界累积 + 每帧 O(n) 派生**
`useWorkbench.ts` 115、272、528–530；`subagents.ts`、`AgentActivityPanel.tsx` 46–56、`tokenUsage.ts` 每次 render 扫全量 events。内存随事件数线性涨。
**建议**：UI 只保留投影状态；events 环形缓冲/按类型抽样；派生改增量状态机。

**[高] W6 — 渲染期原地 mutate state**：`useWorkbench.ts` 897–908 对 state 引用 `rawTimeline.push(...)`。先拷贝再改。

**[中] W7 — 无列表虚拟化**（会话历史 `AgentChatPanel.tsx` 505–529、diff 逐行 `<tr>` `UnifiedDiffView.tsx` 114–137、Eval 日志）；大 diff 建议 Web Worker + 行数阈值 + 虚拟滚动。
**[中] W8 — 无路由级代码分割**：`App.tsx` 5–16 同步 import ops/settings；`vite.config.ts` 无 `manualChunks`。ops/settings `React.lazy`。

### 3.3 类型与结构

**[中] W9 — `TurnEvent`/artifacts 未真正类型化**：`client.ts` 81–87 手写 `type: string; payload: Record<string, unknown>`；OpenAPI 生成的 `tool_timeline`/`artifacts` 是 `Record<string, never>[]`；大量等效 any 的断言。应从 `packages/contracts/schemas/events/envelope.json` + payload schemas 生成事件类型。
**[中] W10 — 巨石与死代码**：`SettingsPage.tsx`（1121 行）、`useWorkbench.ts`（1040 行）、`EvalConsolePage.tsx` 自带一份 `EventSourcePolyfill`（662–703 行，与 TurnStreamClient 重复）；`WorkbenchShell.tsx`、`InterviewPanels.tsx`、`useAdminAuth.ts` 零引用；三份重复的 `findMatches`。
**[中] W11 — API client 错误处理不一致**：`changePassword` 解析 detail、`startTurn` 只抛 status、`warmupRetrieval` 静默吞错；统一 `apiFetch` + `ApiError`。
**[中] W12 — `handleStop` 定时器无清理**（`useWorkbench.ts` 752–776）。
**[低] W13 — 双锁文件**（`package-lock.json` 与 `pnpm-lock.yaml` 并存，声明 pnpm）；删 npm lock。
**[低] W14 — `openapi-typescript` 未声明为依赖**（`scripts/codegen.sh` 26 用 npx 裸调）。
**[低] W15 — `App.tsx` 手写 pathname 分支路由**（29–51、312–332），改 `<Routes>` 便于 lazy/嵌套 layout。

---

## 4. 部署与安全基线（`deploy/`）

**[高] D1 — api 容器挂 docker.sock + `USER root`**（`docker-compose.yml` 129–131；`services/api/Dockerfile` 37–38）：API 被 RCE 即接管宿主。Ops eval 的 compose 控制拆到独立 sidecar（已有 `ops-proof.Dockerfile`）；api 非 root；生产去掉 sock。
**[高] D2 — compose 默认弱密钥**（`POSTGRES_PASSWORD=agent`、`ADMIN_PASSWORD=admin`、`ADMIN_SESSION_BYPASS=true`）：生产 overlay 空值 fail-fast，与 A8 配套。
**[高] D3 — 全栈无 CPU/内存限制**：runtime 含 torch + sentence-transformers，HA 双副本易 OOM 宿主。至少给 runtime/postgres/api 设 memory limit。
**[中] D4 — Retrieval 镜像 torch 装两遍**（`Dockerfile.retrieval` 31–36、63–66）：baker 只下载模型，runtime 单次 pip install。
**[中] D5 — `.dockerignore` 过薄**（仅 3 行）：`workspace/`、`.eval-workspace/`、`*.log`、`.coverage`、`.venv`、`__pycache__` 都进 build context。
**[中] D6 — `queue.yml` 引入代码从不使用的 Redis**（README 明确 outbox 不依赖 Redis）：删除。
**[中] D7 — `retrieval.yml` overlay 给基座服务加 profile，漏传 `--profile` 时 runtime 不启动**；且默认栈已是 retrieval 镜像，overlay 本身过时。
**[中] D8 — HA overlay 手抄基座 env 易漂移**（`ha.yml` 11–44 vs 基座 31–72）：改 anchor/`env_file` 单一来源。
**[中] D9 — 健康检查语义分裂**：compose 与镜像内 HEALTHCHECK 一个用 live 一个用 ready，统一"编排 ready / 存活 live"。

---

## 5. 契约与代码生成（`packages/contracts/`）

**[高] C1 — 命令契约 JSON 与 Pydantic 已漂移**：`schemas/commands/start_turn.json` 缺 `model_mode`/`model_override`/`ops_eval`，而 `python/agent_contracts/commands.py` 42–46 已有；无任何测试比对两边。单一来源生成 + CI diff gate。
**[高] C2 — OpenAPI→TS codegen 无 CI 门禁**：`scripts/codegen.sh` 在无 npx 时 `exit 0` 静默跳过；CI 无 codegen 步骤，前端 `schema.d.ts` 可静默过期。CI 跑 `codegen && git diff --exit-code`。
**[中] C3 — 事件 payload jsonschema 校验在热路径默认开启**（runtime `settings.py` 148 默认 True，每次 `append_event` 走 `iter_errors`）：生产对 `turn.token`/delta 类高频事件抽样或轻量校验，严格模式留给 CI。
**[中] C4 — `validate_payload` 靠 `sys.path.insert` hack 导入**（`app/contracts/event_validation.py` 22–36），应并入 `agent_contracts` 正式包；双 `pyproject.toml` 结构同步收敛。

---

## 6. 数据库迁移

**[高] M1 — 遗留库 stamp 到 head 可跳过迁移**：`services/api/app/db/migrate.py` 27–35，只要存在 `sessions` 表且无 `alembic_version` 就 `stamp head`，缺 phase1* 表的半新库被标成最新，运行期才炸。stamp 应指向已知基线 revision 或按表集合探测。
**[中] M2 — Alembic 只是薄包装，`downgrade` 几乎全 `pass`**：revision 内容是 `run_ddl("phase*.sql")`，可回滚性差；至少 CI 检查"新 revision 必须引用新 DDL 文件"，关键迁移写真 downgrade 或明确 forward-only。
**[低] M3 — 死文件 `schemas/ddl/schema_migrations.sql`**（已迁 Alembic），删除或标 legacy。

---

## 7. CI / 测试 / Makefile

**[高] T1 — api 与 web 测试基本不进 CI**：`scripts/ci_proof.sh` 36–42 只跑 api 的 `test_ux_signals_api.py`（api 共 21 个测试文件、714 行集成测）；web 有 ~24 个 vitest 文件，workflow 完全没跑。CI 矩阵补 `unit.api` 全量 + `pnpm test`。
**[高] T2 — CI 单 job、无缓存、超时 120 分钟**（`.github/workflows/ci.yml` 32–66）：拆 unit（runtime/api/contracts/web 矩阵）与 gate 两个 job；加 pip/pnpm/docker-layer cache。
**[高] T3 — `eval-run-isolated` 约 100 行脆弱 shell 内嵌 Makefile**（L209–309，含 `chmod 0777` workspace）：迁入 `scripts/eval_isolated.sh`，权限收敛为 uid 可写；smoke/gate/eval 三处重复的 compose restore 逻辑合并为 `scripts/compose_restore.sh`。
**[中] T4 — Makefile 62 个目标语义重叠**（`sync-sources`≡`seed-sources`、`hooks-install`≡`ensure-git-hooks`、`contracts-test` 实际跑全量测试）：`help` 分组 + 合并别名。
**[中] T5 — nightly 无 secret 时静默成功、live 失败 `continue-on-error`**（`nightly.yml` 22–35）。
**[中] T6 — runtime 测试 Docker 回退路径丢 coverage gate**（Makefile 329–334 无 `--cov-fail-under=80`）。
**[低] T7 — `.gitignore` `.coverage` 规则写了两次**；本地 `debug.log`/`test.log`/`.coverage` 已被正确 ignore（未入库），属本地垃圾可删。

---

## 8. 跨切面主题汇总

| 主题 | 相关条目 | 一句话 |
|------|----------|--------|
| 事件主链路正确性 | A1 A2 A4 A5 W1 W2 E5 | 链路设计对，但两端实现都有会丢/重/慢的缺陷 |
| 检索热路径 | R1 R2 R3 R6 E11 | 同步阻塞 + 全量加载 + 不稳定 hash，是当前最大的性能与正确性组合债 |
| 安全默认值 | A7 A8 A9 D1 D2 E8 | "开发方便"默认值会原样带上生产 |
| 巨石文件 | G2 E3 E11 A16 W4 W10 T3 | 千行级文件 8 个，复制漏改已产生真实 bug（E1） |
| 契约漂移 | C1 C2 W9 | 三处"人工同步"都已出现或随时会出现漂移 |
| CI 盲区 | T1 T2 T5 | api/web 回归主要靠 golden 撑，单测缺口大 |

---

## 9. 建议落地顺序

**第一批（正确性 + 稳定性，改动面小收益大）**
1. R1/R2：`search_sources` 走 `to_thread` + store 单例 + 去掉每查询全表 load
2. R3：HashEmbedder 稳定哈希 + reindex
3. A1/A3/A4：LISTEN 扇出、SSE ping、QueueFull 兜底
4. A2/A5：view 读路径条件投影 + 投影单调 UPSERT
5. W1/W2/W3/W6：前端去重、断流重连语义、mutate 修复
6. E1：审批恢复补 checkpoint 回调（引擎装配工厂化）
7. G1：gateway 流 `aclose()`

**第二批（安全基线）**
8. D1/A7：docker.sock 拆 sidecar、api 非 root、Ops 读写密钥拆分且不进 URL
9. A8/D2：生产默认密钥 fail-fast
10. M1：migrate stamp 收窄

**第三批（工程效率）**
11. C1/C2：契约单一来源 + codegen CI 门禁
12. T1/T2：CI 拆 job + api/web 测试入 CI + 缓存
13. E2：并行工具结果有序合并

**第四批（结构性还债，可随功能迭代摊销）**
14. 拆 `gateway.py`（stub 分离）、`turn_controller.py`、`tools.py`、`projector.py`、`useWorkbench.ts`、`SettingsPage.tsx`、`eval_run.py`
15. W4/W5/W7/W8：前端长会话性能（Context 分片、events 投影化、虚拟化、路由分割）
16. D4/D5/D6/D7：镜像与 compose 清理；T3/T4：Makefile 瘦身

---

*本文由一次全仓审查产出（2026-07-27），条目未修复前保持有效；修复后请在对应条目标注 ✅ 与 commit。*
