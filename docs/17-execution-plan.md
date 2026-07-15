# 17 — 基于系统问答的执行方案

> **来源**：[16-agent-system-qa.md](16-agent-system-qa.md) 附录 A（安全化后的改进项）+ 速率红线 R1–R5。  
> **性质**：可排期的实施计划；**本文本身不改代码**，落地时按 Phase 拆 PR。  
> **产品焦点**：继续服务 [Q0](16-agent-system-qa.md#q0-agent-的落地场景是什么是否真的有用) 的两条主场景——智能写作 + 沙箱 Agent；不以万档企业库、多租户 SaaS 为当前主目标。  
> **非目标（全程否决）**：固定 pipeline；子 Agent 整包 messages 共享；peer 总线；每轮预注入向量/多表 join；Turn 同步末强制 verify/judge；LLM 每问路由；强制 plan gate。

---

## 0. 执行原则（继承自 16）

| # | 原则 | 验收含义 |
|---|------|----------|
| R1 | 不挡 `turn.accepted` | 新逻辑不得推迟 TTFB |
| R2 | 首 token 前不加模型调用 | 不新增「为正确而再问一轮」的同步 LLM |
| R3 | 热路径同步 CPU ≤ 毫秒级 | schema / 正则 / 集合比对 OK；重 tokenizer / cross-encoder 默认不进热路径 |
| R4 | 重活异步 / 离线 / 抽样 / 用户触发 | 索引、评分、核查不上用户等待 |
| R5 | 可测才合并 | 每 Phase 至少挂一条单测或 golden；🟡 项必须有延迟相关断言或手工 SLO 对照 |

**默认合并策略**：先全绿 🟢；🟡 带超时/降级；不引入任何未改写的 🔴。

**验收总闸**：

```bash
make runtime-test
make eval-all          # stub 全绿
# Phase 含检索时追加：
make eval-retrieval
```

---

## 1. 总览：四段冲刺

| 冲刺 | 主题 | 覆盖附录项 | 预期体感 | 建议工期（单人） |
|------|------|------------|----------|------------------|
| **S0** | 主路径纠错与可观测（净提速） | A1 A2 A3 A14 | 少空转、假参数更快失败、引用可追踪 | **代码已落地（2026-07）**；合入后跑本表出口清单 |
| **S1** | 写作/Agent 引导与委派卫生 | A6 A7 A8 | 规划更清楚、委派更省 token；**不增加默认轮次** | **代码已落地（2026-07）** |
| **S2** | 检索热路径去同步 + 隐私硬化 | A9 A15 A16（A12 仅确认默认） | 搜索不卡索引；出站更可控 | **代码已落地（2026-07）**；合入前跑 retrieval/eval |
| **S3** | 扩库与深化（按需启动） | A10 A11；按需 A4 A5 A13 A17–A21 | 千～万档资料；质量分离线 | 视目标 1–3 周 |

依赖关系：

```text
S0（A1 先于 A2/A3）
  └─→ S1（只动 prompt / Turn 尾 / delegate，无新慢路径）
  └─→ S2（A9 是扩库前置；与 S1 可部分并行）
        └─→ S3（无 A9 完成禁止开 A10/A11）
```

---

## 2. S0 — 主路径纠错与可观测

**目标**：工具假参数、写作假引用、工具误用不可见、模型 egress 失控——四件事用确定性手段修掉，且交互变快或不变慢。

### S0.1 A1 — 工具参数 Schema 校验门（P0）

| 项 | 内容 |
|----|------|
| **改哪里** | `services/runtime/app/context/engine.py` `ToolExecutor.run`；必要时抽出 `tools/validate.py` |
| **做什么** | 调 `handler` 前对 `arguments` 做 `jsonschema`（Draft 2020-12）校验；失败返回 `{"error":"invalid_arguments","missing":[],"details":[]}`，`is_error=True` 回灌，**不调 handler** |
| **依赖** | `packages/contracts` 已有 jsonschema 能力，复用即可 |
| **单测** | 缺 required / 类型错 / 未知字段（若 schema 限制）→ 结构化错误；合法参数仍通 |
| **Golden** | 新增或扩展 shared/agent：mock 一次坏参数 → 出现 error tool_result → Turn 仍可继续或优雅收束（不 hang） |
| **速率** | 🟢 微秒～毫秒；期望减少「炸一轮再改」 |
| **完成标准** | runtime-test 绿；坏参数不再以生 `TypeError` 字符串为主通道 |

### S0.2 A2 — 引用 ∈ evidence + unverified 标记（P0）

| 项 | 内容 |
|----|------|
| **改哪里** | `agent_engine.py`（维护本 Turn `citation_id` 集合）；`draft_section` / `export_document` 落盘前比对；可选新事件 `citations.reported` |
| **做什么** | Turn 内凡 `search_sources`/`check_citation` 命中写入 evidence set；正文/`[cite:…]` 出现不在集合内的 id → **不阻断流式输出**，标记 `unverified` 进事件或 tool_result 附注 |
| **禁止** | 为校验再调一轮模型；阻断 `draft_section` 导致用户看不到稿 |
| **单测** | 有 hit 再 cite → 干净；无 hit 却 cite → unverified；export 带齐 section_ids 行为不变 |
| **速率** | 🟢 集合比对 |
| **完成标准** | writing 相关 golden 不回归；新增至少 1 条「假引用被标记」用例 |

### S0.3 A3 — 工具误用 telemetry（P0）

| 项 | 内容 |
|----|------|
| **改哪里** | 日志字段增强（`tool.completed` 已有 status）；可选 `observability/metrics.py` 计数器；离线脚本或 eval 报告聚合 |
| **做什么** | 统计：schema 校验失败次数、同 Turn 重复只读调用（`_cached`）、`search_sources` 超预算 |
| **禁止** | 同步发外部分析系统挡热路径 |
| **完成标准** | `make eval-all` 后报告或日志可筛出上述三类计数 |

### S0.4 A14 — Egress allowlist（P0）

| 项 | 内容 |
|----|------|
| **改哪里** | `model/gateway.py` 或 `model/factory.py` / `config.py` 出站前 |
| **做什么** | 仅允许 DB/配置中已登记的 model `base_url`；未命中则 fatal（不发送用户内容） |
| **单测** | 白名单命中 / 未命中 |
| **速率** | 🟢 |
| **完成标准** | 任意篡改 base_url 无法带 transcript 出站 |

### S0 冲刺出口

- [x] A1–A3、A14 代码落地（2026-07；见下表路径）
- [ ] `make runtime-test && make eval-all` 全绿（合入前跑）
- [ ] 文档：在 [16 附录 A](16-agent-system-qa.md#附录-a--改进方案速率总表安全化后) 对应行标注「已落地」日期（可选，随 PR）

**S0 落地路径（实现备注）**

| ID | 主要改动 |
|----|----------|
| A1 | `app/tools/validate.py` + `ToolExecutor.run` schema 门；`TOOL_SCHEMA_VALIDATE` |
| A2 | `AgentEngine` evidence set + `unverified_citations` 注解；`CITATION_VERIFY_ENABLED` |
| A3 | `record_tool_misuse`（invalid_arguments / cached_repeat / search_budget / unverified_citation） |
| A14 | `app/model/egress.py` + `create_gateway`；`MODEL_EGRESS_ENFORCE` / `MODEL_EGRESS_ALLOWLIST` |

---

## 3. S1 — 写作/Agent 引导与委派卫生

**目标**：更好规划与更省 delegate token；**默认路径不增加模型轮次**。

### S1.1 A6 — Plan 引导（提示词 + Intake hint）

| 项 | 内容 |
|----|------|
| **改哪里** | `scenarios/agent/system.md`（及必要时 writing）；`controller/input_compiler.py` 或 runtime_context 拼装 |
| **做什么** | system 增加：「≥3 个独立目标时建议先 `update_plan`」；Intake 用**规则**检测多目标关键词时，往 `runtime_context` **塞一行 hint**（模型自决） |
| **禁止** | 强制必须先 plan 再允许其它工具（原 🔴） |
| **速率** | 🟢 |
| **完成标准** | 无新默认 loop 步；stub golden 不因 hint 变长而超时 |

### S1.2 A7 — Plan–execute 回填 open_items

| 项 | 内容 |
|----|------|
| **改哪里** | Turn 终态后路径（`turn_controller` 收尾或 projection 旁路）；`session_context` / `context_summary` |
| **做什么** | 扫描最后一次 `turn.plan` 中 `pending`/`in_progress` → 写入 summary.`open_items`；下一 Turn 经既有 summary/transcript 注入可见 |
| **禁止** | 因有 pending 而拒绝 `completed`（可观测即可） |
| **速率** | 🟢 Turn 尾、不挡 SSE 终态事件顺序中的用户感知结束 |
| **完成标准** | 单测：有 pending plan → summary 含 open_items |

### S1.3 A8 — Delegate 传 path 指针 / hot_files

| 项 | 内容 |
|----|------|
| **改哪里** | `delegate` 工具 schema/description；`delegate_runner.py`；可选 `delegate_context` 注入 hot_files |
| **做什么** | description 引导传 `paths`/`context_refs`；runtime 把主会话 hot_files（≤12）拼进子 system；**禁止**主 messages dump |
| **速率** | 🟢 通常减 token |
| **完成标准** | 既有 delegate golden（writing.06 / agent.05）仍绿；可选断言 context 不含超长正文 |

### S1 冲刺出口

- [x] A6–A8 落地（2026-07；各自独立 commit）
- [ ] `make eval-all` 绿（合入前跑）

**S1 落地路径**

| ID | Commit 主题 |
|----|-------------|
| A6 | Suggest update_plan for multi-goal turns via Intake hints |
| A7 | Backfill pending plan items into session context after turns |
| A8 | Pass path pointers and hot files into delegate sub-agents |

---

## 4. S2 — 检索热路径去同步 + 隐私硬化

**目标**：`search_sources` **只查不建**；内容级隐私用正则而非 LLM。

### S2.1 A9 — 索引出热路径（扩库前置，P0 级于扩库）

| 项 | 内容 |
|----|------|
| **改哪里** | `tools/core/tools.py` `search_sources`；`settings.index_via_worker` 默认策略；upload/sync 命令 → outbox（`deploy/compose/queue.yml` 已有则对齐） |
| **做什么** | 默认 `search_sources` **永不**在请求内 `store.sync()` 全量重建；索引落后返回旧 hit + `index_lag`/`hint`；上传走 worker |
| **兼容** | 开发小库可保留显式「Rebuild index」管理入口（用户触发，非热路径） |
| **Golden** | `eval-retrieval` / writing.07：检索成功且不依赖同步 rebuild 卡超时 |
| **速率** | 🟢 **纯减负**——消灭首查付索引账 |
| **完成标准** | 文档源变更后，查询延迟不随「未索引完」线性爆炸；worker 路径有集成测或 eval-queue |

### S2.2 A15 — 预编译正则 PII 脱敏

| 项 | 内容 |
|----|------|
| **改哪里** | 出站前 middleware（gateway 组 messages 时）；structlog processor |
| **做什么** | 手机/身份证/常见密钥模式预编译正则；仅处理**增量**或出站 payload；开关默认开、可关 |
| **禁止** | LLM 判别脱敏 |
| **速率** | 🟢 |
| **完成标准** | 单测敏感串被替换；正常中文写作正文无误伤（或误伤可配置白名单） |

### S2.3 A16 — 写入路径 secret 扫描

| 项 | 内容 |
|----|------|
| **改哪里** | `write_file` / `export_document` 前 |
| **做什么** | 同步扫描硬预算 **50ms**，超时放行并打日志；异步补扫可告警 |
| **速率** | 🟢～🟡 |
| **完成标准** | 含明显 `AKIA…`/私钥头的写入被拒或告警；正常文稿 50ms 内完成 |

### S2.4 A12 — 确认 rerank 默认姿态

| 项 | 内容 |
|----|------|
| **改哪里** | `settings` + `retrieval/rerank.py` 文档/默认值 |
| **做什么** | **文档与配置双确认**：lexical rerank 可默认开；cross-encoder **默认关**；若实验开启必须 `top≤20` + ≤50ms 预算 + 超时跳过 |
| **完成标准** | `.env.example` / 设置注释与 [16 Q8/Q13](16-agent-system-qa.md) 一致 |

### S2 冲刺出口

- [x] A9 为默认行为；A15/A16 可开关上线（2026-07；各自独立 commit）
- [x] A12 rerank 默认姿态确认（lexical 开 / CE 关 / 池≤20 / 50ms）
- [ ] `make eval-retrieval`（及 queue 若动 worker）绿（合入前跑）

**S2 落地路径**

| ID | Commit 主题 |
|----|-------------|
| A9 | Keep source search off the index rebuild hot path |
| A15 | Redact PII and secrets on model egress and structured logs |
| A16 | Block write-path secrets within a fixed 50ms scan budget |
| A12 | Confirm lexical-default / CE-off rerank posture |

---

## 5. S3 — 按需深化（不自动开工）

仅当产品信号出现时启动对应史诗；每项独立里程碑。

| 触发信号 | 启动项 | 备注 |
|----------|--------|------|
| sources 明显 > 千档或查询变慢 | **A10** pgvector/Qdrant + ANN；**A11** 两级召回（并行+超时降级） | **无 A9 完成禁止开始** |
| 需要对外质量故事 | **A5** 离线 rubric（CI/夜间 ≤5% 抽样） | 永不挂 Turn 同步尾 |
| 用户要「事实核查」按钮 | **A4** `/verify` + 夜间抽样 | 非默认 loop |
| 记忆/偏好干扰资料 RAG | **A13** remember/recall 分仓按需工具 | 禁每轮盲召 |
| compact 成本偏高 | **A17** 小模型分流 + 独立超时 + 降级确定性摘要 | 不挡 TTFB |
| 首 token 仍紧 | **A18** 打字期预热；**A19** 阶段化 ToolScope | 规则切换，无 LLM 判断 |
| 真·多表业务库 | **A20** 蓝图立项（规则路由+通道超时+ACL） | 新工具，不加图节点 |
| 写作交付争议增多 | **A21** critique 提示词 + 按钮 + 夜间批量 | 同 A4 纪律 |

S3 每项开工前补一页「迷你设计」：热路径触点、超时、降级、golden ID——再写代码。

---

## 6. 任务拆解看板（建议 ticket 粒度）

```text
S0
  [ ] T-A1  ToolExecutor jsonschema gate + unit tests
  [ ] T-A2  Turn evidence set + unverified citations + golden
  [ ] T-A3  Misuse counters / eval report fields
  [ ] T-A14 Model egress allowlist

S1
  [ ] T-A6  agent(/writing) system + Intake plan hint
  [ ] T-A7  open_items backfill on turn terminal
  [ ] T-A8  delegate context_refs + hot_files inject

S2
  [x] T-A9  search_sources never sync-rebuild; worker default
  [x] T-A15 Outbound + log regex redaction
  [x] T-A16 Write-path secret scan with 50ms budget
  [x] T-A12 Confirm rerank defaults in settings + .env.example

S3（门铃）
  [ ] Epic-RAG-scale   A10/A11 after A9
  [ ] Epic-offline-qa  A4/A5/A21
  [ ] Epic-memory      A13
  [ ] Epic-speed-tune  A17/A18/A19
  [ ] Epic-multitable  A20 design-first
```

---

## 7. 风险与回滚

| 风险 | 缓解 |
|------|------|
| Schema 过严导致合法工具调用翻车 | 先对核心工具开校验；`additionalProperties` 策略按工具宽严分层；feature flag `TOOL_SCHEMA_VALIDATE=1` |
| 引用标记误杀创作自由 | unverified **只标记不阻断**；UI 弱提示 |
| 索引纯异步导致「刚上传搜不到」 | 明确 `index_lag` hint；管理面 Rebuild；上传后短轮询状态（已有 sources 状态能力则复用） |
| 脱敏误伤人名/书名 | 模式收紧；可按场景关 writing 的部分规则 |
| S3 提前开 ANN | 门禁：A9 checklist 签字前不准合并 A10 |

回滚：每项独立 flag 或短小 PR；优先回滚配置默认值而非撕协议。

---

## 8. 成功定义（对照 Q0）

冲刺全部完成后，仍以北极星衡量，而不是「附录勾完」：

1. **写作**：假引用可观测；检索不因建索引卡顿；diff/approve 路径不变慢。  
2. **Agent**：假参数秒级结构化失败；egress 不串网；delegate 更干净。  
3. **证明**：既有 golden 全绿；S0/S2 至少各 +1～2 条专用用例。  
4. **速率**：TTFB / 首 token / Cancel 门禁不回退；任何 🟡 改动有超时与降级说明。

---

## 9. 关联

| 文档 | 关系 |
|------|------|
| [16-agent-system-qa.md](16-agent-system-qa.md) | 问题与**安全化方案**母本 |
| [14-model-harness.md](14-model-harness.md) | 热路径纪律与 AH 分期 |
| [11-product-experience.md](11-product-experience.md) | SLO 数值权威 |
| [12-eval-and-golden-turns.md](12-eval-and-golden-turns.md) | 验收与 golden 写法 |
| [06-tools-and-context.md](06-tools-and-context.md) | 工具 / Context 契约 |
