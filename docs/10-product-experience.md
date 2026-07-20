# 10 — 产品体验与长期运行

> 本文定义 **「好用」** 与 **「可长期自用」** 的可验收标准。  
> 架构服务于每日使用，而非仅服务于简历；二者通过对齐同一套 SLO 同时成立。

## 0. 北极星

> **我自己愿意每天用它完成真实任务**（写作交付 + 工程/agent 任务），且连续使用数周不因性能、状态丢失或不可预期行为而放弃。

「成熟」在产品层的含义：

| 维度 | 用户感受 | 架构支撑 |
|------|----------|----------|
| **跟手** | 发送后立刻有反馈，流式输出不卡 | `turn.accepted`、SSE、`turn.token` |
| **可控** | 随时打断；改稿能看见 diff、能拒 | `CancelTurn`、checkpoint、`patch.*`、[ADR-015](adr/015-interrupt-cancel-resume.md) |
| **可预期** | 同输入在规则内行为稳定 | Turn Intake 确定性、`scenario_id` 显式 |
| **可恢复** | 刷新/断线不丢进度 | 事件 replay + `TurnView` |
| **可持续** | 长会话不越来越慢、越来越贵 | ContextEngine budget/compact（`06`） |
| **有上界** | 不会无界 hang 数百秒 | model/tool/Step 超时 + Stall Watchdog（ADR-016） |

交互基线对齐 Cursor 类：**流式、可打断、过程可见、变更可审**（`01` §0）。

## 1. 体验 SLO（Phase 1 起测量）

| 指标 | 目标 | 测量点 |
|------|------|--------|
| **TTFB** | ≤ 300ms（P95） | `POST /turns` → 首条 SSE（`turn.accepted` 或 `turn.token`） |
| **UI 停止渲染** | ≤ 50ms | 用户点 Stop → 本地不再 append token/delta（E2E 或清单） |
| **流式 Cancel** | ≤ 500ms（P95） | `turn.token` 流中 `CancelTurn`（`force=false`）→ `turn.cancelled` |
| **工具中 Cancel** | ≤ 3s（P95） | `run_command` 等执行中 cancel（`force=false`） |
| **硬 Cancel** | ≤ 1s（P95） | `force=true` 长 exec |
| **SSE 重连** | 断线 30s 内续流无缺口 | `Last-Event-ID` replay |
| **终态一致** | view 与事件终态 100% 一致（可重建） | projection 回归测试 |
| **长会话** | 50 Turn 后单 Turn P95 延迟无明显线性恶化 | token/step 监控 |
| **首模型 token** | ≤ 800ms（P95） | 首条 `turn.token`（在 `turn.accepted` 之后） |

**TTFB**（≤ 300ms）指 `turn.accepted` 等受理反馈；**首模型 token** 允许更长，二者勿混为一谈。Cancel 指标权威定义见 [ADR-015](adr/015-interrupt-cancel-resume.md)。指标对外统一以本节为准；`10` §7 仅作摘要。

未达标不宣称 Phase 1 完成。

## 2. 写作场景（`writing`）体验门槛

自用是否成立的最低标准：

1. **大纲可见**：`outline.md` / `DocumentOutlineView` 与事件 `outline.updated` 同步。
2. **按节流式**：`section.draft.delta` 在编辑器跟手，不等待 Turn 结束。
3. **改稿必 diff**：模型改文稿走 `propose_patch` → UI diff → Accept → `apply_patch`；**禁止**静默覆盖用户未审内容。
4. **证据可核对**：引用带来源指针；`check_citation` 结果可在侧栏查看（**Phase 1b** 起 `search_sources` 必经，见 `12` `writing.05`）。
5. **场景隔离**：默认不出现 `run_command`；需要工程能力时用户主动切 `agent` 场景。

## 3. Agent 场景（`agent`）体验门槛

1. **工具时间线**：每步 `tool.started` / `tool.delta` / `tool.completed` 可见，不黑盒。
2. **文件变更可审**：优先 `propose_patch`；直写需强审批或明显提示。
3. **exec 可控**：`run_command` 默认审批；可取消；输出截断可展开。
4. **多步任务**：`update_plan` / `turn.plan` 可选展示；不强制 planner 节点。

## 4. 长期运行（数周～数月）

### 4.1 Session 连续性

```text
Turn 结束 → runtime append 终态事件
         → runtime UPSERT session_transcripts（滚动 messages）
         → api 异步更新 sessions.context_summary（薄摘要，UI/兜底）
新 Turn  → runtime 加载 transcript + 本条用户消息（无 transcript 时回退 context_summary）
满窗     → ContextEngine 按 fill 阈值 collapse/snip/autocompact（默认 80%/90%/95%）
强制压缩 → /compact 写摘要并重置 transcript
```

写主权与触发机制见 [`07-domain-model.md`](07-domain-model.md) §5、§7 与 [`08-event-projection-pipeline.md`](08-event-projection-pipeline.md) §6.0。  
**禁止** 未达阈值就自动整窗摘要；落库 trim 必须确定性、无 LLM。**禁止** 单 Session 拖垮 assemble 延迟。

### 4.2 工作区与数据持久化

- `/workspace`：用户文稿与任务文件（bind mount，可备份）
- `/data`：artifacts、向量库、模型缓存（命名卷）
- Turn 历史在 PostgreSQL；**重装栈不丢会话**（卷 + DB 备份策略见 `03` §8）

### 4.3 成本与配额

| 杠杆 | 默认 |
|------|------|
| `max_steps` | Profile 配置（writing 40 / agent 50） |
| token budget | Turn 级硬顶；触顶 `budget_exceeded` 终止 |
| 工具结果截断 | `06` §3.2 |
| shouldQuery 短路 | meta 输入零模型调用（`05` §3.1） |

自用场景应可配置月度 token 上限告警（Phase 2+）。

### 4.4 可靠性

| 风险 | 策略 |
|------|------|
| runtime 崩溃 | checkpoint + `turn_events` 已写事实；恢复或标记 `failed` |
| api 重启 | SSE 重连 replay；无状态 api |
| projection 落后 | 以事件为准；定时全量重建 |
| 重复提交 | `client_request_id` 幂等（`07` §9） |
| 审批中断 | interrupt 在 checkpoint；`ApproveToolCall` 按 `run_id` 恢复 |

### 4.5 升级与迁移

- DB migration 版本化；`packages/contracts/schemas/ddl/` 为起点
- 事件 schema 版本化；旧事件可 replay 读
- Profile YAML 变更不破坏已进行 Turn（仅影响新 Turn）

## 5. Web 工作台原则

技术栈见 [ADR-018](adr/018-web-frontend-stack.md)（Vite + React + TypeScript + nginx）。

1. **不猜阶段**：状态来自 SSE + `TurnView`，见 `09` §5。
2. **按场景换布局**：`web/scenarios/writing` vs `web/scenarios/agent`（`10`）。
3. **共享实时层**：`web/shared/realtime/` 统一 SSE 消费与 cursor。
4. **键盘与焦点**：写作模式编辑器优先；Agent 模式时间线可折叠。

### 5.1 Stop 交互契约（ADR-015）

用户点 **Stop** 时 Web 必须：

```text
T+0ms   立即停止本地渲染（turn.token / tool.delta / section.draft.delta 不再 append）
T+0ms   显示「正在停止…」或禁用重复发送
T+0ms   POST /api/v1/turns/{id}/cancel（默认 force=false）
T+?     收到 turn.cancelled → 对齐终态，恢复输入框
```

| `TurnView.status` | 主操作 | 说明 |
|-------------------|--------|------|
| `running` | **Stop** → CancelTurn | 打断本轮 |
| `waiting_approval` | **批准 / 拒绝** | 非 Stop；走 ApproveToolCall / DenyToolCall |
| `cancelled` | 可发新消息 | 新 Turn，非 Resume |

**禁止**仅等 `turn.cancelled` SSE 到达后才停止 UI 渲染。`waiting_approval` 时 Stop 按钮不得与「拒绝审批」混用（产品层二选一：隐藏 Stop 或明确为「放弃本轮」并走 CancelTurn）。

### 5.2 模型供应商设置（ADR-019）

Web 设置页（`/settings/model`）须支持：

1. 查看已保存的 provider profile 列表（**密钥脱敏**）。
2. 新增 / 更新 / 删除 profile；**激活**后提示「下一 Turn 起生效」。
3. **禁止**提示用户重启 Docker 或 runtime 容器。
4. 进行中的 Turn 不因保存设置而中断。

自用场景下，频繁切换供应商与 API key 是常态；该能力为 **Phase 1 验收项**。

## 6. 「成熟亮点」对外叙事（与实现对应）

面试/作品集应能 **指到文档章节 + 可 demo 行为**：

| 亮点 | 一句话 | 文档/实现锚点 |
|------|--------|----------------|
| Loop 非 Pipeline | 删掉 13 节点，工具扩展 | ADR-005、`05` |
| Turn Intake 非分类图 | 确定性 Intake + 首轮路由 | ADR-014、`05` §3.1 |
| 事件溯源 UI | 断线 replay、不拼状态 | ADR-012、`09` |
| Stop 乐观 UI | 点停即停渲染 | ADR-015、`11` §5.1 |
| Diff-first 写作 | 可审改稿 | `10`、`patch.*` |
| 上下文治理 | 长会话可压缩；golden 逼出 compact | `06` §0.1、ADR-008、`shared.04` |
| RAG 走工具 | 检索仅 `search_*` → tool_result | `06` §10、`writing.05` / `agent.04` |
| 多 agent | `delegate` 工具 + `subagent.*` 事件 | ADR-007、`writing.06` / `agent.05` |
| 可回归 | Golden Turn + CI | `12` |
| 字段不漂移 | 边界 Pydantic + payload schema | ADR-017、`04` §3.5 |
| 执行有上界 | 超时 + Stall Watchdog | ADR-016、`05` §8.3 |
| 模型热切换 | Web 改 key 无需重启 | ADR-019、`contracts` §2.2 |
| 可观测 | trace 贯穿 | `05` §11、`12` §3 |

## 7. Phase 验收（产品向）

| 阶段 | 自用验收 |
|------|----------|
| **1** | writing 2000 字 + 3 次 diff；agent 多文件小改（`12` §5.1）；**Web 切换模型供应商无需重启**（ADR-019） |
| **1b** | 一篇含 **资料引用** 的写作稿；agent 任务 trace 含 **检索 + 一次 delegate** |
| **2** | 同 Session 20 Turn；向量索引可重建；`live` eval 抽样通过 |
| **3+** | 连续数周日常任务；eval 无回归 |

## 8. 相关文档

- [`05-agent-runtime.md`](05-agent-runtime.md) §3.1 Turn Intake
- [`08-event-projection-pipeline.md`](08-event-projection-pipeline.md) — SSE / 重连
- [`09-product-modes.md`](09-product-modes.md) — 场景能力
- [`11-eval-and-golden-turns.md`](11-eval-and-golden-turns.md) — 质量回归
- [ADR-014](adr/014-turn-intake-over-intent-pipeline.md)
