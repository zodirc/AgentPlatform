# 文档索引

本目录为 Agent Platform 的架构与实施规范。**Phase 0–4 核心能力已与代码对齐**。

## 实施状态（摘要）

| 阶段 / 规范 | 状态 |
|-------------|------|
| Phase 0–4 产品能力 + golden + CI profiles | ✅ |
| contracts §10 工具 + `agent-contracts` Python 包 | ✅ |
| shadcn/ui（Radix + CVA + components.json） | ✅ |
| structlog JSON 日志 + `request_id` / `turn_id` 上下文 | ✅ |
| Alembic 唯一迁移入口（0001–0005 revisions） | ✅ |
| OTel OTLP 导出（`OTEL_EXPORTER_OTLP_ENDPOINT`） | ✅ |
| 单测覆盖率 ≥80%（runtime 核心 + api 观测/迁移/路由） | ✅ |
| SLO：`latency.ttfb_ms_max` + `first_token_ms_max` + `cancel_latency_ms_max` golden 门禁 | ✅（stub 路径） |
| ESLint + Prettier + codegen drift CI | ✅ |
| Live eval nightly（`.github/workflows/nightly.yml`） | ✅ |
| Queue worker profile（`make eval-queue` / shared.16） | ✅ |
| Embedding 检索（retrieval 镜像内置本地模型 + hash 降级） | ✅ |

## 设计稿对照（文档 → 代码）

| 文档原「设计稿 / 待实施」 | 落地位置 | 状态 |
|---------------------------|----------|------|
| `deploy/docker-compose.yml` 骨架 | `deploy/docker-compose.yml` | ✅ |
| `runtime/engine/state.py` TurnState | `services/runtime/app/engine/state.py` | ✅ |
| ScenarioProfile + `profiles/*.yaml` | `services/runtime/app/scenarios/` | ✅ |
| `openapi/public.yaml` | `packages/contracts/openapi/public.yaml` | ✅ |
| Web Vite + React Workbench | `services/web/src/scenarios/` | ✅ |
| `dev.override.yml` 热更新模板 | `deploy/compose/dev.override.yml.example` | ✅ |
| embedding 模型预烘焙 `/app/models-baked` | `services/runtime/Dockerfile.retrieval` | ✅ |
| `sentence-transformers` 本地模型 | retrieval profile 默认 `EMBEDDING_BACKEND=sentence_transformers` | ✅ |

验证：`make smoke` · `make eval-all` · `make eval-retrieval` · `make eval-queue` · `make runtime-test`

## 推荐阅读路径

1. **[02-architecture.md](02-architecture.md)** — 架构地图（先读）
2. **[05-agent-runtime.md](05-agent-runtime.md)** + **[06-tools-and-context.md](06-tools-and-context.md)** — 内核
3. **[10-product-modes.md](10-product-modes.md)** — 场景（writing / agent）与扩展宪法
4. **[11-product-experience.md](11-product-experience.md)** — **好用**、长期运行、体验 SLO
5. **[12-eval-and-golden-turns.md](12-eval-and-golden-turns.md)** — **成熟可证明**：golden、metrics、CI
6. **[contracts.md](contracts.md)** — 契约接缝（API、事件、DDL、内部命令）
7. **[07-domain-model.md](07-domain-model.md)** + **[09-event-projection-pipeline.md](09-event-projection-pipeline.md)** — 领域与事件流水线
8. **[03-docker-runtime.md](03-docker-runtime.md)** — 部署、环境变量、工作区与沙箱（§8）

## 完整目录

| 文档 | 内容 |
|------|------|
| [01-problems-and-goals.md](01-problems-and-goals.md) | 目标三角：长期运行 × 好用 × 可证明 |
| [02-architecture.md](02-architecture.md) | **总览地图**（细节在专文） |
| [03-docker-runtime.md](03-docker-runtime.md) | compose、env、健康检查、**工作区/沙箱** |
| [04-development-standards.md](04-development-standards.md) | 仓库结构、代码与测试规范 |
| [05-agent-runtime.md](05-agent-runtime.md) | Loop、**Turn Intake**、AgentEngine |
| [06-tools-and-context.md](06-tools-and-context.md) | 工具协议、审批、上下文治理 |
| [07-domain-model.md](07-domain-model.md) | Session / Run / Turn、checkpoint、幂等 |
| [08-workspace-and-deployment.md](08-workspace-and-deployment.md) | **已合并** → 见 `03` §8 |
| [09-event-projection-pipeline.md](09-event-projection-pipeline.md) | 事件、SSE、投影、UI 数据源 |
| [10-product-modes.md](10-product-modes.md) | ScenarioProfile、writing / agent |
| [11-product-experience.md](11-product-experience.md) | 产品体验 SLO、自用验收 |
| [12-eval-and-golden-turns.md](12-eval-and-golden-turns.md) | Golden Turn、可观测、CI 分层 |
| [contracts.md](contracts.md) | **契约索引** |
| [appendix-migration.md](appendix-migration.md) | 从 agent-langraph 迁移（单一表格） |

## 架构决策（ADR）

见 [adr/README.md](adr/README.md)。共 **19** 条已接受决策（001–004、005–010、011–019）。

## 文档与阶段对应

| 阶段 | 主要文档 |
|------|----------|
| Phase 0 容器骨架 | `03`、`07`、`contracts`、`09`、`12` §4 L0 |
| Phase 1 Turn 闭环 | `05`、`07`、`09`、`10`、`11`、`12` §5.1 |
| Phase 1b 能力融合 | `06` §0.1、`12` §5.2（**阻断进 Phase 2**） |
| Phase 2 能力面 | `06` §10–12、`03` §8 retrieval profile、`12` §5.3 |
| Phase 3+ 垂直与运营 | `02` §3、`03` §8.5、日常自用（`11` §7） |
| Phase 4 CI profiles | `03` queue/retrieval compose、`12` §4 L1c、`eval/README.md` |

## 契约与 eval 落地位置

| 类型 | 路径 |
|------|------|
| 人类可读索引 | [`contracts.md`](contracts.md) |
| Phase 0 DDL | `packages/contracts/schemas/ddl/phase0.sql` |
| Golden Turn Schema | `packages/contracts/eval/golden_turn.schema.json` |
| Golden 用例 | `eval/golden/`（37 YAML） |
| 事件 / 命令 Schema | `packages/contracts/schemas/` |

## 相关

- 仓库总览：[../README.md](../README.md)
