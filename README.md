# Agent Platform

自托管 Agent Runtime：**一个内核，多个场景**。同一条推理循环；写作 / 编码 / 情报只换工具和提示词。

产品面 `http://localhost/`

## 文档 Wiki

公开阅读入口（左侧目录切章、不整页刷新；图首次加载后缓存）：

https://zodirc.github.io/AgentPlatform/

本地：`make docs-tour` → http://127.0.0.1:8765/tour/

不要把 GitHub 文件视图当作 Wiki：每次换篇都会整页刷新并重复下载约 1.5MB 的海报。对照源文件请用 `docs/tour/index.html`。

| 想了解 | 打开 |
|--------|------|
| 进程、表、谁写 turn_events | https://zodirc.github.io/AgentPlatform/tour/#backend |
| 一次 Turn 如何从浏览器进入推理 | https://zodirc.github.io/AgentPlatform/tour/#request-path |
| 组窗、模型调用、工具循环 | https://zodirc.github.io/AgentPlatform/tour/#engine-loop |
| 编码：查找定义、修改后再验证 | https://zodirc.github.io/AgentPlatform/tour/#coding-fuse |
| 写作 / 资料检索 | https://zodirc.github.io/AgentPlatform/tour/#rag |
| 工作台（写作对照编码） | https://zodirc.github.io/AgentPlatform/tour/#writing |
| 写作模块解剖（九块与影响档） | https://zodirc.github.io/AgentPlatform/tour/#writing-module |
| 写作模块详文 | [docs/writing-module.md](docs/writing-module.md) |
| 事件如何投影到界面 | https://zodirc.github.io/AgentPlatform/tour/#events |
| 现行冒烟数字 | https://zodirc.github.io/AgentPlatform/tour/#scorecard |
| Ops 评测原理（题目 / 命中 / harness） | https://zodirc.github.io/AgentPlatform/tour/#ops-eval-why |
| 评测实例走查 | https://zodirc.github.io/AgentPlatform/tour/#ops-eval-walk |

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
            └─ /api/* → api
                 │  INSERT turns/runs · PUBLISH turn.dispatch
                 │  订 turn.live.* + SELECT 耐久 → SSE / turn_views
                 ▼
              Postgres（真源 / CAS / 耐久 turn_events · turn_views · run_commands）
                 │  claim CAS
                 ▼
              runtime（编排 · 写耐久事件 · PUBLISH live · 不持 ST）
                 ├─ HTTP → model-gateway     live LLM NDJSON
                 ├─ HTTP → sources-retrieval  唯一 embedding 池 · sync/watch
                 └─ HTTP → sandbox           bwrap/landlock exec
              redis（turn.dispatch 门铃 · turn.live 活流 · agent.jobs 异步）
旁路：ast-indexer · bench(+bench-postgres) · 发布台 :9090
```

| 模块 | 职责 |
|------|------|
| web | 工作台（SSE + 投影） |
| api | 受理、分发门铃、SSE、投影、Ops；可 enqueue Redis |
| runtime | 编排：claim / Engine / 写耐久 `turn_events`；默认 remote embed；活流 PUBLISH |
| sources-retrieval | 唯一 ST/hash 权重、query/index embed、资料 sync |
| model-gateway | live 上游 LLM 流（NDJSON） |
| sandbox | OS 隔离 exec |
| redis | 异步 job bus（`agent.jobs`）+ Turn 门铃/活流 Pub/Sub |
| postgres | Turn 业务真源 / CAS / 耐久事件（服务间无互 import） |
| ast-indexer | 工作区 AST（旁路） |
| bench + bench-postgres | Official / L1（`make up` 默认起） |
| contracts | OpenAPI / 事件 / 命令体 |

`Work` → `Session` → `Turn` ↔ `Run`。默认 `TURN_DISPATCH=pull`：编排 claim 并心跳续约。[架构导览](https://zodirc.github.io/AgentPlatform/tour/#backend)（进程 · 表 · `turn_events`）。

### `make up` 全量（产品面 + 平面）

| 容器 | mem_limit | 作用 |
|------|-----------|------|
| postgres | 1g | 产品库 / 向量表 |
| bench-postgres | 1g | Bench 隔离库 |
| redis | — | 异步 Streams |
| runtime | 4g | 编排 / 写事件（无 ST） |
| sources-retrieval | 4g → GPU 时 12g | embed / sync（唯一权重） |
| model-gateway | 512m | live LLM 出口（slim 镜像） |
| sandbox | 1g | bwrap/landlock（slim 镜像） |
| ast-indexer | 768m | AST |
| api | 1g | 控制面 / SSE |
| bench | 6g → GPU 时 12g | 评测 worker |
| web / gateway | — | 前端 / Caddy |

宿主机另有发布台 `:9090`。

- **内存**：日常产品空闲约数 GiB；开 GPU retrieval（+可选 bench）时名义 cgroup 可过 20g → 建议宿主 **≥16 GiB**
- **磁盘**：建议空闲 **≥40 GiB**（镜像 + 模型 + Bench 数据）
- **Embedding**（`make up` 自动解析）：无 GPU → **gte-small@384**；VRAM≥8GiB → **bge-m3@1024**。权重在 `/data/models`，**只由 sources-retrieval 加载**（编排 `EMBEDDING_BACKEND=remote`）

```text
deploy/   compose（含 planes.yml）· Caddy
services/ api · runtime · sources-retrieval · model-gateway · sandbox · web · bench
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
