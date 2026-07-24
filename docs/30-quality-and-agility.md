# 30 — 质量与灵敏度(代码 × 写作)

> **状态**:执行中（2026-07-24）— **CQ1 ✅ · CQ2 ✅**；其余票按排期。落地后回写本文状态；写作 WN 落地后同步 [14](14-writing-quality.md)。
> **本模块维护**:代码生成质量(**CQ**)· Agent 灵敏度(**AQ**)· 写作质量/灵敏度下一刀(**WN**)。
> **关联**:速率红线 → [13](13-rate-redlines.md) R1–R5(所有票的前置约束);Harness 总纲 → [12](12-model-harness.md)(§5.1 下一刀:WT5 / 变短≈压缩 / Proof);写作正文 → [14](14-writing-quality.md) · [23](23-writing-work-model.md) · [24](24-writing-token-economy.md);RAG → [15](15-rag-and-sources.md);Eval → [11](11-eval-and-golden-turns.md)。

---

## 0. 票状态

| 票 | 主题 | 状态 |
|----|------|------|
| **CQ1** | 加厚 `agent/system.md` | ✅ |
| **CQ2** | 工具描述 hygiene | ✅ |
| **CQ3** | agent 质量 golden + rubric | ✅ |
| **CQ4** | 代码感知检索 | ⏳ |
| **AQ1** | agent cache 稳定前缀 | ✅ |
| **AQ2** | agent slash 展开 | ⏳ |
| **AQ3** | 灵敏度否决守线 | 守线（无单独实现） |
| **WN1** | 连续性卡片异步提炼 | ⏳ |
| **WN2** | 离线 rubric 维度扩展 | ✅ |
| **WN3** | WT5 写作 cache 落地 | ✅ |

```bash
cd services/runtime && python3 -m pytest \
  tests/test_agent_prefix_stability.py \
  tests/test_bootstrap_registry.py \
  tests/test_eval_rubric.py \
  tests/test_gateway_stub.py \
  tests/test_writing_prefix_stability.py \
  tests/test_plan_phase.py -q
# golden: eval/golden/agent/10_patch_then_lints.yaml
```

落地索引：`scenarios/agent/system.md` · `tools/bootstrap.py` · `writing/cards.py`（stable/volatile 分家）· `context/engine.py`（`[writing_context]` 后置）· `plan_phase.plan_phase_block` · `PendingTurn.volatile_context` · `offline/rubric.py` · `eval/golden/agent/10_patch_then_lints.yaml` · stub `agent.10`。

---

## 0. 原则与边界

两条硬约束,对应所有票的准入门槛:

1. **不影响交互逻辑**:不改 `AgentEngine` while 语义、事件契约、审批门、Plan 相位。策略只进 prompt / 工具描述 / 离线评测 / 异步任务。
2. **不影响交互速率**:服从 [13](13-rate-redlines.md) R1–R5——不挡 `turn.accepted`、首 token 前不加模型调用、热路径同步 CPU 毫秒级、重活异步、可测才合并。

**杠杆排序(对齐成熟产品共识)**:system prompt / 工具描述 > 确定性校验工具闭环 > 检索质量 > 评测门禁。**不加节点、不加 router、不加默认 judge**——质量问题用 harness 策略层解决,不用编排解决(同 [12](12-model-harness.md) §3 结论)。

**核心不对称(本文动机)**:写作侧已有完整质量体系(14 WQ0–WQ4 ✅、23、24),代码侧没有对应模块;[`agent/system.md`](../services/runtime/app/scenarios/agent/system.md) 仅 25 行,而 [`writing/system.md`](../services/runtime/app/scenarios/writing/system.md) 有 182 行(含反模式清单、检索决策树、交付流程)。**CQ 系列 = 把写作侧已验证的方法论移植到代码场景**,不发明新机制。

---

## 1. 市面产品对标

> 结论分三档:**已对齐**(不重做)· **缺失**(开票)· **有意否决**(有据,不翻案)。

### 1.1 代码侧(Cursor · Claude Code · Devin · Codex)

| 机制 | 成功产品做法 | 我们现状 | 结论 |
|------|--------------|----------|------|
| 富 system prompt(验证纪律 / 最小改动 / 注释纪律 / 失败恢复) | Cursor、Claude Code 的 system prompt 都是数百行硬规则 | `agent/system.md` 仅 25 行,只有探索与计划规则 | **缺失 → CQ1** |
| 编辑 → lint/测试反馈闭环 | Cursor 编辑后自动读 lints,宣称完成前跑测试 | `read_lints` / `run_tests` 工具已有,但 prompt 未要求「edit 后必查」 | **缺失 → CQ1** |
| 工具描述即 prompt(何时用 / 何时不用 / 参数示例) | Claude Code 每个工具描述都是小型规范文 | `tools/bootstrap.py` 多为一行式;仍有「simulated in Phase 1」过时文案 | **缺失 → CQ2** |
| 交付质量可测(补丁可应用、测试通过) | Devin / Codex 以「测试跑通」为完成定义 | golden `agent/01–09` 只断言协议行为(patch 流、审批、取消),无质量维度 | **缺失 → CQ3** |
| 代码感知检索(符号 / 函数边界) | Cursor 语义检索按代码结构切块 | `retrieval/chunking.py` 只有 Markdown 标题 / 表格切块 | **缺失 → CQ4** |
| 只读工具并行 | Cursor 单步批量并发读 | **AH3c ✅**([12](12-model-harness.md)) | 已对齐 |
| subagent 委派(explore / shell) | Cursor Task 工具 | `delegate` ✅(ADR-007) | 已对齐 |
| 计划-执行分相 | Devin 计划先行、步骤可见 | Plan 模式 ✅([25](25-writing-runway.md) · [26](26-plan-suggest-complexity.md)) | 已对齐 |
| 项目记忆 | Claude Code 的 CLAUDE.md 常驻注入 | `remember` / `recall` 按需工具 + project 针脚,**不**每轮预注入 | 已对齐(有意保持按需,R3/R4) |
| 意图预分类 LLM 路由 | 部分产品做,普遍被证明拖慢首响 | ADR-014 已否决 | **有意否决**(R2) |

### 1.2 写作侧(Sudowrite · NotebookLM · Claude Projects)

| 机制 | 成功产品做法 | 我们现状 | 结论 |
|------|--------------|----------|------|
| 角色卡 / 风格卡约束生成 | Sudowrite Story Bible、Character cards | cards pin ✅(WQ0/WQ1) | 已对齐 |
| 连续性资料自动维护 | Sudowrite 从章节自动提炼 Story Bible 条目 | cards 全靠 loop 外人工整理 | **缺失 → WN1** |
| citation-first(答案必须溯源) | NotebookLM 逐句挂 citation | `[cite:]` + `check_citation` ✅ | 已对齐 |
| 稳定前缀 + 项目知识 pin(cache 友好) | Claude Projects 固定前缀跨对话命中 cache | WT5 设计 ✅ 实现 ⏸([12](12-model-harness.md) §5.1.1 · [24](24-writing-token-economy.md) §4.6) | **缺失 → WN3 / AQ1** |
| 质量回归可测 | 头部产品都有离线 eval 集 | `offline/rubric.py` 已有,维度偏少 | **缺失 → WN2** |
| 自动串联 polish pipeline | 部分产品自动多 pass | [14](14-writing-quality.md) 已否决(pass 走廊由用户驱动) | **有意否决** |
| Turn 末强制 judge | 部分产品每轮自评 | 13/14 已否决(多一轮 + 延迟) | **有意否决**(R2) |

---

## 2. 代码生成质量(CQ 系列)

> 全部不碰 loop 逻辑;CQ1/CQ2 纯文案且进稳定前缀,与 cache(AH2/WT5)同向。

### CQ1 — 加厚 `agent/system.md`(对标 Cursor / Claude Code)

现文 25 行只管「探索 / 计划 / 交付 / 边界」。补齐五组硬规则(**只加 prompt,零热路径代价**):

| 组 | 规则要点 | 对标出处 |
|----|----------|----------|
| **验证纪律** | `write_file` / `edit_file` / `propose_patch` 之后**必须** `read_lints` 受影响路径;宣称任务完成前,若工作区有测试则 `run_tests`;引入的新 lint 自己修 | Cursor「introduced linter errors → fix them」 |
| **最小改动** | 精修用 `propose_patch`(唯一 span),禁止为改一处而 `write_file` 整文件重写;不顺手重构、不加任务外抽象 | Claude Code minimal-diff 纪律 |
| **失败恢复** | patch 失败(span 不唯一 / 不匹配)→ 先 `read_file` 重读再重试,禁止盲目重发;同错误连续 2 次 → 换策略而不是重试 | Cursor 错误恢复规则 |
| **注释与风格** | 禁复述性注释(「// 导入模块」类);注释只写非显然意图;遵循目标文件既有风格,不发明新约定 | Cursor / Claude Code 通用条款 |
| **完成定义** | done = 交付物写入 + lint 干净 + (有测试时)测试通过 + 一句话总结改了什么、剩什么;禁止「探索完毕」就收工 | Devin / Codex 自我验证 |

**验收**:`agent/system.md` 有对应条目;prefix 稳定性测试对齐写作侧 `test_writing_prefix_stability.py` 的做法(system 逐字节稳定,服务 AQ1);golden `agent/01–09` 不回归;CQ3 新增质量 golden 通过。

### CQ2 — 工具描述 hygiene(`tools/bootstrap.py`)

工具描述是 prompt 的一部分([12](12-model-harness.md) §3 明确「description 持续 hygiene」是 Tools 面缺口)。按 Anthropic tool-use 最佳实践重写:

- 一行式描述(`write_file`「Create or overwrite a workspace file」、`search_codebase`「Search the codebase for a query string」等)扩为:**何时用 / 何时不用 / 参数含义与示例 / 常见误用**。
- 删除过时文案:`run_tests`「(simulated in Phase 1)」。
- 写 / exec 类工具(`write_file`、`run_command`)描述里写明与 `propose_patch` / `read_file` 的选型边界,减少模型乱选工具的回合浪费(**省回合 = 既提质量又提灵敏度**)。

**验收**:契约快照 / 单测覆盖描述变更;golden 中工具误选类 case(如 `08_glob_stub`)不回归;新增 1–2 个「选对工具」golden。

### CQ3 — agent 质量 golden + 离线 rubric

现有 `eval/golden/agent/01–09` 覆盖协议行为(patch 流、审批、取消、委派),**没有一条断言产物质量**。补两层(全部离线 / CI,R4、R5 合规):

1. **golden 质量断言**:新增 agent golden——补丁可干净 apply、修改行数 ≤ 阈值(diff 最小性)、`read_lints` 零新增、(可执行任务)`run_tests` 通过。
2. **离线 rubric**:复用 `offline/rubric.py` 模式建代码维度——整文件重写率(应低)、edit 后是否跟了 lint 检查、失败重试是否先重读。**仅离线评测,不进热路径,不上 judge 模型。**

**验收**:`make eval-all` 扩展含 agent 质量 case;rubric 单测。CQ1/CQ2 的 prompt 迭代以此为回归护栏。

### CQ4 — 代码感知检索(`search_codebase`)

`retrieval/chunking.py` 现为 Markdown 向(标题 / 表格 / 字符预算)。代码文件按段落切会把函数切两半、把签名和实现分家。增**代码切块器**:按函数 / 类边界切(轻量正则或 tree-sitter),chunk 携带符号名与路径标签(复用 RQ1c 稀疏标签机制)。

- 索引侧异步(沿用 IX 系列 `index_scheduler`),**查询热路径不变**(R4)。
- 不做:每轮预注入检索结果(违反 R4 / 13 常用否决)。

**验收**:golden `agent/04_search_codebase` 扩展代码命中 case;离线检索对照(同 query 代码切块 vs 段落切块的命中率)。

---

## 3. Agent 灵敏度(AQ 系列)

> 先说清**已落地不重做**:TTFB ≤ 300ms SLO、SSE 流式 + thinking 直播、Cancel ≤ 500ms、`shouldQuery` 零模型短路、只读工具并行(AH3c)、`@path` 预算预读(AH3b)。剩余杠杆只有三个,全部 R1–R5 合规。

### AQ1 — agent 场景 cache 稳定前缀(WT5 布局的 agent 侧)

CQ1 把 `agent/system.md` 加厚后,输入 token 增量必须被 cache 抵消(12 §4.3「加厚必先能抵消」)。对齐 [12](12-model-harness.md) §5.1.1 的 WT5 布局:

| 层 | agent 场景放什么 | cache |
|----|------------------|--------|
| **稳定前缀** | `agent/system.md` + tools 定义(CQ2 重写后逐字节稳定) | 打 `cache_control`,跨 Turn 命中 |
| **易变后置** | plan 相位块、runtime 上下文、`[plan_hint]` | 照样送模型;挂靠后位置,不焊进稳定块 |

KPI 沿用 12 §5.1.1 口径:**cache miss / 总 input 绝对量**下降,不以命中率 % 为唯一目标。

**验收**:同任务重复 Turn 的 miss / 总 input 下降;TTFB / 首 token 门禁不回归。

### AQ2 — agent 侧确定性 slash 短路

写作侧已证明该路径(`/polish` `/outline` 确定性展开,`/help` `/compact` `/verify` 零模型短路)。agent 侧对齐:`input_compiler.py` 增加如 `/test`(展开为「运行测试并报告失败项」)、`/lint`(展开为「read_lints 全工作区并修复」)的**确定性展开**——不是零模型执行,而是把高频意图编译成无歧义指令,**省掉模型理解模糊输入的回合**。展开本身是正则,R3 合规。

**验收**:`test_input_compiler.py` 扩展;golden 各 1 条(对齐 writing `12_polish_skip_retrieval` / `13_outline_slash` 的做法)。

### AQ3 — 感知灵敏度守线(不新增机制,只守否决)

灵敏度的最大风险不是「没做什么」而是「多做什么」。守住:

- 首 token 前**永不**加同步模型调用(意图分类、路由、预检索均否决,R2)。
- 质量改进全部走「prompt / 描述 / 离线评测 / 异步索引」四通道,任何票若需热路径新增同步逻辑,回本文重审。
- 延迟观测沿用 12 §5.1.3(assemble / TTFB / 首 token 分开归因),CQ/AQ 各票合并前后跑同剧本对照。

---

## 4. 写作质量与灵敏度下一刀(WN 系列)

> 写作正文仍归 [14](14-writing-quality.md)(WQ0–WQ4 ✅);本节只维护**新提案**,落地后状态回写 14。

### WN1 — 连续性卡片异步提炼(对标 Sudowrite Story Bible)

现状:cards 全靠 loop 外人工整理(14 §1 纪律:卡片不在 Agent loop 内生成)。缺口:长篇多章后,人物状态 / 剧情推进无人维护,连续性靠模型窗口内记忆。

方案:章节 `turn.completed` **之后**,离线任务(小模型 / 规则)从新章提炼「人物状态变化 / 关键事件」为**候选卡片**,落 `sources/cards/pending/`;用户确认后才进正式 cards。**不占用户等待(R4),不自动 pin 未确认内容(保住 14 的卡片纪律)。**

**验收**:候选卡片生成有单测;确认流程不碰 loop;golden 断言未确认卡片不进 pin。

### WN2 — 离线 rubric 维度扩展

`offline/rubric.py` 增加与 `writing/system.md` Prose defaults 直接对应的可计算维度(全部正则 / 统计,无 judge 模型):

- **meta-knowing 命中率**:system.md Ban 清单词族(「他知道 / 她明白 / 心里清楚 …」)出现密度;
- **胶水短语密度**:「与此同时 / 就在这时 / 总而言之 …」;
- **场景 / 梗概比**:对话与动作句占比 vs 概述句占比(粗粒度启发式即可)。

仅离线评测(R4),为 prompt / 卡片迭代提供回归信号——**prompt 改了有没有用,用数字说话**,对齐 CQ3 的思路。

**验收**:rubric 单测;`make eval-all` 报告含新维度;写作 golden(`writing/01/04/12`)基线记录在案。

### WN3 — WT5 写作 cache 前缀落地(验收口径挂靠)

设计权威在 [12](12-model-harness.md) §5.1.1 与 [24](24-writing-token-economy.md) §4.6,本文**不重复设计**,只挂状态与统一验收:

- `prepare_writing_system_prompt` / assemble 分块:`system.md`(含 Prose defaults)+ tools 进稳定前缀;cards / work index / focus+prev 易变后置。
- 验收:同任务「写一章」miss / 总 input 绝对量下降;TTFB / 首 token / 写作 golden 质量均不回归。
- **写作灵敏度的最大单一杠杆就是这张票**(换章不再整段 cache miss),优先级高于 WN1/WN2。

---

## 5. 去留总表与排期

### 去留

| 方向 | 做? | 依据 |
|------|------|------|
| CQ1 加厚 agent system prompt | **是** | 纯 prompt;写作侧已验证同方法(WQ1) |
| CQ2 工具描述 hygiene | **是** | 12 §3 既有缺口;省回合双收 |
| CQ3 agent 质量 golden / rubric | **是** | R5 可测才合并;全离线 |
| CQ4 代码切块检索 | **是** | 索引异步 R4;查询路径不变 |
| AQ1 agent cache 前缀 | **是** | 12 §4.3「加厚必先能抵消」的配套 |
| AQ2 agent slash 展开 | **是** | 正则 R3;写作侧已验证 |
| WN1 连续性卡片(候选 + 确认) | **是** | R4 异步;不破坏 14 卡片纪律 |
| WN2 rubric 维度扩展 | **是** | 全离线;prompt 迭代护栏 |
| WN3 WT5 落地 | **是(优先)** | 设计已定;写作灵敏度最大杠杆 |
| 意图预分类 LLM 路由 | **否** | R2;ADR-014 |
| 每轮预注入检索 / 卡片自动 pin | **否** | R4;14 §1 |
| Turn 末强制 judge / 自动 polish pipeline | **否** | R2;14 §0 |
| 在 `AgentEngine` / `ToolExecutor` 写 `if scenario` | **否** | 12 §4.3 条 6 |
| 以 cache 命中率 % 为唯一 KPI | **否** | 12 §5.1.1 |

### 排期建议

```text
① CQ1 + CQ2(纯文案,先行,一并保证前缀字节稳定)
② CQ3 + WN2(评测护栏就位,后续迭代有回归信号)
③ WN3 → AQ1(cache 布局:写作先行,agent 复用同机制)
④ AQ2(slash 展开,小票随缓)
⑤ CQ4 + WN1(异步重活,索引/提炼均不上热路径)
```

### 验收入口

```bash
make gate        # 一票一验收,全绿才合并(R5)
make eval-all    # golden 扩展:agent 质量 case + writing rubric 维度
make runtime-test
# 延迟对照:改动前后同剧本 assemble_ms / TTFB / 首 token / miss 绝对量(12 §5.1.3)
```

---

## 6. 否决清单(全文级)

1. 任何在首 token 前新增同步模型调用的方案(路由、预检索、预评分)
2. 固定 pipeline / 加节点 / 加 router 解决质量问题
3. 默认 judge、自动串联多 pass
4. 每轮预注入向量检索或未确认卡片
5. 热路径引入重 tokenizer / CE / tree-sitter 同步解析(CQ4 只在异步索引侧用)
6. 为 cache 命中率数字牺牲 focus / cards / 上下文内容
7. 无测试或无延迟对照的「质量改进」合并(R5)
