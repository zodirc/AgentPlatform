# Agent Platform

自托管 Agent Runtime：**一个内核，多个场景**。同一 `AgentEngine`；差异在 `ScenarioProfile`（工具 / 提示词 / 审批）。

产品面 `http://localhost/` · 详文 [docs/README.md](docs/README.md)

---

## 1. 部署

依赖 Docker Compose。LLM 在 Web「设置 → 模型」配置。

```bash
cp .env.example .env
make up      # 默认全量栈 + 发布台 :9090
make smoke
# 打开 http://localhost/
```

| 命令 | 作用 |
|------|------|
| `make up` | 按脏模块重建（日常） |
| `make up-all` | 全量重建 |
| `make smoke` / `make gate` | 冒烟 / 门禁 |

`curl -fsS http://localhost/health/live`

---

## 2. 架构 · 资源 · 目录

```text
Browser → Caddy
            ├─ /      → web
            └─ /api/* → api → (pull) runtime → 写事件 → api SSE
Postgres + pgvector · 旁路 ast-indexer · 默认含 bench
```

| 模块 | 职责 |
|------|------|
| web | 工作台（SSE + 投影） |
| api | 受理、分发、SSE、Ops |
| runtime | Agent loop、工具、检索、沙箱 |
| postgres | 事实总线（服务间无互 import） |
| ast-indexer | 工作区 AST（旁路） |
| bench + bench-postgres | Official / L1（`make up` 默认起） |
| contracts | OpenAPI / 事件 / 命令体 |

`Work` → `Session` → `Turn` ↔ `Run`。分发默认 pull + lease。[架构详文](docs/core/architecture.md)

### `make up` 全量：8 容器

| 容器 | mem_limit | 作用 |
|------|-----------|------|
| postgres | 1g | 产品库 / 向量 |
| bench-postgres | 1g | Bench 隔离库 |
| runtime | 4g → GPU 时 12g | loop / RAG / embed |
| ast-indexer | 768m | AST |
| api | 1g | 控制面 |
| bench | 6g → GPU 时 12g | 评测 worker |
| web / gateway | — | 前端 / Caddy |

宿主机另有发布台 `:9090`。

- **内存**：cgroup 上限合计约 **14g**（不含 web/gateway）→ 建议宿主 **≥16 GiB**
- **磁盘**：建议空闲 **≥40 GiB**（镜像 + 模型 + Bench 数据）
- **Embedding**（`make up` 自动解析）：无 GPU → **gte-small@384**（CPU）；VRAM≥8GiB → **bge-m3@1024**（CUDA）。权重在 `/data/models`；runtime 与 bench **各加载一份**

```text
deploy/   compose · Caddy
services/ api · runtime · web · bench
packages/contracts/   eval/   docs/   scripts/
```

---

## 3. 场景 · 框架 · 技术栈

| 场景 | 做什么 |
|------|--------|
| writing | 写作：大纲 / 草稿 / diff / RAG（默认） |
| agent | 编码全工具：文件 / shell / 测试 / LSP·AST |
| intel | 情报研判（闭环方案见 [plan](docs/plan/intel-closed-loop-verification.md)，未全落地） |
| collab | 多 agent（偏薄） |

扩场景 = 改 Profile，不改 Engine 循环。

**框架**：Intake → Engine（组窗 → 模型流 → 工具/审批 → checkpoint）→ 事件 SSE；沙箱 Landlock/bwrap；`make gate` + Golden。

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11 · FastAPI · Postgres/pgvector · ST embedding |
| 前端 | React 18 · Vite · TanStack Query · Tailwind |
| 部署 | Compose · Caddy · Make |

---

## 文档

[总索引](docs/README.md) · [架构](docs/core/architecture.md) · [Runtime](docs/core/runtime.md) · [工具与上下文](docs/core/tools-and-context.md) · [事件](docs/core/events.md) · [RAG](docs/topics/rag.md) · [工作台](docs/topics/workbench.md)
