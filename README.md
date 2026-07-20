# Agent Platform（新项目）

> 基于 `agent-langraph` 的经验，从零设计的 **Agent Runtime**：**一个内核，多个场景**。默认 **写作** `writing`；**Agent** `agent` 为通用全工具面。详见 [场景与扩展](docs/09-product-modes.md)。  
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

完整连续目录见 **[docs/README.md](docs/README.md)**（01–22）。常用入口：

| 文档 | 内容 |
|------|------|
| [01 问题与目标](docs/01-problems-and-goals.md) | 设计原则 |
| [02 架构](docs/02-architecture.md) | 服务划分、数据流 |
| [03 Docker 运行时](docs/03-docker-runtime.md) | 拓扑、env、工作区/沙箱 |
| [05–06 Runtime / 工具](docs/05-agent-runtime.md) | 内核与工具协议 |
| [09 场景](docs/09-product-modes.md) | writing / agent |
| [12 Harness](docs/12-model-harness.md) | 调用与 cache |
| [13 速率红线](docs/13-rate-redlines.md) | R1–R5 |
| [14 写作](docs/14-writing-quality.md) | WQ0–WQ4 |
| [15 RAG / 资料库](docs/15-rag-and-sources.md) | 索引、验收、票状态 |
| [contracts](docs/contracts.md) | API / 事件 / DDL |

工作区与沙箱：[Docker 运行时 §8](docs/03-docker-runtime.md#8-工作区沙箱与拓扑)。

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
# 编辑 .env：填入 MODEL_API_KEY（或启动后在 Web「设置 → 模型」配置）
make up    # 默认：live + pgvector + sentence-transformers（Dockerfile.retrieval）
make smoke
curl -fsS http://localhost/health/live
```

验收清单：

- [x] 仅依赖 Docker / Docker Compose，无需本机 Python 环境（CI / eval 可选本机 Python）
- [x] 所有服务通过 healthcheck 串联启动
- [x] 配置入口唯一：`.env` → 各服务环境变量
- [x] 默认栈：`MODEL_MODE=live`、`RETRIEVAL_BACKEND=pgvector`、本地 embedding 全开
- [x] `docker compose ps` 显示核心服务 `healthy`
- [x] 访问 `http://localhost/` 可打开 Web 壳层
- [x] `POST /api/v1/sessions` 可创建会话；stub golden 全绿（`make eval-*` 仍隔离为 stub）

## 快速验证

```bash
make smoke          # L0
make eval-all       # stub golden（isolated + runtime-lite，不改日常 live）
make eval-retrieval # writing.07（默认 ST 镜像）
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
│   └── compose/             # 可选：queue、retrieval、ha、runtime-lite
├── services/
│   ├── gateway/             # Caddy 边缘
│   ├── api/                 # HTTP API、outbox worker
│   ├── runtime/             # Agent 执行、检索索引
│   └── web/                 # Vite + React
├── packages/
│   └── contracts/           # OpenAPI、事件 schema、agent-contracts
├── eval/golden/             # Golden Turn 用例（39 stub YAML）
└── scripts/                 # smoke、eval、codegen
```

## 与 agent-langraph 的关系

- **不直接迁移代码**：先建立骨架与契约，再按模块逐步 port 能力。
- **保留已验证的概念**：`Session` / `Run` / `Turn`、证据治理、上下文 gateway、产物诚实性。
- **废弃的形态**：巨型 `services/` 平铺、单进程全量 lifespan 初始化、多 compose overlay 组合、**13 节点固定 pipeline 图**。
- **重做的内核**：执行编排从「固定状态图」改为「agentic loop」（ADR-005/006/007）；接缝闭环见 `contracts`、`07`、`09`。
