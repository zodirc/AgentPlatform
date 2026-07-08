# Agent Platform（新项目）

> 基于 `agent-langraph` 的经验，从零设计的 **Agent Runtime**：**一个内核，多个场景**。默认 **写作** `writing`；**Agent** `agent` 为通用全工具面。详见 [场景与扩展](docs/10-product-modes.md)。  
> **第一阶段目标**：仅用 Docker 即可完整启动最小可用栈。

## 为什么要重写

`agent-langraph` 已验证了大量运行时能力（Turn 闭环、检索、上下文治理、写作交付等），但工程形态上出现了典型「成功系统的债务」：

| 问题 | 表现 | 后果 |
|------|------|------|
| 单体进程承载一切 | 一个 FastAPI 进程挂载 20+ 路由、调度器、MCP、A2A、Web 静态资源 | 启动慢、故障域大、无法按能力独立扩缩 |
| `services/` 膨胀 | 200+ 模块平铺在同一目录 | 边界模糊、依赖网状、新人难以理解改动影响面 |
| 配置与特性开关过载 | 800+ 行 `config.yaml` + 多份 compose overlay | 本地/生产行为不一致，排障成本高 |
| 部署组合复杂 | `docker-compose.yml` + `dev` / `redis` / `ha` 叠加 | 「能跑」依赖 Makefile 记忆，而非声明式契约 |
| 文档与实现脱节 | `arch.md` 1400+ 行描述理想态，代码已多处分叉 | 架构讨论无法落到可执行的模块边界 |

本项目不否定原有业务能力，而是**用清晰的容器边界、模块边界和契约，重新承载这些能力**。

## 文档索引

按顺序阅读：

| 序号 | 文档 | 内容 |
|------|------|------|
| 1 | [问题与目标](docs/01-problems-and-goals.md) | 现状诊断、设计原则、分阶段交付 |
| 2 | [目标架构](docs/02-architecture.md) | 服务划分、Agentic Loop 内核、数据流 |
| 3 | [Docker 运行时](docs/03-docker-runtime.md) | 容器拓扑、启动顺序、健康检查、环境变量契约 |
| 4 | [开发规范](docs/04-development-standards.md) | 仓库结构、代码风格、测试、配置、发布 |
| 5 | [Agent 运行时](docs/05-agent-runtime.md) | **核心循环**：控制器+引擎、messages 状态、终止、子 agent |
| 6 | [工具与上下文工程](docs/06-tools-and-context.md) | 工具协议、副作用/审批、budget·compact·collapse |
| 7 | [场景与扩展](docs/10-product-modes.md) | writing / agent、ScenarioProfile、扩展宪法 |
| 8 | [契约索引](docs/contracts.md) | API、事件、DDL、内部命令 |
| 9 | [领域模型](docs/07-domain-model.md) | Session/Run/Turn/Step、checkpoint、幂等 |
| 10 | [事件与投影流水线](docs/09-event-projection-pipeline.md) | SSE、turn_events、UI 数据源 |
| 11 | [产品体验与长期运行](docs/11-product-experience.md) | SLO、自用门槛、可靠性 |
| 12 | [评估与 Golden Turn](docs/12-eval-and-golden-turns.md) | 回归、metrics、CI |

工作区与沙箱见 [Docker 运行时 §8](docs/03-docker-runtime.md#8-工作区沙箱与拓扑)。

完整索引见 [docs/README.md](docs/README.md)。

## 架构决策（ADR）

| ADR | 决策 |
|-----|------|
| [001](docs/adr/001-three-service-split.md) | api / runtime / web 三服务拆分 |
| [002](docs/adr/002-postgresql-primary-store.md) | PostgreSQL 唯一关系型存储 |
| [003](docs/adr/003-env-pydantic-settings.md) | 环境变量 + Pydantic Settings |
| [004](docs/adr/004-sse-turn-streaming.md) | SSE 流式协议与事件目录 |
| [005](docs/adr/005-agentic-loop-over-pipeline.md) | Agentic Loop 替代固定 pipeline |
| [006](docs/adr/006-tool-centric-capabilities.md) | 能力以工具暴露 |
| [007](docs/adr/007-subagent-delegation.md) | 子 agent 委派 |
| [008](docs/adr/008-context-engineering-layers.md) | 上下文多层防线 |
| [009](docs/adr/009-protocol-four-layers.md) | Resource / Command / Event / Projection |
| [010](docs/adr/010-async-projection-layer.md) | 异步任务不阻塞主路径 |
| [011](docs/adr/011-domain-run-turn-1-1.md) | Run 与 Turn 1:1 |
| [012](docs/adr/012-event-pull-sse.md) | 事件 Pull + api 独占 SSE |
| [013](docs/adr/013-dual-product-modes.md) | Scenario 双场景与 Profile 扩展 |
| [014](docs/adr/014-turn-intake-over-intent-pipeline.md) | Turn Intake 非意图 Pipeline |
| [015](docs/adr/015-interrupt-cancel-resume.md) | Cancel / interrupt / resume（对齐 Cursor） |
| [016](docs/adr/016-execution-timeouts-and-stall-watchdog.md) | 执行超时与卡住检测 |
| [017](docs/adr/017-contract-validation-and-event-payloads.md) | 边界校验与事件 payload schema |
| [018](docs/adr/018-web-frontend-stack.md) | Web：Vite + React + TS + nginx 静态部署 |
| [019](docs/adr/019-model-provider-runtime-config.md) | 模型供应商 Web 管理 + DB 热生效（无需重启） |

> **架构宪法**：一个 Runtime，多个 Scenario。**好用**看 `11`，**可证明**看 `12`。先读 **05、06、10**。

## 第一阶段交付标准（Docker Only）

当以下命令在全新机器上**一次成功**时，Phase 0 完成：

```bash
cp .env.example .env
make up    # 或 docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
make smoke
curl -fsS http://localhost/health/live
```

验收清单：

- [x] 仅依赖 Docker / Docker Compose，无需本机 Python 环境（CI / eval 可选本机 Python）
- [x] 所有服务通过 healthcheck 串联启动
- [x] 配置入口唯一：`.env` → 各服务环境变量
- [x] `docker compose ps` 显示核心服务 `healthy`
- [x] 访问 `http://localhost/` 可打开 Web 壳层
- [x] `POST /api/v1/sessions` 可创建会话；stub golden 全绿

## 快速验证

```bash
make smoke          # L0
make eval-all       # 31 条 stub golden
make eval-retrieval # retrieval profile（writing.07）
make eval-queue     # queue + worker profile（shared.16）
make runtime-test   # Python 3.11+
```

## 仓库结构

```
agent/
├── README.md
├── docs/                    # 架构与规范
├── deploy/
│   ├── docker-compose.yml   # 唯一 compose 入口
│   └── compose/             # 可选 profile：queue、retrieval、ha
├── services/
│   ├── gateway/             # Caddy 边缘
│   ├── api/                 # HTTP API、outbox worker
│   ├── runtime/             # Agent 执行、检索索引
│   └── web/                 # Vite + React
├── packages/
│   └── contracts/           # OpenAPI、事件 schema、agent-contracts
├── eval/golden/             # Golden Turn 用例（37 YAML）
└── scripts/                 # smoke、eval、codegen
```

## 与 agent-langraph 的关系

- **不直接迁移代码**：先建立骨架与契约，再按模块逐步 port 能力。
- **保留已验证的概念**：`Session` / `Run` / `Turn`、证据治理、上下文 gateway、产物诚实性。
- **废弃的形态**：巨型 `services/` 平铺、单进程全量 lifespan 初始化、多 compose overlay 组合、**13 节点固定 pipeline 图**。
- **重做的内核**：执行编排从「固定状态图」改为「agentic loop」（ADR-005/006/007）；接缝闭环见 `contracts`、`07`、`09`。
