# 架构决策记录（ADR）

重大技术选型与不可轻易推翻的约束写入本目录。格式：背景 → 决策 → 理由 → 后果 → 备选方案。

## 索引

| ADR | 标题 | 状态 | 关联文档 |
|-----|------|------|----------|
| [001](001-three-service-split.md) | API / Runtime / Web 三服务拆分 | 已接受 | `02-architecture` §3 |
| [002](002-postgresql-primary-store.md) | PostgreSQL 作为唯一关系型存储 | 已接受 | `02-architecture` §3、`03-docker-runtime` §6 |
| [003](003-env-pydantic-settings.md) | 配置仅用环境变量 + Pydantic Settings | 已接受 | `03-docker-runtime` §3、`04-development-standards` §5 |
| [004](004-sse-turn-streaming.md) | SSE 作为 Turn 流式传输协议 | 已接受 | `08-event-projection-pipeline`、`05-agent-runtime` §7 |
| [005](005-agentic-loop-over-pipeline.md) | Agentic Loop 替代固定 Pipeline | 已接受 | `05-agent-runtime` |
| [006](006-tool-centric-capabilities.md) | 能力以工具暴露（Tool-Centric） | 已接受 | `06-tools-and-context` |
| [007](007-subagent-delegation.md) | 子 Agent 委派与上下文隔离 | 已接受 | `05-agent-runtime` §10 |
| [008](008-context-engineering-layers.md) | 上下文工程多层防线 | 已接受 | `06-tools-and-context` §7–9 |
| [009](009-protocol-four-layers.md) | Resource / Command / Event / Projection 四层协议 | 已接受 | `02-architecture` §6 |
| [010](010-async-projection-layer.md) | 异步任务与投影层不阻塞主路径 | 已接受 | `08-event-projection-pipeline` §6 |
| [011](011-domain-run-turn-1-1.md) | Run 与 Turn 1:1 绑定 | 已接受 | `07-domain-model` |
| [012](012-event-pull-sse.md) | 事件 Pull 模型与 api 独占 SSE | 已接受 | `08-event-projection-pipeline` |
| [013](013-dual-product-modes.md) | Scenario 双场景与 Profile 扩展 | 已接受 | `09-product-modes` |
| [014](014-turn-intake-over-intent-pipeline.md) | Turn Intake 替代意图分类 Pipeline | 已接受 | `05-agent-runtime` §3.1、`10-product-experience` |
| [015](015-interrupt-cancel-resume.md) | Interrupt / Cancel / Resume 语义 | 已接受 | `05` §8、`07` §2.5、`11` §5.1、`contracts` §2.1 |
| [016](016-execution-timeouts-and-stall-watchdog.md) | 执行超时与 Stall Watchdog | 已接受 | `05` §8.3、`12` §3.3、`09` §9 |
| [017](017-contract-validation-and-event-payloads.md) | 边界契约校验与事件 Payload Schema | 已接受 | `04` §3.5、`contracts` §3.1、`07` §10 |
| [018](018-web-frontend-stack.md) | Web 前端：Vite + React + TS + nginx 静态部署 | 已接受 | `03` §5.4、`04` §2–3.2、`10`、`11` §5 |
| [019](019-model-provider-runtime-config.md) | 模型供应商 Web 管理 + DB 热生效 | 已接受 | `03` §3、`05` §6、`07` §7、`contracts` §2.2、`11` §6 |
| [020](020-writing-work-over-session-drafts.md) | Writing 作品树优先于 Session 草稿目录 | 已接受 | `23-writing-work-model`、`09` §5.1 |
| [021](021-multi-tenancy-work-scope.md) | 多租户作为 Work 作用域绑定（默认开启 · 非编排） | 提案 | `27-multi-tenancy`、`15` §6、`16`、`23` §11 |

> 历史：曾有一版「ADR-014 ScenarioProfile 扩展」已并入 ADR-013；当前 014 为 Turn Intake 决策。

## 新增 ADR 规则

1. 文件名：`NNN-short-title.md`，编号递增，**不重用**已废弃编号。
2. 涉及 API / 事件 schema 变更时，同步更新 `packages/contracts/`（已落地，含 `agent-contracts` Python 包）与 `contracts.md`、`07`/`09` 及 ADR-004。
3. 否决的备选方案应简要记录原因，避免后人重复讨论。
4. PR 中架构级变更须新增或更新 ADR，并在本 README 登记。
