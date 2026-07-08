# 01 — 问题与目标

## 0. 产品定位

**Agent Runtime**：一个内核，多个 **Scenario**。默认 `writing`（写作）；`agent`（通用 Agent，Cursor 式）。差异仅在 **ScenarioProfile**，见 [`10-product-modes.md`](10-product-modes.md)。

**三重目标**（同时成立）：

1. **可长期运行** — 架构可维护、可扩展，数周数月持续使用（[`11-product-experience.md`](11-product-experience.md) §4）
2. **自用好用** — 流式、可打断、diff 审阅、长会话不劣化（`11` §1–3）
3. **对外成熟** — Golden Turn 回归、可观测、可 demo 的技术亮点（[`12-eval-and-golden-turns.md`](12-eval-and-golden-turns.md)）

交互标准：**流式、可打断、过程可见、diff 改稿**。

扩展宪法：一个 Runtime，多个 Scenario；一个 Loop，多组 Tool；一条事件管道，多种工作台布局。见 [ADR-013](adr/013-dual-product-modes.md)。

## 1. 为何重写 agent-langraph

旧系统**领域概念正确**（Session / Run / Turn），但**工程形态**导致不可维护。典型线上痛点与新设计对策：

| 老项目痛点 | 根因（归纳） | 新设计对策 | 文档 |
|------------|--------------|------------|------|
| 很难即时取消 | 图节点长事务；cancel 传不到 stream/子进程 | 全程 abort + 双通道取消 + 乐观 UI | ADR-015、`05` §8.1、`11` §5.1 |
| 流程卡几百秒 | 13 节点强制链 + 无界等待 provider/tool | 单 loop + 三层超时 + Stall Watchdog | ADR-016、`05` §8.3 |
| 某步 str 对不上对象 | 膨胀 AgentState；节点间 dict 无 schema | messages + 边界 Pydantic + payload schema | ADR-017、`07` §10 |
| 启动慢 / 改一处崩全局 | 单进程 lifespan 拉满；200+ 平铺模块 | 三服务拆分 + 契约索引 | `02`、`04` |

摘要表（工程形态）：

| 问题 | 后果 |
|------|------|
| 单进程承载 API + 执行 + Web + 调度 | 故障域大、难扩缩 |
| `services/` 200+ 文件平铺 | 边界模糊、循环依赖 |
| 800 行 YAML + 多 compose 叠加 | 环境不一致 |
| 13 节点固定 pipeline | 简单任务也跑全链路；加能力改全图 |
| 文档与实现脱节 | 架构无法落地 |

新项目保留领域语义，更换承载方式：**三服务 + agentic loop + 工具扩展 + Docker 契约**。

## 2. 设计原则

| # | 原则 |
|---|------|
| P1 | **Docker First** — 容器为验收路径 |
| P2 | **边界先于功能** — 契约先于代码；禁止跨服务 Python import |
| P3 | **十二要素配置** — 环境变量 + Pydantic Settings |
| P4 | **渐进交付** — Phase 0 stub → Phase 1 双场景闭环 |
| P5 | **可测试** — healthcheck + compose 集成测试 |
| P6 | **场景扩展** — 新能力 = Profile + 工具注册，不改 loop |
| P7 | **体验可测** — TTFB、Cancel、重连等有 SLO（`11`） |
| P8 | **行为可回归** — Golden Turn + CI（`12`） |
| P9 | **Intake 确定性** — Turn Intake 门控，非意图 Pipeline（ADR-014） |
| P10 | **能力走主路径** — ContextEngine / RAG / delegate 经 loop 工具与 golden 强制调用，禁止摆设模块（`06` §0.1、`12` §5.2） |
| P11 | **边界可校验** — 命令/事件/tool 在边界 Pydantic + JSON Schema；防止字段漂移（ADR-017） |
| P12 | **执行有上界** — model/tool/step 超时 + Stall Watchdog；防止无界 hang（ADR-016） |
| P13 | **运营配置热生效** — 模型供应商 / API key 经 Web → DB 注入；Turn 边界生效，无需重启（ADR-019） |

## 3. 非目标（当前）

K8s/Helm、多区域 HA、完整 port 旧 API、MCP/A2A/Marketplace。

## 4. 里程碑

| 阶段 | 验收 |
|------|------|
| **0** | `docker compose up` 全绿；最小 SSE + stub API；1 条 stub golden |
| **1** | **管道**：patch/diff、timeline、SLO；`12` §5.1 全绿 |
| **1b** | **能力融合**：ContextEngine 压缩链、RAG、`delegate` 各 ≥1 条 golden；`12` §5.2 全绿（**Phase 2 前置**） |
| **2** | 向量索引运维、多角色 delegate、`live` eval；metrics |
| **3+** | 日常自用数周；eval 无回归；可选多副本 |
| **4** | CI profiles：`eval-retrieval` / `eval-queue`；nightly live；retrieval 镜像内置本地 embedding 模型 |

## 5. 领域对象（摘要）

`Session` → `Turn`（含 `scenario_id`）→ `Run`（1:1）→ `Step`（事件）。详见 [`07-domain-model.md`](07-domain-model.md) 与 [`contracts.md`](contracts.md)。

## 6. 成功标准

### Phase 0（骨架）

1. 读 [`03-docker-runtime.md`](03-docker-runtime.md) + [`contracts.md`](contracts.md) 可启动并理解接缝。
2. 每个服务目录有 README（端口、env）。
3. [`02-architecture.md`](02-architecture.md) 文档地图可导航全貌。

### Phase 1+（自用 + 成熟）

4. 满足 [`11-product-experience.md`](11-product-experience.md) 体验 SLO 与场景门槛。
5. [`12-eval-and-golden-turns.md`](12-eval-and-golden-turns.md) 中 **§5.1 + §5.2** golden 全绿（管道 + 能力融合）。
6. 能向他人 demo：写作 diff + 资料引用（`search_sources`）+ agent 检索/委派 trace + SSE 重连。

旧模块迁移：[`appendix-migration.md`](appendix-migration.md)。
