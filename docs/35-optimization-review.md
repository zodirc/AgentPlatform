# 35 — 全仓优化审查·第二轮(2026-07-27)

> 第一轮审查(2026-07 上旬)共 79 条,经 `0dd6634`(stabilize realtime/retrieval and harden production defaults)、`e319cfa`(harden tool exec with OS sandbox)等提交,**约 24 条已修复、20 条部分修复、35 条未修复**(未修的多为结构性还债)。
> 本轮为在此基础上的全量复审,按两个视角重新组织:
> **视角一 = Agent 客户端交互**(不改交互逻辑的前提下,把交互速率、流畅度、正确性做到成熟 agent 水准);
> **视角二 = Agent 后端成熟度**(停机/崩溃/幂等/安全/可观测性/资源治理)。
> 每条标注 **[高]/[中]/[低]**,附精确 file:line。**第二轮建议落地顺序(§6)四批已于 2026-07-27 全部落地**;条目状态见 §1.4。

---

## 0. 总体判断

第一轮最痛的几处已经兑现:检索热路径异步化 + store 单例 + 稳定哈希(R1/R2/R3)、gateway 流治理(G1/G3)、SSE/投影链路的抢通知与全量投影(A1–A4)、前端去重与断流重连(W1/W2/W3/W6)、并行工具状态隔离(E2)、审批恢复 checkpoint(E1)、生产弱密钥 fail-fast(A8 大部分)。**事件主链路的"丢/重/慢"三类正确性缺陷基本清零。**

本轮 §6 四批建议项已落地后,原先四类主债状态:

1. ~~**流式热路径的 per-token DB 放大**~~ → ✅ I1/I2/I3/I4/I6(首包立即写 + 40ms 批窗;SSE 空闲 2s;投影追平后再兜底 project);
2. ~~**停机/崩溃/幂等语义缺失**~~ → ✅ B2(启动 reconcile + drain)/B3/B4/B5/B6 + I11/I12(认领仅 `accepted`;审批原子 claim + 幂等重放);
3. ~~**三个真实的前端功能缺陷**~~ → ✅ I7/I8/I9(+ I10 审批失败落 `turn.failed`);
4. ~~**运维基线缺口**~~ → ✅ F1–F7 主体 + B9/B23/B24 主体(备份/轮转/restart/gitleaks/lint;histogram 固定桶;stdlib→structlog)。

**仍开放**(未列入本轮四批,或仅部分兑现):I5(真流式 shell)、I18/I20–I22、I19 中 `tool_timeline.stream_output` 无界累加、B7/B8/B11–B14/B19–B22/B25/B26、F4 镜像 SHA 打 tag、F8 live/interview 覆盖、F10–F14、以及 §1.3 结构性还债。

---

## 1. 第一轮条目结算

### 1.1 已修复(✅,不再跟踪)

| 域 | 条目 | 证据 |
|---|---|---|
| Runtime | R1 检索热路径阻塞 | `tools.py:17-23` `_run_retrieval_blocking`(to_thread + ContextVar 拷贝) |
| Runtime | R2 store 无单例/全表 load | `store.py:78-124` 进程级缓存;pgvector `load()` 仅 ensure_schema |
| Runtime | R3 HashEmbedder 不稳定哈希 | `embedder.py:48-53` 改 blake2b |
| Runtime | G1 流不 aclose() | `gateway.py:991-999` finally 无条件 aclose |
| Runtime | G3 liveness 禁止重试 | `gateway.py:854-872` 区分 emitted_liveness / emitted_user_visible |
| Runtime | E1 审批恢复丢 checkpoint | `turn_controller.py:1310-1325` resume 路径传 on_step_checkpoint |
| Runtime | E2 并行工具乱序写 state | `agent_engine.py:516-570` 隔离副本 + 按序确定性合并 |
| Runtime | C3 事件校验热路径 | `event_validation.py:64-75` 高频 delta 默认轻量 shape check |
| API | A1 SSE/投影抢通知 | `listener.py:49-73` per-turn Event 扇出 + 独立投影队列 |
| API | A2 view 读路径全量投影 | `projector.py:562-581` 条件投影 |
| API | A3 SSE 无 keep-alive | `sse.py:10,20-21` 空闲约 15s 一次 `: ping` |
| API | A4 QueueFull 丢通知 | `listener.py:52-61` 捕获 + 指标 + reconcile 兜底 |
| API | A9 NULL owner 全员可写 | `end_user/auth.py:91-95` 一律 403 |
| API | A15 WS 审批失败静默 | `ws.py:73-127` 回发结构化 error |
| API | M1 遗留库 stamp head | `migrate.py:27-37` stamp 到 0001_phase0 |
| Web | W1 事件不去重 | `TurnStreamClient.ts:109-117` 跳过旧 sequence |
| Web | W2 干净断流不重连 | `TurnStreamClient.ts:131-134` 非终态 done → 指数退避重连 |
| Web | W3 WS onerror 即报错 | `TurnWebSocketClient.ts:84-86` onerror no-op,由 onclose 驱动 |
| Web | W6 渲染期 mutate state | `useWorkbench.ts:994-1006` 先拷贝再 push |
| 基建 | C1 start_turn 契约漂移 | schema 已补齐 + `test_commands_schema_sync.py`(注意:断言单向) |
| 基建 | C2 codegen 无门禁 | `codegen.sh:10-14` CI 缺 npx 即 fail;`ci.yml:120-124` diff gate |
| 基建 | T1 api/web 测试不进 CI | `ci_proof.sh:82-96` api 全量;`ci.yml:117-119` web vitest |

### 1.2 部分修复(⚠️,剩余部分并入 §2/§3;本轮已闭合的见 §1.4)

- **A5** 投影单调性:`turn_views` UPSERT 已加 `last_event_sequence <=` 守卫(`projector.py:519`),但 `turns`/`runs` 状态 UPDATE 无保护(`projector.py:487-504`),并发重放仍可写回旧 status → 见 B14。
- **A6/R6** LISTEN 已池外独立连接(`listener.py:93-95`),但两侧池 `max_size=10` 仍硬编码(api/runtime `db/pool.py`);检索仍是 psycopg 每查询新建短连接(hybrid 一次 3 条)。**本轮**已加 `command_timeout` + PG `statement_timeout`(B10)。
- **A7** Ops 密钥已出 URL 改 Bearer + 常量时间比较(`ops/auth.py:14-30`),但同一密钥仍兼读写(创建 eval run、docker recreate,`ops_eval.py:62-74`)。
- ~~**A8** 生产守卫不强制 `auth_enabled`~~ → ✅ 升级项 **B1** 已落地。
- **A11** runtime 客户端已进程级复用(`runtime_client.py:12,35-40`),但无重试;cancel/approve/deny/patch 仍不捕获 httpx 异常 → 裸 500。
- **A18** session 列表已 keyset 分页(≤50),但 title/preview 仍每行两个相关子查询(`resource/sessions.py:75-88,113-126`)。
- **G4** Provider 协议已标 StreamActivity,gateway 自身标注仍缺(`gateway.py:822,941`)。
- **G5** CI 下 stub 未路由即 fail(`gateway.py:463-469`),本地默认仍返回 `[stub] Acknowledged`。
- ~~**E7** token 估算逐字符~~ → ✅ 升级项 **I6**(预编译正则 + `lru_cache`)。
- **E8** bwrap 默认开启…——已文档化为威胁模型选择,保持跟踪。
- **E10** 静默吞异常大幅减少;残余含 ToolExecutor 吞堆栈 → 见 B25。
- **W4** delta 已 rAF 批量;Context 仍是单体 `value={wb}`。
- **W5** 直播 delta 已不进 events,但刷新恢复仍全量回放;派生仍每 render 全量扫描。
- **W15** 已引入 react-router,但 `App.tsx` 仍手写前缀分支。
- **D1** docker.sock 已移入 opt-in overlay,但 api 镜像仍 `USER root` + 打包 docker-cli → 见 F10。
- **D2** 生产守卫已覆盖 api/runtime,但 compose 默认值仍弱、`POSTGRES_PASSWORD` 不在守卫内、无生产 overlay。
- **D3** 已加 mem_limit;~~ha.yml runtime 无限制~~ → ✅ 本轮 ha.yml 补 `mem_limit: 4g` + restart;全栈仍无 CPU 限制。
- **D7/D9** retrieval overlay 已注释为兼容用途;api 的 compose(ready)与镜像 HEALTHCHECK(live)语义仍分裂。
- **T2** CI 已拆 job + 缓存;本轮新增 `static-checks`(lint/typecheck/gitleaks)。proof 仍单个大串行 job。

### 1.3 未修复直接结转(编号沿用第一轮;本轮已闭合的划掉)

- **结构性巨石**:G2、E3、E11、A16、W10、W7、W8、W9、W11 — 仍开放。
- **检索**:R4、R5 — 仍开放。
- ~~**DB 卫生**:A12 / A13 / A14~~ → ✅ 本轮落地(删 session 清 envelopes;部分索引;reconcile LIMIT 200)。A17/M2/M3 仍开放。
- **引擎**:~~E4~~→B9-① TTL;~~E5 写放大~~→I2 批写缓释(advisory lock 路径仍在);E6、E9 仍开放。
- **前端**:W7–W9、W11、W13、W14 仍开放;~~W12~~→✅ I9。
- **基建**:D4、D6、D8、T3–T7、C4 仍开放;~~D5~~→✅ F2。

### 1.4 第二轮已修复(✅,2026-07-27 四批落地)

| 批 | 条目 | 证据(摘要) |
|---|---|---|
| 1 | I1 | 流式循环删逐 chunk `_check_cancel`;draft 重放 250ms 节流 |
| 1 | I7 | WS 审批统一 HTTP;`TurnWebSocketClient` 去掉 socket approve |
| 1 | I8 | 子代理 delta 进 rAF 缓冲 → `subagentLive` |
| 1 | I9 | Stop 定时器捕获点击时 `turnId` + 同 turn 守卫 |
| 1 | I10 | 审批超时/状态丢失落 `turn.failed`(`approval_resume_timeout` / `approval_state_lost`) |
| 1 | B1 | production 强制 `AUTH_ENABLED` / `END_USER_AUTH_ENABLED` |
| 1 | B3 | runtime `_try_claim_command` 进程内原子占用 |
| 1 | I11 | api `(turn_id, client_request_id)` TTL 去重重放 |
| 1 | I12 | `create_turn` → `INSERT … ON CONFLICT DO NOTHING` + 回读 |
| 1 | F1 | pre-push → `preflight_unit.sh`(核实无需再改) |
| 1 | F2 | `.dockerignore` 重写(含 `.env`、workspace、全深度 node_modules) |
| 1 | F3 | compose + ha.yml `restart: unless-stopped` |
| 1 | B18+A10 | `hmac.compare_digest`;两侧 `/metrics` Bearer |
| 2 | I2 | `BufferedEventWriter`(首包立即 + 40ms 窗;非 delta 先冲刷);`EVENT_BATCH_WINDOW_SECONDS=0` 可回滚 |
| 2 | I3 | `IDLE_WAIT_SECONDS=2.0`;有 NOTIFY 仍即时唤醒 |
| 2 | I4 | 流结束等投影追平(2s 兜底才 `project_turn`) |
| 2 | I6 | CJK 正则 + `lru_cache(2048)` |
| 2 | A12/A13/A14+B10 | 清 envelopes;迁移 0016 部分索引;reconcile LIMIT;池级 statement_timeout |
| 3 | B2/B4 | 启动 `reconcile_runner_orphans`;SIGTERM `drain_active_turns`;认领仅 `accepted`;枚举 `runner_restart`/`budget_exceeded` |
| 3 | B9+B24 | pending TTL;固定桶 histogram + `# TYPE`;secret_scan `kind=`;listener TTLCache;inflight/DB 池/append/HTTP 延迟指标 |
| 3 | B5/B6 | outbox 回收 >10min `processing`;LISTEN 30s `SELECT 1` |
| 3 | B15–B17 | login/register IP 限流;token `pv` 改密吊销;`audit_log`(迁移 0017) |
| 3 | F4/F5/F6+B23 | `make backup`;json-file 10m×3;eval baseline diff;stdlib→structlog ProcessorFormatter |
| 4 | I13–I17 | ErrorBoundary;乐观气泡;Markdown;online 重附着;SSE idle watchdog |
| 4 | I19(部分) | view ETag/304;events `limit`/`has_more`;**未修** `tool_timeline.stream_output` 无界 |
| 4 | F7 | CI `static-checks`:ruff 关键规则 + web lint/typecheck + gitleaks |
| 4 | F8(部分) | 越权集成测试 13 项;`make eval` 一次起栈 `--phase 1,1b`;live/interview 覆盖仍薄 |
| 4 | F9 | SemVer + `CHANGELOG.md` 0.2.0;`test_openapi_contract.py`(yaml ⊆ FastAPI) |

单测基线(落地后冒烟):runtime 459 / api 121 / web 101 / contracts 62。

---

## 2. 视角一:Agent 客户端交互(编号 I*)

> 目标:在不改变交互逻辑的前提下,把"每个 token 的成本、每次断流的恢复、每次审批的往返"做到成熟 agent 水准。

### 2.1 流式热路径(交互速率的上限)

**✅ [高] I1 — 每个流式 chunk 一次 Postgres 取消查询**
`services/runtime/app/engine/agent_engine.py:274`:`async for chunk in stream` 循环内每个 delta 都 `await self._check_cancel()`(一条 SELECT,`run_lock.py:50-62`)。而 `:265-267` 已有 50ms 后台取消监视任务,完全冗余——每个 token 在写事件前先付一次 DB RTT,长回复时 DB QPS 随 token 速率线性爆炸。
**建议**:删循环内 DB 查询,只检查后台 watcher 置位的内存标志 `state.cancelled`。

**✅ [高] I2 — 每个 token delta 一次完整事件事务(叠加旧 E5)**
`agent_engine.py:298-304` 每个 delta 发一条 `turn.token`;`turn_controller.py:528-538` 每次取连接开事务;`events.py:16-30` advisory lock + `MAX(sequence)` + INSERT。合计**每 token 约 4 次 DB 往返**。`draft_section` 更甚:内容已完整生成,按 16 字符切片逐条走同样路径且每片再查一次 cancel(`agent_engine.py:807-822`)。
**建议**:进程内 per-turn 序号计数器 + 50–100ms 时间窗合并 delta 批量插入;draft 重放砍掉逐片 cancel 查询。

**✅ [中] I3 — SSE/WS 空闲期每客户端 0.3s 一次全量 DB 轮询**
`services/api/app/services/realtime/events.py:76-94`:循环内无条件 `fetch_turn_events`,`wait_for_turn(timeout=0.3)` 只降延迟不省查询——每个观看客户端约 3.3 QPS,LISTEN 通知的价值没吃满。
**建议**:仅 `notified=True` 或长超时(如 2s)后才查询。

**✅ [中] I4 — 每个流客户端在 pause/terminal 时各自全量重放投影**
`events.py:88-92` 流结束前调 `project_turn`,与 `_consumer_loop` 重复;同一 turn N 个客户端 N 倍重放。
**建议**:流侧等待 `turn_views.last_event_sequence` 追平,由投影队列独家投影。

**[中] I5 — run_command 无实时输出且全量缓冲内存**
`services/runtime/app/tools/core/shell.py:122,158`:`proc.communicate()` 等进程结束才拿全部输出,32k 截断发生在完整读入之后——长命令期间 UI 零反馈,大输出命令先吃满内存;`agent_engine.py:875-888` 的 `tool.delta` 是命令结束后按 24 字符切片的"假流式"。
**建议**:增量读 pipe,边读边限量边发 delta。

**✅ [中] I6 — 每 step ≥5 次全窗口逐字符 token 估算(旧 E7 剩余)**
`services/runtime/app/context/engine.py:553-560` 逐字符 CJK/ASCII 分类;`_build_envelope` 调 `_window_fill` ≥5 次(`:353,381,400-414,416,432`),128k 上下文时是每次模型调用前的数十万次 Python 循环,且阻塞同进程所有其它 Turn 的事件发射。
**建议**:按 message 缓存估算值只重算变更消息,或整体移入 `to_thread`。

### 2.2 交互正确性(功能缺陷)

**✅ [高] I7 — WS 模式下审批动作静默丢失**
`services/web/src/shared/realtime/TurnWebSocketClient.ts:78-82` 收到 `approval.requested` 即 `close()` 并把 socket 置 null;用户点批准时 `useWorkbench.ts:939-941`(deny 同 `:970-971`)仍调 `streamRef.current.approveToolCall()`,内部 `this.socket?.send`(`TurnWebSocketClient.ts:103`)对 null 静默 no-op——**审批永远到不了后端**,UI 已乐观置 running。
**建议**:WS 模式审批统一改走 HTTP approve API(该路径已存在且正确)。

**✅ [高] I8 — 子代理实时流式文本被 delta 过滤整体丢弃**
`useWorkbench.ts:357` 把所有 delta 事件挡在 events 之外,`:361,369,389` 对带 `subagent_id` 的 delta 直接 return;而子代理卡片的 `streamText/thinkingText` 唯一来源是扫 events(`subagents.ts:91-99`)。直播期间子代理标签页看不到任何思考/输出文本,只有刷新回放后才补齐。
**建议**:带 `subagent_id` 的 delta 单独进 rAF 缓冲累积到 subagent 状态。

**✅ [高] I9 — handleStop 定时器竞态误伤新 turn(旧 W12 升级)**
`useWorkbench.ts:849-865` 500ms 定时器用 `turnIdRef.current` 决定 force-cancel:软取消快速生效、outboundQueue 立即 flush 启动新 turn 后(`:787-802`),定时器会 **force-cancel 新 turn**;`:867-873` 的 2.5s 兜底无条件 `setBusy(false)` 同样可清掉新 turn 的 busy。
**建议**:定时器闭包捕获点击时的 turnId;新 turn 启动/unmount 时 clearTimeout。

**✅ [中] I10 — 审批命令在 runtime 侧静默丢弃,用户无感知**
`services/runtime/app/controller/turn_controller.py:363-369,397-403`:`_wait_turn_inactive` 超时(120s)或 pending 无法解析时仅 warning 后 return,不发任何事件——前端按钮点了没反应,Turn 永远停在 `waiting_approval`。
**建议**:失败路径落 `turn.failed` 或专门 approval-error 事件,让 UI 可提示重试。

**✅ [中] I11 — 审批/取消命令幂等字段收而不用**
`services/api/app/routers/turns.py:36,42`:`client_request_id` 在请求模型中声明但从不传 runtime 也不去重,网络重试会重复下发 approve/deny/cancel(与 B3 的双重执行竞态叠加成真实风险)。
**建议**:透传 runtime 或 api 侧按 (turn_id, client_request_id) 去重。

**✅ [中] I12 — create_turn 幂等有 TOCTOU 竞态**
`services/api/app/resource/turns.py:17-57` 先 SELECT 后 INSERT,并发重复请求撞 UNIQUE 约束返回裸 500 而非已有 turn。
**建议**:`INSERT ... ON CONFLICT DO NOTHING` + 回读。

### 2.3 客户端体验成熟度(对标成熟 agent 客户端)

**✅ [中] I13 — 全应用无 ErrorBoundary**:`main.tsx:15-27` 任一渲染异常直接白屏。App 外层与 ops 页各加一层。
**✅ [中] I14 — 发送无乐观上屏**:用户气泡仅在 `startTurn` 响应后 upsert(`useWorkbench.ts:743-758`),慢网下点发送后消息区空白。先 upsert 一条 pending 占位。
**✅ [中] I15 — 重连耗尽后无法重附着**:8 次重连失败即清 busy(`TurnStreamClient.ts:55-58`),无 `online` 监听、无手动重连按钮,恢复逻辑 `sessionRestoredRef` 只跑一次(`useWorkbench.ts:602`),只能整页刷新。
**✅ [中] I16 — 助手输出无 Markdown 渲染**:`AgentChatPanel.tsx:102-111` 用 `<pre>` 纯文本,代码块/链接/列表全裸露——与成熟客户端差距最直观的一处。
**✅ [中] I17 — SSE 无空闲看门狗**:`TurnStreamClient.ts:90-92` `reader.read()` 在代理静默挂起(不断连也不发数据)时永久阻塞,turn 卡死在 busy。加 heartbeat 超时(服务端已有 15s ping 可作信号)。
**[中] I18 — 多 tab 零同步**:localStorage 无 `storage`/BroadcastChannel 监听,双 tab 打开同一 session 时 busy/queue/history 各自为政,queue flush 可能重复发送。
**⚠️ [中] I19 — view/事件接口无条件请求与上限**:view 轮询无 ETag/304 且 `tool.delta` 无限累入 `tool_timeline.stream_output`(`projector.py:362-374`),长流 turn 响应体积无上界;`fetch_turn_events` 无 LIMIT(`events.py:18-51`),`since_sequence=0` 一次载入全部;前端刷新恢复也全量回放(`useWorkbench.ts:624-626`)。支持 `If-None-Match: last_event_sequence` + 事件分页。
> ✅ 已落地:view ETag/304 + events `limit`/`has_more`(前端自动翻页)。⚠️ 残余:`tool_timeline.stream_output` 无界累加未截断。

**[低] I20 — 会话切换全量重建**:`App.tsx:280` `key={sessionId}` 强制 remount 整个 Provider 树 + 全量事件回放,长会话切换有可感知卡顿。
**[低] I21 — start_turn 超时标记与 runtime 实态分叉**:30s 超时后 `mark_turn_start_failed`(`sessions.py:172-176`),但 runtime 可能已开跑,前端先见 failed 再被事件翻转为 running。超时路径补发 cancel 或标记 unknown 待 reconcile。
**[低] I22 — 错误码对前端可操作性弱**:error.code 只是 HTTP 状态映射(`main.py:43-53`),业务语义全在人读 detail 里;且无全局 Exception handler,未捕获异常返回裸 500 无 request_id。前端错误通道也是单条 string 互相覆盖(`useWorkbench.ts:132,289-292`)。
**⚠️ [低] I23 — 细节体验**:输入历史光标定位失效(`useChatInputHistory.ts:70-76` rAF 里 `e.currentTarget` 已为 null)、审批卡片仅主 tab 可见(`AgentChatPanel.tsx:548`)、流式区域无 `aria-live`、草稿不持久、删除会话用 `window.confirm`、openSession 连点竞态(`workbenchSession.tsx:95-108`)。
> ✅ 已落地:流式区域 `aria-live="polite"`。其余子项仍开放。

---

## 3. 视角二:Agent 后端成熟度(编号 B*)

### 3.1 停机 / 崩溃 / 幂等(多副本部署前的正确性门槛)

**✅ [高] B1 — 生产守卫不强制 `auth_enabled`,默认配置下 `/admin/workspace/*` 匿名可读写删**
`services/api/app/services/admin/auth.py:64-65` `require_admin_or_end_user`:无 end-user 且 `auth_enabled=False`(默认值)时直接放行;匿名 tenant 为空 `{}`(`admin/workspace.py:27-28`),经 `X-Internal-Token` 转发 runtime 无任何租户约束,含 `POST /entries/delete`、`/sources/upload`。`validate_production_security`(`settings.py:51-73`)不检查 `auth_enabled`/`end_user_auth_enabled`。
**建议**:production 强制 `auth_enabled=True`,或该路由匿名一律 401。

**✅ [高] B2 — 无优雅停机,mid-turn 崩溃无恢复路径**
Turn 以 BackgroundTasks 运行(`runtime/app/main.py:70-86`);SIGTERM 无 `_active_turns` drain,lifespan 直接 `close_pool()`(`main.py:495`)。每步都写 checkpoint(`turn_controller.py:1058-1064`),但唯一消费入口 `_pending_from_checkpoint` 在 `interrupt is None` 时返回 None(`:285-287`)——**非审批中断的 step checkpoint 从未被任何代码读取**。崩溃后 Turn 永久卡 `running`,兜底 `stall_auto_fail` 默认关闭(`settings.py:153`)。
**建议**:启动时按 `runner_id` 扫描本机认领的 running runs,基于 checkpoint 恢复或 fail-fast 落 `turn.failed`;SIGTERM 先停新 Turn 再 drain。

**✅ [高] B3 — 审批双重执行竞态**
`turn_controller.py:363-386`:`_wait_turn_inactive`(轮询非锁)→ `_resolve_pending` → `_active_turns.add`,两个并发 approve(双击/重试,`main.py:99-112` BackgroundTasks 使并发可能)都能拿到同一 pending,**把已批准的写工具执行两次**。deny 同理。
**建议**:原子 test-and-set——先 `pop(turn_id)` 抢占 pending,抢不到即返回。

**✅ [中] B4 — start_turn 重放会整轮重跑**
`run_lock.py:22-25` 允许同 runner 对 `status='running'` 重复认领;进程重启后内存去重失效,api 重发 start-turn 会把同一 Turn 从头再跑一遍,事件表追加整套重复事件。
**建议**:认领仅允许 `accepted`;`running` 一律走 B2 的恢复路径。

**✅ [中] B5 — outbox `processing` 无超时回收**
`services/api/app/services/outbox.py:44-85`:claim 后进程崩溃,job 永久卡 `processing` 无人认领;重试 5 次后需人工。
**建议**:`updated_at < now() - interval '10 min'` 的 processing 重置为 retry。

**✅ [中] B6 — LISTEN 连接死活不检测**
`listener.py:98-99` 建连后 `sleep(3600)` 死循环,PG 重启/网络闪断后的半开连接不触发重连,实时性静默退化为 0.3s 轮询且无告警。
**建议**:循环内周期 `SELECT 1` 探活。

**[低] B7 — 孤儿取消器可与存活 worker 竞争写终态**:`turn_controller.py:115-123` 仅以"最后事件 >3s"判死;长思考期间取消会双写 `turn.cancelling/cancelled`。孤儿判定应结合 runner 心跳。
**[低] B8 — API 优雅停机不管在飞 SSE/WS**:`api/app/main.py:96-106` 无信号让 `iter_turn_events` 退出,shutdown 被活跃长连接拖到强杀。

### 3.2 内存与资源治理

**✅ [高] B9 — 长期运行内存无界增长(三处)**
① `runtime/app/controller/pending_store.py:25` 模块级 `_store` 无 TTL/上限——放弃审批的 Turn 把完整 messages + gateway + tools 永久留在内存(旧 E4 叠加成泄漏);② runtime 与基建共用的自研 metrics:`observability/metrics.py:13-15` `_Histogram._values` 只增不减,进程跑数周必然膨胀;③ `secret_scan.py:91` 把动态 findings 拼进 metrics label,无界 label 基数。api 侧同类:`listener.py:51,64` `_turn_events` per-turn Event 永不清理;`ops/runs.py:58` `_RUNS` 只增不减。
**建议**:pending 加 TTL(checkpoint 已可兜底恢复);histogram 改固定桶;禁止动态值入 label;终态后清理 per-turn dict。

**✅ [中] B10 — DB 层无语句超时**:`pool.py:13`(两侧)无 `command_timeout`,慢查询(如 A13 全表聚合)可无限占住连接。池级 command_timeout + PG statement_timeout。
**[中] B11 — 子 agent token 用量逃逸计量**:`delegate_runner.py:139-147,177` 子 agent 的 `sub_state.usage` 用完即弃,不进父 Turn 预算(`agent_engine.py:473-478`)、不进月度限额、Ops 不可见——预算控制可被委派绕过。返回前累加回父 usage 并补发带 `subagent_id` 的 usage 事件。
**[中] B12 — 多处同步 FS 操作仍在事件循环**:`sources_watch.py:33-44,74` 每 2s 同步 rglob 全 sources 树;grep/keyword 同步扫树(旧 E11);`read_file` 无条件整文件 `read_text` 再切片(`tools.py:176`),GB 级文件同时阻塞 loop 和吃内存。统一 to_thread + 大小预检。
**[低] B13 — 每 Turn 工件无清理**:`.agent/work/turns/{turn_id}.json` 永不清理(`tools.py:398,510-522`),目录无界增长。

### 3.3 数据正确性与安全

**[中] B14 — turns/runs 状态更新无单调性保护(A5 剩余)**:`projector.py:487-504` 并发重放可把旧 status 写回 `turns` 表;`turn_views` 的 `<=` 守卫也允许同序覆盖。补条件更新或 advisory lock。
**✅ [中] B15 — 全站无 rate limit**:`/auth/login`、`/auth/register`(`routers/auth.py:45-67`)可无限暴力,密码最短 6 位;create_turn 亦无限流。至少 auth 端点加 IP 限流/失败锁定。
**✅ [中] B16 — 会话 token 无吊销**:自制 HMAC token TTL 30 天(`tokens.py:14,26-38`),logout 仅清 cookie,改密码不失效旧 token。token 内嵌 password_hash 派生版本号。
**✅ [中] B17 — 敏感操作无审计**:approve/deny/cancel/patch/删 session 不落库记录 actor(`routers/turns.py` 全文件)。加 audit_log 表。
**✅ [低] B18 — 内部令牌非常量时间比较**:`runtime/app/main.py:56-58` 用 `!=`,改 `hmac.compare_digest`(api 的 ops/auth 已是正确示范)。
**[低] B19 — 502 透传 runtime 内部错误文本**:`sessions.py:177-182` 前 300 字符直达终端用户。
**[低] B20 — 无 CORS/安全头/CSRF token**:同源网关假设未在代码层固化,cookie 仅靠 SameSite=lax。
**[低] B21 — health/ready 级联依赖 runtime 且每次新建客户端**:`api/app/main.py:174-185`,runtime 故障连带 api 被摘流,放大故障域。ready 只查自身依赖。
**[低] B22 — ws 消息循环忙轮询且脆弱**:`ws.py:31-38` 每 0.2s 轮询;非 JSON 消息使整条连接崩掉。

### 3.4 可观测性

**✅ [中] B23 — 绝大多数日志绕过 structlog,无关联 ID**
两侧同病:structlog + request_id/turn_id contextvars 已配好(`middleware/request_context.py:29-33`),但业务代码全用 `logging.getLogger`(gateway、engine、tools、listener 无一例外),实际产出的日志**大部分无时间戳、非 JSON、无 trace/turn 关联**。
**建议**:`structlog.stdlib` ProcessorFormatter 把 stdlib 日志接入同一处理链。

**⚠️ [中] B24 — 指标覆盖缺口且无采集端**
runtime 缺 in-flight turns gauge(`runtime_max_inflight_turns=16` 拒绝时无从预警)、DB 池占用、事件 append 延迟、模型首字节直方图;histogram 只出 `_sum/_count` 无分位数。api 自研 registry 连 histogram 都没有(`api/observability/metrics.py:8-33`),无 HTTP 延迟指标,`/metrics` 输出无 `# HELP/# TYPE`,且仍无鉴权(旧 A10)。deploy/ 里没有任何 Prometheus/OTLP 采集端——**指标存在但没人看得到**。
**建议**:换 prometheus_client 标准库 + 部署最小采集端;顺带解决 B9-② 泄漏。
> ✅ 已落地:固定桶 histogram + `# TYPE`、inflight/DB 池/append/HTTP 延迟、`/metrics` Bearer。⚠️ 残余:未换 `prometheus_client`、deploy 无采集端、模型首字节直方图未加。

**[低] B25 — ToolExecutor 吞堆栈**:`context/engine.py:92-93` 工具 bug 只以 `{"error": str(exc)}` 出现在模型上下文,运维日志无堆栈。返回前 `logger.exception`。
**[低] B26 — projector 死变量误导**:`projector.py:309,396` `pending_interrupt = None  # noqa: F841` 从未被读。

---

## 4. 工程基建(编号 F*)

**✅ [高] F1 — pre-push 跑完整 CI proof,过重且有副作用**
`.githooks/pre-push:34-35` → 全量 unit×5 + `make gate`(docker build + smoke + eval-all,期间 force-recreate 开发者正在跑的栈)+ web vitest + codegen 检查——几十分钟级。`33b9bb2` 引入后紧跟 `3ac36a2`/`f60afcb`/`263afae` 三个补丁全在修 hook 自身崩溃,已证明脆弱。
**建议**:pre-push 降级为已有的 `preflight_unit.sh`(路径分类做得不错),完整 proof 留给 Actions 与手动 `make preflight`。

**✅ [高] F2 — .dockerignore 模式不生效 + `.env` 在 build context 内(旧 D5 升级)**
`.dockerignore:2` 的 `node_modules` 只匹配 context 根;三个镜像 context 都是仓库根(`docker-compose.yml:25,96,150`),`services/web/node_modules` 数百 MB 每次全量上传;`.env`(真实密钥)、`workspace/`、`.eval-workspace/` 全在 context 内——今天没有 `COPY . .`,任何人加一句就把密钥烧进镜像层。
**建议**:改 `**/node_modules`、`**/dist`、`**/.venv`,显式排除 `.env*`、`workspace`、`.eval-workspace`、`*.log`、`docs`。

**✅ [高] F3 — 全栈无 restart 策略**:compose 及所有 overlay 无 `restart:`;宿主重启、runtime 触发 4g mem_limit 被 OOM kill 后不自愈。全部 `restart: unless-stopped`。

**⚠️ [高] F4 — 无备份、无镜像版本化、无回滚路径**:`pg_data`/`agent_data` 裸 volume 无任何备份任务;镜像 tag 全 `:latest`,回滚只能 git checkout 后全量重建。最小可用:`make backup`(pg_dump + tar)+ 按 git SHA 打 tag。
> ✅ 已落地:`make backup` → `deploy/backup.sh`(pg_dump + agent_data tar,保留最近 7 份)。⚠️ 残余:镜像未按 git SHA 打 tag / 无正式回滚流程。

**✅ [中] F5 — 容器日志无轮转**:compose 无 `logging:` 配置,json-file 无上限。加 `x-logging` anchor(max-size 10m × 3)。
**✅ [中] F6 — eval 结果无回归基线**:`eval_run.py:1652` 只写 `reports/`(被 gitignore),无 baseline 对比/趋势;nightly live 结果不上传 artifact 且 `continue-on-error`(叠加 T5,live 质量回归完全不可见)。入库 baseline 摘要 JSON,eval 结束时 diff 输出退化项。
**✅ [中] F7 — CI 缺 lint/typecheck/secret-scan 门禁**:CI 不跑 ruff/mypy;web 定义了 `lint` script 但 CI 只跑 test;`security_audit.sh:18` 注释声称 "CI runs gitleaks-action" 但**没有任何 workflow 跑 gitleaks**。三个分钟级 job,各自独立并设为分支保护必需检查。
**⚠️ [中] F8 — golden 覆盖偏科 + gate 重复起栈**:46 个 golden 中 live 仅 2、interview 仅 1;缺权限/越权/错误注入类 case。`make eval` 两个 phase 各自完整 `--force-recreate` 起栈一次,同一套容器可复用。
> ✅ 已落地:api 越权集成测试 13 项;`make eval` 一次起栈 `--phase 1,1b`(phase 精确匹配)。⚠️ 残余:live/interview golden 数量仍偏少。

**✅ [中] F9 — 契约无版本化与兼容演进策略**:schemas 无 version/changelog,事件 schema 一律 `additionalProperties: false`——加字段即双端锁步升级,ha.yml 滚动升级期间新旧副本互踩。另 `openapi/public.yaml` 手维护,codegen 只保证 TS ⊆ yaml,不校验 yaml ⊆ FastAPI 实际路由(可 CI diff `app.openapi()`)。
**[低] F10 — api 镜像打包 EOL 的 docker-compose v1**(`services/api/Dockerfile:19`);ops 工具链应拆到专用镜像,api 回归 `USER app`(顺带清 D1 残留)。
**[低] F11 — 阿里云镜像源硬编码为 Dockerfile 默认值**(`Dockerfile:6-7`、`Dockerfile.retrieval:5-8`),海外 CI 反而更慢。默认官方源,本地 build arg 覆盖。
**[低] F12 — pip 无 cache mount**:已有 `# syntax=docker/dockerfile:1`,加 `--mount=type=cache,target=/root/.cache/pip` 一行事,retrieval 的 torch ×2 立省数百 MB 重复下载(叠加 D4)。
**[低] F13 — 根目录本地产物堆积**:`debug.log`(145KB)、`test.log`、root 属主 `.coverage`(会让下次本地 `pytest --cov` PermissionError)、root 属主空目录 `deploy/workspace/`。均未入库(已核实 `git ls-files` 干净),建议 `make clean` 一并处理。
**[低] F14 — nightly 职责过窄**:唯一定时 workflow,只有 live 抽样(且永远绿);低成本挂上 pip-audit/pnpm audit/镜像 CVE 扫描。

---

## 5. 跨切面主题

| 主题 | 相关条目 | 一句话 |
|---|---|---|
| 流式热路径成本 | ✅ I1–I4 I6;残余 I5/R4/R6 | 批写 + SSE 2s + 投影追平已落地;真流式 shell(I5)仍开放 |
| 崩溃/幂等语义 | ✅ B2–B6 I11 I12 | reconcile fail-fast + drain;认领仅 accepted;审批 claim + 幂等 |
| 交互功能缺陷 | ✅ I7–I10 | 审批 HTTP、子代理直播、Stop 守卫、失败落 turn.failed |
| 内存无界增长 | ✅ B9 主体;残余 B13 | pending TTL、固定桶、TTLCache;工件目录清理仍开放 |
| 可观测性断层 | ✅ B23 F5;⚠️ B24 | JSON 日志 + 日志轮转 + 关键指标;无独立采集端 |
| 安全默认值 | ✅ B1 B15–B18;残余 D2 | auth 强制、限流、吊销、审计、compare_digest |
| 运维基线 | ✅ F1–F3 F5–F7;⚠️ F4/F8 | restart/备份脚本/轮转/CI 门禁;镜像 SHA tag 与 live 覆盖仍薄 |
| 结构性还债(结转) | G2 E3 E11 A16 W10 W7 W8 W9 T3 T4 | 仍开放,随迭代摊销 |

---

## 6. 建议落地顺序

> **状态(2026-07-27)**:下列 1–17 已全部落地(证据见 §1.4)。第 18 项结构性还债仍随迭代摊销。

**第一批(定点修复,正确性 + 手感)** ✅
1. I1:删流式循环内逐 chunk 取消查询
2. I7/I8/I9:WS 审批改 HTTP、子代理 delta 进缓冲、Stop 定时器捕获 turnId
3. B1:生产守卫强制 `auth_enabled`
4. B3 + I11:审批 pending 原子抢占 + client_request_id 真去重
5. F1/F2/F3:pre-push 降级、重写 .dockerignore、compose 加 restart
6. B18 + A10:内部令牌常量时间比较、/metrics 加鉴权

**第二批(热路径降本)** ✅
7. I2:token 事件批量写入(per-turn 序号计数器 + 时间窗合并)
8. I3/I4:SSE 通知驱动查询、投影去重
9. I6:context 窗口估算缓存
10. A12/A13/A14 + B10:DB 卫生三件套 + 语句超时

**第三批(生产化门槛)** ✅
11. B2/B4:崩溃恢复(启动 reconcile fail-fast + drain)与 start-turn 重放收窄
12. B9 + B24:内存泄漏三处 + 固定桶直方图/关键 gauge(未换 prometheus_client、未部署采集端)
13. B23:stdlib 日志接入 structlog
14. F4/F5/F6:备份、日志轮转、eval 基线(F4 镜像 SHA tag 未做)
15. B5/B6/B15/B16/B17:outbox 回收、LISTEN 探活、限流、token 吊销、审计

**第四批(体验与结构)** ✅(I19/F8 部分)
16. I13–I17 + I19(ETag/分页):ErrorBoundary、乐观上屏、Markdown、重附着、看门狗、条件请求
17. F7/F8/F9:CI lint/gitleaks、越权集成测试 + eval 合并起栈、契约版本化
18. 结转的结构性还债(§1.3):巨石拆分、虚拟化、代码分割、事件类型化 — **仍开放**

---

*本轮审查 2026-07-27 由四路并行深查产出(runtime / api / web / 基建)。§6 四批已落地并回标于 §1.4;未标 ✅/⚠️ 的条目仍有效。第一轮已修复条目见 §1.1。*
