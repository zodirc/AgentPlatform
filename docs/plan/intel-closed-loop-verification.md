# 方案：威胁情报 · 以攻促防的验证闭环

> **临时草稿 · 可删。** 尚未实施。intel 现状以 `scenarios/profiles/intel.yaml` 与 [架构 §4](../core/architecture.md) 为准；实施时改 Profile / 工具 / 六篇正文，不必先扩本文。  

本文回答：

1. 当前仓库里的 `intel` **实际是什么**，与图片叙事差在哪里。  
2. 我们要把威胁情报场景做成什么（目标态一句话 + 四阶段契约）。  
3. 哪些能力可以复用现有 Runtime，哪些必须新建，哪些明确不做。  
4. **如何像现有 Ops Bench 一样测效果**（分层、指标、题集、与合入门禁的边界）。  
5. 演进分层与否决清单（保证不破坏「一个内核、多场景」与安全红线）。

---

## 0. 一句话立场

**`intel` 不是告警放大器，也不是通用编码 Agent；目标态是「授权前提下的验证闭环」——线索入场 → 攻击面理解 → 实证（含可控验证）→ 攻击链影响排序 → 可复核报告与复测确认。今日已落地的是闭环前半段的桌面研判（IOC 富化 + RAG + 带引用简报）；后半段（PoC / 复测）按阶段引入，且永远不假装已处置。**

```text
今日（已落地）                 目标态（本文）
─────────────────              ──────────────────────────────
线索 → enrich / lookup         01 攻击面理解（资产·服务·接口）
     → search_sources          02 验证（去伪存真·证据留痕）
     → 带 cite 的一页简报       03 攻击链推理（组合风险·业务影响）
硬禁：无封禁 / 无 shell         04 报告与复测（修复建议·闭环确认）
                               底线：授权测试 · 全流程留痕 · 可复核交付
```

---

## 1. 现状钉死（从代码与语料读出）

### 1.1 平台位置

| 项 | 事实锚点 |
|----|----------|
| Profile | `scenarios/profiles/intel.yaml` · `scenario_id: intel` · `web_layout: writing-workbench` |
| 提示词 | `scenarios/intel/system.md`：分析员助手；证据优先；默认 `path_prefix=seed/intel` |
| 工具白名单 | 读/检索/写作交付向：`enrich_ioc` · `lookup_indicator` · `search_sources` · `draft_section` · `check_citation` · …；**无** `run_command` / coding 结构工具 |
| 语料 | `seed/sources/intel/`：`_demo` + `ioc/` 进 git；`vendor/` 离线 fetch（ATT&CK / Atomic / MISP 等） |
| 验收 | `eval/golden/intel/*`（富化出简报、引用校验、闲聊不强制 enrich） |
| 与其它场景 | 与 `writing` 同属 RAG 平面；与 `agent`（LSP/AST）**硬隔离**（CSI §3） |

### 1.2 今日价值主张（已成立）

- **不堆告警**：按需工具，闲聊不拉 enrich（golden `03`）。  
- **证据优先**：本地卡表 + 语料检索；禁止无源 APT 归属。  
- **可交付**：一页研判 + `[cite:]` + `check_citation`。  
- **不伪处置**：明确禁止声称已封禁 / 隔离 / 改 ACL。

### 1.3 今日缺口（相对目标叙事）

| 图片阶段 | 今日覆盖度 | 缺口本质 |
|----------|------------|----------|
| 01 攻击面理解 | 弱 | 无资产/服务/接口结构化面；仅有 IOC 卡与实验室笔记 |
| 02 PoC / 验证 | 无 | 无授权验证动作、无证据产物契约；Profile 禁 shell |
| 03 攻击链推理 | 弱 | `related` 字段与语料共现，缺链图与影响排序 |
| 04 报告与复测 | 半 | 有报告骨架；无「修复后复测确认」相位 |

结论：**已有「研判闭环」；缺少「验证闭环」。** 二者共享「线索 → 证据 → 交付」骨架，但验证闭环要求 **可复核的实证**（含可控攻击路径证明），而不只是情报卡片与叙述引用。

---

## 2. 目标

### 2.1 产品目标

1. **优先确认能造成业务影响的风险**，而不是把更多告警交给团队。  
2. 输出必须是 **可交付、可复核**：结论 + 证据指针 + 修复建议；复测通过才算闭环。  
3. 资源排序依据 **真实攻击路径**（链上可达 + 影响），而非单 IOC 声誉分。  
4. 全过程可审计：**授权边界、工具调用、证据产物、报告版本** 均可回放。

### 2.2 工程目标（与本仓宪法对齐）

1. **仍是一个 Scenario**：差异只在 Profile / 工具 / 语料 / 提示词阶段契约；Engine **禁止** `if scenario == "intel"`。  
2. **能力即工具**：新能力先进白名单工具（或既有工具的结果契约加厚），不新增固定 pipeline 节点。  
3. **R1–R5**：验证与重索引不得挡 `turn.accepted`；重活旁路；可测才合入（golden / 门禁）。  
4. **安全默认**：默认态保持「离线研判」；任何「验证」能力必须显式授权、可关、可审计；永不自动声称已处置。  
5. **与 coding 隔离**：不把 Agent AST / LSP 绑进情报 RAG；若未来「只读代码库做情报」，单独评审只读导航（CSI §3.2）。

### 2.3 非目标（写死）

- 不做通用漏洞扫描器 / 告警 SOC 替代品。  
- 不做未授权攻击、不提供「一键打穿」操作面。  
- 不在 Turn 热路径拉外部威胁情报网（保持今日「Turn 永不拉网」；充实语料仍走环外 `make intel-corpus-fetch`）。  
- 不把 `intel` 变成第二个 `agent`（全工具编码面）。  
- 不在未落地验证能力前，用文案假装已有 PoC / 复测。

---

## 3. 四阶段契约（目标态语义）

> 阶段是 **分析员可见的工作相位与产物契约**，不是 Engine 固定状态机。模型经工具推进；缺证据则显式 `uncertain` / `blocked_on_auth`，禁止脑补。

### 01 · 攻击面理解

| 项 | 约定 |
|----|------|
| 输入 | 线索：IOC、告警、资产清单、服务/接口描述、授权范围 |
| 动作 | 归一化资产与暴露面；关联本地语料与 IOC 卡；划定「允许验证的边界」 |
| 产出 | 攻击面摘要（资产·服务·接口）+ 可疑假设列表（带来源） |
| 今日可借用 | `enrich_ioc` / `lookup_indicator` / `search_sources` / 用户 `sources/` 上传 |
| 缺口 | 结构化攻击面对象（哪怕先是 Work 内 YAML/JSON 清单） |

### 02 · 验证（去伪存真 · 证据留痕）

| 项 | 约定 |
|----|------|
| 输入 | 假设 + 授权范围 |
| 动作 | **优先非破坏性**核对（配置、版本、暴露、公开指纹）；仅在授权且 Profile 放开时，才允许受限验证环境中的实证 |
| 产出 | 证据包：时间戳、步骤摘要、原始输出引用、真阳性/假阳性判定 |
| 今日可借用 | 语料对照、IOC 卡声誉 stub、引用校验 |
| 缺口 | 证据产物模型；受限验证工具（若引入，必须沙箱 + 审批 + 留痕） |

### 03 · 攻击链推理

| 项 | 约定 |
|----|------|
| 输入 | 已验证节点 + 关联情报 |
| 动作 | 组合单点为链；估计业务影响；按「路径可达 × 影响」排序 |
| 产出 | 攻击链视图（节点/边/前提）+ 优先处置队列 |
| 今日可借用 | IOC `related`、vendor ATT&CK/Atomic 语料、子 agent `researcher` / `fact_checker` |
| 缺口 | 链对象与排序 rubric；禁止无证据的「必属某 APT」跳步 |

### 04 · 报告与复测

| 项 | 约定 |
|----|------|
| 输入 | 链排序结果 + 证据包 |
| 动作 | 起草修复建议；复测同一验证路径；确认关闭或打回 |
| 产出 | 可复核交付件（报告版本 + cite + 复测记录） |
| 今日可借用 | `draft_section` / `propose_patch` / `check_citation` / `export_document` |
| 缺口 | 「复测」相位与通过准则；报告与证据包绑定 |

**底线标签（全阶段）**：授权测试 · 全流程留痕 · 可复核交付。

---

## 4. 思考：为何这样切，而不是「直接上 PoC」

### 4.1 与平台演进一致

本仓从 `agent-langraph` 重写的教训是：**先契约与场景边界，再加厚能力**。`intel` 今日已有可证明的研判路径（golden）；若一上来绑破坏性验证，会同时炸开：安全边界、审批、沙箱、评测、产品文案诚实性。

### 4.2 「验证」≠「扫描」≠「处置」

| 概念 | 含义 | 本场景态度 |
|------|------|------------|
| 扫描 | 广撒网出告警 | **拒绝**作为产品主路径 |
| 研判 | 线索 + 情报 → 有引用的结论 | **今日主路径** |
| 验证 | 在授权边界内证明可否利用 / 是否误报 | **目标态核心增量** |
| 处置 | 封禁、隔离、改 ACL | **永远人工；Agent 只建议** |

图片「以攻促防」落在本仓的正确读法是：**用可控实证提升修复优先级的可信度**，不是把 Agent 变成攻击者控制台。

### 4.3 证据是第一公民

Coding 链用 LSP/测试做「可复核」；情报链应对齐同一精神：

- 没有证据指针的结论 = 草稿，不是交付。  
- 假阳性被证伪，与真阳性被证实，同等有价值（去伪存真）。  
- 复测是闭环的句号；只有报告没有复测 = 开环。

### 4.4 演进三层（建议）

```text
L0  研判加固（低风险，可立即排）     ← 今日底座
    · 攻击面清单约定（文档/种子格式）
    · system.md 四阶段工作流（仍 on-demand）
    · 报告模板：假设 / 证据 / 影响 / 建议 / 不确定项
    · golden：阶段字段与「不伪处置」回归

L1  结构化闭环（中风险）
    · Work 内 AttackSurface / Finding / Evidence / Chain 轻量产物
    · 工具结果契约加厚（或少量新工具名，须 adoption 友好）
    · 链排序 rubric + 子 agent 分工（retrieve / fact_checker）
    · GUI：阶段进度与证据列表（复用 writing 工作台，不另起壳）

L2  授权验证与复测（高风险，单独评审）
    · 显式授权对象 + 审批闸
    · 受限验证环境（与 agent bwrap 同源思路，白名单更窄）
    · 复测同一证据路径；通过/失败写入 Evidence
    · 默认关闭；演示与生产策略分离
```

**原则**：L0/L1 不依赖 L2；没有 L2 时产品叙事只能声称「研判 + 结构化证据」，不得声称「已 PoC / 已复测」。

### 4.5 与 RAG / coding 的边界再确认

| 平面 | 服务谁 | 本场景用法 |
|------|--------|------------|
| RAG `sources/` | writing / intel | 情报语料与用户上传；切块几何可含代码，但是 **检索**，不是 PoC |
| Agent LSP / AST | agent | **不**进入 intel 默认工具面；只读代码库情报另案 |
| Exec / 沙箱 | agent（及未来可选 intel L2） | L2 才讨论；默认 intel 保持无 shell |

---

## 5. 基准测试（Bench）思考

> **立场**：intel 也要有「效果温度计」，但**不能**把契约 golden、离线模型考题、产品闭环 bench 揉成一栏。对齐现有 Ops 三层：Bench ≠ Golden ≠ ci_proof（见 [工作台 · §2](../topics/workbench.md)）。

### 5.1 为何现有套件不够

| 现有套件 | 测什么 | 对 intel 的缺口 |
|----------|--------|-----------------|
| **retrieval / retrieval_zh**（BEIR · C-MTEB） | `search_sources` 召回宏分 | 语料域是科文/电商/医疗，**不是**威胁报告 / IOC / ATT&CK；且只测检索，不测研判交付 |
| **context**（LongBench） | 长文阅读 F1/EM | 缺情报任务形态（告警→简报、链推理、证伪） |
| **coding**（SWE-bench） | 补丁 / harness resolve | **错误平面**：编码修复 ≠ 威胁验证闭环 |
| **golden/intel**（今日 3 条） | 协议与主路径不炸 | **不能**冒充效果分；覆盖 enrich/cite/闲聊，无攻击链 / 假阳性 / 复测 |

结论：需要 **intel 专属效果臂**，复用 Ops 编排与隔离纪律，**不**往 BEIR/SWE 宏分里塞情报题。

### 5.2 三层别搞混（intel 版）

| 层 | 是什么 | 挡合并？ | 今日 / 目标 |
|----|--------|----------|-------------|
| **G · Golden** | `eval/golden/intel/*`：工具调用、禁止伪处置、cite 契约 | 间接（经 `eval-all` / gate） | 已有 01–03；随 L0 加厚 |
| **B · Effect Bench** | 官方/自建题集 × **agent-path**（Session→Turn→真实工具）→ SCORECARD | **否**（温度计） | **本文主提案** |
| **C · ci_proof** | smoke + stub golden + unit | **是** | 保持；intel 重效果不进默认 gate 墙钟 |

与 retrieval/coding 一样：**Ops 验收主栏只认 L1 agent-path**——分数必须来自产品 `intel` Session/Turn 与真实工具事件，禁止为刷分绕过 Engine（对照 `official_agent_path` / `eval_path=agent`）。

旁路对照臂（L0 component：直接调 embed / 直接喂 prompt 考题）只作诊断，**不进** Ops 主栏。

### 5.3 测什么：按产品四阶段拆指标

Bench 应对齐「可复核交付」，而不是「答对多少道网络安全选择题」。

| 产品阶段 | Bench 任务族（建议 id） | 主指标（草案） | 金标从哪来 |
|----------|-------------------------|----------------|------------|
| 01 攻击面 | `intel.surface` | 资产/服务/接口覆盖率 · 越权假设率↓ | 题面附授权范围 + gold 资产清单 |
| 02 验证 / 去伪 | `intel.verify` | 真阳性召回 · **假阳性正确证伪率** · 证据指针完备率 | 题面含真/假线索；gold = 判定 + 必引 path |
| 03 攻击链 | `intel.chain` | 边/节点 F1 · 排序 NDCG@k（相对 gold 优先队列） | 预置链图与优先级 |
| 04 报告与复测 | `intel.report` | 必填章节覆盖 · cite 有效率 · **伪处置零容忍** ·（L2）复测判定一致率 | 报告 rubric + 负面用例 |
| 横切 · 检索 | `intel.retrieval` | nDCG@10 / Recall@k **在威胁语料上** | 自建 qrels 或 vendor 切片；**与 BEIR 宏分分栏** |
| 横切 · 安全红线 | `intel.safety` | 伪处置 / 无授权验证 / 编造归属 = **硬失败** | 负面题；一票否决进 SCORECARD 脚注 |

**聚合原则**：主栏看「闭环任务宏分」（verify + chain + report），检索是支撑栏；safety 失败则整 run 标 `safety_fail`，不得用检索高分洗白。

### 5.4 外部基准怎么用（借鉴 ≠ 直接当产品分）

业界已有 CTI 向 LLM 题集，适合做 **模型能力对照** 与部分子任务校准，但**不等于**本产品的验证闭环温度计：

| 外部源 | 内容 | 对本仓用法 | 不适合直接当主栏的原因 |
|--------|------|------------|------------------------|
| **[CTIBench](https://github.com/maveryn/cti-bench)**（NeurIPS'24） | MCQ · CVE→CWE · CVSS · ATT&CK 抽取 · 归因 | L0 **知识/映射**诊断臂；可挂 `agent-bench` worker | 多为单轮考题，不经 `enrich_ioc`/`search_sources`/`check_citation` 产品路径 |
| **AthenaBench** 等动态 CTI 集 | 更新语料 + 缓解策略等 | 可选刷新源；许可与拉取策略另审 | 动态拉网与本仓「Turn 不拉网 / 环外 fetch」冲突，须缓存固化 |
| CyberMetric / SecEval 类 | 广域安全 MCQ | **不做**主依赖 | 测记忆，不测闭环交付 |
| Atomic Red Team / ATT&CK STIX（已在 `SOURCES.yaml`） | 技术与检测叙述 | **产品语料 + 自建 qrels/链题** 的原材料 | 本身不是带 agent 协议的 bench |

**推荐姿态**：

1. **产品主栏 = 自建 Closed-Loop Suite**（下节）：fixture Work + gold 产物 + agent-path。  
2. **对照栏 = CTIBench 小切**（可选）：同一模型、旁路或 agent 答卷，回答「模型 CTI 知识够不够」，**不**回答「产品闭环好不好」。  
3. 协议戳记分开：`intel-closed-loop-YYYY-MM` vs `ctibench-slice-vN`，SCORECARD **分栏**，禁止混宏分。

### 5.5 产品主栏：Closed-Loop Suite（目标形态）

心智模型对齐官方小集三步：**Pull → Eval → Regress**（见 [eval/official/README](../../eval/official/README.md)）。

```text
make up-bench（或复用）
  → 物化 intel fixture corpus → 独立 schema / 索引面（不碰产品 sources 索引）
  → Ops / make：suite=intel（或 targets+=intel）
  → official_agent_path：scenario_id=intel
       每题：建临时 Work · 挂 sources/告警 · StartTurn（自由臂为主）
       从 tool/turn 事件 + 交付件抽取结构化结果
  → 对照 SCORECARD · 写 runs/<uuid>/ · publish suite=official|intel
```

**题型设计（小集起步）**：

| 题型 | 例 | 自由臂期望轨迹 |
|------|----|----------------|
| 真阳性简报 | Alert 含真实 scanner IOC | enrich → search → draft；cite 命中 gold note |
| 假阳性证伪 | 诱饵 IOC / 过期情报 | 明确「不足以下结论/证伪」；不得硬控 APT |
| 多跳链 | IP→域名→hash→技术 | 链节点覆盖 gold；排序靠近业务高影响边 |
| 检索支撑 | 「哪份 lab-note 提到 X」 | `search_sources` 命中 path；可与 writing.07 同构但语料换 intel |
| 红线 | 「请直接封禁」 | **零**处置声称；可建议人工 follow-up |

**tier**：先 `n5` / `n10` 手工金标（进 git 的薄 fixture + 环外大语料），再扩；Wall-clock 与 SWE 抢机时 **intel 夜间跑**，不挡 coding 双轨。

### 5.6 计分与诚实性

| 规则 | 说明 |
|------|------|
| 自由臂为主 | 自然工具选择；forced「必须 enrich」仅诊断 |
| 证据可机器核 | cite path ∈ 允许集；Evidence 字段 schema 稳定后做结构化比对 |
| 开放叙述要约束 | 报告正文可用 checklist / 必含键；**避免**无约束 LLM-as-judge 当唯一分（可作辅分并标注） |
| 同条件才比 Δ | `protocol_version` + 语料指纹 + 模型 meta；换 embedder 须 bump 协议 |
| 隔离 | 索引进 `bench-postgres` 独立 schema（如 `retrieval_ops_intel`）；**禁止**写产品 `source_chunks` |
| R1–R5 | 评测不改 Engine 语义；不预注入 gold 链进 prompt；失败显式，不把 miss 妆成 pass |

**与 L0–L2 能力对齐**：

- L0 能力未齐时，SCORECARD 只启用 `intel.retrieval` + `intel.report`（章节/cite/safety）子集。  
- L1 产物落地后启用 `verify` / `chain`。  
- L2 验证工具未开：**不得**出「PoC 成功率」栏；桌面/沙箱复测题单独 suite 且默认关。

### 5.7 与落地序的衔接（评测轨）

| 序 | 评测动作 | 说明 |
|----|----------|------|
| B0 | 文档与分层共识（本节） | 不写代码 |
| B1 | 加厚 `eval/golden/intel`（阶段字段、伪处置负面、假阳性） | 进 gate 友好的契约层 |
| B2 | 自建 `eval/intel/` 小集：corpus + qrels + n5 闭环题 + 评分脚本草案 | 可先 CLI，后挂 Ops |
| B3 | Ops 卡 `suite=intel` + SCORECARD 分栏 + protocol 戳记 | 对齐 retrieval/coding 发布姿势 |
| B4 | 可选：CTIBench 切片对照臂（缓存、许可审过） | 分栏；非主栏 |
| B5 | L2 若启用：受限复测题集（仅夹具环境） | 与安全评审绑定 |

### 5.8 评测否决（本节追加）

1. 用 BEIR/SWE 分数宣传「威胁情报能力」。  
2. 用 CTIBench MCQ 准确率替代闭环交付分。  
3. 为刷分绕过 `intel` Profile / 真实工具（非 agent-path 进 Ops 主栏）。  
4. 评测 Turn 拉真网下载 exploit，或对非夹具目标做验证。  
5. LLM-as-judge 无 rubric、无抽检，却写入 SCORECARD 主栏。  
6. 把 intel 效果臂默认并进 `make gate` 墙钟（应保持温度计属性，除非另立 nightly）。

---

## 6. 成功标准（草案级，落地前再钉数字）

### 6.1 体验

- 分析员从一条告警/IOC 出发，能在同一 Work 内看到：**假设 → 证据 → 链排序 → 报告**，且每步可回放工具与 cite。  
- 明确假阳性时，交付件写清「已证伪」与依据，而不是沉默或改口硬控。  
- 任何回复不得出现「已封禁/已隔离」类伪处置（保持并加强 golden 负面用例）。

### 6.2 工程

- Profile / system / golden 可证明 L0。  
- 新产物有 schema 或至少稳定 JSON/Markdown 约定，进 `packages/contracts` 或种子 FORMAT。  
- 延迟与 R1–R5：索引与验证旁路；Turn 热路径无同步拉网、无全库重扫。  
- L2 未开时，工具白名单与文案双闸，防止模型「演」PoC。

### 6.3 评测

- 存在可复现的 **intel 效果臂**（至少 CLI；目标进 Ops），与 BEIR/SWE **分栏**。  
- SCORECARD 能回答：「闭环交付变好了吗？」，而不仅是「模型更会考 CTI 了吗？」。  
- safety 硬失败可见；回归 Δ 同协议可比。

### 6.4 明确暂不承诺

- 漏洞发现率、CVE 覆盖率、自动化 exploit 成功率。  
- 替代商业 ASM / BAS / 红队平台。  
- CTIBench 全量或动态网更题集的日常 gate。

---

## 7. 建议落地序（仅方向，非排期承诺）

| 序 | 主题 | 产出 | 依赖 |
|----|------|------|------|
| I0 | 本文评审：目标 / 非目标 / 三层演进 / 评测分层 | 共识 | — |
| I1 | L0：`system.md` 四阶段 on-demand 契约 + 报告章节模板 + golden 加固 | 行为可测 | I0 |
| I2 | L0：攻击面 / 告警种子格式（`seed/sources/intel` + FORMAT） | 语料可搜可引用 | I1 |
| I3 | L1：Finding / Evidence 轻量产物约定 + 工具结果字段 | 结构可交付 | I1 |
| I4 | L1：攻击链排序 rubric + 子 agent 提示 | 优先级可解释 | I3 |
| I5 | L2 单独安全评审（授权 · 沙箱 · 审批 · 默认关） | 决策记录 | I3–I4 |
| I6 | 若 I5 通过：受限验证工具 + 复测相位 + 专项 golden | 验证闭环可测 | I5 |
| B1–B3 | 评测轨：golden 加厚 → 自建闭环小集 → Ops `suite=intel` | 效果温度计 | I1+；与 I3 并行可 |

与 coding 主线（SWE / AST）**并行不抢同一评测臂**；intel 变更以 `eval/golden/intel`、自建 intel bench、RAG 回归为主证明。

---

## 8. 风险

| 风险 | 含义 | 缓解 |
|------|------|------|
| 叙事超前于能力 | UI/文案写「PoC/复测」，实际只有 RAG | L 分层；文案跟能力开关 |
| 模型演戏验证 | 无工具也输出「已利用成功」 | system 硬禁 + golden 负面 + 无证据不得写死结论 |
| L2 安全事故 | 验证能力越权或留痕不足 | 默认关；审批；沙箱；与 agent shell 配额隔离 |
| 与 writing 工具面缠死 | 情报报告质量绑死写作稿件模型 | 共享布局可接受；产物类型与 system 分离 |
| 做成告警台 | 又回到「更多告警」 | 成功标准盯「可复核交付」与排序，不盯告警条数 |
| 偷接 coding 结构面 | intel Session 拉起 LSP/AST | CSI §3 硬隔离验收 |
| **用错温度计** | 用 BEIR/CTI-MCQ 宣传闭环能力 | §5 分栏；主栏=闭环 suite |
| **评测污染产品索引** | intel bench 写入店内 `source_chunks` | bench-postgres 独立 schema；对齐 retrieval_ops 先例 |

---

## 9. 否决清单

1. 把 `intel` 做成扫描告警中心或未授权攻击控制台。  
2. Agent 自动声称已封禁 / 隔离 / 改防火墙。  
3. Turn 热路径拉外部情报网或下载 exploit。  
4. 为情报闭环在 Engine 增加固定多节点 pipeline（回到旧图编排）。  
5. 未授权即开放 PoC / shell；或 L2 默认对全体租户开启。  
6. 用 RAG 命中率冒充「已验证可利用」。  
7. 将 Agent 工作区 AST / LSP 默认焊进 intel Profile。  
8. 无证据包却在交付件写「复测通过」。  
9. 用虚构 APT 归属或无法引用的「内部情报」充证据。  
10. 为赶叙事在 golden 里断言尚未存在的验证工具调用。  
11. 用 BEIR / SWE / 纯 MCQ 分数冒充 intel 闭环效果（见 §5.8）。  
12. 非 agent-path 刷分结果进入 Ops intel 主栏。

---

## 10. 与既有文档的关系

| 文档 | 关系 |
|------|------|
| [架构](../core/architecture.md) | Scenario 扩展方式、R1–R5；本文遵守 |
| [工作台 · Ops Bench](../topics/workbench.md) | 三层评测与 L1 agent-path；intel suite 应对齐此纪律 |
| [RAG](../topics/rag.md) | intel 检索平面；L0/L1 主依赖；bench 索引隔离 |
| [CSI §1.4](coding-structural-intelligence.md) | writing/intel vs agent 隔离；本文不推翻 |
| [工作区 AST](agent-workspace-ast-index.md) | **非目标**；intel 面板不挂 AST 进度 |
| [eval/official](../../eval/official/README.md) | Pull→Eval→Regress 与 SCORECARD 先例 |
| 现网 `scenarios/intel/system.md` | L0 将回写阶段契约；以评审后补丁为准 |

升格路径：L0/L1 稳定后，将「intel 场景说明」回写 `docs/topics/`（或工作台章一节），本文降为历史草案并标注状态；bench 协议稳定后回写工作台 §2 套件表。

---

## 11. 修订记录

| 日期 | 修订 |
|------|------|
| 2026-08-13 | **v0**：基于现网 `intel` 实现与「以攻促防验证闭环」产品图，写下立场、目标、四阶段契约、L0–L2 演进、否决清单；明确今日=研判闭环、目标=验证闭环，且 L2 单独安全评审 |
| 2026-08-13 | **v0.1**：新增 **§5 基准测试思考**——对齐 Ops 三层（Golden/Bench/ci_proof）；论证 BEIR/SWE/现有 golden 不足；按四阶段拆指标；外部 CTIBench 作对照栏、产品主栏为自建 Closed-Loop Suite（agent-path）；B0–B5 评测轨与否决 11–12 |
