# 文档索引

Agent Platform 架构与实施规范。**01–24 连续编号，一文一模块**；变更只改对应正文。

验证：`make smoke` · `make eval-all` · `make eval-retrieval` · `make retrieval-bench-prod` · `make runtime-test`

---

## 模块目录（01–25）

| # | 文档 | 内容 |
|---|------|------|
| 01 | [problems-and-goals](01-problems-and-goals.md) | 目标三角 |
| 02 | [architecture](02-architecture.md) | 架构地图 |
| 03 | [docker-runtime](03-docker-runtime.md) | 部署、env、工作区/沙箱 |
| 04 | [development-standards](04-development-standards.md) | 仓库与工程规范 |
| 05 | [agent-runtime](05-agent-runtime.md) | Loop / Intake / Engine |
| 06 | [tools-and-context](06-tools-and-context.md) | 工具协议、上下文治理 |
| 07 | [domain-model](07-domain-model.md) | Session / Run / Turn |
| 08 | [event-projection-pipeline](08-event-projection-pipeline.md) | 事件、SSE、投影 |
| 09 | [product-modes](09-product-modes.md) | ScenarioProfile、writing / agent |
| 10 | [product-experience](10-product-experience.md) | 体验 SLO |
| 11 | [eval-and-golden-turns](11-eval-and-golden-turns.md) | Golden、CI |
| 12 | [model-harness](12-model-harness.md) | Harness（AH1–AH4） |
| 13 | [rate-redlines](13-rate-redlines.md) | **速率红线 R1–R5** |
| 14 | [writing-quality](14-writing-quality.md) | **写作模块**（WQ0–WQ4 ✅） |
| 15 | [rag-and-sources](15-rag-and-sources.md) | **RAG / 资料库**（IX0–IX4 ✅） |
| 16 | [user-session-history](16-user-session-history.md) | 会话历史（U0–U2 ✅） |
| 17 | [search-records](17-search-records.md) | `search_records` 蓝图 |
| 18 | [multimodal-design](18-multimodal-design.md) | 多模态设计（待落地） |
| 19 | [skills-layer](19-skills-layer.md) | Skills（近期末） |
| 20 | [context-compaction-walkthrough](20-context-compaction-walkthrough.md) | 压缩演练 |
| 21 | [agent-system-qa](21-agent-system-qa.md) | 原理问答 Q0–Q20 |
| 22 | [highlights-vs-legacy](22-highlights-vs-legacy.md) | 相对旧项目全景 |
| 23 | [writing-work-model](23-writing-work-model.md) | **写作作品模型**（WW0–WW4 ✅） |
| 24 | [writing-token-economy](24-writing-token-economy.md) | **写作 Token 经济**（WT0–WT4 ✅） |
| 25 | [writing-runway](25-writing-runway.md) | **Plan 模式（平台）**：步骤可见 / 同意执行 |

未编号：[contracts.md](contracts.md) · [adr/](adr/README.md) · [appendix-migration.md](appendix-migration.md)

---

## 日常入口（产品主线）

| 场景 | 读 |
|------|----|
| 部署 / 默认栈 | [03](03-docker-runtime.md) |
| 速率约束 | [13](13-rate-redlines.md) |
| 写作 | [14](14-writing-quality.md) · [23](23-writing-work-model.md)（作品） · [24](24-writing-token-economy.md)（Token） · [25](25-writing-runway.md)（Plan / 步骤可见） |
| RAG / 索引 / 验收命令 | [15](15-rag-and-sources.md) |
| 会话归属 | [16](16-user-session-history.md) |
| 内核参考 | [05](05-agent-runtime.md) · [06](06-tools-and-context.md) · [12](12-model-harness.md) |

**维护纪律：** 禁止再开 `*-execution` 平行文；过时内容进 git，不留 stub 空号。

---

## 实施状态

| 项 | 状态 | 文档 |
|----|------|------|
| Phase 0–4 + golden / contracts | ✅ | 11 · contracts |
| 写作 WQ0–WQ4 | ✅ | 14 |
| RAG RE0–RE3+RE1；IX0–IX4 | ✅ | 15 |
| 会话 U0–U2 | ✅ | 16 |
| Harness 核心 | 🔧 | 12 |
| 写作作品模型 WW0–WW4 | ✅ | 23 · ADR-020 |
| 写作 Token 经济 WT0–WT4 | ✅ | 24 |
| Prompt cache 布局 WT5 | ⏸ 设计已定 | 24 §4.6 / §10 |
| Plan 模式（平台 · 步骤可见） | 🔧 P0 落地 | 25 |
| Skills / 多模态 / IX5·RE4·RE5 | ⏸/⏳ | 19 · 18 · 15 |

---

## 编号变迁（查旧链）

| 旧 | 新 |
|----|----|
| 08 工作区 | → 03 |
| 09 事件 | → **08** |
| 10/11 场景/体验 | → **09/10** |
| 12 Eval | → **11** |
| 13 交付事故 | 删除（见 git / 14） |
| 14 Harness | → **12** |
| 15 全景 | → **22** |
| 16 QA 过程稿 | → **21** |
| 17 执行方案 | → **13**（仅 R1–R5） |
| 18 多表 | → **17** |
| 19 QA 现状 | → **21** |
| 20 会话 | → **16** |
| 21 多模态 | → **18** |
| 22 Skills | → **19** |
| 23/24 写作 | → **14** |
| 25 压缩 | → **20** |
| 27–31 RAG | → **15** |

---

## 相关

- 仓库总览：[../README.md](../README.md)
