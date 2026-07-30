# 04 — 开发规范

## 1. 仓库结构

```text
agent/
├── README.md
├── docs/
│   ├── README.md          # 索引
│   ├── core/              # 活规范（01–13、contracts）
│   ├── topics/            # 写作 / RAG / 沙箱 / Ops …
│   ├── learn/             # Demo、心智模型、面试（非权威）
│   ├── archive/           # 已闭环票 / 暂停设计
│   ├── adr/README.md      # ADR 已退役
│   └── assets/
├── eval/                  # Golden Turn（见 core/11）
├── deploy/
├── packages/contracts/
├── services/{api,runtime,web}/
├── scripts/
├── .env.example
├── Makefile
└── .github/workflows/
```

服务内模块布局见各服务 README。runtime 关键边界：`controller` / `engine` / `context` / `tools` / `scenarios`（**engine 禁止 import scenarios**）。

### 目录规则

| 规则 | 说明 |
|------|------|
| 禁止根级 `app/` | 所有代码在 `services/*` 或 `packages/*` 下 |
| `services/*/app/services/` 深度 ≤ 2 | 超过则拆子包 |
| 跨服务禁止 Python import | 仅通过 HTTP 或 `packages/contracts` |
| web 禁止 import Python 服务代码 | 仅 HTTP + `packages/contracts` codegen 的 TS 类型 |
| 每个服务独立 `pyproject.toml` | 依赖不向上泄漏到根目录巨型 requirements |
| web 独立 `package.json` + `pnpm-lock.yaml` | Node 依赖仅存在于 web build；不进 api/runtime 镜像 |

## 2. 技术栈

### 2.1 api / runtime（Python）

| 层 | 选型 | 版本 |
|----|------|------|
| 语言 | Python | 3.11+ |
| API 框架 | FastAPI | 0.110+ |
| 图编排 | LangGraph | 与 agent-langraph 对齐最新稳定版 |
| 数据库 | PostgreSQL | 16 |
| 迁移 | Alembic | — |
| 校验 | Pydantic | v2 |
| 测试 | pytest + pytest-asyncio | — |
| 格式化/检查 | ruff | 替代 black+isort+flake8 |
| 类型检查 | pyright 或 mypy | CI 必选其一 |
| 容器 | Docker Compose v2 | — |

### 2.2 web（前端）

前端栈见 [03-docker-runtime](03-docker-runtime.md)。

| 层 | 选型 | 版本 |
|----|------|------|
| 语言 | TypeScript | 5+ |
| UI | React | 18+ |
| 构建 | Vite | 6+ |
| 包管理 | pnpm | 9+（仅 build / 本地 dev） |
| 样式 | Tailwind CSS + shadcn/ui | — |
| REST | TanStack Query | 5+ |
| SSE | `shared/realtime/` 自研封装 | EventSource 或 fetch-stream |
| 类型生成 | openapi-typescript 等 | 从 `packages/contracts` |
| 生产服务 | nginx:alpine | 托管 `dist/`；**禁止**生产容器常驻 Node |
| Node（构建） | node:20-alpine | 仅 Dockerfile build stage 与本地 dev |

编辑器（Phase 1+）：CodeMirror 6 或 Monaco，按场景 **懒加载**。

## 3. 代码风格

### 3.1 Python

- **强制类型注解**：公开函数、路由 handler、Provider 方法。
- **async 优先**：I/O 边界（DB、HTTP、LLM）使用 `async def`。
- **显式依赖注入**：FastAPI `Depends`；Graph 节点通过 state + 工厂获取 Provider。
- **错误处理**：业务错误用自定义异常 → HTTP 异常处理器；禁止裸 `except Exception`。
- **日志**：`structlog` 或标准 `logging` + JSON formatter；禁止 `print` 调试。

### 3.2 TypeScript / Web

- **强制类型**：公开组件 props、API 响应使用 TypeScript；类型优先从 `packages/contracts` codegen，禁止手写与 OpenAPI 漂移的重复定义。
- **API 基址**：生产与容器内使用相对路径 `/api/v1`；本地 dev 用 Vite `server.proxy` 转发 `/api`。
- **状态**：Turn 执行态来自 SSE + `TurnView` 投影；禁止在组件内维护 Turn 阶段状态机（见 `09` §5）。
- **SSE**：统一经 `shared/realtime/TurnStreamClient`；须支持 `Last-Event-ID` 重连；Stop 乐观 UI = **冻结增量渲染、继续消费终态**（见 `10` §5.1、ADR-015）；忙时出站排队见 `10` §5.1.1。
- **格式化/检查**：ESLint + Prettier（或 Biome）；`tsc --noEmit` 在 CI 必选。
- **测试**：Vitest + Testing Library（Phase 1 起）；关键 realtime hook 须有单测。
- **依赖**：`pnpm` + lockfile；禁止在 api/runtime 镜像中安装 Node 依赖。

```typescript
// 推荐：零运行时配置的 API 基址
const API_BASE = '/api/v1';
```

```python
# 好的模式
async def create_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    ...

# 禁止：在节点内直接读全局 settings 并 new 客户端
```

### 3.3 命名

| 类型 | 约定 | 示例 |
|------|------|------|
| 模块 | snake_case | `turn_controller.py` |
| 类 | PascalCase | `TurnController` |
| API 路径 | kebab 或 snake，统一前缀 | `/api/v1/sessions` |
| 环境变量 | SCREAMING_SNAKE | `DATABASE_URL` |
| 数据库表 | snake_case 复数 | `sessions`, `turns` |

### 3.4 文件大小

- 单文件 **≤ 400 行**；超过则拆分。
- 单函数 **≤ 60 行**；超过则提取私有函数或子模块。

### 3.5 边界契约校验（ADR-017）

下列边界 **禁止** 裸 `dict` 进入业务逻辑；须 Pydantic v2 或 JSON Schema 校验：

| 边界 | 来源 |
|------|------|
| api HTTP 请求/响应 | OpenAPI 同步 models |
| api → runtime 命令 | `schemas/commands/*.json` → 共享 `packages/contracts/python/` |
| `turn_events` append 前 | `envelope.json` + `events/payloads/{type}.json` |
| `ToolCall` / `ToolResult` | `ToolSpec.input_schema` + 统一 result 模型 |

runtime 写入事件若 payload 校验失败 → `turn.failed`（`schema_validation_error`），**禁止**写入不合规行。

CI：`packages/contracts` 下 jsonschema 夹具测试；`mypy`/`pyright` 覆盖各服务 `app/`。

## 4. API 规范

### 4.1 版本与路径

- 对外 API 统一前缀：`/api/v1/`
- 内部 API 统一前缀：`/internal/`
- 健康检查：`/health/live`、`/health/ready`（不加版本前缀）

### 4.2 响应格式

```json
{
  "data": { },
  "error": null,
  "meta": { "request_id": "uuid" }
}
```

错误时：

```json
{
  "data": null,
  "error": {
    "code": "TURN_NOT_FOUND",
    "message": "人类可读说明",
    "details": {}
  },
  "meta": { "request_id": "uuid" }
}
```

错误码注册表：`packages/contracts/schemas/errors.json`

### 4.3 流式

- Turn 执行流使用 **SSE**（`text/event-stream`）
- 事件类型枚举在 `packages/contracts/schemas/events/`
- 每个事件必须可 JSON 序列化，带 `turn_id` 与 `ts`

## 5. 配置规范

### 5.1 十二要素与配置分层

权威决策：[ADR-003](03-docker-runtime.md)（Bootstrap）、[ADR-019](03-docker-runtime.md)（Operational）。

1. **Bootstrap 配置**存在环境变量中（`DATABASE_URL`、`APP_SECRET_KEY` 等）；变更须重启对应服务。
2. **Operational 配置**（模型供应商、API key）存 PostgreSQL `model_provider_profiles`；经 Web → api 写入；runtime 在 `StartTurn` 读取；**禁止**为频繁改 key 而重启 runtime。
3. 每个服务一个 `Settings` 类，启动时校验 Bootstrap 项。
4. 敏感项（key、password）禁止默认值入库（git）；运营密钥以 **密文** 存 DB。
5. 开发默认值仅在 `docker-compose` 的 `${VAR:-default}` 用于本地；`MODEL_*` env 为 DB 无激活 profile 时的 fallback。

```python
# services/api/app/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str
    runtime_url: str = "http://runtime:8001"
    auth_enabled: bool = True
    app_secret_key: str
    # config_encryption_key: str | None  # 可选；见 ADR-019
```

`runtime` Settings 同样读取 `database_url`、`config_encryption_key`（或与 api 共享派生规则），**不**在启动时把 `MODEL_API_KEY` 当作唯一来源（DB 优先）。

### 5.2 Feature Flag

- 命名：`FEATURE_<NAME>_ENABLED`
- 必须有过期 issue 或 ADR 引用
- 默认 `false` 的新能力不影响 Phase 0 启动

## 6. 数据库规范

- 所有迁移通过 Alembic；禁止 hand-edit 生产库。
- 表必须有 `created_at`；可变实体加 `updated_at`。
- 软删除用 `deleted_at`，非物理删除会话数据。
- `api` 拥有迁移主权；`runtime` 只读写，不擅自建表。

## 7. 测试规范

### 7.1 金字塔

```text
        ┌─────────┐
        │ E2E     │  compose 冒烟 + 少量 golden
        ├─────────┤
        │ 集成     │  API + DB（testcontainers 或 compose）
        ├─────────┤
        │ 单元     │  纯逻辑、节点、Provider mock
        └─────────┘
```

### 7.2 要求

| 类型 | 覆盖率目标 | 说明 |
|------|------------|------|
| 单元 | 核心模块 ≥ 80% | `engine/`, `controller/`, `tools/core/`, `routers/` |
| 集成 | 每个 router 至少 1 个 |  happy path + 主要 4xx |
| E2E | Phase 里程碑 | `smoke_test.sh`（L0）；`eval_run.py --phase 1`（L1）；`--phase 1b`（L1b 阻断）见 `12` §4 |

### 7.3 命名

```text
tests/unit/test_input_compiler.py
tests/unit/test_should_query.py
tests/integration/test_sessions_api.py
tests/e2e/test_single_turn.py
```

### 7.4 禁止

- 依赖外部 LLM 真实调用的单元测试（必须 mock）
- 测试间共享可变全局状态
- 无 assert 的「烟雾测试」

## 8. Git 工作流

### 8.1 分支

- `main`：可部署
- `feat/<issue>-<short-name>`：功能分支
- `fix/<issue>-<short-name>`：修复

### 8.2 Commit 消息

```
<type>(<scope>): <subject>

<body>
```

type：`feat` | `fix` | `docs` | `refactor` | `test` | `chore` | `build`

scope：`api` | `runtime` | `web` | `deploy` | `contracts`

### 8.3 PR 要求

- CI 全绿：`static-checks`（ruff 关键规则 + web lint/typecheck + gitleaks）与 proof / web-and-codegen
- **推送前**：`make hooks-install`（一次）后，`git push` 自动跑 `scripts/preflight_unit.sh`（CI `unit.*` 本地镜像）。全量 Actions 镜像请手动 `make preflight-ci`（久；勿挂在 pre-push，以免 SSH 空闲被掐），通过后可用 `SKIP_PREFLIGHT=1 git push`。应急绕过：`SKIP_PREFLIGHT=1` / `--no-verify`；偶尔要在 push 时全量：`PREFLIGHT_CI=1 git push`
- 涉及 API 变更须更新 `packages/contracts/openapi` 并同步 web codegen 类型；契约 SemVer / CHANGELOG 见 `packages/contracts/README.md`
- 涉及架构变更须新增或更新 ADR
- 单 PR 聚焦一个服务或一个垂直能力

## 9. 可观测性

| 项 | Phase 0 | Phase 2+ |
|----|---------|----------|
| 结构化日志 | JSON stdout（stdlib 经 ProcessorFormatter 接入 structlog） | + 集中收集 |
| request_id | 中间件注入，全链路透传 | |
| 指标 | Prometheus 文本 `/metrics`（需内部 Bearer；固定桶 histogram） | + 采集端 / 告警 |
| 追踪 | — | OpenTelemetry |

日志字段最小集：`timestamp`, `level`, `service`, `request_id`, `turn_id`, `message`

## 10. 安全规范

- 依赖扫描：`pip-audit` 或 `uv pip audit`（本地 `scripts/security_audit.sh`；可挂 nightly）
- 密钥扫描：gitleaks（CI `static-checks` job：`gitleaks dir . --config .gitleaks.toml`；本地同配置）
- 工具执行：路径白名单 + 租户隔离
- `runtime` 内部 API 校验 `X-Internal-Token`（`hmac.compare_digest`）
- 生产 `AUTH_ENABLED=true` 且 `END_USER_AUTH_ENABLED=true`，`APP_SECRET_KEY` 非默认值
- auth 端点 IP 固定窗口限流；改密吊销旧 token（token 内嵌密码版本）；敏感写操作写 `audit_log`

## 11. 文档规范

| 文档类型 | 位置 | 何时更新 |
|----------|------|----------|
| 架构 | `docs/core/02-architecture.md` | 服务边界变化 |
| Agent 内核 | `docs/core/05-agent-runtime.md` | 循环/终止/子 agent 机制变化 |
| 工具与上下文 | `docs/core/06-tools-and-context.md` | 工具协议/审批/上下文策略变化 |
| 产品模式 | `docs/core/09-product-modes.md` | 场景、ScenarioProfile、扩展宪法 |
| 领域模型 | `docs/core/07-domain-model.md` | Session/Run/Turn 变化 |
| 事件与投影 | `docs/core/08-event-projection-pipeline.md` | SSE/投影流水线变化 |
| 产品体验 / SLO | `docs/core/10-product-experience.md` | 体验门槛、长期运行策略 |
| 评估与 golden | `docs/core/11-eval-and-golden-turns.md` | 用例、metrics、CI |
| 部署与工作区 | `docs/core/03-docker-runtime.md`（§8 工作区/沙箱） | compose/env/卷/扩缩变化 |
| 契约索引 | `docs/core/contracts.md` | API/事件/投影 schema 变更 |
| 服务 README | `services/*/README.md` | 端口、env、本地运行 |
| OpenAPI / DDL / 命令 | `packages/contracts/` | API、表结构、内部命令变更 |

**禁止**写 1400 行单体 arch 文档；细节放 `core/` / `topics/` 与服务 README。**不再新增 ADR**。

## 12. Phase 0 代码评审清单

PR 合并前自检：

- [ ] 是否只改了一个服务的边界内代码？
- [ ] 新增 **Bootstrap** 环境变量是否已写入 `.env.example`？高级旋钮是否只改 Settings 默认值并记入 `docs/03` 附录 A？
- [ ] 是否有 `/health/live` 且不在 live 探针做重操作？
- [ ] 是否有对应测试？
- [ ] 是否引入跨服务 Python import？（应拒绝）
- [ ] `services/runtime/app/engine/` 是否 import `scenarios`？（**应拒绝**；场景分支仅允许在 `TurnController`）
- [ ] 契约变更是否同步 `packages/contracts/` 与 `docs/core/contracts.md`？（见 `packages/contracts/README.md`）
- [ ] 行为变更是否更新/新增 golden（`eval/golden/`）并同步活文档？
- [ ] 改动 `context/`、`search_*`、`delegate` 是否同步 `12` §5.2 对应用例？
- [ ] `InputCompiler` / `shouldQuery` 规则变更是否有单元测试？
- [ ] Dockerfile 是否非 root 运行？
- [ ] 镜像构建是否可在 CI 无缓存完成？

## 13. Makefile 约定（薄封装）

```makefile
.PHONY: up down logs ps smoke

COMPOSE = docker compose -f deploy/docker-compose.yml

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

smoke:
	./scripts/smoke_test.sh
```

Makefile **不得**隐藏必须的 `-f` 叠加；复杂组合写进文档而非 Makefile 记忆。
