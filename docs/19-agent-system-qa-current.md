# 19 — Agent 系统问答（现状重答 · 2026-07）

> **定位**：在 [16](16-agent-system-qa.md) 同一套 Q0–Q20 上，按 **S0–S3 落地后的真实代码与自用验证** 重新作答。  
> **与 16 的关系**：16 是「问题 + 安全化方案设计」；本文是「方案落地之后的事实对照」。执行细节仍见 [17](17-execution-plan.md)，A20 蓝图见 [18](18-a20-multitable-recall.md)。  
> **口径**：2026-07；写作主场景已实测：`search_sources(hybrid)` → 落稿 → `/verify`（含中文 `[cite:亮剑]`）通过。  
> **速率红线**：仍继承 16 的 R1–R5，本文不再重复论证，只写「现在是什么样」。

---

## 图例

| 标记 | 含义（相对 16） |
|------|----------------|
| ✅ | 主路径机制已落地，可自用 / 可观测 |
| 🔸 | 主路径可用，边界或规模仍受限 |
| ❌ | 企业级/完整后端尚未接上（可能有 stub） |

---

## 总览（相对 16 的状态变化）

| # | 问题 | 16 时 | **现在** | 变了什么 |
|---|------|-------|----------|----------|
| 0 | 落地场景 | ✅ | ✅ | 定位不变；实测写作闭环更完整 |
| 1 | 幻觉 / 乱调工具 | 🔸 | 🔸→趋✅ | Schema 门、引用 evidence、`/verify` |
| 2 | 评价指标 | ✅ | ✅ | + 离线 `eval-rubric` |
| 3 | 任务规划 | 🔸 | 🔸 | Intake plan hint + open_items 回填 |
| 4 | 子 Agent 上下文 | ✅ | ✅ | `context_refs` / hot_files |
| 5 | ReAct | ✅ | ✅ | 不变 |
| 6 | 捏造工具参数 | 🔸 | ✅ | JSON Schema 预校验 |
| 7 | 多 Agent 模式 | 🔸 | 🔸 | + 按需 fact_checker / `/verify` / 夜间 batch |
| 8 | 万档 RAG | ❌ | 🔸 | 索引出热路径 + 可选 pgvector ANN + 两级召回 |
| 9 | Context/Prompt/Harness | ✅ | ✅ | + compact 小模型分流、阶段化 ToolScope |
| 10 | Tool / Memory | 🔸 | 🔸→趋✅ | `remember`/`recall` 按需工具 |
| 11 | 隐私 | 🔸 | ✅～🔸 | egress + PII 正则 + secret 扫描（无多租户） |
| 12 | 加速推理 | 🔸 | 🔸 | + 打字预热、compact 分流、晚步缩工具 |
| 13 | 混合召回 / chunk | ✅ | ✅ | lexical 默认；CE 默认关 |
| 14 | Harness | ✅ | ✅ | 六面更厚，仍守「厚不挡快」 |
| 15 | 多表召回 | ❌ | 🔸 | stub + 蓝图；无真实业务表 |
| 16 | 动/静 prompt | ✅ | ✅ | 不变 |
| 17 | 记忆是否召回 | 🔸 | 🔸 | 模型调 `recall`；禁每轮盲召 |
| 18 | 静/动态长记 | 🔸 | 🔸 | 分层仍在；显式记忆仓已接上 |
| 19 | 端到端链路 | ✅ | ✅ | 链路同构，节点更全 |
| 20 | Function calling | ✅ | ✅ | 执行前 schema；晚步可缩 tools JSON |

---

## Q0. Agent 的落地场景是什么？是否真的有用？

**结论：✅ 仍以智能写作为主、沙箱 Agent 为辅；自用闭环（检索 → 起草 → 引用检查）已在本机验证。**

| 场景 | 事实 |
|------|------|
| `writing` | `search_sources` / 素材卡 pin / `draft_section` / `export_document` / `/verify`、「事实核查」按钮 |
| `agent` | 全工具面 + 审批写路径；另有 `remember`/`recall`/`search_records`(stub) |
| 有用判据 | 跟手、可控、有据、可回归 —— 与 [11](11-product-experience.md) 北极星一致 |

**诚实边界**：内容质量仍依赖 live 模型；万档企业 ACL / 多租户未做；`search_records` 无真实表。

---

## Q1. Agent 是否经常幻觉或乱调工具？如何缓解？

**结论：🔸 幻觉不能消灭；入口与证据链已明显加厚。**

| 层 | 现在有什么 |
|----|------------|
| 缩小空间 | ToolScope 白名单；写作无 `run_command`；晚步可再砍 search/delegate（A19） |
| 入口失败 | **JSON Schema 校验**（A1）→ `invalid_arguments`，不进 handler |
| 证据链 | Turn 内 evidence 集合；文中引用不在集合 → `unverified` 标记不阻断（A2） |
| 用户核对 | `/verify` 确定性扫草稿引用（含中文 id）；报告落 `.agent/verify-reports/`（A4） |
| 可观测 | `record_tool_misuse`（A3） |

**仍依赖**：模型是否遵守「零命中不编 cite」——机制能标、能查，不能从概率上抹掉胡说。

---

## Q2. 如何设计评价 Agent 系统好坏的指标体系？

**结论：✅ 五层体系仍成立；质量分坚持离线。**

| 层 | 现状 |
|----|------|
| 行为契约 | golden / contracts |
| 体验 SLO | TTFB / 首 token / Cancel（[11](11-product-experience.md)） |
| 工具健康 | misuse 计数、schema 失败 |
| 检索 | `eval-retrieval`；hybrid + index_lag |
| 内容质量 | **`make eval-rubric`** ≤5% 抽样启发式（A5）；**永不挂 Turn 尾** |

---

## Q3. 主 Agent 任务规划怎么保证拆解合理？

**结论：🔸 规划仍是可选工具，不是强制阶段。**

- 多目标时 Intake 注入 **一行 `plan_hint`**，引导可选 `update_plan`（A6）
- Turn 结束把 pending plan 回填 session `open_items`（A7）
- **禁止**强制 plan gate（否则每任务多一轮税）

实测写作回合里模型会按需 `update_plan`，但简单任务可不调。

---

## Q4. 子 Agent 之间的上下文怎么传递？

**结论：✅ task + 指针进、summary 出；整包 messages 共享仍否决。**

- `delegate(context_refs, paths)` + 父侧 `hot_files`（A8）
- 子 Agent 工具面按类型收窄；depth ≤2
- 写作可按需 `fact_checker`，**默认不挂交付末尾 critique 链**（A21）

---

## Q5. 是否使用 ReAct？优缺点？

**结论：✅ 主循环仍是 while + function calling ≡ ReAct。**

优点：灵活、可打断、过程可见。缺点：步数/工具误用风险 —— 用 budget、schema、缓存、watchdog、阶段化 ToolScope 抑制。

---

## Q6. 大模型捏造工具参数怎么处理？

**结论：✅ 假参数在 handler 前被确定性拦下。**

1. `ToolExecutor` → `validate_tool_arguments`（jsonschema）  
2. 失败结构化 `invalid_arguments` 回灌  
3. 开关：`TOOL_SCHEMA_VALIDATE`（默认 true）

这是相对 16「🔸」变化最大的一题之一。

---

## Q7. 多 Agent 协作常见模式有哪些？

**结论：🔸 本仓库只认真做 supervisor–delegate。**

| 模式 | 本项目 |
|------|--------|
| Single agent + tools | ✅ 主形态 |
| Supervisor–delegate | ✅ `delegate` |
| Pipeline / peer bus | ❌ 否决 |
| Critique | 转提示词 + **事实核查按钮** + `critique.batch`/`verify.sample`（A21/A4） |

---

## Q8. 一万个长文档构建 RAG 知识库，怎么解决？

**结论：🔸 小库～千档路径已齐；「企业万档 + ACL」未完。扩库前置已做完。**

| 环节 | 现在 |
|------|------|
| 热路径 | `search_sources` **永不**同步全量 `sync()`；`INDEX_VIA_WORKER=true`（A9） |
| 存储 | 默认 JSON；**可选** `RETRIEVAL_BACKEND=pgvector` + HNSW（A10） |
| 召回 | hybrid BM25+向量+RRF；**两级 doc→chunk 并行，超时降级 chunk-only**（A11） |
| Rerank | lexical 默认可开；cross-encoder **默认关**（A12） |

**仍缺**：多租户 ACL、Elastic 级 BM25、离线语义再切分流水线。写作小库（亮剑等）在 pgvector 下已验证 hybrid 有 hit。

---

## Q9. Context / Prompt / Harness Engineering？

**结论：✅ 三层仍清晰，且都更厚。**

| 层 | 现实现状增量 |
|----|--------------|
| Context | assemble + autocompact；可选 **`COMPACT_MODEL_*`**（A17）；失败确定性摘要 |
| Prompt | writing/agent system；plan hint；critique 按需提示 |
| Harness | Intake → Context → Tools → Model → Guard → Proof；Guard 含 egress/脱敏/secret |

---

## Q10. Tool 与 Memory？长短时？

**结论：🔸→趋✅ 工具协议完整；记忆仓已有按需工具，但仍靠模型选择是否召回。**

| 寿命 | 机制 |
|------|------|
| 极短 | 当前 Turn messages + 截断 |
| 短 | session transcript / summary / open_items |
| 中 | workspace 文件、revisions |
| 外知识 | `sources/` + RAG（模型调 `search_sources`） |
| 偏好 | **`remember` / `recall`**，独立 JSON 仓，禁与 sources 混用（A13） |

**铁律不变**：不每轮预灌向量或盲召记忆。

---

## Q11. 隐私消息怎么防止泄漏？

**结论：✅～🔸 内容级防护已上；多租户仍无。**

| 面 | 现状 |
|----|------|
| 沙箱路径 / 内网 token / key 加密 | 仍在 |
| **Egress allowlist** | live `base_url` fail-closed（A14） |
| **PII 正则脱敏** | 出站 messages + structlog（A15）；禁 LLM 脱敏 |
| **Secret 扫描** | `write_file`/`export_document`，50ms 预算（A16） |
| 多租户 / at-rest 字段级 | 未做 |

---

## Q12. 保证效果的前提下怎么加速推理？

**结论：🔸 旧杠杆仍在；新增不挡 TTFB 的加速项。**

| 新增 | 作用 |
|------|------|
| A18 打字 debounce → warmup | 预热 embedder/index，不进 Turn |
| A17 compact 小模型 | 摘要成本可下沉 |
| A19 晚步缩 tools | 交付后少带 search/delegate schema |
| A9 搜索不建索引 | 消「首查付索引账」 |

纪律不变：加厚必须能被取消、超时、降级抵消。

---

## Q13. RAG 为什么混合召回？Chunk 怎么切？

**结论：✅ 设计未改，实现与开关已对齐文档姿态。**

- 混合：防专名盲区；向量不可用 → keyword 兜底  
- Chunk：Markdown 标题优先，超长 400/80  
- Tool-mediated：检索只经工具进入，不每轮预灌  
- 引用：evidence + `/verify`；CJK `cite:` 可解析  

---

## Q14. Harness 讲解？

**结论：✅ Harness = 包住模型的运行时厚度；AH1–AH4 核心仍在，S0–S3 补了 Guard/Proof 侧。**

六面速记：Intake / Context / Tools / Model / Guard / Proof。铁律：**厚不许牺牲快**。

---

## Q15. 多数据表下怎么设计稳定召回？

**结论：🔸 蓝图 + stub 已落地；真实业务通道未接。**

- 文档：[18](18-a20-multitable-recall.md)  
- 工具：`search_records` → `status=unimplemented`，通道并行脚手架 ≤300ms（A20）  
- **下一步**（产品触发）：接一张带 ACL 的表，仍走同一 tool，不加图节点  

---

## Q16. 动态 Prompt 与静态 Prompt？

**结论：✅**

| 类型 | 例子 |
|------|------|
| 静态 | `scenarios/*/system.md`、工具描述 |
| 动态 | ContextEnvelope、plan_hint、cards pin、runtime_context |

原则：能静不动；动态可截断、可预算。

---

## Q17. 模型如何决定长期记忆是否需要召回？

**结论：🔸 决策权在模型 + ToolScope；系统不每轮自动召回。**

- 资料 → `search_sources`  
- 偏好/约定 → **`recall(namespace=…)`**  
- Intake 可给弱提示，但 **禁止** 每轮向量预注入记忆（🔴）

---

## Q18. 为什么要静态 / 动态长期记忆？

**结论：🔸 分工仍按「钉子 vs 滚窗」。**

| | 静态倾向 | 动态倾向 |
|--|----------|----------|
| 内容 | 角色卡、风格卡、硬规则 | 会话摘要、open_items、remember 笔记 |
| 注入 | pin / 高优先级前缀 | 工具召回或滚动压缩 |

静态保一致性；动态保上下文不爆窗。

---

## Q19. 整个链路怎么运转？

**结论：✅ 主链路未改形态，节点更完备。**

```text
Web 发消息
  → api 建 Turn / Run
  → runtime turn.accepted（快）
  → Intake（slash：/help /compact /verify 可短路）
  → while step:
        assemble Context +（阶段化）Tools
        model stream + FC
        ToolExecutor（schema → handler → 审批/截断）
  → turn.completed → 投影 / summary / 可选 open_items 回填
  → SSE 推 UI
```

旁路：索引 worker、warmup、verify.sample / critique.batch、eval-rubric —— **都不在首 token 前。**

---

## Q20. Function Calling 怎么运作？

**结论：✅**

1. Profile → ToolScope →（A19 可再缩）tools JSON  
2. Provider FC / tool_calls  
3. **Schema 校验**  
4. 审批门（写/exec）  
5. handler；搜索只查不建；写路径 secret 扫  
6. tool_result 回灌；引用进 evidence / unverified  

对应「模型只出意图，Runtime 出事实」。

---

## 附录 A — 相对 16 的「方案账本」落地摘要

全部 A1–A21 的最小切片均已提交（见 [17](17-execution-plan.md)）。使用上注意：

| 项 | 默认 / 启用注意 |
|----|-----------------|
| A10 pgvector | `.env`：`RETRIEVAL_BACKEND=pgvector`；需 `vector` 扩展 |
| A5 rubric | `make eval-rubric`；启发式，非 LLM judge |
| A20 records | stub；接表前看 [18](18-a20-multitable-recall.md) |
| A4/A21 verify | `/verify` 或 UI「事实核查」；事件 payload 仅 `summary` |

---

## 附录 B — 自用冒烟清单（写作）

1. 写作场景：「根据资料写一段张白鹿出场介绍并带引用」  
2. 时间线出现 `search_sources(hybrid)` 有 hit、`draft_section`、`check_citation`  
3. 发送 `/verify` → `checked≥1`，中文 cite 可计  

---

## 附录 C — 一句话（现状版）

| # | 一句话 |
|---|--------|
| 0 | 落地仍是写作 + 沙箱 Agent；自用闭环已跑通。 |
| 1 | 幻觉靠入口与证据链压，不靠「再问一轮模型」。 |
| 2 | 行为契约 + SLO 在线证明；质量分永远离线。 |
| 3 | 规划可选；hint 与 open_items，不加强制门。 |
| 4 | 子 Agent 传指针不传整包历史。 |
| 5 | while+FC 就是本仓库的 ReAct。 |
| 6 | 假参数：schema 门秒级結構化失败。 |
| 7 | 只做 supervisor–delegate；critique 用户触发/离线。 |
| 8 | 扩库：先只查不建，再 ANN；企业 ACL 仍后置。 |
| 9 | Context 管看见什么；Prompt 管话术；Harness 管厚度。 |
| 10 | 短记截断保速；长记指针+按需工具。 |
| 11 | 结构边界 + egress/脱敏/secret；无多租户。 |
| 12 | 加速靠超时、缓存、预热、缩工具，不挡受理。 |
| 13 | 混合召回 + 标题切块 + Tool-mediated。 |
| 14 | Harness 六面；厚不挡快。 |
| 15 | 多表：规则路由 stub；真表未接。 |
| 16 | 能静不动；动态可截断。 |
| 17 | 记不记得住由模型调工具决定，系统不盲召。 |
| 18 | 静态钉规则；动态滚会话。 |
| 19 | 受理快→逐步 FC→投影；重活旁路。 |
| 20 | FC：意图在模型，校验与副作用在 Runtime。 |

---

## 关联

| 文档 | 用途 |
|------|------|
| [16](16-agent-system-qa.md) | 原问答 + 方案设计过程（含速率改写叙事） |
| [17](17-execution-plan.md) | 冲刺清单与启用/重启 |
| [18](18-a20-multitable-recall.md) | 多表召回蓝图 |
| [14](14-model-harness.md) | Harness 总纲 |
| [11](11-product-experience.md) | SLO 数值权威 |
