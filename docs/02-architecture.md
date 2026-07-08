# 02 — 架构总览

> **本文仅作地图**：细节分别在专文，避免重复。实施以专文为准。

## 1. 一句话

**Agent Runtime 平台**：一个 **agentic loop** 内核 + **ScenarioProfile** 扩展（默认 `writing`，通用 `agent`）；**核心应用三服务**为 `api / runtime / web`，部署上额外包含 `gateway + postgres`。

设计基线：Cursor、Claude Code 类产品的 **单 loop、工具中心化、流式事件、上下文压缩**——不是固定 pipeline 平台。

> 口径统一：本文中的“三服务”专指核心应用 `api / runtime / web`；`gateway` 属于边缘接入组件，`postgres` 属于持久化基础设施。部署图仍按五个容器组件理解，不与 ADR-001 冲突。

## 2. 部署拓扑

```text
Client → gateway → web
                 → api → runtime → postgres
                              ↘ /data, /workspace
```

| 服务 | 职责 | 不做 |
|------|------|------|
| **gateway** | TLS、路由 | 业务状态 |
| **api** | 鉴权、资源/命令、SSE、投影 | 不跑 loop |
| **runtime** | Turn 执行、工具、模型、checkpoint | 不公网、不做 UI 投影 |
| **web** | 工作台（Vite + React；按 `scenario_id` 换布局） | 不猜 Turn 阶段 |

Web 技术栈见 [ADR-018](adr/018-web-frontend-stack.md)。部署与环境变量：**[`03-docker-runtime.md`](03-docker-runtime.md)**（含工作区、沙箱、卷）。

## 3. 逻辑分层（概念模型）

| 层 | Phase 0–1 承载 | 职责 |
|----|----------------|------|
| 边缘 | `gateway` | TLS、入口 |
| 控制面 | `api` | 鉴权、CRUD、命令 |
| 实时 | `api`/`realtime/` | SSE 读 `turn_events` |
| 执行面 | `runtime` | loop + tools |
| 异步/投影 | `api`/`projection/` | 刷新 views；Phase 2+ worker |

Phase 0–2：**runtime 单副本**。水平扩展见 `03` §10。

## 4. 运行时内核（摘要）

```text
TurnController  InputCompiler + shouldQuery + ScenarioProfile → ToolScope
AgentEngine     while: assemble → model → tools → checkpoint
```

- Intake：确定性输入编译与门控，**非** LLM 意图分类图（ADR-014、`05` §3.1）

- 状态：`TurnState.messages` + 少量控制字段（**非**大 `AgentState`）
- 编排：模型在循环内选工具；平台管护栏（审批、budget、终止）
- 禁止：13 节点 pipeline、引擎内 `if scenario` 分支

**全文**：[`05-agent-runtime.md`](05-agent-runtime.md) + [`06-tools-and-context.md`](06-tools-and-context.md)

## 5. 场景（产品入口）

| `scenario_id` | 产品名 | 要点 |
|---------------|--------|------|
| `writing` | 写作模式 | 文稿、diff、`propose_patch`、大纲 |
| `agent` | Agent 模式 | 全工具面、时间线、exec |

扩展宪法：**[`10-product-modes.md`](10-product-modes.md)** · [ADR-013](adr/013-dual-product-modes.md)

## 6. 契约与数据流（摘要）

```text
POST /turns → StartTurn → runtime 写 turn_events
api 读 turn_events → SSE → web
projection 异步刷新 turn_views
```

- 领域对象：Session → Turn → Run (1:1) → Step（事件粒度）
- 协议：Resource / Command / Event / Projection 四层

**全文**：[`contracts.md`](contracts.md)（契约索引）· [`07-domain-model.md`](07-domain-model.md) · [`09-event-projection-pipeline.md`](09-event-projection-pipeline.md)

## 7. 与 agent-langraph 的差异

| 旧 | 新 |
|----|-----|
| 单进程 + 13 节点图 | api/runtime 拆分 + 单 loop |
| 能力 = 图节点 | 能力 = 工具 + Scenario |
| 前端拼状态 | projection + SSE |

模块迁移表：**[`appendix-migration.md`](appendix-migration.md)**

## 8. 文档地图

| 主题 | 文档 |
|------|------|
| 目标与原则 | [`01-problems-and-goals.md`](01-problems-and-goals.md) |
| 本总览 | `02`（本文） |
| 部署 | [`03-docker-runtime.md`](03-docker-runtime.md) |
| 工程规范 | [`04-development-standards.md`](04-development-standards.md) |
| Loop 内核 | [`05-agent-runtime.md`](05-agent-runtime.md) |
| 工具与上下文 | [`06-tools-and-context.md`](06-tools-and-context.md) |
| 领域模型 | [`07-domain-model.md`](07-domain-model.md) |
| 事件/SSE/投影 | [`09-event-projection-pipeline.md`](09-event-projection-pipeline.md) |
| 场景与扩展 | [`10-product-modes.md`](10-product-modes.md) |
| 产品体验 / 长期运行 | [`11-product-experience.md`](11-product-experience.md) |
| 评估与可观测 | [`12-eval-and-golden-turns.md`](12-eval-and-golden-turns.md) |
| 契约索引 | [`contracts.md`](contracts.md) |
| ADR | [`adr/README.md`](adr/README.md) |

## 9. 架构决策（索引）

| ADR | 决策 |
|-----|------|
| [001](adr/001-three-service-split.md) | api / runtime / web |
| [005](adr/005-agentic-loop-over-pipeline.md) | Agentic loop |
| [009](adr/009-protocol-four-layers.md) | 四层协议 |
| [012](adr/012-event-pull-sse.md) | 事件 Pull + api SSE |
| [013](adr/013-dual-product-modes.md) | Scenario + 扩展模型 |
| [014](adr/014-turn-intake-over-intent-pipeline.md) | Turn Intake 非意图 Pipeline |

其余 ADR 见 [`adr/README.md`](adr/README.md)（含 [015](adr/015-interrupt-cancel-resume.md) Cancel、[016](adr/016-execution-timeouts-and-stall-watchdog.md) 超时、[017](adr/017-contract-validation-and-event-payloads.md) 契约校验、[018](adr/018-web-frontend-stack.md) Web 前端栈、[019](adr/019-model-provider-runtime-config.md) 模型供应商热配置）。

## 10. 成熟 agent 三角（自用 × 架构 × 可证明）

```text
        好用（11：SLO、diff、长会话）
              ╱╲
             ╱  ╲
            ╱    ╲
  可长期运行 ╱      ╲ 对外成熟
  （03/07/09）╲    ╱ （12：golden、metrics）
              ╲  ╱
               ╲╱
         同一套 turn_events 事实链
              +
    Phase 1b golden 强制 Context / RAG / delegate 走主路径（12 §5.2）
```

Phase 1 起：**文档定稿 + §5.1 golden + SLO** 与代码同步验收。  
宣称能力健全：**§5.2 全绿** 为 Phase 2 前置。

## 11. Phase 0 落地检查（摘要）

- [x] compose 全绿；`03` 清单完整（`make smoke`）
- [x] `AgentEngine` 无 scenario 分支；`ScenarioRegistry` 可加载 `writing`/`agent`/`interview`
- [x] `turn_events` + SSE + WebSocket + 最小 `TurnView`（见 `contracts.md` §3–4）
- [x] `packages/contracts/` DDL + 命令 schema 与 `contracts.md` 同步
- [x] stub golden 在 CI 通过（`12` §4 L0 + `make eval-all`）
