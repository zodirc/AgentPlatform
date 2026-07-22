# 03 — Docker 运行时（Phase 0 定稿）

> 本文是 Phase 0 的**唯一部署真相来源**。  
> 目标：`docker compose up -d --build` 在干净机器上一次成功。

## 1. 容器拓扑

```text
                    ┌─────────┐
    :443 / :80 ────►│ gateway │
                    └────┬────┘
           ┌─────────────┼─────────────┐
           │             │             │
           v             v             v
      ┌────────┐   ┌────────┐   ┌──────────┐
      │  web   │   │  api   │   │ runtime  │
      │ :80    │   │ :8000  │   │ :8001    │
      └────────┘   └───┬────┘   └────┬─────┘
                       │             │
                       └──────┬──────┘
                              v
                       ┌────────────┐
                       │  postgres  │
                       │  :5432     │
                       └────────────┘

可选 --profile queue
                       ┌────────────┐
                       │   redis    │
                       │   :6379    │
                       └────────────┘
```

### 1.1 部署视角与逻辑视角

容器拓扑是物理部署视角。逻辑上仍必须遵守 [`docs/02-architecture.md`](docs/02-architecture.md) 中定义的五层模型：

- 边缘接入层
- 控制面
- 实时交互层
- 执行面
- 异步任务与投影层

这里的“五层”是**逻辑分层**，不是“五个独立应用服务”。统一口径如下：

- 核心应用三服务：`api`、`runtime`、`web`
- 边缘接入组件：`gateway`
- 持久化基础设施：`postgres`

Phase 0 不要求把这五层都拆成独立容器，但要求：

1. 容器职责边界与逻辑层边界不冲突
2. `api` 不执行 Agent loop
3. `runtime` 不承担长期异步副作用
4. projection 刷新失败不阻断主执行闭环

### 1.2 Docker 运行时设计基线

Docker 运行时设计同样必须吸收成熟 agent 的经验，并反向约束源项目暴露出的工程问题：

- 容器启动链必须短，避免源项目那种“一启动就初始化全部能力”的膨胀模式
- 镜像职责必须单一，避免 `api` 或 `runtime` 被塞入与主职责无关的大量依赖
- 健康检查必须廉价、稳定、可预测，避免把诊断接口变成性能热点
- 默认按最小可运行栈设计，而不是默认把所有可选能力都常驻启动
- Phase 0 的 Docker 目标不是功能最多，而是启动稳定、故障易定位、性能损耗可控

## 2. 启动顺序与依赖

Compose 通过 `depends_on.condition: service_healthy` 保证顺序，**禁止** entrypoint 里 `sleep 30`。

```text
postgres healthcheck pg_isready
    ↓
runtime healthcheck /health/live；ready 检查 DB 与模型配置（**DB 激活 profile 或 env `MODEL_API_KEY`**，ADR-019）
    ↓
api healthcheck /health/live；ready 检查 DB 与 runtime
    ↓
web healthcheck wget /
    ↓
gateway healthcheck wget gateway /health
```

### 2.1 健康检查分层

| 端点 | 含义 | 用于 |
|------|------|------|
| `/health/live` | 进程存活，不查依赖 | **runtime compose healthcheck**（允许无 `MODEL_API_KEY` 先起栈）、K8s liveness |
| `/health/ready` | 依赖可用，例如 DB、下游服务、关键配置 | api compose healthcheck、ops / K8s readiness；runtime ready = 模型已配置 |

**禁止**在 `/health/live` 中做向量库全量扫描、知识库重建、projection 全量补算等重负载操作。

### 2.2 与事件和投影的一致性要求

- `runtime` 的 `ready` 只检查执行主路径依赖，不等待异步 worker 或历史投影补算完成
- `api` 的 `ready` 需要确认最小 projection 读取路径可用
- 健康检查失败不应导致事件序列回退或 projection 数据被删除

### 2.3 运行时性能保护规则

为避免重蹈源项目“服务启动慢、路径过长、错误边界扩大”的问题，Docker 运行时必须满足：

- 容器启动时只加载主路径必需依赖，检索索引预热、历史补算、评估采样不得阻塞 `ready`
- `runtime` 镜像中的重依赖必须有明确 owner，不得因为“未来可能要用”而预装大批无关组件
- `api` 镜像必须保持轻量，避免引入模型、向量库、系统级工具链
- 健康检查命令必须在秒级完成，且资源消耗稳定
- 单容器日志输出必须可区分主链路与异步链路，避免故障排查时重新陷入日志泥团

## 3. 环境变量契约

### 3.1 全局 `.env`

```bash
# --- 网络 ---
PUBLIC_DOMAIN=localhost
HOST_PORT=443
HTTP_PORT=80

# --- PostgreSQL ---
POSTGRES_USER=agent
POSTGRES_PASSWORD=agent
POSTGRES_DB=agent
DATABASE_URL=postgresql://agent:agent@postgres:5432/agent

# --- 安全 ---
APP_SECRET_KEY=change-me-in-production
AUTH_ENABLED=true
ADMIN_PASSWORD=admin
INTERNAL_SERVICE_TOKEN=change-me-internal

# --- 工作区 ---
WORKSPACE_ROOT=/workspace
WORKSPACE_HOST_PATH=./workspace

# --- 可观测 ---
LOG_LEVEL=INFO
APP_ENV=production
```

模型 API key / base URL：**主路径是 Web「设置 → 模型」**（ADR-019）。仅当 DB 无激活 profile 时，才可选填 env `MODEL_API_KEY` 作 fallback（见仓库 `.env.example` 注释段）。

### 3.2 按服务注入

| 变量 | api | runtime | 说明 |
|------|:---:|:-------:|------|
| `DATABASE_URL` | ✓ | ✓ | 共享库，不同 schema 前缀可选 |
| `RUNTIME_URL` | ✓ | — | 默认 `http://runtime:8001` |
| `INTERNAL_SERVICE_TOKEN` | ✓ | ✓ | api → runtime 鉴权 |
| `MODEL_*` | — | ✓ | **Bootstrap fallback**；Phase 1 起运营配置以 DB 为准（ADR-019） |
| `CONFIG_ENCRYPTION_KEY` | ✓ | ✓ | 可选；api 加密 / runtime 解密 `model_provider_profiles` |
| `APP_SECRET_KEY` | ✓ | ✓ | Session 签名；未设 `CONFIG_ENCRYPTION_KEY` 时派生配置加密密钥 |
| `AUTH_ENABLED` | ✓ | — | 鉴权开关 |
| `DATA_DIR` | — | ✓ | 默认 `/data` |
| `WORKSPACE_ROOT` | — | ✓ | 默认 `/workspace` |

### 3.3 配置分层（Bootstrap vs Operational）

权威决策：[ADR-019](../adr/019-model-provider-runtime-config.md)。

| 层级 | 存放 | 变更 | 生效 |
|------|------|------|------|
| **Bootstrap** | `.env` → 容器环境变量 | 极少 | 重启对应服务 |
| **Operational** | PostgreSQL `model_provider_profiles` | 频繁（换供应商 / key） | **不重启**；**下一 Turn** 生效 |

Bootstrap 示例：`DATABASE_URL`、`APP_SECRET_KEY`、`INTERNAL_SERVICE_TOKEN`。  
Operational 示例：`provider`、`model_name`、API key、`base_url` — 经 **Web 设置页 → api 加密落库 → runtime 在 `StartTurn` 读取**。

Phase 0 可仅配置 env `MODEL_*`；Phase 1 起 Web 管理面为主路径，env 作 DB 无激活行时的 fallback。

### 3.4 配置规则

- 容器内**不**使用 `CONFIG_PATH` 指向巨型 YAML
- 每个服务 `app/settings.py` 用 Pydantic `BaseSettings` 读取环境变量
- 每个 Python 服务在容器内与本地开发环境都必须使用独立 `venv` 管理依赖，这是**必须要求**
- Docker 镜像构建应基于服务自己的 `venv` 或等价隔离依赖产物，禁止依赖宿主机 Python 包环境
- 本地调试允许直接激活 `venv` 运行 `api` 或 `runtime`，但该路径只是开发加速手段，不能替代 Docker 验收路径
- `.env.example` 只列 **Bootstrap 起栈变量**；高级旋钮见本文 **附录 A**（代码已有默认值）。`.env` 不入库
- `api` 与 `runtime` 共享连接信息，但不共享 Python 内部配置对象

## 4. Compose 文件策略

### 4.1 唯一入口

```text
deploy/docker-compose.yml      # 主文件，Phase 0 全部服务
deploy/compose/queue.yml       # profile queue（redis + api WORKER_MODE=outbox）
deploy/compose/retrieval.yml   # 可选 overlay（主 compose 已默认 embedding）
deploy/compose/runtime-lite.yml # CI/eval：轻量 Dockerfile + hash embedding
deploy/compose/ha.yml          # profile ha（多 runtime 副本）
```

**禁止** `docker-compose.dev.yml` 等多文件叠加作为默认路径；`redis.yml` 已合并为 `queue.yml`。

本地开发差异通过：

```bash
# 热更新：挂载源码卷 documented override
docker compose -f deploy/docker-compose.yml -f deploy/compose/dev.override.yml up
```

`dev.override.yml` **不入库默认值**，仅 `.example` 提供模板。

### 4.2 已落地的 compose 骨架

权威来源：**[`deploy/docker-compose.yml`](../../deploy/docker-compose.yml)**（已实施，非设计稿）。

| 服务 | 容器名 | 暴露 | 职责 |
|------|--------|------|------|
| `postgres` | `agent-postgres` | 内部 | 关系型存储 + pgvector 扩展 + 健康串联 |
| `runtime` | `agent-runtime` | 内部 `:8001` | Agent 执行、工具、检索索引（默认 ST embedding） |
| `api` | `agent-api` | 内部 `:8000` | REST、SSE 代理、投影、outbox worker |
| `web` | `agent-web` | 内部 `:80` | Vite 静态产物（nginx） |
| `gateway` | `agent-gateway` | `${HTTP_PORT}` / `${HOST_PORT}` | Caddy 反代 `/api` + `/` |

**陌生机默认（主 compose）**：`MODEL_MODE=live`、`RETRIEVAL_BACKEND=pgvector`、`RETRIEVAL_MODE=hybrid`、`EMBEDDING_BACKEND=sentence_transformers`、镜像 `Dockerfile.retrieval`。模型配置优先 Web「设置 → 模型」；也可用 env `MODEL_API_KEY` 作无 profile 时的 fallback。Compose 健康检查用 `/health/live`（允许无 key 先起栈）；`/health/ready` 表示「env key **或** DB 中任一条激活的 Web profile 可解密」。

**runtime / api 环境变量**：起栈见仓库根 `.env.example`；调参 / HA / 检索细项见 **附录 A**。

启动：

```bash
cp .env.example .env
# 推荐：make up 后在 Web 配置模型；或可选填 MODEL_API_KEY 作 fallback
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
```


## 5. Dockerfile 规范

### 5.1 通用规则

- 基础镜像：`python:3.11-slim`
- 多阶段构建：builder 装依赖，runtime 只拷贝 venv 或 site-packages
- 构建时安装 CPU 版 torch 若需 embedding，避免 CUDA wheel
- `HEALTHCHECK` 与 compose healthcheck 保持一致
- 非 root 用户运行 `USER app`，uid `1000`

### 5.2 runtime 镜像特殊要求

- **默认镜像**：`Dockerfile.retrieval` — 构建期烘焙 `EMBEDDING_MODEL` 至 `/app/models-baked`；entrypoint 首次启动同步至 `/data/models`；默认 `EMBEDDING_BACKEND=sentence_transformers`；`RETRIEVAL_BACKEND=pgvector`；向量索引 `INDEX_VERSION=7`（叶预算 + path/tag embed + BM25/RRF profile；见 [`15` §9](15-rag-and-sources.md)）
- **轻量镜像**：`Dockerfile`（无 torch）— CI / `deploy/compose/runtime-lite.yml` / isolated stub golden；`EMBEDDING_BACKEND=hash`
- `EXPOSE 8001`
- 内部命令接口、事件写入、健康检查与检索为默认路径必需能力

#### 资料库索引状态排障

资料上传采用异步索引：`POST /api/v1/admin/workspace/sources/upload` 在文件写入成功后返回
`index.status=pending`，runtime 后台任务再把状态推进为 `building`，最终进入 `ready` 或
`error`。因此上传成功不等于索引已经可检索，API 也不得等待 embedding 构建完成。

**Turn 外投影（docs/15 IX0–IX2）：** runtime 启动后默认延迟数秒异步增量同步 `workspace/sources`
（`SOURCES_STARTUP_SYNC_ENABLED`，不挡 `/health/live`）。默认另启目录监视（`SOURCES_WATCH_ENABLED`，
轮询 + debounce）。也可：工作台「资料库 → 同步资料库」（IX1），或运维：

```bash
make sync-sources   # 或 make seed-sources（同义）
```

**常驻种子库（只读挂载，不拷贝）：** 宿主机 `seed/sources/writing` → 容器
`/workspace/sources/seed/writing:ro`（`SEED_SOURCES_HOST_PATH`）。索引逻辑路径为
`sources/seed/writing/...`；改仓库内 seed 后重建索引即可，勿往沙箱里复制。

**IX3：** `GET …/sources/index-status` 仅报告**摄取面**（`plane=ingestion`，`effect_ready=false`）。
`ready` / `path_current` 表示已投影可被检索，**不等于**效果闸（`make retrieval-bench-prod` + 难句工作台）。

运维侧可轮询
`GET /api/v1/admin/workspace/sources/index-status?path=sources/<文件名>`：

- `pending` / `building`：文件已保存，继续等待后台任务；
- `ready` 且 `path_current=true`：磁盘文件 mtime 与索引一致，可以检索；
- `error`：查看 runtime 日志中的 `sources index sync after upload failed`；原文件仍保留，
  修复 embedding 配置或模型可用性后重新触发索引。

默认 compose 已注入 `EMBEDDING_BACKEND=sentence_transformers`、`EMBEDDING_DIMENSIONS=384` 等。
仅改宿主机 `.env` 而未重建/重启 runtime 时，容器内仍可能是旧值。轻量降级显式设
`EMBEDDING_BACKEND=hash` 并改用 `runtime-lite.yml` 或 `Dockerfile`。若从 hash(256) 切到 ST(384)，
需 drop `source_chunks`/`source_files`（或整库重建）后再 `make sync-sources`。

### 5.3 api 镜像

- 不含 torch 或 sentence-transformers
- 镜像体积目标小于 `300MB`
- `EXPOSE 8000`
- 必须包含 projection 读取与 SSE 代理依赖

### 5.4 web 镜像

权威决策：[ADR-018](../adr/018-web-frontend-stack.md)。

- **多阶段构建**：`node:20-alpine`（`pnpm install` + `pnpm build`）→ `nginx:alpine`（拷贝 `dist/`）
- **运行时禁止 Node 进程**：生产 healthcheck 为 `wget` 静态首页（见 compose 示例）
- **nginx 职责**：托管 `dist/`；SPA 路由 `try_files` 回退 `index.html`
- **API 访问**：浏览器经 gateway 相对路径 `/api/v1/*`；web 镜像内**不**注入 API URL 环境变量
- **已实现**：Vite + React + TS；写作 / Agent / 访谈三场景 Workbench + 模型设置页；shadcn/ui 组件库
- **镜像体积**：运行时目标 < `50MB`（nginx + 静态资源）；Monaco 等重依赖须 lazy chunk

Dockerfile 见 **`services/web/Dockerfile`**（多阶段 build → nginx）。

## 6. 卷、事件与数据持久化

| 卷名 | 挂载点 | 内容 |
|------|--------|------|
| `pg_data` | postgres | 资源表、事件日志、projection、outbox |
| `agent_data` | runtime `/data` | 向量库、产物、模型缓存、日志 |
| 宿主机路径 `WORKSPACE_HOST_PATH` | runtime `/workspace` | **用户代码库**（工具沙箱） |
| `caddy_data` | gateway | TLS 自动证书存储 |

**备份策略** 文档约定：`pg_data` 与 `agent_data` 定期快照。

### 6.1 PostgreSQL 最小表面

Phase 0 设计上至少需要为以下对象预留位置（详见 [`07-domain-model.md`](07-domain-model.md)）：

- `sessions`
- `turns`
- `runs`
- `turn_events`
- `turn_views`
- `outbox_jobs` 预留

### 6.2 事件与投影持久化要求

- SSE 事件写入 `turn_events`（runtime 写、api 读），见 [`08-event-projection-pipeline.md`](08-event-projection-pipeline.md)
- projection 可以延迟刷新，但必须可重建
- projection 刷新失败不得导致 turn 主状态丢失
- 事件表与 projection 表属于可观测与重连基座，不可视为可选装饰

### 6.3 日志与 debug 运行时要求

为保证 debug 简便，Docker 运行时必须具备最小日志观测能力：

- 所有核心服务输出结构化日志到 stdout
- 日志必须可按 `trace_id`、`turn_id`、`request_id` 进行检索
- `api` 必须记录 access log、command log、auth 失败日志
- `runtime` 必须记录 step 开始结束、模型调用、工具调用、终止原因、异常边界日志
- projection 刷新链路必须记录 sequence 与刷新状态，便于定位“事件到了但界面没更新”的问题
- Phase 0 不强制引入 ELK、Loki、OpenTelemetry 全家桶，但日志字段和输出格式必须为后续接入这些系统保留兼容性

## 7. 本地开发工作流

```bash
# 首次
cp .env.example .env
# 推荐：make up 后在 Web 配置模型

# 启动
docker compose -f deploy/docker-compose.yml up -d --build

# 查看状态
docker compose -f deploy/docker-compose.yml ps

# 跟踪日志
docker compose -f deploy/docker-compose.yml logs -f api runtime

# 停止
docker compose -f deploy/docker-compose.yml down

# 清数据重来
docker compose -f deploy/docker-compose.yml down -v
```

### 7.1 本地 `venv` 开发要求

虽然 Docker 是唯一验收路径，但本地开发必须允许使用独立 `venv` 获得更快迭代速度。

要求如下：

- `services/api` 与 `services/runtime` 各自拥有独立 `venv` 或可明确隔离的依赖环境
- 本地 `venv` 只作为开发与 debug 加速手段，不替代容器构建结果
- 本地 `venv` 中的依赖版本必须能映射回容器依赖清单，避免“本地能跑、容器不能跑”
- 开发文档必须同时给出 `venv` 路径与 Docker 路径

推荐工作方式：

1. 平时修改代码时使用 `venv` 本地启动单服务快速调试
2. 联调与回归时使用 Docker Compose 进行真实验收
3. 发布前以容器环境为准，不以宿主机环境为准

### 7.2 web 本地开发（可选加速）

web 与 Python 服务依赖隔离；本地前端热更新不替代 Docker 验收。

```bash
cd services/web
corepack enable
pnpm install
pnpm dev    # 默认 http://localhost:5173，proxy /api → api:8000 或 localhost:8000
```

`vite.config.ts` 须将 `/api` 代理至 compose 中的 `api` 服务或本机 `8000`，与生产 gateway 反代语义一致。生产构建 `pnpm build` 产物仅含相对路径 `/api/v1`，无需 `VITE_*` 运行时变量。

### 7.3 热更新（可选）

复制模板并启用源码挂载：

```bash
cp deploy/compose/dev.override.yml.example deploy/compose/dev.override.yml
docker compose -f deploy/docker-compose.yml -f deploy/compose/dev.override.yml up
```

模板内容（`deploy/compose/dev.override.yml.example`）：

```yaml
services:
  api:
    volumes:
      - ../../services/api/app:/app/app:ro
    environment:
      APP_ENV: development
  runtime:
    volumes:
      - ../../services/runtime/app:/app/app:ro
    environment:
      APP_ENV: development
```

## 8. 工作区、沙箱与拓扑

> 原独立文档 `03-docker-runtime.md` 已并入本章。

### 8.1 部署阶段

| 阶段 | runtime |
|------|---------|
| Phase 0–1 | **单副本**（默认验收路径） |
| Phase 2 | 单副本 + 可选 `redis` profile |
| Phase 3+ | 多副本（须 Turn 亲和路由，见 §8.5） |

### 8.2 卷布局

```text
/workspace/     # bind mount；WORKSPACE_ROOT；工具沙箱根
  # writing: outline.md, sections/, sources/（见 09-product-modes）
  # agent: 任务文件 / 仓库
/data/            # agent_data 卷
  artifacts/{turn_id}/
  vectorstore/    # Phase 2+ profile
  models/         # Phase 2+ profile
  logs/
```

| 变量 | 默认 |
|------|------|
| `WORKSPACE_ROOT` | `/workspace` |
| `WORKSPACE_HOST_PATH` | `./workspace` |
| `DATA_DIR` | `/data` |

### 8.3 工具沙箱

- 允许：`{WORKSPACE_ROOT}/**`（写按工具审批）、`{DATA_DIR}/artifacts/{turn_id}/**`
- 拒绝：其他路径在 `ToolExecutor` 入口失败
- `run_command`（Phase 1+，agent scenario）：容器内子进程；`timeout`、可取消；不注入模型密钥

### 8.4 审批与取消路由（单副本）

`ApproveToolCall` 必带 `run_id` → 唯一 runtime 恢复 checkpoint。interrupt 持久化在 checkpoint，非仅内存。SSE 断线时审批仍走 REST。

`CancelTurn` 双通道：api 写 `runs.cancel_requested_at` / `cancel_force` **并** 转发 `cancel-turn`；runtime 在 stream / tool / Step 全过程轮询（ADR-015）。`ModelGateway.stream` 须在检查点断开 provider 连接。

### 8.5 多副本（MT7 · 与多租户配套的扩容面）

**多租户 ≠ 空架子：** 划分面（Work）保证不串味（MT5c SQL deny）；**多副本保证多人同时跑 Turn 时跟得上**。两者一起才像「多人 Web 平台」。

| 默认 `make up` | 多人并发推荐 `make up-ha` |
|----------------|---------------------------|
| 单 `runtime` | `runtime-a` + `runtime-b`（`--scale runtime=0`） |
| 适合自用 / 开发 | 适合多用户同时发消息 |

已具备：

1. **Claim**：`runs.runner_id` + `ensure_run_owned_by_runner`（一 Run 一副本）  
2. **新 Turn 负载**：`RUNTIME_URL_MAP` 上 round-robin（`RuntimeRouter.url_for_new_turn`）  
3. **续命令亲和**：Cancel / Approve / patch → `runtime_client_for_turn` 按 `runner_id` 打回持有者  
4. **共享存储**：两副本挂同一 `agent_data` + `workspace`（`/data/works/{id}` 可见）  
5. **单副本软闸**：`RUNTIME_MAX_INFLIGHT_TURNS`（默认 16）；HA 下总容量 ≈ 副本数 × 该值  

```bash
make up-ha          # 双 runtime + 路由表
make eval-ha        # ha_runner golden（stub）
```

仍须注意：同 Work 多写者默认乐观后写覆盖；跨区域多活不在范围。

### 8.6 api ↔ runtime 网络

公网仅 `gateway`；`api → runtime:8001` + `X-Internal-Token`；runtime 不暴露公网。

## 9. 启动故障排查

| 现象 | 检查 |
|------|------|
| `runtime` unhealthy | `docker logs agent-runtime`；模型 key 是否配置 |
| `api` 等待 runtime | `curl http://runtime:8001/health/ready` 在 api 容器内 |
| gateway 502 | `docker compose ps` 确认 api 和 web healthy |
| postgres 连接失败 | `DATABASE_URL` 主机名必须为 `postgres` 非 `localhost` |
| SSE 无法重连 | 检查事件表是否存在 `sequence` 与 replay 查询 |
| projection 不更新 | 检查投影刷新逻辑、outbox 或事件订阅链路 |
| 磁盘占满 | embedding 模型与向量库；检查 `agent_data` 卷 |

## 10. Phase 0 实施检查清单

实施代码时逐项勾选（**当前均已验收**，本地用 `make smoke` / `make eval*` / `make runtime-test`）：

- [x] `deploy/docker-compose.yml` 可独立运行
- [x] `.env.example` 覆盖 Bootstrap 起栈变量（高级见附录 A）
- [x] 每个服务有 `Dockerfile` 与 `README.md`
- [x] PostgreSQL migration 应用 `packages/contracts/schemas/ddl/phase0.sql`
- [x] `api` stub：`POST /api/v1/sessions` 返回 `201`
- [x] `api` stub：`GET /api/v1/turns/{id}/view` 返回最小 `TurnView`
- [x] `runtime` stub：`POST /internal/commands/start-turn` 可产出模拟 done 事件
- [x] SSE 事件至少具备 `event_id`、`sequence`、`type`
- [x] `gateway` Caddyfile 路由正确
- [x] projection 刷新失败不影响 Turn 主闭环
- [x] `make up` 与 `make down` 为薄封装
- [x] 本地：compose up + `curl health` + 最小 turn stream + **L0 golden**（`12` §4）

---

## 附录 A — 高级环境变量（非起栈必需）

> **默认已够用。** 下列变量在 `services/*/app/settings.py` 与 compose 中有默认值；仅排障 / CI / HA 时再覆盖。  
> **不要**把它们重新堆回 `.env.example`（避免老项目式参数膨胀）。权威起栈模板：仓库根 `.env.example`。

### A.1 模型（fallback / CI）

| 变量 | 默认意图 | 何时改 |
|------|----------|--------|
| `MODEL_MODE` | `live` | CI / golden：`stub` |
| `MODEL_API_KEY` / `MODEL_PROVIDER` / `MODEL_NAME` | 空或 compose 默认 | **仅** DB 无 Web profile 时 |
| `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` | 官方 | 自建代理（另见 egress allowlist） |
| `MODEL_EGRESS_ENFORCE` / `MODEL_EGRESS_ALLOWLIST` | 出站白名单 | 代理域名 |
| `CONFIG_ENCRYPTION_KEY` | 由 `APP_SECRET_KEY` 派生 | 独立轮换加密密钥 |

日常换模型：**Web → 设置 → 模型**，不要改 `.env`。

### A.2 检索 / embedding

产品默认：`pgvector` + `hybrid` + `sentence_transformers`（`Dockerfile.retrieval`）。

| 变量 | 说明 |
|------|------|
| `RETRIEVAL_BACKEND` / `RETRIEVAL_MODE` | 默认即可；轻量 CI 用 `runtime-lite` + `hash` |
| `EMBEDDING_*` | 模型名 / 维度 / 目录 |
| `SOURCES_STARTUP_SYNC_*` / `SOURCES_WATCH_*` | 启动同步与目录监视 |
| `SEED_SOURCES_*` | 常驻种子库挂载 |
| `RETRIEVAL_TWO_LEVEL_*` / `RETRIEVAL_RERANK_*` | 召回 / rerank 细调 |
| `SEARCH_SOURCES_*` | 每 turn 检索预算 |

### A.3 上下文压缩与配额

| 变量 | 说明 |
|------|------|
| `CONTEXT_WINDOW_TOKENS` / `CONTEXT_OUTPUT_RESERVE_TOKENS` | 窗与输出预留 |
| `CONTEXT_FILL_*` / `CONTEXT_HOT_ZONE_RATIO` | collapse / snip / autocompact |
| `TURN_TOKEN_BUDGET` / `MONTHLY_TOKEN_*` | 配额与告警 |

### A.4 写作（docs/23 · 24）

| 变量 | 说明 |
|------|------|
| `WRITING_PATCH_AUTO_APPLY` | 默认跟手落盘 |
| `WRITING_MANUSCRIPT_MODE` / `WRITING_MANUSCRIPT_PATH` | 默认 monofile + `manuscript.md` |
| `WRITING_TOKEN_ECONOMY_*` / `WRITING_FOCUS_*` / `WRITING_PREV_TAIL_*` | 按章作业面 |
| `WRITING_CARDS_*` / `WRITING_EXPORT_PROFILE` | 素材卡与导出 |
| `WRITING_DRAFT_HISTORY_KEEP` | 草稿历史份数 |

### A.5 工具 / 隐私 / 可观测 / HA

| 变量 | 说明 |
|------|------|
| `RUN_COMMAND_MODE` | `shell` / `simulate` |
| `TOOL_SCHEMA_VALIDATE` / `CITATION_VERIFY_ENABLED` | harness 校验 |
| `PII_REDACT_*` / `SECRET_SCAN_*` | 脱敏与密钥扫描 |
| `OTEL_*` | 默认关 |
| `WORKER_MODE` | `queue.yml` profile |
| `RUNTIME_URL` / `RUNTIME_URL_MAP` / `RUNTIME_RUNNER_ID` | `ha.yml` |
