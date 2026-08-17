# Agent Platform

自托管 Agent Runtime：**一个内核，多个场景**。同一条推理循环；写作 / 编码 / 情报只换工具和提示词。

产品面 `http://localhost/`

## 文档 Wiki

GitHub 上请点下面这一行（会打开 Markdown，正文和图都会渲染）。不要点仓库里的 `docs/tour/index.html`，那只是源码。

https://github.com/zodirc/AgentPlatform/blob/master/docs/README.md

| 想了解 | 打开 |
|--------|------|
| 一次提问怎么从浏览器走到推理 | https://github.com/zodirc/AgentPlatform/blob/master/docs/core/architecture.md |
| 组窗、问模型、跑工具 | https://github.com/zodirc/AgentPlatform/blob/master/docs/core/runtime.md |
| 编码：找定义、改完再验 | https://github.com/zodirc/AgentPlatform/blob/master/docs/core/tools-and-context.md |
| 写作 / 搜资料 | https://github.com/zodirc/AgentPlatform/blob/master/docs/topics/rag.md |
| 工作台（写作对照编码） | https://github.com/zodirc/AgentPlatform/blob/master/docs/topics/workbench.md |
| 事件怎么上屏 | https://github.com/zodirc/AgentPlatform/blob/master/docs/core/events.md |
| 现行冒烟数字 | https://github.com/zodirc/AgentPlatform/blob/master/eval/official/baseline/RESULTS.md |

本地翻页导览：`make docs-tour`（http://127.0.0.1:8765/tour/）。

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

`Work`（作品世界）→ `Session`（聊天线程）→ `Turn`（点一次发送）↔ `Run`（真正在跑的实例）。runtime 自己来领活并心跳续约。[架构详文](docs/core/architecture.md)

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
| writing | 写作：大纲 / 草稿 / 按差异改稿 / 按需搜资料（默认） |
| agent | 编码：查找、改文件、跑测试；找定义和改完再验写进工具返回值；评测题的测试进该题 Docker |
| intel | 情报向资料与提示（核实闭环未落地） |
| collab | 多助手协作（偏薄） |

扩场景 = 改配置，不改推理循环。

用户点发送之后：整理输入 → 组窗 → 问模型 → 跑工具（要人批准就停住）→ 存断点。编码时若写完就收工却还欠验证，再催一轮。评测题的测试不在工作区源码树上跑。效果日记 [`RESULTS.md`](eval/official/baseline/RESULTS.md)。

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11 · FastAPI · Postgres/pgvector · ST embedding |
| 前端 | React 18 · Vite · TanStack Query · Tailwind |
| 部署 | Compose · Caddy · Make |
