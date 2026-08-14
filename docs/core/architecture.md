# 架构

部署拓扑、分模块发布、领域对象、场景与速率红线。两张主图：请求路径与发布台；Turn 生命周期另附详图。

## 图

1. [请求主路径](../assets/architecture/request-path-zh.png) — 浏览器 → 领取制 → Engine → 事件/SSE → Web  
2. [分模块发布台](../assets/ops/release-modular-deploy-zh.png) — `:9090` · dirty · 分模块重建 · 如何确认已更新  

![请求主路径](../assets/architecture/request-path-zh.png)

![分模块发布台](../assets/ops/release-modular-deploy-zh.png)

## 1. 部署拓扑

```text
Client
  → Caddy :80/:443
       ├─ /          → web（工作台）
       └─ /api/* · /health/* → api :8000
              │
              ├─ 默认 TURN_DISPATCH=pull
              │    INSERT turns/runs → 准入 → pg_notify(分发)
              │    → runtime LISTEN / claim + lease → TurnController
              │
              └─ 回退 push：HTTP 内部 start-turn → runtime :8001（不公网）

Postgres 16 + pgvector
  · 领域表 · turn_events · 产品向量
  · 另：run_commands / runners 租约（分发与控制命令）

旁路（不挡受理）
  · ast-indexer：工作区 AST 冷启动/增量
  ·（可选）bench-postgres：Ops L1 向量隔离

卷：用户 Work 根 · /data 运行数据
```

| 组件 | 职责 | 明确不做 |
|------|------|----------|
| **gateway（Caddy）** | TLS、路由 | 业务状态、鉴权逻辑 |
| **web** | 场景工作台；消费 SSE + `GET /view` | 推断 Turn 阶段；直连 runtime |
| **api** | 鉴权、准入、Session/Turn 落库与分发通知、LISTEN、SSE、投影、Ops 旁路 | 跑 Agent loop |
| **runtime** | claim/lease、Intake、AgentEngine、工具、检索、checkpoint、写 `turn_events` | 对浏览器开 SSE；UI 投影 |
| **ast-indexer** | 工作区符号索引旁路（入队领取解析） | 进 Turn 热路径；替代 LSP |
| **postgres** | 领域表 · 事件 · 向量 · 分发/命令通道 | — |
| **发布台** | 本机 `:9090` 健康/脏模块/一键重建 | 第二套产品栈；不替代 `:80` |

硬约束：

- 服务之间 **无 Python 互 import**。  
- 跨服务实时事实桥 = **Postgres**（`INSERT` + `NOTIFY` / `LISTEN`）。  
- 契约源在 `packages/contracts`（OpenAPI、事件 JSON Schema、DDL）；api/web 由此派生。

起栈：`make up`（分模块重建脏服务）+ 发布台 `:9090`；全量 `make up-all`。配置入口 `.env`；**模型供应商在 Web「设置 → 模型」配置**。可选 overlay：queue、ha（双 runtime，同为 pull）、runtime-lite、ops-eval、bench。  
扩缩与故障注入见 [Pull 分发运维手册](../ops/pull-dispatch-runbook.md)。

## 2. 分模块发布（:9090）

产品面始终是 `http://localhost/`（Caddy）。发布台是**同仓旁路控制台**，不另起一套业务服务。

```text
make up / make release-plan / 浏览器 :9090
  → 对比 HEAD · 工作树 · 已部署标记
  → 标出 dirty：api / runtime / web / gateway / ast-indexer（+ embedding / 索引健康）
  → 勾选模块 → 对应 up-* 重建
  → mark 写入已部署指纹
  → 容器 healthy + 看板变绿 = 已更新
```

### 2.1 模块 ↔ 路径

| 模块 | 脏前缀（概念） | 重建 |
|------|----------------|------|
| **api** | api 服务 · 契约包 | `make up-api` |
| **runtime** | runtime 服务 · 契约包 | `make up-runtime`（常 recreate ast-indexer） |
| **ast-indexer** | 工作区索引包 · compose 入口 | `make up-ast-indexer` |
| **web** | web 服务 | `make up-web` |
| **gateway** | Caddy · compose 入口 | compose recreate |

改契约包会同时弄脏 **api + runtime**。改工作区 AST 包会弄脏 **runtime + ast-indexer**。

### 2.2 怎样算 dirty（需重建）

| 信号 | 含义 |
|------|------|
| **已提交相对 deployed** | 上次 mark 之后有提交落在该模块前缀 → **`make up-*`** |
| **工作树指纹** | 未提交改动；已 bake 进上次重建的同指纹不再当 dirty |
| **容器未起** | **不是** rebuild dirty。重启主机后镜像仍在 → **`make start`**（或 `make up` 会先拉起再只重建真正脏的模块） |

看板模式：本地开发看「已提交 + 未提交」；同步部署只看已提交。Ops Bench 未起同样是 `make start-bench`，不 rebuild。

### 2.3 如何确认更新已生效

1. 看板该模块由 action → **ok**。  
2. `make release-plan` 终端对照同一份健康 JSON。  
3. `docker compose ps`：核心 `agent-*` **healthy**。  
4. 产品面：`curl -fsS http://localhost/health/live`；改 UI 则硬刷新。  
5. 新生成的 Ops 密钥会触发 api recreate。

强制全量：`make up-all`。日常优先 `make up`（先拉起已有镜像，再只重建脏模块）。主机重启后优先 `make start`；只有代码相对已部署有变才需要 `up-*`。

## 3. 领域对象与状态

![Turn 生命周期](../assets/architecture/turn-lifecycle-zh.png)

```text
Principal → default Work（work_id, work_root）
                └── Session*（对话线程，携带 work_id）
                      └── Turn（一次用户输入的业务闭环）
                            ↔ Run（1:1 执行实例，checkpoint / cancel / lease）
                                 └── Step*（assemble → model → tools → checkpoint；仅事件粒度）
```

| 对象 | 含义 | 关键约束 |
|------|------|----------|
| **Work** | 稿件与资料的世界根 | 不随 Session compact 拆散 |
| **Session** | 连续性容器：transcript、策略、压缩摘要 | 换 Session 不换默认 Work |
| **Turn** | 从受理到终态的一次用户闭环 | **恰好一个** Run |
| **Run** | agentic loop 执行实例；持有 runner 租约 | 审批挂起仍用同一 `run_id` |
| **Artifact** | 产物引用（补丁、文件） | 归属 Turn |

Turn 状态机：

```text
pending → running ⇄ waiting_approval
               ↓
        completed | failed | cancelled
```

分发相关失败（仍属 `failed` 族，≠ cancelled）：

| 原因 | 含义 |
|------|------|
| **start_timeout** | 超过 claim 时限仍无人领取 |
| **runner_lost** | 副本租约丢失且无法安全续跑 |

- **取消是终态**：`cancelled ≠ failed`。  
- **没有 ResumeTurn**：取消或跑完后再聊 = 同 Session **新 Turn**。  
- 重试/恢复审批：仍是 **同一个** `run_id` + checkpoint。

## 4. 场景（ScenarioProfile）

产品入口差在配置，不在第二套图：

| `scenario_id` | 定位 |
|---------------|------|
| `writing` | 写作：大纲/草稿/diff-first、资料 RAG |
| `agent` | 通用全工具面（shell/测试/结构智能等） |
| `intel` | 情报向资料与提示 |
| `collab` | 多 agent 协作（目标态） |

Profile 提供：工具白名单、系统提示、审批覆盖、检索 path 过滤、子 agent 类型等。  
**AgentEngine 禁止** `if scenario == "..."`；差异只经 Profile / ToolScope 注入。

### 4.1 扩展点清单（官方替代方案）

场景差异只能走下列挂载点（实现见 `scenarios/registry.py` · `scenarios/hooks.py` · profiles `*.yaml`）：

**标量 / 声明式字段（Profile）**

| 字段 | 作用 |
|------|------|
| `tool_names` / `approval_overrides` / `subagent_types` | 工具面与审批（ToolScope） |
| `retrieval` | 检索 path 过滤（工具侧消费） |
| `generation.temperature` | 采样温度 |
| `patch_auto_apply` | `propose_patch` 后自动 apply（settings 总闸仍可关） |
| `structural_prewarm` | StartTurn LSP 软预热 |
| `plan_suggest.threshold` | Plan 建议阈值 |
| `subagent_prompt_suffix` | 子 agent 系统提示追加文案 |
| `post_turn_jobs` | Turn 终态后 api outbox 额外任务（如 `sources.index_sync`） |

**命名 Hook 槽位（`Profile.hooks` → 实现名）**

| 槽位 | 典型实现 | 何时 |
|------|----------|------|
| `system_prompt_composer` | `writing_cards` | StartTurn 组窗 |
| `volatile_composer` | `collab_orchestrator` | StartTurn volatile |
| `step_checkpoint` | `collab_gap_hint` | 每步 checkpoint |
| `post_turn` | `writing_continuity` | Turn 收尾旁路 |
| `compact_bookmark` | `writing_focus` | `/compact` |

槽位集合固定；未知槽位 / 未知实现名 → **启动期 fail-fast**。  
静态门禁：`make constitution-check`（`scripts/check_scenario_leak.py`）禁止新增 `if scenario == "…"`。

## 5. 速率红线 R1–R5

| # | 原则 | 验收含义 |
|---|------|----------|
| **R1** | 不挡受理 | `turn.accepted` / TTFB 不因新逻辑同步恶化 |
| **R2** | 首 token 前不加同步模型 | 禁止热路径同步摘要/裁判/改写 |
| **R3** | 热路径 CPU 毫秒级 | 整库 embed、大扫描禁止上主链 |
| **R4** | 重活异步 | 索引、审计、软预压缩走旁路 |
| **R5** | 可测才合并 | `make gate` / Ops `suite=ci` 等同完整证明 |

索引、Ops、Golden 都必须是 **环外或工具中介**，不能为了分数改 loop 语义。
