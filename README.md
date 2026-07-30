# Agent Platform（新项目）

> 基于 `agent-langraph` 的经验，从零设计的 **Agent Runtime**：**一个内核，多个场景**。默认 **写作** `writing`；**Agent** `agent` 为通用全工具面。

## 30 秒看懂

| | |
|--|--|
| **是什么** | Docker 一键起的 Agent 平台：`api`（控制面）+ `runtime`（单 loop 执行）+ `web`（工作台）+ Caddy + Postgres/pgvector |
| **怎么扩展** | 同一 `AgentEngine`；差异在 `ScenarioProfile`（工具白名单 / 提示词 / 审批），不是再画一张流程图 |
| **亮点** | 流式 SSE · 可取消 · 写作 RAG+diff · exec **bwrap** 沙箱 · Golden/`make gate` 可证明 |
| **非目标** | 不宣称对齐 Cursor 全功能；Skills / 多模态 / K8s 暂缓 |
| **起栈** | `cp .env.example .env` → `make up` → `http://localhost/` |
| **Demo** | 见 [docs/learn/DEMO.md](docs/learn/DEMO.md) |
| **旁路观测** | `/ops/<OPS_TEST_SECRET>/…` · [Ops](docs/topics/ops-eval-console.md) |

文档已收敛为 **core / topics / learn / archive**，见 **[docs/README.md](docs/README.md)**。

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

| 文档 | 内容 |
|------|------|
| [docs/README](docs/README.md) | 总索引（core / topics / learn / archive） |
| [DEMO](docs/learn/DEMO.md) | 5 分钟路径 |
| [架构](docs/core/02-architecture.md) | 服务划分、数据流 |
| [Docker](docs/core/03-docker-runtime.md) | 拓扑、env、工作区/沙箱 |
| [Runtime / 工具](docs/core/05-agent-runtime.md) | Loop 与工具协议 |
| [场景](docs/core/09-product-modes.md) | writing / agent / intel |
| [写作](docs/topics/writing/) | 质量 / 作品 / Token / Plan |
| [RAG](docs/topics/rag-and-sources.md) | 索引与资料库 |
| [沙箱](docs/topics/sandbox.md) | exec 隔离（bwrap） |
| [Ops](docs/topics/ops-eval-console.md) | 评测台与旁路观测 |
| [contracts](docs/core/contracts.md) | API / 事件 / DDL |

> **架构宪法**：一个 Runtime，多个 Scenario。先读 **05、06、09**。原 ADR 已退役，约束写在 `core/` / `topics/`。

## 第一阶段交付标准（Docker Only）

当以下命令在全新机器上**一次成功**时，Phase 0 完成：

```bash
cp .env.example .env
# 起栈后在 Web「设置 → 模型」配置供应商（勿堆 MODEL_* 进 .env）
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
make up              # 起栈；并自动启用本仓库 .githooks（pre-push → preflight）
make preflight       # 手动：CI unit.* 本地镜像（无 Docker；按变更选择性）
make smoke           # L0
# 日常自测：浏览器打开 /ops/<OPS_TEST_SECRET>/test（docs/topics/ops-eval-console）
make gate            # CI/无头 Proof 门禁：smoke → eval-all → runtime-test
make ux-signals      # 体验信号自检（环外）
make eval-all        # stub golden（isolated + runtime-lite，不改日常 live）
make eval-retrieval  # writing.07（默认 ST 镜像）
make eval-queue      # queue + worker profile（shared.16）
make runtime-test    # Python 3.11+
```

推送绕过（应急）：`SKIP_PREFLIGHT=1 git push` 或 `git push --no-verify`。  
仅装 hooks、不起栈：`make hooks-install`（`make up` / `make start` 已默认执行）。

## 仓库结构

```
AgentPlatform/
├── README.md
├── docs/                    # core / topics / learn / archive
├── deploy/
│   ├── docker-compose.yml   # 唯一 compose 入口
│   ├── caddy/               # 边缘网关（Caddyfile）
│   └── compose/             # 可选：queue、retrieval、ha、runtime-lite
├── services/
│   ├── api/                 # HTTP API、SSE、投影、Ops 只读观测
│   ├── runtime/             # Agent 执行、检索、工具沙箱
│   └── web/                 # Vite + React 工作台 + Ops 页
├── packages/
│   └── contracts/           # OpenAPI、事件 schema、agent-contracts
├── eval/golden/             # Golden Turn 用例
└── scripts/                 # smoke、eval、codegen、ci_proof
```

## 与 agent-langraph 的关系

- **不直接迁移代码**：先建立骨架与契约，再按模块逐步 port 能力。
- **保留已验证的概念**：`Session` / `Run` / `Turn`、证据治理、上下文 gateway、产物诚实性。
- **废弃的形态**：巨型 `services/` 平铺、单进程全量 lifespan 初始化、多 compose overlay 组合、**13 节点固定 pipeline 图**。
- **重做的内核**：执行编排从「固定状态图」改为「agentic loop」；接缝闭环见 `contracts`、`07`、`09`。
