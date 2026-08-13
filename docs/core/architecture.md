# 架构

部署拓扑、分模块发布、领域对象、场景与速率红线。两张主图：请求路径与发布台；Turn 生命周期另附详图。

## 图

1. [请求主路径](../assets/architecture/request-path-zh.png) — 浏览器 → gateway → api → runtime → 事件/SSE → Web  
2. [分模块发布台](../assets/ops/release-modular-deploy-zh.png) — `:9090` · dirty · `up-api|up-runtime|up-web` · 如何确认已更新  

![请求主路径](../assets/architecture/request-path-zh.png)

![分模块发布台](../assets/ops/release-modular-deploy-zh.png)

## 1. 部署拓扑

```text
Client
  → Caddy :80/:443
       ├─ /          → web（工作台静态/SSR 壳）
       └─ /api/* · /health/* → api :8000
              → HTTP 内部命令 → runtime :8001（不公网）
              ↔ Postgres 16 + pgvector
runtime / api 另挂卷：/workspace（用户 Work 根）· /data（运行数据）
```

| 组件 | 职责 | 明确不做 |
|------|------|----------|
| **gateway（Caddy）** | TLS、路由 | 业务状态、鉴权逻辑 |
| **web** | 场景工作台；消费 SSE + `GET /view` | 推断 Turn 阶段；直连 runtime |
| **api** | 鉴权、Session/Turn 命令、LISTEN、SSE、投影 `turn_views`、Ops 旁路 | 跑 Agent loop |
| **runtime** | Intake、AgentEngine、工具、检索、checkpoint、写 `turn_events` | 对浏览器开 SSE；UI 投影 |
| **postgres** | 领域表 · `turn_events` · 产品向量 | — |
| **发布台** | 本机 `:9090` 健康/脏模块/一键重建 | 第二套产品栈；不替代 `:80` |

硬约束：

- 服务之间 **无 Python 互 import**。  
- 跨服务实时事实桥 = **Postgres**（runtime `INSERT` + `NOTIFY`，api `LISTEN`）。  
- 契约源在仓库 `packages/contracts`（OpenAPI、事件 JSON Schema、DDL）；api/web 由此派生，不在文档里另起一套字段表。

起栈：`make up`（分模块重建脏服务）+ 发布台 `:9090`；全量 `make up-all`。配置入口 `.env`；**模型供应商在 Web「设置 → 模型」配置**，不要堆一堆 `MODEL_*` 进 `.env` 当日常手段。可选 overlay：queue、retrieval、ha（双 runtime）、runtime-lite（stub 评测）、ops-eval（api 挂 docker.sock，见工作台）。

## 2. 分模块发布（:9090）

产品面始终是 `http://localhost/`（Caddy）。发布台是**同仓旁路控制台**，不另起一套业务服务。

```text
make up / make release-plan / 浏览器 :9090
  → plan.py 对比 HEAD · 工作树 · reports/release/status.json 里的 deployed_*
  → 标出 dirty：api / runtime / web / gateway（+ embedding / 索引健康）
  → 勾选模块 → make up-api | up-runtime | up-web（或 release.sh run）
  → mark 写入 deployed_sha + worktree_digest
  → 容器 healthy + 看板变绿 = 已更新
```

### 2.1 模块 ↔ 路径

前缀定义在 `scripts/release/paths.env`：

| 模块 | 路径前缀（任一命中即可能 dirty） | 重建目标 |
|------|----------------------------------|----------|
| **api** | `services/api/` · `packages/contracts/` | `make up-api` |
| **runtime** | `services/runtime/` · `packages/contracts/` | `make up-runtime`（并 recreate `ast-indexer`） |
| **ast-indexer** | `services/runtime/.../workspace_index/` · compose 入口 | `make up-ast-indexer` |
| **web** | `services/web/` | `make up-web` |
| **gateway** | `deploy/caddy/` · compose 入口 | compose recreate（无独立 image 时） |

改 `packages/contracts/` 会同时弄脏 **api + runtime**。改工作区 AST 包会弄脏 **runtime + ast-indexer**。

### 2.2 怎样算 dirty

| 信号 | 含义 |
|------|------|
| **committed since `deployed_sha`** | 上次 mark 之后有已提交改动落在该模块前缀 |
| **worktree_digest** | 本地未提交内容；已 bake 进上次 `up-*` 的同 digest 不再当 dirty |
| **容器未起** | 对应 `agent-api` / `agent-runtime` / `agent-ast-indexer` / `agent-web` / `agent-gateway` 不在 `docker ps` |

两种看板模式（见 `scripts/release/README.md`）：

- **本地开发**：已提交 + 未提交都算。  
- **同步部署**：只看已提交；先「拉取远程」再发。

### 2.3 如何确认更新已生效

1. 看板该模块由 action → **ok**，`deployed_sha` 对齐当前意图。  
2. `make release-plan` 打印同一份健康 JSON（终端对照）。  
3. `docker compose ps` / healthcheck：`agent-*` **healthy**。  
4. 产品面：`curl -fsS http://localhost/health/live`；改 UI 则硬刷新 `:80`。  
5. Ops / 密钥：新生成的 `OPS_TEST_SECRET` 会触发 api recreate（`up-web` 路径也会处理）。

强制全量：`make up-all`（不分模块 `--build` 后 mark 全模块）。日常优先 `make up` 只重建脏的。细节与日志：`reports/release/` · `scripts/release/release.sh`。

## 3. 领域对象与状态

![Turn 生命周期](../assets/architecture/turn-lifecycle-zh.png)

```text
Principal → default Work（work_id, work_root）
                └── Session*（对话线程，携带 work_id）
                      └── Turn（一次用户输入的业务闭环）
                            ↔ Run（1:1 执行实例，checkpoint / cancel）
                                 └── Step*（assemble → model → tools → checkpoint；仅事件/日志粒度，无独立 REST）
```

| 对象 | 含义 | 关键约束 |
|------|------|----------|
| **Work** | 稿件与资料的世界根：`outline` / `sections|manuscript` / `drafts` / `sources` | 不随 Session compact 拆散 |
| **Session** | 连续性容器：transcript、策略、压缩摘要 | 换 Session 不换默认 Work |
| **Turn** | 从受理到终态的一次用户闭环 | **恰好一个** Run |
| **Run** | agentic loop 执行实例 | 审批挂起仍用同一 `run_id`；禁止跨 Turn 共用未结束 Run |
| **Artifact** | 产物引用（补丁、文件） | 归属 Turn |

Turn 状态机（概念）：

```text
pending → running ⇄ waiting_approval
               ↓
        completed | failed | cancelled
```

- **取消是终态**：`cancelled ≠ failed` / `model_error`。  
- **没有 ResumeTurn**：取消或跑完后再聊 = 同 Session **新 Turn**。  
- 重试/恢复审批：仍是 **同一个** `run_id` + checkpoint，不是第二个 Run。

## 4. 场景（ScenarioProfile）

产品入口差在配置，不在第二套图：

| `scenario_id` | 定位 |
|---------------|------|
| `writing` | 写作：大纲/草稿/diff-first、资料 RAG |
| `agent` | 通用全工具面（含 shell/测试等） |
| `intel` | 情报向资料与提示 |
| `collab` | 多 agent 协作（目标态；编排者+委派） |

Profile 提供：工具白名单、`system.md`、审批覆盖、检索 path 过滤、子 agent 类型等。  
**AgentEngine 禁止** `if scenario == "..."`；差异只经 Profile / ToolScope 注入。

## 5. 速率红线 R1–R5

任何「加厚」能力都先过这五条，再谈效果：

| # | 原则 | 验收含义 |
|---|------|----------|
| **R1** | 不挡受理 | `turn.accepted` / TTFB 目标不因新逻辑同步恶化 |
| **R2** | 首 token 前不加同步模型 | 禁止热路径同步摘要/裁判/改写 |
| **R3** | 热路径 CPU 毫秒级 | 同步重活（整库 embed、大扫描）禁止上主链 |
| **R4** | 重活异步 | 索引、审计落盘、软预压缩缓存走旁路 |
| **R5** | 可测才合并 | `make gate` / Ops `suite=ci` 等同完整证明 |

索引、Ops、Golden 都必须是 **环外或工具中介**，不能为了分数改 loop 语义或伪造路径。
