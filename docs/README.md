# 文档索引

Agent Platform：**一个 Runtime，多个 Scenario**。验证：`make gate` · `make smoke` · `make eval-all`。

> 2026-07 已收敛为 **core / topics / learn / archive**。旧扁平路径已删除（请改打开新路径）。**ADR 正文已删**，对照见 [adr/README.md](adr/README.md)。

## 起手

| 目的 | 读 |
|------|-----|
| 起栈 | [../README.md](../README.md) · [learn/DEMO.md](learn/DEMO.md) |
| 架构地图 | [core/02-architecture.md](core/02-architecture.md) |
| Loop / 工具 | [core/05](core/05-agent-runtime.md) · [core/06](core/06-tools-and-context.md) |
| 契约 | [core/contracts.md](core/contracts.md) |

---

## `core/` — 活规范（改代码对照这里）

| 文档 | 内容 |
|------|------|
| [01](core/01-problems-and-goals.md) | 目标与原则 |
| [02](core/02-architecture.md) | 架构地图 |
| [03](core/03-docker-runtime.md) | 部署、env、工作区 |
| [04](core/04-development-standards.md) | 工程规范 |
| [05](core/05-agent-runtime.md) | Loop / Intake / Engine |
| [06](core/06-tools-and-context.md) | 工具与上下文 |
| [07](core/07-domain-model.md) | Session / Run / Turn |
| [08](core/08-event-projection-pipeline.md) | 事件、SSE、投影 |
| [09](core/09-product-modes.md) | ScenarioProfile |
| [10](core/10-product-experience.md) | 体验 SLO |
| [11](core/11-eval-and-golden-turns.md) | Golden / CI |
| [12](core/12-model-harness.md) | Harness |
| [13](core/13-rate-redlines.md) | 速率红线 R1–R5 |
| [contracts](core/contracts.md) | API / 事件 / DDL |

---

## `topics/` — 产品与横切专题

| 专题 | 文档 |
|------|------|
| 写作 | [writing/](topics/writing/)（[quality](topics/writing/quality.md) · [work](topics/writing/work-model.md) · [token](topics/writing/token-economy.md) · [runway](topics/writing/runway.md) · [plan-suggest](topics/writing/plan-suggest.md)） |
| RAG | [rag-and-sources](topics/rag-and-sources.md) |
| 会话 | [user-session-history](topics/user-session-history.md) |
| 多租户 | [multi-tenancy](topics/multi-tenancy.md) |
| Proof / UX | [proof-gate-and-ux-signals](topics/proof-gate-and-ux-signals.md) |
| Ops | [ops-eval-console](topics/ops-eval-console.md) |
| 沙箱 | [sandbox](topics/sandbox.md) |
| 读降本 | [read-cache](topics/read-cache.md) |
| collab（未实施） | [collab-multi-agent](topics/collab-multi-agent.md) |
| search_records 蓝图 | [search-records](topics/search-records.md) |

---

## `learn/` — 教学 / 面试（非实施权威）

冲突时以 `core/` / `topics/` 为准。

| 文档 | 内容 |
|------|------|
| [DEMO](learn/DEMO.md) | 5 分钟路径 |
| [mental/](learn/mental/) | RAG / Context / Harness / Intake / bwrap 心智模型 |
| [agent-system-qa](learn/agent-system-qa.md) | 面试向原理问答 |
| [highlights-vs-legacy](learn/highlights-vs-legacy.md) | 相对旧项目 |
| [context-compaction-walkthrough](learn/context-compaction-walkthrough.md) | 压缩演练 |
| [INTERVIEW-MOCK-RESUME](learn/INTERVIEW-MOCK-RESUME.md) | 面试稿 |

---

## `archive/` — 已闭环票 / 暂停设计

不作为日常入口；需要细节时再翻。含 multimodal、skills、优化审查、镜像分层、嵌套沙箱计划、迁移附录等。

---

## 维护纪律

1. **新能力**：改对应 `core/` 或 `topics/`；禁止再开顶层 `39-xxx-plan.md`。
2. **设计草案**：进 `archive/` 或 `topics/`，写明状态；落地后把现行规则收进权威文。
3. **教学文**：只进 `learn/`，文首标明非权威。
4. **不再新增 ADR**；重大约束写进 `core/` / `topics/` 正文。
