# 11 — 评估、Golden Turn 与可观测性

> 成熟 agent 的判据不仅是「能跑」，而是 **行为可预期、退化可发现、故障可定位**。  
> 本文闭合 eval 体系与生产级观测，支撑长期自用与对外技术叙事。

## 0. 原则

1. **Golden Turn 是契约**：输入 + 期望事件序列/终态；本地 `make eval*` 回归，不靠人工点测。
2. **Eval 不阻塞主路径**：采样与全量回归异步或本地脚本运行（ADR-010）。
3. **观测与事件同源**：`turn_events` + 结构化日志；metrics 从二者聚合。
4. **先覆盖主路径**：管道（patch/SSE）→ **能力融合**（context/RAG/delegate）→ 长尾。

### 0.1 能力融合 golden（禁止摆设）

下列用例属于 **Phase 1b 阻断项**（`01` §4、`06` §0.1）。缺任一不得进入 Phase 2：

| 能力 | Golden ID | 证明什么 |
|------|-----------|----------|
| ContextEngine | `shared.04` | 大输入触发 budget/compact，日志含策略名 |
| RAG（写作） | `writing.05` | `search_sources` → `tool_result` → 成稿引用 |
| RAG（agent） | `agent.04` | `search_codebase` 被调用且结果进入 timeline；Phase 1b 可由 `grep` + 小索引退化实现 |
| 多 agent | `writing.06` 或 `agent.05` | `delegate` → `subagent.started/completed` → 主 Turn 完成 |

## 1. Golden Turn 定义

一条 Golden Turn = 可重复执行的 **固定场景用例**。

```text
eval/golden/
├── writing/
│   ├── 01_outline_and_section.yaml … 09_export_document.yaml
├── agent/
│   ├── 01_read_and_propose_patch.yaml … 08_glob_stub.yaml
├── interview/
│   └── 01_notes_stub.yaml
├── shared/
│   ├── 00_stub_turn_complete.yaml
│   ├── 01_should_query_help.yaml … 16_outbox_worker_index.yaml
└── live/
    └── 01_smoke_complete.yaml …
```

（完整列表见仓库 `eval/golden/`；YAML 内 `id` 字段为权威标识。）

### 1.1 文件格式（YAML）

```yaml
id: writing.02_propose_patch_accept
scenario_id: writing
phase: 1
description: 用户要求改第二节；模型 propose_patch；用户 accept

fixtures:
  workspace:
    - path: outline.md
      content: |
        # Doc
        - [ ] Section 1
        - [ ] Section 2
    - path: sections/02.md
      content: "旧正文"

input:
  message: "把第二节改得更简洁"
  client_request_id: "00000000-0000-4000-8000-000000000002"

# 模型调用可 mock 或 recorded（见 §2）
model_mode: recorded  # stub | recorded | live

assertions:
  events:
    sequence_contains:
      - turn.accepted
      - step.started
      - patch.proposed
    sequence_not_contains:
      - turn.failed
  turn:
    status: completed
  workspace:
    - path: sections/02.md
      matches: ".*简洁.*"   # 仅 accept 后
  metrics:
    max_steps: 8
    max_total_tokens: 50000

tags: [writing, patch, p1]
```

Schema：`packages/contracts/eval/golden_turn.schema.json`

### 1.2 断言类型

| 类型 | 说明 |
|------|------|
| `events.sequence_contains` | 子序列匹配（顺序） |
| `events.sequence_equals` | 完整序列（stub 用） |
| `events.sequence_not_contains` | 禁止出现 |
| `events.payload_validates` | 每条事件 payload 按 `payloads/_index.json` 校验（Phase 1 管道 golden 默认 `true`） |
| `turn.status` | 终态 |
| `workspace` | 文件内容/hash |
| `metrics.max_steps` | 步数上限 |
| `metrics.max_total_tokens` | 成本上限 |
| `latency.ttfb_ms_max` | 体验 SLO（`11` §1） |
| `latency.first_token_ms_max` | 首 token 延迟上限（stub mock 路径） |
| `latency.cancel_latency_ms_max` | Cancel 到 `turn.cancelled` 上限 |
| `latency.model_timeout_triggers_fail` | mock provider 超过 model_timeout → `turn.failed`（`shared.07`） |
| `tool.retrieval` | 检索模式断言（如 `vector`，`writing.07` / `shared.16`） |

## 2. Eval 执行模式

| 模式 | 用途 | 何时 |
|------|------|------|
| **stub** | 固定事件回放；测 api/SSE/projection | Phase 0 CI |
| **recorded** | 录制的 model/tool 响应；测 runtime 编排 | Phase 1 CI |
| **live** | 真模型；夜间/发布前 | Phase 2+；允许 flaky 阈值 |

```text
eval runner（scripts/eval_run.py 或 services/eval/）
  → 准备 fixture workspace
  → POST /turns（或直调 StartTurn）
  → 收集 turn_events + TurnView + workspace 快照
  → 跑 assertions
  → 输出 junit / markdown 报告
```

**禁止** eval 通过修改生产代码路径「作弊」；mock 仅在 `model_mode: stub|recorded` 注入 `ModelGateway` / `ToolExecutor` 端口。

## 3. 可观测性

### 3.1 追踪（Tracing）

全链路共享 `trace_id`（=api 生成，贯穿 command、event、log）：

```text
POST /turns [trace_id]
  → StartTurn [trace_id]
  → turn_events[*].trace_id
  → step/model/tool logs [trace_id]
```

排查顺序见 `09` §9。

### 3.2 结构化日志

`05` §11 最小字段。补充 **聚合友好** 字段：

| 字段 | 用途 |
|------|------|
| `scenario_id` | 分场景 SLO |
| `termination_reason` | 终止分布 |
| `tool_name` | 工具成功率 |
| `approval_outcome` | 审批漏斗 |

### 3.3 Metrics（Phase 1+ 推荐）

| 指标 | 类型 | 说明 |
|------|------|------|
| `turn_duration_seconds` | histogram | 按 scenario |
| `turn_steps_total` | histogram | 防失控 |
| `turn_tokens_total` | counter | 成本 |
| `tool_calls_total` | counter | 按 tool_name, status |
| `sse_reconnect_total` | counter | 稳定性 |
| `projection_lag_seconds` | gauge | view 落后 |
| `should_query_short_circuit_total` | counter | Intake 省钱 |
| `turn_stall_detected_total` | counter | 卡住检测（ADR-016） |
| `turn_step_duration_seconds` | histogram | Step 墙钟 |
| `turn_model_timeout_total` | counter | provider 超时 |

暴露：`GET /metrics`（Prometheus 格式，api + runtime）。

### 3.4 健康与就绪

| 探针 | 检查 |
|------|------|
| `live` | 进程存活 |
| `ready` | DB 连接、runtime 可达、可选 model ping |

## 4. 回归分层（CI + 本地）

> **权威门禁**：[docs/28](28-proof-gate-and-ux-signals.md) PX0。  
> 本地一键：**日常**用 Web 评测台（[29](29-ops-eval-console.md)）；**CI/无头**用 `make gate`（= `smoke` + `eval-all` + `runtime-test`）。  
> Web 台对部分环境耦合命令会 **skipped**（不是失败），见 [29 §2.1](29-ops-eval-console.md)。  
> 详见 [28](28-proof-gate-and-ux-signals.md)。
> PR：`.github/workflows/ci.yml`（L0 + L1 + unit **阻断合并**）。  
> Nightly：`.github/workflows/nightly.yml`（L2 live 样本，**告警不阻断**）。

| 层级 | 内容 | 触发 |
|------|------|------|
| **L0 smoke** | compose up + health + 1 stub golden | 每 PR（`make smoke` / CI） |
| **L1 stub** | 全量 stub Golden（`make eval-all`） | 每 PR |
| **L1 unit** | `runtime-test` + contracts + ux-signals | 每 PR |
| **L1b** | 能力融合用例（含于 eval-all / phase 1b） | 每 PR |
| **L1c profiles** | `make eval-retrieval`、`make eval-queue` | 改 retrieval/queue 时本地加跑（见 CI 注释 PX0d） |
| **L2 live sample** | `eval/golden/live/`（需 `MODEL_API_KEY`） | nightly（`EVAL_LIVE_STRICT=1`，不阻断） |
| **L3 load** | 并发 5 Turn、SSE 重连压测 | nightly / 按需 |

失败策略：L0/L1 阻断合并；L2 告警不阻断（记录漂移）。

体验信号（环外）：`make ux-signals` · [docs/28](28-proof-gate-and-ux-signals.md) PX1。

## 5. Golden 清单

### 5.1 Phase 1 — 管道（必做）

完成 Phase 1 宣称的最低集。

#### writing

| ID | 验证点 |
|----|--------|
| `writing.01` | 创建大纲 + `outline.updated` |
| `writing.02` | `propose_patch` → accept → 文件变更 |
| `writing.03` | `propose_patch` → reject → 文件不变 |
| `writing.04` | `section.draft.delta` 流式（recorded） |

#### agent

| ID | 验证点 |
|----|--------|
| `agent.01` | read + `propose_patch` 小改 |
| `agent.02` | `CancelTurn` 工具执行中途取消（`force=false`） |
| `agent.03` | `approval.requested` → approve → **同一 `run_id`** 继续 |

#### shared

| ID | 验证点 |
|----|--------|
| `shared.01` | `/help` → shouldQuery 短路，零 step |
| `shared.02` | SSE 断线重连 sequence 连续 |
| `shared.03` | 重复 `client_request_id` 幂等 |
| `shared.05` | `turn.token` 流中途 `CancelTurn` → `turn.cancelled`；provider mock 断言 stream abort |
| `shared.06` | cancel 后同 Session 新 Turn 可 `StartTurn`；`session_context` 衔接 |
| `shared.07` | mock provider 超过 model_timeout → `turn.failed`（`termination_reason: model_timeout`） |

> **Cancel 族**（`shared.05`、`agent.02`、`writing.04` 流式场景）与 **超时**（`shared.07`）为 Phase 1 宣称「可打断 / 不卡死」的阻断项。见 ADR-015、ADR-016。

### 5.2 Phase 1b — 能力融合（必做，Phase 2 前置）

证明 ContextEngine、RAG、`delegate` **走主路径**，非摆设模块。

| ID | 场景 | 验证点 |
|----|------|--------|
| `shared.04` | 共用 | 大文件 `read_file` 或多轮 tool 历史 → 上下文日志含 `budget`/`compact`/`collapse` 之一；`metrics` 或日志可断言 |
| `writing.05` | writing | fixture 含 `sources/`；输入要求引用资料 → 序列含 `tool.started`(search_sources) → 终稿含引用指针 |
| `writing.06` | writing | `delegate`(researcher) → `subagent.started` + `subagent.completed` → 主 Turn `completed` |
| `agent.04` | agent | 代码库 fixture → `search_codebase` 命中并进入后续推理；Phase 1b 可由 `grep` + 小索引退化实现 → 后续 `propose_patch` 或 read |
| `agent.05` | agent | `delegate`(explore) → `subagent.*` 事件；子结果摘要出现在 tool_timeline（非整包 dump） |

`model_mode` 推荐 `recorded`；`live` 可作为 nightly 补充。

### 5.3 Phase 2 — 扩展

| ID | 验证点 |
|----|--------|
| `writing.07` | 向量索引增量更新后 `search_sources` 召回新 chunk（`make eval-retrieval`；`tool.retrieval: hybrid`） |
| `writing.11` | 长资料中按专名召回人物专节（BM25+向量 RRF + lexical rerank；`tool.retrieval: hybrid`） |
| `agent.06` | 多角色串联：explore → verify（两次 delegate） |
| `shared.08` | 50 Turn Session；单 Turn token P95 无线性恶化（对照 `11` §1） |
| `shared.16` | outbox worker 异步索引：`WORKER_MODE=outbox` + `wait-index`（`make eval-queue`） |

## 6. 意图与 Eval（ADR-014）

- **不做** LLM 意图分类 golden（不稳定）。
- **可做** Intake golden：`shouldQuery`、`InputCompiler` 输出快照。
- Phase 2+ 可选 `intent_tags` 仅作 **telemetry**，断言 `tags` 存在即可，不断言具体分类。

## 7. 目录落点

```text
eval/
├── golden/              # YAML 用例（37 条）
├── recordings/          # recorded 模型响应
└── README.md
scripts/
├── eval_run.py
└── smoke_test.sh
packages/contracts/eval/
└── golden_turn.schema.json
```

> workspace fixture 内联在各 golden YAML 的 `fixtures.workspace` 字段，无独立 `eval/fixtures/` 目录。

## 8. 相关 ADR 与文档

- [ADR-010](adr/010-async-projection-layer.md) — eval 不阻塞主路径
- [ADR-014](adr/014-turn-intake-over-intent-pipeline.md) — Intake 可测性
- [`10-product-experience.md`](10-product-experience.md) — SLO
- [`06-tools-and-context.md`](06-tools-and-context.md) §0.1 — 能力主路径
- [`05-agent-runtime.md`](05-agent-runtime.md) §8.1 — abort 检查点
- [ADR-015](adr/015-interrupt-cancel-resume.md) — Cancel / interrupt / resume
- [ADR-016](adr/016-execution-timeouts-and-stall-watchdog.md) — 超时与卡住检测
- [ADR-017](adr/017-contract-validation-and-event-payloads.md) — 边界校验与 payload schema
- [`contracts.md`](contracts.md) — 事件与 DDL
