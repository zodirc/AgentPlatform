# 方案：Coding 结构智能（LSP / AST）

> **状态**：Wave 1 + 写入链揉合（Locate / Impact / `edit_file.checks` / span 候选）**已落地** · 正文摘要见 [工具与上下文](../core/tools-and-context.md) 图 3 · 本文保留协议、日记与收尾项  
> **范围**：`agent` 写入链的 **LSP 结构揉合** + SWE/Ops 评测协议  
> **姊妹**：[工作区异步 AST](agent-workspace-ast-index.md)（A6 旁路 indexer **已接线**；双轨 n5 数字待复跑）  
> **最新 n5 harness**：`b3357dd6` · **resolve 3/5**（§6.7.9）；对照 `d459ca51` resolve 0/5（§6.7.8）· 下一步 **Wave 3 方案** §7.7  
> **非范围**：writing/intel RAG 主链；不以资料检索充当 Agent Locate  
> **相关现状**：`read_lints`=LSP∪CLI · Locate=`search_codebase`/裸符号 `grep`→definition · Impact=`edit_file.impact` · Verify=`edit_file.checks`  

正文已覆盖主路径时，优先改 core；本文作详册与评测对照。

---

## 0. 一句话立场

**LSP 是 coding 写入链已落地的结构车道（定位 · Impact · 验证）；写作 / 威胁情报走 RAG。工作区异步 AST 旁路已接线（见姊妹文），不与资料 RAG 混写，也不替代本文 SWE 评测主线。**

形态必须是：

```text
能力 = agent Profile 工具面的固有环节
  · Locate：search_codebase（符号→definition）+ 精度 goto_definition
  · Impact：edit_file.impact.references + 精度 find_references
  · Verify：edit_file.checks + read_lints（LSP∪CLI）
差异 = ScenarioProfile 白名单
  · agent：结构工具有 / search_sources 无
  · writing · intel：search_sources 有 / 结构工具无
Engine = 禁止 if scenario；禁止为结构智能加固定 pipeline 节点
失败 = 基础设施故障显式 failed（缺 language server 不算「降级成 grep 产品路径」）
旁路 = 工作区 AST 索引（A6 已接线）→ agent-workspace-ast-index.md（不携带 RAG）
```

---

## 1. 问题与目标

### 1.1 问题（写入链视角）

Agent 改代码的质量，不只取决于模型「会不会写」，还取决于三条结构车道是否存在：

| 写入阶段 | 今天大致靠什么 | 结构层缺失时的典型失败 |
|----------|----------------|------------------------|
| **改前定位** | 模型常点 `grep`/`read_file`/`run_command`；产品契约要求符号走 Locate（`search_codebase` 或裸符号 `grep` 重定向） | 假阳性、漏调用点、跨文件符号找不到、多跳靠猜 |
| **改时落笔** | `edit_file` 唯一 span；成功后附 `impact.references` | 切碎函数、span 不唯一、改完不知调用面 |
| **改后验证** | `read_lints`(LSP∪CLI) / `run_tests` | 非 Python 弱或无诊断；类型/未解析引用靠测试偶然抓住 |

CQ1–CQ3（system 纪律、工具描述、golden/rubric）解决的是 **行为闭环**；本文解决的是闭环里 **传感器与手术刀是否够结构化**。两者叠加，不以互斥。

### 1.2 目标

| ID | 目标 | 可观测 |
|----|------|--------|
| G1 | Coding Profile 具备符号级定位（definition / references） | 工具可调用；golden 命中跨文件引用 |
| G2 | 写入后验证具备多语言/项目级 diagnostics（优先经统一 `read_lints`） | 非仅 ruff；受影响路径诊断回灌 |
| G3 | 索引面按真实语法边界切代码（AST/tree-sitter 升级 CQ4） | 异步；查询热路径不重建；切块对照指标 |
| G4 | Writing 场景零感知（无新工具、无新进程、无前缀膨胀） | Profile 对比 + cache/组装对照 |
| G5 | 全程合宪 R1–R5；失败可降级；可测才合并 | 门禁矩阵见 §10 |
| G6 | 结构能力的贡献可被外部基准量化 | SWE-bench Lite `structural on/off` 双轨对照（§8） |

### 1.3 非目标

- 不对齐 Cursor「全 IDE 能力」宣传口径。  
- 不在首 token 前同步起全语言 Language Server / 全库 parse。  
- 不把 LSP/AST 做成强制 pipeline（parse → lint → 才允许模型说话）。  
- 不在 `AgentEngine` / `ToolExecutor` 写 `if scenario == "agent"`。  
- 不默认开启 rename / code action 等写副作用结构操作（见 §7 阶段 D）。  
- 不替代 `run_tests`：类型绿 ≠ 任务完成。  
- 不为基准分数预注入结构上下文、改 loop 语义或伪造路径（R5 精神；见 §8.4）。

### 1.4 设计原则

1. **写入一等，不是凑合**：结构导航与结构诊断是 coding 应有能力，不是「检索再增强一点」。  
2. **场景隔离**：只挂 coding 向 Profile；写作不背成本。  
3. **两平面**：重活在索引面（R4）；交互面只有按需工具调用。  
4. **能力即工具**：与 [工具与上下文](../core/tools-and-context.md) 一致——注册 `ToolSpec`，不改 while。  
5. **失败显式，禁止「够用」冒充成功**：无 server / timeout / 不支持语言 → Locate/Impact 标 `failed` / `locate_incomplete`；**不得**把纯词面命中当成结构 Locate 完成。  
6. **证明优先（R5）**：无 agent 质量 golden / 延迟对照 / Ops 过程指标，不合并「感觉更好」。  
7. **揉合进真实调用路径**：能力必须落在模型**实际会点**的动词上（见 §6.7）；禁止只加旁支工具名 + 纪律催用。

---

## 2. 概念澄清：LSP 与 AST 各买什么

### 2.1 AST / tree-sitter

| | |
|--|--|
| **是什么** | 把源码解析成语法树；按节点（函数、类、方法）理解边界 |
| **买入链路** | （1）**RAG 旁路**：`sources/` 代码切块几何（writing/intel）；（2）**Agent 工作区 AST 旁路**（A6 已接线，无向量）；（3）工具内单文件语法门 / span 候选 |
| **不直接买** | 跨文件引用图、类型错误、项目配置感知（这些仍归 LSP） |
| **成本特征** | 单文件解析相对可控；全库同步 parse 伤 R3；适合 **异步旁路** 与 **单次工具内** 使用；**Agent 全仓索引 ≠ 必须绑 RAG** |

本仓现状：`retrieval/chunking.py` 在 **RAG sync** 路径上优先 tree-sitter、失败回落 CQ4 正则（*not a full IDE index*）。**Agent Profile 当前不消费该旁路**（无 `search_sources`）。Agent 侧 Cursor 式工作区 AST 索引见 [agent-workspace-ast-index.md](agent-workspace-ast-index.md)。
### 2.2 LSP（Language Server Protocol）

| | |
|--|--|
| **是什么** | IDE ↔ 语言服务协议：定义跳转、引用、诊断、补全、重命名等 |
| **买入链路** | 项目级符号图、跨文件 references、多语言 diagnostics（常强于单 CLI linter） |
| **不直接买** | 「写出更好业务逻辑」；也不能免除测试 |
| **成本特征** | 进程生命周期、冷启动、内存、工作区同步（didOpen/didChange）、部分 server 会执行项目配置 |

### 2.3 和现有工具的映射（当前态 · 2026-08-11）

| 能力 | 当前实现 |
|------|----------|
| 词面 / regex 搜索 | `grep`（精确串、报错文本、regex） |
| 符号 Locate | `search_codebase`（符号→LSP definition）+ **裸符号 `grep` 重定向**同一路径；结果 `definitions[]` / `locate_incomplete` |
| 精度定义 / 引用 | `goto_definition` / `find_references`（模型极少主动点；供加深与委派） |
| 改后 Impact | 代码路径 `edit_file` 成功 → **必附** `impact.references`（同 refs 适配器） |
| 诊断 | `read_lints` = LSP ∪ ruff/CLI |
| 代码切块（RAG · writing/intel） | `sources/` sync：CQ4 / tree-sitter；**Agent 不消费** |
| 工作区 AST 索引（Agent） | **A6 已接线**（旁路 indexer + 队列；双轨 n5 数字待复跑）→ [agent-workspace-ast-index.md](agent-workspace-ast-index.md) |

---

## 3. 场景分型：写作 / 威胁情报（RAG）vs Agent（LSP + 结构索引）

> **硬隔离**：RAG 语料面与 Agent 编码结构面 **不是同一条旁路**。  
> Agent Profile **没有** `search_sources`；写作 / 威胁情报 **没有** coding 结构工具面。  
> 不得把「`sources/` sync → embed/FTS」当成 Agent 的 codebase AST；也不得在 writing/intel Session 上偷偷起 LSP。

### 3.0 总表（先读这张）

| 场景 | Profile | 主检索 / 定位入口 | 索引 / 旁路 | 与 AST 的关系 | 与 LSP 的关系 |
|------|---------|-------------------|-------------|---------------|---------------|
| **写作** | `writing` | `search_sources`（资料 RAG） | `sources/` → `index_scheduler` 切块 + embed/FTS | 代码文件若落在 `sources/`，切块可走 tree-sitter（**RAG 切块几何**，服务检索召回） | **不起** Language Server；无 `search_codebase` / `edit_file` / `read_lints` |
| **威胁情报** | `intel` | 同左：`search_sources` 为主 | 同左（资料/情报语料面） | 同左；默认 **不开** coding 结构工具 | **默认不起** LSP；若未来只读导航需单独评审，仍不开写副作用结构操作 |
| **Agent 编码**（含 SWE L1） | `agent` | `search_codebase` / `grep` / `read_file`（**无** `search_sources`） | **旁路**：工作区 AST（A6 已接线）粗筛 + 词面 + LSP | Locate 漏斗可融合 AST 候选；写前语法门 / checks 属单文件 | **已揉合**：Locate→definition；Impact→references；Verify→`edit_file.checks` + `read_lints` |
| **协作等** | `collab` 等 | 以工具白名单为准 | 仅当白名单含编码工具时启用结构能力 | 同 agent 子集 | 同左 |

**一句话**：写作 / 情报买的是 **RAG**；Agent 评测/写入主链买的是 **LSP（+ 词面）**；Cursor 式工作区 AST 见姊妹草案（不携带 RAG）。

### 3.1 写作（`writing`）— RAG 语料面

| 项 | 约定 |
|----|------|
| 工具 | 有 `search_sources`；**无** `edit_file` / `read_lints` / `search_codebase` / `run_tests` |
| 旁路在做什么 | 启动 / watch / 显式 sync → 扫 Work 的 **`sources/`** → 切块（Markdown 标题；代码扩展名可 tree-sitter）→ embed / FTS |
| AST 角色 | **仅服务切块边界**（召回几何），不是符号 Locate，不是 IDE 式 codebase index |
| 新建 `.py` 在写作工作区 | 仍无结构工具；不偷偷起 LSP；若文件在 `sources/` 内，下一次 **sources sync** 才更新检索切片 |
| 验收 | writing Profile 工具列表与前缀稳定；RAG 回归不因 Agent 结构改动而变差 |

### 3.2 威胁情报（`intel`）— 同属 RAG 语料面

| 项 | 约定 |
|----|------|
| 与写作的关系 | **同一检索平面家族**（`search_sources` + `sources/` 索引），语料与过滤策略可不同（如隐藏 writing 种子语料），但 **不是** Agent 编码链 |
| 结构智能 | **默认关闭**（无 coding 工具白名单 → 无 LSP / 无 Agent AST 索引） |
| 未来扩展 | 若要「读代码库做情报」，单独开 **只读** 导航；仍不开 rename 等写副作用；**仍不**把 Agent 工作区 AST 与情报 RAG 绑死 |

### 3.3 Agent（`agent`）— LSP + 词面（当前）；工作区 AST 见姊妹草案

#### 3.3.1 当前已落地（2026-08）

```text
Locate  ：符号 → search_codebase（可经工作区 AST 粗筛）→ LSP definition（裸符号 grep 重定向同一路）
         非符号 → 词面扫盘；LSP 基建失败 → 显式 failed（禁止词面冒充 Locate 成功）
Impact  ：edit_file.impact.references ← LSP references
Verify  ：edit_file.checks（写前语法门 + 写后增量诊断）+ read_lints = LSP ∪ CLI
词面    ：grep / lexical search_codebase（磁盘扫描；须 off-loop）
RAG     ：Profile **无** search_sources —— 讨论 Agent 结构时 **不考虑** 资料检索旁路
```

SWE-bench L1：默认可瞬态建 AST（评测 profile）；Locate 仍以 LSP 确认为权威。

#### 3.3.2 Agent 工作区异步 AST（已拆出 · A6 已接线）

Cursor 式「按 Work 冷启动 + 增量符号表 + GUI 进度 + DB 缓存」**不在本文展开**，以免与 SWE/Ops 评测主线缠在一起。

→ 见独立草案：[agent-workspace-ast-index.md](agent-workspace-ast-index.md)

要点摘要（详细契约以该文为准）：

- **不携带 RAG**；与 `sources/` embed 流水线隔离。  
- **主权在 `work_id`**，不在 GUI 模式点击。  
- 精确定义 / Impact / 诊断仍以 **LSP** 为准；索引可脏须显式 `stale`。  
- SWE/ops-l1 默认不持久。

### 3.4 Profile 工具事实（对照）

| Profile | 与结构 / RAG 相关的工具事实 |
|---------|------------------------------|
| `writing` | 有 `search_sources`；无 coding 结构工具 |
| `intel` | 有 `search_sources`；默认无 coding 结构工具 |
| `agent` | 有 `search_codebase` / `edit_file` / `read_lints` / …；**无** `search_sources` |

### 3.5 隔离规则（硬）

1. **工具白名单**：结构工具只写入 `agent.yaml`（及明确 coding 的 Profile）；RAG 入口只在 writing/intel 等资料向 Profile。  
2. **进程 / Job**：Language Server **不** 因 writing/intel Session 启动；Agent AST **job 按 Work** 调度（可在用户正停留在写作 GUI 时继续跑增量），但 **writing/intel 面板不展示、不调用** 其查询 API。  
3. **前缀**：writing / intel 的 `system.md` + `tools[]` 字节布局不因 Agent 结构改动而膨胀。  
4. **两条索引旁路不得混用**：  
   - RAG：`sources/` → 切块 → embed/FTS（写作/情报）；热语料以用户上传私有库为主  
   - Agent AST（旁路已接线）：工作区 → 符号表（**DB 持久 + 内存投影**，无向量）  
5. **Engine**：禁止 `if scenario`；「无工具注册 = 无能力」即隔离。  
6. **GUI**：模式切换只换 Scenario/面板；**禁止**把模式点击绑成「拆掉 / 重建」另一套索引。

### 3.6 边界情况

| 情况 | 行为 |
|------|------|
| 用户在 writing 工作区放了 `.py` | 仍无结构工具；可用资料向检索工具；不偷偷起 LSP；若该 Work 已启用 Agent AST，则 **异步脏更新**（写作 GUI 不显示进度） |
| GUI 点击 Agent ↔ 写作（同 Work） | 不重建 RAG / 不重建 AST；分别订阅各自进度通道；工具白名单瞬时切换 |
| 同一账号切换到另一 Work | 进度条与符号查询切到新 `work_id`；旧 Work 索引保留在 DB，idle GC 另议 |
| 另一账号同名路径 | ACL 隔离；不可见他人 `work_ast_*` 行 |
| runtime 重启 | 从 DB 恢复 meta + 符号投影；generation 不变则不必全量冷启动，按脏队列追平即可 |
| 同一 Work 先 writing 后切 agent Session | agent Session 可软预热 LSP；AST 进度显示该 Work 已有世代 |
| Agent Turn 内 `write_file` 新建代码 | **立即**对词面可见；下次 Locate 可走 LSP；**不**触发写作 RAG sync；Agent AST 异步脏更新 + 进度可短暂 `stale`/`building` |
| `delegate` 子 agent | 仅当子类型工具集包含结构工具时可用；写作子类型不可见 |
| intel 要读代码库 | 单独评审只读导航；不自动获得 Agent 全量写码结构面 |
| Ops L1 / SWE 临时 Work | 默认不写 AST DB（或短 TTL）；详见 [工作区 AST 草案](agent-workspace-ast-index.md) |

---

## 4. 架构放置：交互面 · LSP 结构服务 · RAG 隔离

```text
┌─────────────────────────────────────────────────────────────┐
│  Turn 交互面（AgentEngine loop）                             │
│  模型按需调用工具；写盘仍走 edit_file + 审批                 │
│  ✗ 禁止：assemble 内同步全库 parse / 强制起 LSP 再首 token │
└─────────────────────────────────────────────────────────────┘
        │ tool_result
        ▼
┌─────────────────────────────────────────────────────────────┐
│  结构服务（本文主线）                                         │
│  Language Server 池 · Locate/Impact/read_lints 适配器         │
│  生命周期与 Turn 解耦；失败显式 failed                        │
└─────────────────────────────────────────────────────────────┘
        │（场景隔离）
        ▼
┌─────────────────────────────────────────────────────────────┐
│  RAG sources 索引（writing/intel · 已有）                     │
│  sources/ → 切块 → embed/FTS · ✗ 不充当 Agent Locate        │
└─────────────────────────────────────────────────────────────┘

旁路（Agent 工作区 AST · A6 已接线 · GUI/Work/DB）→ agent-workspace-ast-index.md
```

热路径只 **使用** 已有结构，不 **同步重建**（R4）。

---

## 5. 速率红线 R1–R5：放置矩阵

权威定义见 [架构 §5](../core/architecture.md)。

| 红线 | 含义 | 结构智能如何遵守 | 违规示例 |
|------|------|------------------|----------|
| **R1** | 不挡受理 / TTFB | StartTurn 路径不 await LSP initialize；不 await 全库 parse | `turn.accepted` 前 `await language_servers.ready()` |
| **R2** | 首 token 前无同步模型 | 结构层是工具/索引，不加「先摘要代码再答」的模型调用 | 用 LLM 做符号提取当热路径 |
| **R3** | 热路径 CPU 毫秒级 | assemble / intake 不做重解析；重活在工具 handler 或旁路 | ContextEngine 每步 tree-sitter 整仓 |
| **R4** | 重活异步 | AST 切块、符号导出、server 预热均旁路 | 每次 `search_codebase` 先 rebuild index |
| **R5** | 可测才合并 | §10 门禁；无对照不合入 | 「本地手感好」无 golden |

### 5.1 允许的速率形态

| 形态 | 延迟落点 | 是否合宪 |
|------|----------|----------|
| 旁路软预热（Work 进入 agent 后后台 initialize） | 不挡 TTFB；首次工具可能已热 | ✅ |
| 首次结构工具冷启动 | 该次 tool 墙钟变长；结果标 `cold_start=true` | ✅（需 timeout） |
| edit 后对 **受影响路径** 调 `read_lints` | 单次工具延迟 | ✅（现有 CQ1 纪律） |
| `edit_file` 内联 **单文件** 语法门 + 增量诊断（Wave 2 W1，§7.3） | 单次工具延迟；语法门毫秒级、诊断有 timeout | ✅（timeout 强制、超时显式不失败 edit） |
| edit 后默认全仓库 LSP diagnostics | Turn 墙钟与上下文膨胀 | ❌ 默认禁用 |
| 索引面 tree-sitter 切块 | 查询路径不变 | ✅ |

### 5.2 超时与预算

- 每个结构工具必须有 `timeout_s`（建议导航 5–15s，诊断 15–60s，可配置）。  
- `tool_result` 继续走统一 budget（约 4k 截断 + 再读指针）；推荐 **紧凑行协议**，避免肥 JSON。  
- 并行：只读结构工具可与 `grep`/`read_file` 并行（现有只读并行规则）。

---

## 6. 交互逻辑：长在现有树上

权威：能力即工具；只读可并行；写盘审批；取消是终态；无 ResumeTurn。

### 6.0 当前端到端流程与问题清单（完整细节）

> 读本节即可回答：「现在一题 SWE L1 从点跑到交卷发生了什么、结构智能插在哪、还卡什么。」  
> 历史跑数与决策背景见 §6.7；协议与双轨见 §8。

#### 6.0.1 总览（两层）

```text
┌─ Ops L1 套件层（api / official_agent_path）─────────────────────────────┐
│  pull Lite → plan(n, checkout, harness) → mirror prewarm                 │
│  → 每题 checkout(commit) → StartTurn(agent) → 等 Turn 终态                │
│  → 抽 git_diff / 校验 apply → bucket →（可选）harness → 报告              │
└──────────────────────────────────────────────────────────────────────────┘
                              │ Work 已 materialize；prompt 含 Required loop
                              ▼
┌─ Turn 交互层（runtime AgentEngine while）────────────────────────────────┐
│  assemble → model → tool_use* → tool_result 回灌 → … → 终态              │
│  结构智能不改 while：只在工具 handler / 结果契约里生效（§6.0.3）           │
└──────────────────────────────────────────────────────────────────────────┘
```

#### 6.0.2 Ops L1 套件层（逐步）

| 步 | 谁 | 做什么 | 失败 / 注意 |
|----|----|--------|-------------|
| 1 | Ops UI / api | 开跑 L1 coding：`scenario_id=agent`，`checkout=True`（UI 锁定），可选 harness | checkout=False **已禁止**（API 400 / runner hard-require） |
| 2 | api | pull SWE-bench Lite instances（可缓存） | 缓存命中则跳过下载 |
| 3 | api | `coding plan`：n、parallel、checkout、harness | 日志可能因重入打两遍 plan；以真实 checkout 为准 |
| 4 | api | **suite mirror prewarm**：对本批涉及 repo 拉/暖 mirror | `ok`/`failed` 计数；失败题后面 checkout 易挂 |
| 5 | api | 每题 **checkout** 到 Work：`repo@commit`，写 `problem.md` | `mirror_hit`；**失败 → `checkout_failed`，不再 fallback 成「只有 problem.md」** |
| 6 | api | `StartTurn`：注入 L1 `coding_prompt`（Required loop：search_codebase Locate → edit → impact/lints） | 禁网：`OPS_EVAL_DENY_NETWORK` 须进 **runtime** 容器 |
| 7 | runtime | Turn 跑满 / 失败 / 取消（`max_steps` 现默认 **150**） | 步数触顶常见于半截 edit |
| 8 | api | 从 worktree 抽 patch（`git_diff`，含合理 untracked）；clean-HEAD / reverse **apply-check** | 拒收截断 / 不可 apply；脏树 forward-check 假阴性已修 |
| 9 | api | 分桶：`ok` / `no_patch` / `patch_no_apply` / `checkout_failed` / … | Official `process.jsonl` **只有 case 摘要**，无逐工具名 |
| 10 | api/harness | 可选跑 swebench harness → `resolve_rate` | **仍可能 exit 1**（见开放问题）；失败读 `harness.stdout.log` |

并行：同 suite 可 `parallel=2` 多题 Turn 同时跑（各 Work 隔离）。

#### 6.0.3 Turn 内写入流程（模型视角 + runtime 契约）

产品要求的阶段（`system.md` / L1 prompt）与 **runtime 强制契约** 对照：

```text
① Orient
   模型：读 problem.md / issue；抽出符号名、失败测试、路径提示
   Ban：list_dir(".") 摸根、repo tourism

② Locate（结构车道 · 已揉合）
   模型常点：grep / read_file /（偶尔）search_codebase
   Runtime：
     · search_codebase(符号) → adapters.goto_definition → definitions[]
     · grep(裸符号整串) → 内部同上，事件名仍是 grep，结果带 redirected_from
     · grep(报错串/regex) → 纯词面
     · LSP 基建挂 → status=failed（禁止词面冒充 Locate 成功）
     · 无 definition 仅有词面 → locate_incomplete=true
   精度：goto_definition（有 path:line / 多跳）——模型实测几乎不点

③ Read
   read_file 定义命中；完整读完后禁止无故再读同一 path（Read-after-complete）

④ Edit
   edit_file 唯一 span；失败则 read 一次再改 span
   Ban：无故 write_file 整文件重写；半截行

⑤ Impact（结构车道 · 已揉合 · 不依赖模型再点 find_references）
   edit_file 成功且路径为代码（当前 language_for_path：.py/.pyi）→
     extract_symbols_from_edit(old,new) → adapters.find_references →
     结果必含 impact{status,symbol,references,lines,…}
   非代码 / 抽不出符号 → impact.status=skipped
   LSP 基建挂 → impact.status=failed（文件已改，须显式暴露）

⑥ Verify
   模型应 read_lints(受影响路径)；必要时 run_tests / 最小 run_command
   read_lints = LSP ∪ ruff；LSP 基建挂 → status=failed

⑦ 结束
   worktree 上完整可 apply 的改动；平台用 git_diff 计分，不靠模型口述 patch
```

**符号判定（Locate 重定向门槛）** — `app/structural/symbols.py`：

- `is_symbol_query`：整串为 `Ident` 或 `a.b.c`，无空白、无 regex 元字符。  
- 例：`Widget` / `astropy.io.fits` → Locate；`ValueError: boom` / `def foo\(` → 词面 grep。

**Impact 符号抽取**：优先 span 内 `def`/`class`/… 头；否则 old/new 标识符差集；再否则旧 span 中出现的标识符。

> **Wave 2 落地态**（§7.3）：⑥ `edit_file.checks`（写前语法门 + 写后增量诊断）**已焊**；④ span 失配**已回显候选**；② Reproduce / 交卷自检为 **prompt 层已写**；pager→`read_file` 硬重定向仍为纪律文案（未做工具级强制改写）。

#### 6.0.4 一题内「实际常发生」的调用形态（实测）

设计期望 vs `01599d49` 上模型真实习惯：

```text
期望：problem.md → search_codebase(符号) → read_file → edit_file(+impact) → read_lints → tests
实测：problem.md → list_dir?/grep?/run_command(sed -n …) → read_file → …
      → edit_file →（很少 read_lints）→ …
      工具名：search_codebase=0, goto=0, refs=0；grep/read/run_command 占主导
```

因此揉合策略是：**不指望模型改点工具名**，而把 definition/references **焊进它已经会点的 grep / edit_file**。下一趟验收看结果字段，不看 `search_codebase` 计数（§6.7.6）。

#### 6.0.5 问题清单（当前）

| ID | 问题 | 状态 | 说明 |
|----|------|------|------|
| P1 | 无仓 / 仅 problem.md，结构工具无意义 | **已解** | checkout 强制 + mirror prewarm；失败 → `checkout_failed` |
| P2 | `STRUCTURAL_ENABLED` 默认关 / 评测未开 | **已解** | 开关删除；能力=Profile 白名单 |
| P3 | 缺 LSP 时静默降级成「grep/ruff 也行」 | **已解** | Locate/Impact/read_lints 基建失败 → 显式 `failed` |
| P4 | `max_steps` 触顶 → 半截 diff | **已缓解** | 默认 150；交卷拒截断；**W3 失败候选回显 + W5 交卷自检** 进一步压缩重试与半截（§7.3） |
| P5 | 脏树 `git apply --check` 假阴性 → 误 `patch_no_apply` | **已解** | clean-HEAD / reverse-check |
| P6 | harness 无法给出官方 `resolve_rate` | **已解（N0）** | 2026-08-11：看板预拉 n5 5/5 + `require_local`；首次完整 harness 跑次 `d459ca51` **产出真 `resolve_rate=0/5`**（非缺图/空 predictions）。详见 §6.7.8 |
| P7 | 模型不点 `goto_definition` / `find_references` / `search_codebase` | **部分解** | 能力已揉进 grep/edit；**adoption 的工具名 KPI 仍低**（预期，不再作 KPI；§7.6） |
| P8 | 大量 `run_command`+`sed -n` 当 pager | **方案已定** | Ban 文案已证偏弱；**W2 纯 pager 软重定向进 `read_file`**（§7.3，同 grep→Locate 手法），排 N3 |
| P9 | Impact 仅 Python 扩展（`language_for_path`） | **已知边界** | 非 .py 编辑 → `impact.skipped`；Lite 全 Python，暂不扩 |
| P10 | Ops 面板按工具名找不到 Locate | **文档澄清** | 事件名常为 `grep`；看 `definitions`/`redirected_from`；`process.jsonl` 无工具明细 |
| P11 | 揉合后尚未用新契约复跑 n5 验收 | **已有第二跑** | `d459ca51`（§6.7.8，resolve 0/5）→ **`b3357dd6`（§6.7.9，resolve 3/5）**：交卷/impact/checks 仍满；官方通过跃迁；Locate fuse 仍弱。双轨 AST on/off 仍排后续 |
| P12 | Verify 车道 adoption 同样趋零（两题 `read_lints`=1；纪律催用无效） | **方案已定** | 与 P7 同根：独立工具名不在控制环里。**W1：`checks`（写前语法门 + 写后增量诊断）焊进 `edit_file` 成功契约**（§7.3），排 N1 |

#### 6.0.6 合宪边界（流程里故意不做的）

- **不**在 `turn.accepted` 前 await LSP ready / 全库 parse（R1）。  
- **不**改 AgentEngine `while`、不加「先 LSP 再说话」节点。  
- **不**把 writing Profile 挂上结构工具。  
- **不**默认每次 edit 后全仓库 diagnostics。  
- **不**为分数预注入符号大纲或读 gold patch。

### 6.1 工具族（已落地）

| 工具 | side_effect | 审批 | 说明 |
|------|-------------|------|------|
| `read_lints` | read | 默认无 | **保留原名**：LSP∪CLI；CQ1「edit 后 read_lints」 |
| `search_codebase` | read | 无 | **Locate 主入口（名）**：符号 → 同 `goto_definition` 适配器 → `definitions[]`；非符号词面；LSP 基建失败 → `status=failed` |
| `grep` | read | 无 | 精确串 / regex；**裸符号整串重定向**到 Locate（事件名仍是 `grep`，结果含 `redirected_from`） |
| `goto_definition` | read | 无 | **精度面**：已有 path/line 或需消歧多跳 |
| `find_references` | read | 无 | **精度面 / 加深**；成功代码 `edit_file` 已附同传感器 `impact` |
| `edit_file` | write | 有 | 成功且代码路径 → **必附** `impact.references` |
| （阶段 D）`rename_symbol` 等 | write | always | 显式写副作用；默认不开 |

不新增 Engine 相位。观测：工具结果字段 `definitions` / `locate_incomplete` / `impact` / `redirected_from`；事件仍走 `tool.started|completed`（`payload.tool_name`）。

### 6.2 写入闭环（agent `system.md` — 阶段契约，非可选）

```text
1. Orient：从 issue / problem.md 抽符号与错误串（禁止 root list_dir 开局）
2. Locate：符号 → search_codebase（必交付 definitions[]；同 goto_definition 适配器）
         裸符号若误点 grep → runtime 重定向同一 Locate（见 §6.7）
         精度跳转 → goto_definition；词面/报错串 → grep；文件名 → glob
         locate_incomplete / 空 definitions ≠ Locate 完成
3. Read → Edit：read_file 后 edit_file 最小 span
4. Impact：代码 edit_file 成功结果必须带 impact.references（同 find_references 传感器）
         显式 find_references 用于加深 / 改签名预扫
5. Verify：read_lints(受影响路径) → 必要时 run_tests
6. 结束：交付物 + 简要 what-changed
```

揉合口径：能力进 **流程入口与写成功契约**；`goto_definition` / `find_references` 保留为精度面，不是可跳过旁支。

### 6.3 审批与沙箱

| 点 | 规则 |
|----|------|
| 只读导航 / 诊断 | 不打断用户；不进 write 审批 |
| 文件编辑 | 仍走现有 `edit_file` / `write_file` 审批覆盖 |
| Language Server 进程 | 跑在 Work 边界内；**deny-by-default env**（与 shell 子进程同纪律）；不继承宿主机密钥 |
| 会执行项目配置的 server | 威胁模型单列（§11）；可先 allowlist 语言（如 pyright 只读诊断模式） |
| `run_command` 与 LSP | 禁止用 shell 当 LSP 替代仪式去「cat 源码」——Ban 列表已有 pager 纪律，保持 |

### 6.4 取消 / 失败 / 挂起

| 情况 | 行为 |
|------|------|
| 用户 Cancel | Run 终态 `cancelled`；进行中的 LSP 请求取消；**不**引入 ResumeTurn |
| 审批 waiting | server 可保活（Session/Work 级）；checkpoint 语义不变 |
| LSP timeout | 工具返回可恢复错误 + 建议降级；模型应改用 grep/ruff |
| Server crash | 标记不健康；同 Turn 内降级；旁路可重启，不挡下一 Turn 受理 |
| 不支持的语言 | 明确 `unsupported`；勿假装成功 |

### 6.5 与上下文组窗

- 结构工具结果进 Conversation，走 budget / read_fold 同类卫生。  
- 禁止每轮预注入「全项目符号大纲」（违反 RAG/上下文「按需工具回灌」纪律，也伤 R4 精神）。  
- agent 稳定前缀因新 `tools[]` 变长：必须描述 hygiene（CQ2）+ 前缀稳定测试；**加厚须可被 cache 抵消**。

### 6.6 子 agent

| 子类型 | 结构工具 |
|--------|----------|
| `explore` / `retrieve` | 导航 + 搜索 |
| `verify` | `read_lints` + 可选 references + `run_tests` |
| `edit` | 编辑工具 + 验证；导航按需 |
| 写作向 `drafter`/`stylist` 等 | 不开放 |

### 6.7 揉合、Ops 实测与完整过程记录（2026-08-10 → 08-12）

**当前流程与问题总表以 §6.0 为准。** 本节是同一事实的历史纪要：早期 n5 数字、复跑工具面计数、揉合决策、**首次完整 harness 官方 resolve**、验收探针。

#### 6.7.1 时间线（过程）

| 时间 | 阶段 | 发生了什么 |
|------|------|------------|
| 2026-08-10 | 早期 n5（`d10472fd` / 子跑 `309e5ab1`） | checkout 有仓；`propose_patch` 已移除；patch 来自 `git_diff`；**patch_rate=0.6** 但 3×`patch_no_apply`（截断 span / 脏树假阴性）；harness **exit 1** → 无 `resolve_rate`；`max_steps` 偏紧 |
| 随后 | 基建与交卷链 | `max_steps`→150；patch 提取含 untracked；apply-check 改 clean-HEAD；harness 日志加厚；去掉 `STRUCTURAL_ENABLED` 产品开关（能力=Profile）；checkout 强制；suite mirror prewarm；checkout 失败不再 fallback 到仅 `problem.md` |
| 2026-08-11 | 复跑 n5（`01599d49`） | checkout/mirror **正常**；14182 交出可 apply `git_diff`（`bucket=ok`）；但 **`search_codebase`/`goto_definition`/`find_references` 调用为 0** —— 新问题从「供给」变为 **adoption/绑定** |
| 同日 | 产品决策 | 禁止「够用 / 可选」；将 definition/references **揉进** agent 流程：Locate 焊 `search_codebase`+裸符号 `grep` 重定向；Impact 焊 `edit_file.impact`；精度面保留显式 goto/refs |
| 同日 | 落地 | `symbols.py` + tools handler + `system.md` + L1 `coding_prompt`；runtime recreate；单测覆盖 Locate/Impact 契约 |
| 2026-08-11 | N0 诊断（P6） | 后续 infer（如 `4b2a89c6` / `69f166f2`）**`patch_rate=1.0`**，但开启 harness 时卡在 `Evaluation: 0/5`、实例 `run_instance.log` 空；根因：**本机无 `swebench/sweb.eval.x86_64.*`**，harness 在 **agent-api（ops-eval sock）** 内现拉 Docker Hub **挂死**（连 `hello-world` 亦 Waiting）。早期「完成」的 harness（`8be119d4`）实为 **空 predictions / empty_patch** → `resolve_rate=0`，不是模型真测。默认 `cache_level=env` 会在评后删实例图，下次再挂 |
| 同日 | N0 方案落地 | `suites.coding.harness`：`cache_level=instance`、`clean=false`、`require_local_images=true`、`board_tier=n5`；`scripts/official_bench/swe_images.py` + `coding --phase pull-images` / `make official-bench-coding-pull-images`；**部署看板 :9090** 项「Ops · SWE eval 镜像」一键预拉；进度写 `reports/release/swe_eval_images_progress.json`，看板 live 显示 **n/N · % · 当前 ref** + 日志 tab「SWE 镜像」。单图压缩约 **1.0–1.2 GiB**（n5 ≈ 5–6 GiB），**不进 git / 不进产品镜像** |
| 2026-08-11 晚 | N0 出口达成 | 本机预拉 **n5 5/5** `sweb.eval`；看板增 **Ops Bench worker**（`start-bench` 秒级拉起，避免误点 `up-bench` 全量重建）；`agent-bench` healthy 后 Ops meta 正常 |
| 2026-08-11→12 | 完整 harness n5（`d459ca51`） | **首次真跑完官方 evaluate**：`patch_rate=1.0` · `apply_ok=5/5` · **`resolve_rate=0.0`（0/5）**；分桶 `patch_not_resolved`×4 + `no_verify`×1（14182 turn 超时）。过程：`locate_fuse≈0.36` · `impact_cov=1` · `checks_cov=1` · `syntax_rej=0`。结论：**基建/harness 过关，效果（官方通过）仍差** — 见 §6.7.8 |
| 2026-08-13 | 完整 harness n5（`b3357dd6`） | **官方 resolve 3/5（60%）**：patch/apply 仍满分；分桶 `ok`×3 + `patch_not_resolved`×2（无 no_verify）。过程：`locate_fuse≈0.27`（仍弱，主桶 no_ws_symbol）· impact/checks=1 · span_fail=0。结论：**效果跃迁真实；Locate 与 resolve 脱钩** — 见 §6.7.9 |

#### 6.7.2 早期 n5 套件结果（`d10472fd`，2026-08-10）

来源：`TEST.log` + 跑次 `d10472fd-548b-4dbe-8299-306f86921a41`（子套件 `309e5ab1-f872-4457-a1f9-c1e56279dd72`）。UTC 约 15:57–16:39。

**配置**

| 项 | 值 |
|----|-----|
| 路径 | L1 agent-path（`scenario_id=agent`） |
| tier | n5（5 题，全 astropy） |
| checkout | 是（`has_repo=true` / `mirror_hit=true`） |
| harness | 开启，但 **exit 1** → 无 `resolve_rate` |
| 写工具 | 白名单已无 `propose_patch`；patch 来源 `git_diff` |

**套件指标**

| 指标 | 值 | 含义 |
|------|-----|------|
| `n_instances` | 5 | 题数 |
| `n_nonempty_patches` | 3 | 非空 patch |
| `patch_rate` | 0.60 | 3/5 非空 diff（≠ 官方 resolve） |
| `harness_error` | `harness exit 1` | 无 `resolve_rate` |

分桶：`patch_no_apply`×3（60%）、`no_patch`×2（40%）。

**逐题**

| instance | bucket | source | apply | steps | terminal | 备注 |
|----------|--------|--------|-------|-------|----------|------|
| `astropy__astropy-12907` | `no_patch` | none | — | 12 | failed | 有 `ran_tests`；无提取 diff |
| `astropy__astropy-14182` | `no_patch` | none | — | 57 | failed | 步数触顶附近；无 patch |
| `astropy__astropy-14365` | `patch_no_apply` | git_diff | no | 50 | completed | diff ~1.8k，当时 `apply --check` 失败 |
| `astropy__astropy-14995` | `patch_no_apply` | git_diff | no | 50 | completed | diff ~0.7k |
| `astropy__astropy-6938` | `patch_no_apply` | git_diff | no | 50 | completed | diff ~0.6k |

抽查可见 **diff 行中截断**（半写 span）。事后确认：在已脏 worktree 上做 forward `git apply --check` 会把合法完整 diff 也判失败 —— 已改为 clean-HEAD / reverse-check；解读本跑桶分布需打折。

**当时结论**

1. 尚不能谈官方 resolve（harness 失败）。  
2. 相对伪 `propose_patch` 有进步（真实 worktree diff）。  
3. 主卡点曾是「落笔可 apply」+ 步数；测量假阴性已修。  
4. 下一步曾排：harness → 完整 diff 门禁 → 再跑 n5（结构 adoption 另计）。

产物路径：`eval/reports/official/runs/309e5ab1-…/`；聚合 run `d10472fd-…`。Ops 报告链曾修：鉴权 blob 打开、聚合 HTML CSS。

#### 6.7.3 复跑 n5：基建健康 vs 工具 adoption（`01599d49`，2026-08-11）

跑次：`01599d49-2ef1-441f-bf28-15066b2d948e`。checkout=`True`，mirror prewarm ok，结构能力已在 Profile（无开关剥离）。

抽样 Turn：`f7346ade…`（astropy-14182）、`d0a2c024…`（astropy-12907）。

14182：`patch_source=git_diff` · `patch_applies=true` · `bucket=ok` · 12 步（`terminal_state=failed` 但仍可 apply）。

**本跑两题 `tool.started`（`turn_events`）**

| tool_name | count |
|-----------|------:|
| `run_command` | 36 |
| `read_file` | 20 |
| `grep` | 6 |
| `edit_file` | 5 |
| `list_dir` / `glob` | 3 / 3 |
| `read_lints` | 1 |
| `search_codebase` | **0** |
| `goto_definition` / `find_references` | **0 / 0** |

**全站近 14 天对照（含非 SWE）**

| tool_name | count |
|-----------|------:|
| `read_file` | 5288 |
| `grep` | 2072 |
| `list_dir` | 1473 |
| `search_sources` | 1376 |
| `run_command` | 419 |
| `edit_file` | 34 |
| **`search_codebase`** | **27** |
| `read_lints` | 6 |
| `goto_definition` | **0** |
| `find_references` | **0** |

**读法**

1. **供给已满足**：仓在、工具在白名单 —— 不是「没挂上」。  
2. **adoption 失败**：SWE 上模型几乎不点 `search_codebase` / 精度导航；主路径 `run_command` + `read_file` + `grep`。  
3. **新问题定义**：结构能力在菜单里，不在控制环里；纪律催用独立工具已证偏弱。  
4. **产物注意**：Official `process.jsonl` 只有 case 摘要，**不含**逐工具名；分布查 `turn_events` 或实时 `tool.started`。

#### 6.7.4 设计意图 vs 模型真实习惯 → 揉合决策

| | 设计（纪律 / 描述） | Ops 实测 | 决策（禁止够用/可选） |
|--|---------------------|----------|----------------------|
| Locate 入口名 | 优先 `search_codebase` / `goto_definition` | 几乎不点；常点 `grep` | Locate **实现**焊进符号向 `search_codebase` + **裸符号 `grep` 重定向** |
| Impact | 再调 `find_references` | ≈0 | **焊进** `edit_file` 成功回灌 `impact.references` |
| 精度面 goto/refs | 一等工具 | 调用 0 | **保留**（可测/加深/委派）；不删成「增强 grep」 |
| Verify | `read_lints` | 偶发 | 保留 CQ1；与 Impact 并列 |

#### 6.7.5 Runtime 实际调用链（已落地）

```text
模型调用 search_codebase(query)
  ├─ is_symbol_query? 否 → 词面 hits（mode=lexical）
  └─ 是 → adapters.goto_definition
        ├─ LSP 基建失败 → status=failed（禁止词面冒充 Locate 成功）
        ├─ 有 definitions → locate_incomplete=false
        └─ 无 definitions → 词面兜底 + locate_incomplete=true

模型调用 grep(pattern)
  ├─ 裸符号整串 → 内部转 search_codebase（同上）
  │     tool 事件名仍是 grep；结果含 redirected_from=grep + definitions/…
  └─ 否则 → 词面/regex matches

模型调用 edit_file(path, …) 且 apply 成功
  ├─ 非代码扩展名 → impact.status=skipped (non_code_path)
  ├─ 抽不出符号 → impact.status=skipped (no_symbol_detected)
  └─ 代码 + 有符号 → adapters.find_references → impact.references
        └─ LSP 基建失败 → impact.status=failed（edit 本身仍 edited）

模型调用 goto_definition / find_references
  └─ 精度面直达同一 adapters（可测、可委派、可加深）
```

代码锚点：`app/structural/symbols.py` · `app/tools/core/tools.py` · `app/tools/bootstrap.py` · `scenarios/agent/system.md` · `scripts/official_bench/l1_prompts.py`。

#### 6.7.6 在 Ops 里怎么观测揉合

| 错误读法 | 正确读法 |
|----------|----------|
| 面板搜不到 `search_codebase` ⇒ Locate 没进流程 | SWE 常点 **`grep`**；看结果是否含 `redirected_from` / `definitions` / `locate_incomplete` |
| 没有 `find_references` 事件 ⇒ 无 Impact | 看 **`edit_file` completed** 是否含 `impact` |
| `process.jsonl` 无工具名 | 查 **`turn_events`** / 实时 `tool.started` |

下一趟 n5 验收探针：**以 §7.6 的 Wave 1+2 合并清单为准**（本节原有三条已并入其中）。

#### 6.7.7 仍开放

- 重定向路径可附加 `meta.locate=search_codebase` 方便面板过滤（未做）。  
- `run_command`+`sed -n` 读源仍偏高：Ban 文案已证不够，改走 **W2 软重定向**（§7.3）。  
- **官方 resolve 效果**：N0 可测后已有第二跑（§6.7.9 **`resolve_rate=3/5`**）；下一优先仍是 **Locate（fuse / incomplete / AST 双轨）** 与剩余 `patch_not_resolved` 的修复正确性，勿混成单指标。整体下一步已成文：**§7.7 Wave 3**。  
- Verify 车道：两跑 `checks_cov=1.0`（编辑护栏在干活）；独立 `read_lints` adoption 仍非 KPI。

#### 6.7.8 完整 harness n5（`d459ca51`，2026-08-11→12）— 首次官方 resolve 可测

来源：`TEST.log`（Ops smoke HTML 摘要）· 跑次 `d459ca51-ba98-4462-90d8-edae0144a2b2`。  
配置：L1 agent-path · **tier=n5** · checkout=True · **harness=yes** · mirror prewarm ok=1 · 本地 `sweb.eval` 5/5。

**套件指标**

| 指标 | 值 | 含义 |
|------|-----|------|
| `n_instances` | 5 | 题数（全 astropy） |
| `n_nonempty_patches` | 5 | 非空 patch |
| `patch_rate` | **1.000** | 5/5 交出 diff |
| `apply_ok` | **5/5** | `git_diff` 均可 apply |
| `resolve_rate` | **0.000** | **官方 fail-to-pass 0/5** |
| `n_resolved` | 0 | 同上 |
| `locate_fuse_ok_rate` | 0.364 | n=11 · 定位偏弱 |
| `edit_impact_coverage` | 1.000 | 有编辑时 Impact 覆盖满 |
| `edit_checks_coverage` | 1.000 | 有编辑时 checks 覆盖满 |
| `syntax_reject_count` | 0 | 无语法拒编 |
| `span_fail_n` | 1 | 失配 1 次（带候选） |
| `n_grep_locate_incomplete` | 7 | Locate 未完成偏多 |
| harness `exit_code` | 1 | 零通过时的正常语义（报告已归档） |

分桶：`patch_not_resolved`×4（80%）· `no_verify`×1（20%）。

**逐题**

| instance | bucket | apply | 官方 | steps | terminal | 备注 |
|----------|--------|-------|------|------:|----------|------|
| `astropy__astropy-14365` | `patch_not_resolved` | yes | 未过 | 32 | completed | span_fail=1；grep_ok=0 |
| `astropy__astropy-12907` | `patch_not_resolved` | yes | 未过 | 105 | completed | edits=5；仍未 resolve |
| `astropy__astropy-14182` | `no_verify` | yes | 未过 | — | **failed** | turn 超时等待 completed；未完整 verify |
| `astropy__astropy-14995` | `patch_not_resolved` | yes | 未过 | 99 | completed | edits=16 · reads=19；最重编辑仍未过 |
| `astropy__astropy-6938` | `patch_not_resolved` | yes | 未过 | 56 | completed | reads=36 · grep_ok=0 · edits=1 |

**读法（钉死）**

1. **N0 出口已达成**：缺图/空 predictions 误报时代结束；本 `resolve_rate=0` 是 **真测零分**，不是基建假象。  
2. **L1「有 patch」≠ 官方过**：patch/apply 满分只说明交卷链健康。  
3. **效果不好的主因**：定位偏弱（fuse≈36%、多题 grep_ok=0）+ 修复未过 fail-to-pass；编辑护栏（impact/checks）在线但救不了「改错点/改错逻辑」。  
4. **14182** 单独记为超时/`no_verify`，勿与「改错了」混桶。  
5. 下一优先：压 locate incomplete / pager 重定向（W2）→ 再谈模型与双轨分数。

#### 6.7.9 完整 harness n5（`b3357dd6`，2026-08-13）— 官方 resolve 3/5

来源：`debug.log`（Ops smoke HTML 摘要 + `official.coding_infer.*` 指标）· 跑次 `b3357dd6-19d5-4669-ae06-ec3bc1a50d27`。  
配置：L1 agent-path · **tier=n5** · **harness=yes** · smoke · mirror prewarm ok=1。

**套件指标（对照 §6.7.8）**

| 指标 | `d459ca51` | **本跑** | 含义 |
|------|------------|----------|------|
| `patch_rate` | 1.000 | **1.000** | 5/5 非空 patch |
| `apply_ok` / `n_nonempty_patches` | 5/5 | **5/5** | 均可 apply（`git_diff`） |
| `resolve_rate` | **0.000** | **0.600** | **官方 fail-to-pass 3/5** |
| `n_resolved` | 0 | **3** | 同上 |
| `locate_fuse_ok_rate` | 0.364（n=11） | **0.273**（n=11） | Locate 仍弱，略低于先前 |
| `n_locate_fuse_no_ws_symbol` | — | **10** | fuse 失败主桶（AST 索引主责） |
| `n_locate_fuse_definition_null` | — | 1 | 有候选但 definition 空 |
| `n_locate_fuse_lsp_failed` / timeout | — | 0 / 0 | LSP 基建未挂 |
| `n_grep_locate_incomplete` | 7 | **8** | 词面 incomplete 仍高 |
| `edit_impact_coverage` | 1.000 | **1.000** | Impact 揉合满 |
| `edit_checks_coverage` | 1.000 | **1.000** | checks 揉合满 |
| `syntax_reject_count` / `span_fail_n` | 0 / 1 | **0 / 0** | 编辑护栏干净 |
| harness `exit_code` | 1 | **0** | 有通过时的正常语义 |

分桶：`ok`×3（60%）· `patch_not_resolved`×2（40%）· **无** `no_verify` / `no_patch`。

**逐题**

| instance | bucket | apply | 官方 | steps | reads | grep_ok | impact/checks | patch 字 |
|----------|--------|-------|------|------:|------:|--------:|--------------:|---------:|
| `astropy__astropy-12907` | `ok` | yes | **通过** | 55 | 10 | 0 | 10 / 10 | 506 |
| `astropy__astropy-14995` | `ok` | yes | **通过** | 42 | 15 | 1 | 1 / 1 | 999 |
| `astropy__astropy-6938` | `ok` | yes | **通过** | 48 | 21 | 1 | 1 / 1 | 733 |
| `astropy__astropy-14365` | `patch_not_resolved` | yes | 未过 | 35 | 5 | 0 | 2 / 2 | 619 |
| `astropy__astropy-14182` | `patch_not_resolved` | yes | 未过 | 72 | 22 | 1 | 2 / 2 | 1359 |

**读法（钉死）**

1. **效果跃迁真实**：相对 §6.7.8 的 0/5，本跑 **3/5 官方通过**（12907 / 14995 / 6938）；不是空 predictions / 缺图假象。  
2. **交卷与揉合仍非短板**：patch/apply/impact/checks 继续满分；失败 2 题均为「改了、可 apply、官方测试未绿」。  
3. **Locate 与 resolve 脱钩**：fuse≈27%（主桶 `no_ws_symbol`）低于先前 ~36%，但 resolve 大涨——通过题里 12907 的 `grep_locate_ok=0`，说明可以「定位一般仍修对」。  
4. **未过两题画像**：14365 路径最短（35 steps / 5 reads）偏改少或改偏；14182 最长（72 / 22）且先前曾 `no_verify` 超时，本跑完整完成仍 `patch_not_resolved`——偏修复正确性 / 验证相位（Wave 2），非交卷失败。  
5. **下一刀分开量**：AST 双轨认领 fuse / incomplete（§7.7.2 D2）；剩余 `patch_not_resolved` 走 **Wave 3 修复正确性主攻（§7.7）**。勿用 resolve 单指标混评索引 on/off。

---

## 7. 揉合波次：Wave 1 落地态与 Wave 2 方案

### 7.0 波次总览

| 波次 | 内容 | 状态 |
|------|------|------|
| **Wave 1** | 结构基建 + **Locate/Impact 揉合** | **已落地**（行为契约 §7.1） |
| **Wave 2** | Verify（`edit_file.checks`）· span 候选回显 · Reproduce/交卷自检（prompt）· pager 纪律 | **主项已落地**；pager 工具级硬重定向仍开放（§7.3 W2） |
| **Wave 3** | **修复正确性主攻**：证据归档 D1 · AST 符号供给 D2 · `read_file` 截断折叠 W7 · `edit_file.related_tests` W8 | **方案已定（§7.7，未实施）** |
| Wave 3 外候选 | 按需 repo map · 写副作用结构操作（原阶段 D） | 后置（§7.4） |

Wave 2 的核心判断来自实测（§6.7.3）：**模型的控制环只经过 `run_command` / `read_file` / `grep` / `edit_file` 四个高频动词**。Locate/Impact/Verify 与 span 恢复已焊进结果契约；Reproduce/交卷为 prompt 层。**不新增模型必须主动学会点的工具名**。正文摘要见 [工具与上下文](../core/tools-and-context.md) 图 3。

### 7.1 Wave 1 落地态（原阶段 A–C 的行为契约，已落地）

每项默认 **仅 agent Profile**。以下逐情况表是已落地实现的**规范性契约**，回归时对照。

#### 7.1.1 阶段 A — 验证车道升级（已落地）

要点：`read_lints` = LSP∪ruff（支持语言走 LSP diagnostics，否则 CLI，再否则显式降级）；pyright langserver **openFilesOnly** + `didOpen` 定向（禁 workspace 全量——django 量级全量分析分钟级）；诊断优先 LSP 3.17 pull，push 差异由适配器屏蔽；范围=调用方 path，目录有文件数/深度上限。

**行为契约（各种情况）**

| 情况 | 期望 |
|------|------|
| 仅 Python + ruff 可用 | 行为 ≈ 今天 |
| Python + pyright LSP | 诊断可含类型；输出统一成 issues[] |
| 编辑了 `foo.ts` 但无 tsserver | `unsupported` 或 CLI fallback；不失败整 Turn |
| path 出 Work 根 | 与现有工具同样拒绝 |
| 沙箱无网络、需下加载插件 | 不允许运行时下载体；镜像预装 |

回归基线：golden「edit → read_lints → 修新增问题」；ruff-only 不回归；writing Profile 工具列表不变。

#### 7.1.2 阶段 B — 只读导航 + Locate/Impact 揉合（已落地）

要点：`goto_definition` / `find_references` 输入**符号名为主**（适配器内 `workspace/symbol` 两跳，模型只见一次调用；path+行列作消歧提示）；输出紧凑位置列表**每条附单行源码**（行协议 §9.4）；与 A 共用同一 pyright 会话（Work 级进程池）。实测模型几乎不主动点这两个名字，故 **Locate 焊进符号向 `search_codebase` + 裸符号 `grep` 重定向，Impact 焊进 `edit_file.impact`**（完整调用链 §6.7.5）；显式双工具保留为精度面。

**行为契约（各种情况）**

| 情况 | 期望 |
|------|------|
| 符号有唯一定义 | 返回定义（含源码片段）；需要更多上下文再 `read_file` |
| 多定义（重载/同名） | 列表返回，不擅自选 |
| 符号名解析不到（拼写差异/动态属性） | 空候选 + 明确建议改用 `grep` 词面；**不**静默转 grep 结果伪装成符号命中 |
| 未打开过的文件 | server didOpen 后查询；计冷路径 |
| 仅词面同名、非引用 | 不得把 grep 结果伪装成 references |
| server 不可用 | 错误 + 提示用 grep；禁止空 hits 装成功 |

回归基线：跨文件改签名类 golden（references 覆盖调用点）；工具误选类不回归；lite-50 文件级定位命中率对照（§8.3）。

#### 7.1.3 阶段 C — 索引面 AST（已落地为可选依赖，正则回落）

要点：`chunking.py` 代码路径优先 tree-sitter（`py-tree-sitter` + `tree-sitter-language-pack`，构建期安装），失败回落 CQ4 正则；仅旁路（`index_scheduler` / sync-sources）执行；chunk 元数据保留 `symbol` / `section_title` / 行列。**与 SWE-bench Lite 解耦**（harness 工作区无预建索引），验收用离线切块对照（未做，见 §9.3）。

**行为契约（各种情况）**

| 情况 | 期望 |
|------|------|
| 支持语言 | AST 边界切块 |
| 不支持/解析失败 | 正则 CQ4 或整文件滑窗；索引任务不因单文件失败崩溃 |
| 超大生成文件 | 预算上限；跳过或降级，可观测 |
| 查询热路径 | **零** 新增同步 parse |

回归基线：离线切块对照（同 query 命中率/边界完整率）；`search_sources` 相关评测不因切块变差；R1–R3 延迟对照持平。

#### 7.1.4 阶段 D — 写副作用结构操作（维持后置，未落地）

`rename_symbol` / 有限 code action；`approval=always`；重命名多文件须可审批可取消；server 部分成功须明确失败集，禁止静默半应用；与手工编辑冲突则失败回读。单独评审，不进 Wave 2。

### 7.2 借鉴：成熟 agent 的已验证做法 → 本仓映射

选取标准：只借鉴**有公开消融/长期产品验证**、且落点是「模型实际高频动词」的做法；与我们「揉合而非催用」的实测结论一致的优先。

| 来源 | 被验证的做法 | 为什么可信 | 映射到本仓（Wave 2） |
|------|--------------|------------|---------------------|
| SWE-agent（ACI 研究） | **lint 门控编辑**：edit 引入语法错误则拒绝写入并回显错误位置 | 其 ACI 消融中**单项收益最大**的接口改动；直接治「半截 diff / 改坏」 | **W1 语法门**：`edit_file` 写盘前 parse 新全文，坏则拒收（含逃生门） |
| SWE-agent | 观察结果必须**紧凑**（搜索限条数、文件窗口化） | 同上消融；肥输出挤占上下文与步数 | 已有 budget/行协议（§9.4）；W1/W3 新回灌沿用同协议 |
| Cursor / Claude Code | edit 后**自动回灌 lint 增量**，模型无须主动点 lint 工具 | 两个最大规模 coding agent 的默认产品行为 | **W1 checks.new_issues**：写后单文件增量诊断随 `edit_file` 结果附回 |
| Claude Code（text_editor） | str-replace **失配时回显最近候选**，而非裸失败 | 产品验证：显著减少「read→重试」空转 | **W3 编辑失败恢复** |
| Anthropic SWE-bench 配方 / OpenHands | **先复现失败 → 修 → 复跑同一命令**；工具面保持极简 | 公开复盘中对 resolve 提升最稳定的流程纪律 | **W4 Reproduce 相位**（纯 prompt，零新工具） |
| OpenHands / Devin | 交卷前**自检**（diff 非空、无半截、测试复跑过） | 产品行为；直接对应我们 `no_patch`/`patch_no_apply` 桶 | **W5 交卷自检契约** |
| Aider | tree-sitter **repo map**（符号级仓库骨架，按引用排序注入） | 长期产品验证，但形态是**预注入**，与否决 8 冲突 | 改造为按需工具后列 **Wave 3 候选**（§7.4），本波不做 |

共同规律：这些 agent 没有一个靠「加工具名 + 文案催用」获得结构收益——收益全部来自**把结构信息焊进模型无法绕开的动词**（edit 的结果、失败的回显）。这与我们 `01599d49` 的实测结论（§6.7.3/§6.7.4）互为印证，Wave 2 是同一决策在 Verify/恢复车道上的延伸。

### 7.3 Wave 2：把 Verify、失败恢复、复现纪律焊进高频动词

全部改动落在**工具 handler 与 prompt 文案**：不加 Engine 节点、不预注入、不新增模型需学会主动点的工具名；writing Profile 零感知。

| 项 | 状态（2026-08-13） |
|----|---------------------|
| **W1** `edit_file.checks` | **已落地** |
| **W2** pager → `read_file` 硬/软重定向 | **未做工具级改写**（仅 system 纪律文案）；排期仍见 N3 |
| **W3** span 失配候选 | **已落地** |
| **W4** Reproduce 相位 | **已落地**（prompt） |
| **W5** 交卷自检 | **已落地**（prompt） |

#### W1 — Verify 揉合：`edit_file` 附 `checks`（已落地）

**动机**：P12——两题 `read_lints` 仅 1 次；Verify 与 Locate/Impact 一样，必须焊进写成功契约而非等模型自觉。

**契约**：代码路径 `edit_file` 结果增加 `checks{status, syntax, new_issues[], baseline_count}`，分两拍：

1. **写前语法门（毫秒级）**：apply 前 parse 编辑后全文（Python 用 `ast.parse`；其他语言 tree-sitter 可用则用，否则 skip）。**旧文本可 parse 而新文本不可 → 拒绝写盘**，返回 `syntax_error` + 出错行单行源码，worktree 不落脏。**逃生门**：旧文本本身 parse 失败 → 仅警告放行（允许修复本就坏的文件）；不支持语言 → `checks.syntax=skipped`。
2. **写后增量诊断**：对该 path 内部跑 read_lints 同款车道（LSP openFilesOnly ∪ ruff），与**写前基线做差集**，只回灌 `new_issues[]`（上限条数，行协议 §9.4）。timeout / LSP 基建挂 → `checks.status=timeout|failed`，**不影响 edited 结果本身**。

**速率**：单工具时延内；语法门毫秒级；诊断沿用 `structural_diag` 预算与 timeout（§5.1 已列为合宪形态）。禁止借 checks 做全仓诊断（§6.0.6 不变）。

**与 CQ1 关系**：`read_lints` 工具与纪律保留——跨文件/目录级验证仍需显式调用；checks 覆盖的是「刚改的这个文件」这条最高频路径。

**验收**：代码 edit 成功结果 100% 含 `checks`；语法门拦截数与**误拦率**（旧文件已坏场景）单列进观测；n5 复跑 `patch_no_apply` 桶占比应下降。

#### W2 — pager 软重定向：`run_command` → `read_file`（仍开放）

**动机**：P8——两题 36 次 `run_command`，大量 `sed -n 'A,Bp'` 当 pager，绕开 read-fold / 预算 / Read-after-complete 卫生，还烧步数；Ban 文案已证无效。

**契约**：`run_command` handler 识别**纯 pager 型命令**——整条命令无管道 / 重定向 / `&&` / `;`，形如 `sed -n 'A,Bp' path`、`cat path`、`head -n K path`、`tail -n K path`、`awk 'NR>=A&&NR<=B' path`，且 path 在 Work 内——内部转 `read_file(path, 对应行窗)`；事件名仍 `run_command`，结果含 `redirected_from=run_command`。与裸符号 `grep` 重定向完全同一手法。

**保守边界**：任何带管道、多命令、写副作用或解析不确定的命令 → **原样执行，不猜**；误伤率进观测。不升级为硬 Ban（拒绝执行会伤交互，先软重定向看数据）。

**验收**：重定向命中数 / 误伤数；pager 型 `run_command` 占比对照下降。

#### W3 — 编辑失败恢复：span 失配回显候选（已落地）

**动机**：P4 的主要形态是 span 重试打转烧步数（早期 n5 三题 50 步触顶均含半截 edit）。

**契约**：`edit_file` span 未命中 → 返回 top-k 最近匹配（`path:line | 单行源码`，行协议）；span 不唯一 → 返回全部出现位置。模型据此一步改对 span，省掉「再 read_file 一轮」的往返。

**验收**：edit 失败后的平均恢复步数下降；同 span 连续失败 ≥3 次的 Turn 占比下降。

#### W4 — Reproduce 相位（已落地 · 纯 prompt）

**动机**：成熟配方公认「先复现 → 修 → 复跑」对 resolve 提升最稳定；当前 ①–⑦（§6.0.3）缺该相位。

**契约**：agent `system.md` 与 L1 `coding_prompt` 的阶段表在 Orient 与 Locate 之间加 **Reproduce**：优先运行 issue 给出的失败片段 / 最小 repro 脚本 / 失败测试（用已有 `run_command` / `run_tests`）；修完在 Verify 中**复跑同一命令**。禁网环境下 repro 限本地执行。无法复现（纯文档 / 环境缺依赖）→ 显式说明后继续，不硬卡。

**速率**：纯文案；前缀字节变化过 hygiene 测试（CQ2）。

#### W5 — 交卷自检（已落地 · prompt + 观测）

**契约**：宣告完成前自查三条：a) `git diff` 非空且能自述改了什么；b) 最近一次 `edit_file` 不处于 failed 未收尾；c) repro / 相关测试至少复跑一次（做不到须说明）。Ops 侧 apply-check 门禁不变（双保险，见 §6.0.2 步 8）。

**验收**：`no_patch` 桶中「实际动过 edit 但没收尾」子类占比下降。

### 7.4 候选但仍后置（不进 Wave 2/3）

| 候选 | 内容 | 不进的原因 |
|------|------|----------------|
| W6 repo map（Aider 式） | 按需 `repo_map` 只读工具：符号级仓库骨架（tree-sitter，按引用密度排序，预算内截断） | 尊重否决 8（不预注入）后只剩按需形态；Lite 工作区无预建索引、首查需现算付冷启动；且实测卡点（Verify/pager/半截）优先级更高。`b3357dd6` 后判断不变——**W7 单文件按需折叠（§7.7.3）以更小成本先覆盖主要收益面** |
| pager 硬 Ban | `run_command` 拒绝执行纯 pager | 伤交互；先 W2 软重定向 + 观测 |
| 阶段 D 写副作用 | rename / code action | 维持后置（§7.1.4） |

### 7.5 优先级与里程碑（N0–N7）

| 里程碑 | 内容 | 依赖 | 出口判据 |
|--------|------|------|----------|
| **N0** | 官方 harness 可测（P6）——本地 `sweb.eval` 就绪 + 跑通 resolve，否则只剩 `patch_rate` 代理指标 | 无；**先于/并行于所有 Wave 2 开发** | 看板/Make 预拉 board_tier 镜像完成；`require_local` 缺图 fail-fast；任一 lite 题产出官方 `% resolved` 并入档（非空 predictions） |
| **N1** | W1（语法门 + checks）+ W3 + W4/W5 文案 | 无（与 N0 并行） | 单测覆盖拒收/逃生门/timeout；golden；前缀 hygiene 绿 |
| **N2** | n5 复跑（P11）：验收 Wave 1+2 探针（§7.6） | N0、N1 | 探针全绿；桶分布对照入档 |
| **N3** | W2 pager 软重定向 | N2 数据确认 P8 仍高 | 重定向命中/误伤入档；pager 占比下降 |
| **N4** | lite-50 双轨（§8.2）→ 按 §9.3 决策规则定论 | N0–N2 | resolved 差值 + 全过程指标 |
| **N5** | D1 证据归档：`file_hit` / `repro_rerun` / `tests_before_submit`（§7.7.1） | 无（评测侧，零交互影响） | 报告含三指标；`b3357dd6` 两失败题回溯分类（H1/H2）入档 |
| **N6** | D2 AST `no_ws_symbol` 修复 + 双轨 n5（姊妹文执行，§7.7.2） | N5 | fuse 失败主桶显著消减；AST on/off 过程对照入档 |
| **N7** | W7 `read_file` 截断折叠 + W8 `related_tests`（§7.7.3–7.7.4） | N5 证据支持（`file_hit` 低→W7 优先；`tests_before_submit` 低→W8 优先） | 单测 + 探针 8–10 绿；前缀 hygiene 绿；n5 复跑对照入档 |

排序依据：N0 是**测量前提**；W1/W3 直接治实测最大失血点（半截 diff、Verify 缺位），且实现面最小（改一个 handler + 文案）；W2 依赖复跑数据确认优先级，避免为已缓解的问题加复杂度。**N0–N2 已达成（§6.7.8–§6.7.9）**。Wave 3 追加 N5–N7，现行顺序 **N5 →（N6 ∥ N7）→ N3（条件触发）→ N4 定论**——证据先行，防对 n5 两个失败题过拟合（§7.7.0）。

### 7.6 验收探针（Wave 1+2 合并清单，替代 §6.7.6 原三条）

1. 裸符号 `grep` → 结果含 `definitions` 或 LSP `status=failed`（禁词面冒充 Locate 完成）。  
2. 代码 `edit_file` 成功 → 必有 `impact` **且**（N1 后）必有 `checks`。  
3. 语法门拦截数 / 误拦率（旧文件已坏场景）单列。  
4. pager 型 `run_command` 占比与重定向命中/误伤计数（N3 后）。  
5. `edit_file` span 失败重试率、失败后平均恢复步数。  
6. `no_patch` / `patch_no_apply` 桶占比对照（早期 n5 与 `01599d49` 为基线）。  
7. **不以** `search_codebase` / `goto_definition` / `find_references` 调用次数为 KPI（不变）。  
8. 每跑归档 `file_hit` / `repro_rerun` / `tests_before_submit`（N5 后；§7.7.1）。  
9. `read_file` outline 附带率与工具 p95 时延对照；同一大文件重复 read 次数（N7 后）。  
10. `related_tests` 附带率 / 命中率；「编辑后跑过相关测试」题占比（N7 后）。  
11. `locate_fuse` 仅作 AST 供给回归信号，**不以单指标追高**（§7.7.0）。

### 7.7 Wave 3：修复正确性主攻（`b3357dd6` 之后 · 方案，未实施）

> 本波回答一个问题：**patch 全部可 apply 之后，为什么官方测试还是不绿？** 全部改动仍遵守 §7.3 同一约束：只焊进模型已在点的动词（`read_file` / `edit_file` / `run_tests`）与评测侧归档；不加新工具名、不预注入、不动 Engine、不动模型与步数预算（控制变量）；writing Profile 零感知。

#### 7.7.0 读数 → 主攻推导

| `b3357dd6` 事实（§6.7.9） | 推论 |
|---------------------------|------|
| patch / apply / impact / checks 连续两跑满分 | 交卷链与编辑护栏**退出主攻**，转维持性回归（探针 1–3 不撤） |
| 失败全部为 `patch_not_resolved`（改了、可 apply、官方测试未绿） | 短板 = **修复正确性**，拆两类假设：**H1 改错位置**（读得少 / 定位供给不足）· **H2 改对位置改错逻辑**（验证不深，fail-to-pass 面没跑到） |
| `locate_fuse` 失败主桶 `no_ws_symbol`=10/11 | Locate 缺口在**工作区符号供给**（AST 索引），不是 LSP 故障（`lsp_failed`/timeout=0）→ 姊妹文认领（D2） |
| fuse 降（36%→27%）而 resolve 升（0→3/5） | Locate 与 resolve 部分脱钩：**禁止**把 fuse 当质量目标单指标追高 |
| n=5 · 全 astropy · 失败仅 2 题 | 统计上不可对 2 题过拟合：**证据归档先行（D1），机制（W7/W8）按证据触发** |

H1/H2 目前**不可区分**——这正是 D1 要补的测量。两失败题画像（§6.7.9 读法 4）分别偏 H1（14365：5 reads / 35 steps，改少改偏）与 H2（14182：完整跑完仍未过），但 n=2 只作方向提示，不作结论。

#### 7.7.1 D1 — 证据归档：把「改错位置 vs 改错逻辑」变成可测（评测侧 · 零交互影响）

**动机**：`patch_not_resolved` 是混桶；§8.3 早已定义文件级定位命中率，但从未按跑归档，每次复盘只能靠逐题画像猜。

**契约**：official bench 报告每跑固定归档三个过程指标（全部**事后**由 `turn_events` / patch / gold 文件清单计算，合规 §8.4-1，gold 不进任何 prompt）：

| 指标 | 定义 | 回答 |
|------|------|------|
| `file_hit` | model patch 文件 ∩ gold patch 文件 ≠ ∅（逐题 bool + 套件率） | H1：是否连文件都改错 |
| `repro_rerun` | 同一 repro / 测试命令在 Turn 内运行 ≥2 次（改前 + 改后） | W4 纪律是否真被执行 |
| `tests_before_submit` | 交卷前是否运行过任何 pytest / `run_tests` 类命令 | H2：验证深度下限 |

**验收**：下一次 n5 / lite-50 报告含三指标；`b3357dd6` 两失败题回溯分类入档（14365 / 14182 各归 H1 或 H2）。

#### 7.7.2 D2 — Locate 供给修复（AST 姊妹文认领）

`no_ws_symbol` 10/11 说明 fuse 失败主因是**工作区符号表查不到**（覆盖、归一化、别名、建成前 stale 等），不是 LSP 基建故障。修复方案与双轨 n5 数字归 [agent-workspace-ast-index.md](agent-workspace-ast-index.md)；本文只认两个出口数：fuse 失败主桶显著消减 + AST on/off 过程指标对照入档。

**红线**：不许为抬 fuse 把词面命中改记成符号命中（原则 5 不变）；fuse 只作供给回归信号，不作质量 KPI（§7.7.0 第 4 行）。

#### 7.7.3 W7 — `read_file` 大文件结构折叠（焊进读动词 · 治 H1）

**动机**：H1 的机制是「大文件预算截断后，模型只能盲翻或反复 read 同文件」；14365 偏此画像。成熟先例：SWE-agent ACI 文件视窗、Aider repo map 的单文件形态——但我们取**按需附带**（仅当模型已请求读该文件且命中截断），不预注入，尊重否决 8。

**契约**：`read_file` 命中预算截断且 path 为代码文件 → 结果尾部附 `outline[]`：`<line> <kind> <name>`（def / class / method，行协议 §9.4，上限约 40 条，超限按层级折叠只留顶层）。来源单文件 `ast.parse` / tree-sitter；解析失败或非代码 → 省略字段。事件名不变；**未截断读取的输出不变**。

**速率**：单文件 parse 毫秒级（与 W1 语法门同量级），落在单工具时延内（§5.1 合宪形态）；不触发任何跨文件 / 全仓动作。

**验收**：outline 附带率与 p95 时延入观测；同一大文件重复 read 次数下降；`file_hit` 对照（N5 基线 → N7 后）。

#### 7.7.4 W8 — `edit_file` 附 `related_tests` + Verify 测试锚定（治 H2）

**动机**：repro 复跑（W4）只覆盖 issue 给出的片段，**不覆盖仓库自带测试面**——官方判分恰恰是 fail-to-pass 测试。成熟先例：CI 测试选择（命名约定 + 反向 import）与 Anthropic / OpenHands 配方的「修完跑相关测试」。

**契约**：代码 `edit_file` 成功结果附 `related_tests[]`（≤5 条路径，**只给路径不执行**）：
（a）命名约定：同包 `tests/` 下 `test_<stem>*.py`；（b）工作区 AST / 词面反查 import 被改模块的测试文件。
两路均为 glob / 索引查表毫秒级；附前做存在性检查；空集 → 省略字段，不影响 `edited`。prompt 层（`system.md` + L1）Verify 相位补一句：**优先运行 `related_tests`，再复跑 repro**。

**边界**：不替代 `run_tests` 语义（否决 9）；不自动执行测试（执行权在模型 + 现有审批 / 沙箱）；禁网评测下测试本地跑。

**验收**：`related_tests` 附带率 / 命中率（≥1 条与 gold 测试文件相交，事后算）；「编辑后跑过相关测试」题占比上升；`patch_not_resolved` 中 `tests_before_submit=false` 子类占比下降。

#### 7.7.5 本波仍不做

| 候选 | 原因 |
|------|------|
| best-of-n patch 生成 + 重排 | 成本倍增、属评测工程而非编码质量；与「抬编码质量为主」相悖 |
| repo map 预注入 / 常驻骨架 | 维持 §7.4 原判；W7 单文件按需折叠先覆盖主要收益面 |
| 换模型 / 调采样参数追分 | 控制变量；模型变更走 §8.2 复现存档 + 重跑对照，不混入本波 |
| W2 pager 提前 / 硬 Ban | 维持 N3 条件触发（复跑数据确认 P8 仍高才做） |
| 自动执行 `related_tests` | 执行副作用越权；先给路径看采纳率，数据支持后另评 |

---

## 8. 外部基准：SWE-bench Lite

### 8.1 它决定了什么

- Lite = 300 个真实 GitHub「issue → patch」任务，**全部 Python**（django / sympy / sphinx / scikit-learn / matplotlib / astropy 等约 12 个大仓）。
- 直接决策一：**语言矩阵 Python-first**。阶段 A/B 只需 Python provider 即可全覆盖基准；TS/Go 等降为 P2，有真实需求再评。
- 直接决策二：**阶段收益排序 B ≥ A ≫ C**。Lite 的主要失败源是「大仓里找不对文件/找不全调用点」，其次是「改完不知道破坏了什么」；索引切块（C）完全不在基准链路上（§7 阶段 C 说明）。
- Lite 是外部标尺，**不替代**本仓 golden：writing 不回归、前缀稳定、延迟对照等内部门禁独立生效（§10）。

### 8.2 运行协议

| 项 | 约定 |
|----|------|
| 判定 | 官方 harness（docker）跑 FAIL_TO_PASS + PASS_TO_PASS，口径为 `% resolved`（pass@1）；不自造判分脚本 |
| 工作区 | 每题 base commit checkout 即 Work workspace；无预建索引、无历史 Session |
| 网络 | **基准运行必须禁外网**。现行 agent `system.md` 明确允许出网——基准配置必须覆盖为 deny，否则模型可检索上游原修复 commit，分数作废。此差异写进基准 runner，不改日常 Profile |
| 双轨 | 同一模型、同一剧本跑 `structural=off`（基线）与 `structural=on`；**差值**才是本方案的贡献声明 |
| 抽样 | 合并前冒烟：固定 **lite-50** 子集（按仓库分层抽样、种子固定、入库存档）；里程碑：全量 300 |
| patch 提取 | Turn 结束后取 Work workspace 的 `git diff` 作为 model patch；空 diff / harness apply 失败一律记 unresolved，且单列比率（区分「没改」与「改坏」两类失败） |
| 隔离与并发 | 每题独立 Work，无跨题状态与缓存；并发度只受资源限制；每题另设墙钟上限（建议 30min）防单题挂死拖垮整轮 |
| 复现存档 | 模型版本、temperature/seed、Profile 与 system.md 快照、provider 版本（pyright 等）一并入档；**任一变更须重跑对照**，禁止跨配置比数字 |
| 预算 | 每题步数上限沿用 Profile `max_steps`；记录墙钟与 token 成本，防「分数升、成本爆」 |

### 8.3 指标分层

| 层 | 指标 | 用途 |
|----|------|------|
| 结果 | `% resolved` | 唯一对外口径 |
| 过程 | 文件级定位命中率（model patch 涉及文件 ∩ gold patch 文件） | 阶段 B 的直接信号；比 resolved 更灵敏 |
| 过程 | patch apply 成功率、`edit_file` span 失败重试率 | 落笔几何健康度 |
| 过程 | 平均步数、工具错误率、结构工具 p95 时延、cold_start 率、降级触发率 | 速率与交互健康（R1–R3 旁证） |

### 8.4 反过拟合红线

1. 不读 gold patch 做题级 prompt / 工具描述调优；gold 仅用于事后计算定位命中率。  
2. 不为分数预注入结构上下文（呼应 §10 否决 8）；不因单题失败给 Engine 加特判。  
3. lite-50 子集一经选定冻结；换子集须记录原因并同时报告新旧两组。  
4. 基准 runner 的环境差异（禁网、判分容器）只存在于 runner，不回流污染日常 Profile / system 文案。

### 8.5 官方 harness 前置：`sweb.eval` 镜像与部署看板（N0 / P6）

**问题（已核实）**

| 表象 | 实质 |
|------|------|
| 「评测挂了」 | L1 **infer 往往正常**（可 apply patch / 高 `patch_rate`）；挂的是 **官方 docker harness** |
| harness 长时间 `Evaluation: 0/n` | 本机无 `swebench/sweb.eval.x86_64.{id with __→_1776_}:latest`，进程在 **api/ops-eval** 内拉 Hub 卡住 |
| 偶发 `resolve_rate=0` 且很快结束 | 常是 **空/坏 predictions**（`empty_patch_ids` / No instances），**不是**模型 0 分 |
| 下次又要现拉 | 旧默认 `cache_level` 评后清实例层镜像 |

**解法（已接线）**

| 项 | 位置 / 行为 |
|----|-------------|
| 配置 | `eval/official/suites.small.yaml` → `suites.coding.harness`（`cache_level: instance`、`clean: false`、`require_local_images: true`、`board_tier: n5`）；可用 `SWE_HARNESS_*` / `SWE_MAX_WORKERS` 覆盖 |
| 预拉 CLI | `coding --phase pull-images`；`make official-bench-coding-pull-images`（`OFFICIAL_SWE_IMAGE_TIER` / `FORCE=1`） |
| 部署看板 | `:9090` 检查项 **Ops · SWE eval 镜像**（仅 `OPS_EVAL_DOCKER_SOCK` 开启时出现）；按钮 → 同上 Make；日志 tab **SWE 镜像** |
| 实时进度 | 拉取写 `reports/release/swe_eval_images_progress.json`（`images_done/total`、当前 ref、cached/pulled、heartbeat）；看板 `_collect_live` 叠到该项 **detail / 顶栏 job**：`预拉镜像 · 下载中 · k/n · pct% · short-ref`；单图下载中每 15s heartbeat，避免大镜像把 live 判死 |
| 评测护栏 | harness 前 `_harness_preflight`：缺本地图且 `require_local_images` → **立即失败**（禁止静默 Hub 挂死） |
| 体积纪律 | 约 **1GiB/题压缩**；只进 **宿主机 Docker 缓存**；不进 git、不 bake 进产品镜像 |

**看板可观测性结论**：队列 pending/running、pid、日志流、**结构化 n/N+%** 均可实时看；单层 docker 层进度仍在日志原文（plain pull），看板以「镜像张数」为第一进度轴（与索引 sync 的 chunk% 同构）。

**出口（N0）**：board_tier 本地 `ready` → 带非空 patch 跑 harness → 报告含官方 `resolve_rate`（可为 0，但必须是真跑完，不是缺图/空 predictions）。

---

## 9. 实际执行方案

> §9.1–§9.2 记录 Wave 1 的选型与触点（已落地为准，保留作规范与回归参照）；Wave 2 触点见 §9.2 末行；**现行排期以 §7.5 N0–N4 为准**。

### 9.1 Provider 与依赖选型

| 车道 | 首选 | 备选 | 降级（保底） | 说明 |
|------|------|------|--------------|------|
| 诊断（A） | pyright langserver（openFilesOnly） | jedi-language-server（纯 Python 依赖更轻，弱类型推断） | ruff CLI（现状） | pyright 需 node 运行时，**构建期打入镜像**；basedpyright 可作无 node 分发替代评估 |
| 导航（B） | 同一 pyright 会话（definition / references） | jedi-language-server | `grep` + 明确降级提示 | A/B 共用进程池，冷启动只付一次 |
| LSP 客户端 | 评估 `multilspy`（微软出品、研究界惯用、封装 server 生命周期） | 自研薄 JSON-RPC 客户端（仅需 initialize / didOpen / didChange / definition / references / publishDiagnostics / shutdown 七个面） | — | 若 multilspy 依赖面或多 Work 隔离不合需求则自研；两者都不引入运行时下载 |
| 切块（C） | `py-tree-sitter` + `tree-sitter-language-pack` | — | CQ4 正则（现状） | grammar 预编译随包安装 |
| 语言序 | Python = P0（覆盖 Lite 全部） | — | — | TS/Go/Rust = P2，触发条件：真实用户需求或新基准 |
| 版本纪律 | 镜像 / lockfile 锁定 provider 与 grammar 版本 | — | — | provider 升级（如 pyright 大版本）视为**行为变更**：须重跑 lite-50 双轨对照后才可合入，防「分数漂移当成果」 |

### 9.2 模块与文件触点

| 触点 | 变更 |
|------|------|
| **新增** `services/runtime/app/structural/` | `client.py`（LSP JSON-RPC 会话封装：initialize / didOpen / didChange / 诊断 pull 或 publish 等待 / definition / references / workspace-symbol / shutdown）· `pool.py`（Work 级 server 池：获取 / 健康检查 / 空闲回收 / 崩溃标记）· `adapters.py`（符号名→位置解析两跳；provider 输出 → 统一 `issues[]` / `locations[]`；LSP∪ruff 合并去重见 §9.4）· 全部旁路可预热、工具内可冷启 |
| `tools/core/tools.py` | `read_lints` 增强（LSP∪ruff，保留现有降级分支与返回形状；顺手修正现实现将 ruff 全记 `warning` 的 severity 粗化）；新增 `goto_definition` / `find_references` handler |
| `tools/bootstrap.py` | 注册 2 个新 `ToolSpec`（read-only、无审批、描述含「符号名输入 + 失败降级 grep」提示）；`search_codebase` 描述诚实化（一行文案，M0 即做）；中期（M2 后）同名工具可后接 `workspace/symbol` + 词面混合（§2.3），交互不变 |
| `scenarios/profiles/agent.yaml` | `tool_names` 增 `goto_definition` / `find_references`；writing / intel 不动 |
| `scenarios/agent/system.md` | Tool choice 表加一行「符号定义/引用 → 导航工具」；Verify 文案不改（CQ1 零改动）；前缀字节变化过 hygiene 测试 |
| `tools/delegate_runner.py` | `explore` / `verify` / `edit` 子集按 §6.6 增导航；写作子类型不动 |
| `settings.py` | **`structural_enabled` 产品开关已废除**：能力 = Profile 白名单。运行参数含 `structural_nav_timeout_s` · `structural_diag_timeout_s` · `structural_checks_max_issues` · `structural_checks_timeout_s` 等 |
| `retrieval/chunking.py` | 阶段 C：代码切块优先 tree-sitter，失败回落正则 |
| 基准 runner / 测试 | swebench 双轨脚手架 · structural 单元 · writing 不回归 |
| **Wave 2 触点** | **已落地**：`edit_file`（`checks` + span 候选）· `system.md` / L1 prompt（Reproduce · 交卷自检）。**仍开放**：`run_command` pager→`read_file` 工具级重定向（N3） |
| **Wave 3 触点（方案，§7.7）** | `read_file`（截断附 `outline[]`）· `edit_file`（`related_tests[]`）· `system.md` / L1（Verify 测试锚定一句）· official bench 报告（D1 三指标 `file_hit` / `repro_rerun` / `tests_before_submit`）；AST 符号供给修复在姊妹文（D2） |

### 9.3 里程碑（M 序列状态归档；现行排期见 §7.5 N0–N4）

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| **M0 基线** | 搭基准 runner + lite-50 脚手架；`search_codebase` 描述诚实化 | **脚手架已落地**（2026-08-10）；lite-50 基线**数字未入库**——被缺 `sweb.eval` / harness 不可测卡住，随 N0（§8.5）解锁 |
| **M1 = 阶段 A** | `structural/` 包 + `read_lints` 增强 | **已落地**，并入 Wave 1（§7.1.1）；产品开关随后废除 |
| **M2 = 阶段 B** | 导航双工具 + 子 agent 白名单 | **已落地**，并入 Wave 1；实测 adoption 为零后追加 **Locate/Impact 揉合**（§6.7.4） |
| **M3 全量对照** | lite-300 双轨 + 全部过程指标 | 未做；重排到 **N4 之后**（依赖 N0/N2） |
| **M4 = 阶段 C** | tree-sitter 切块 + 离线切块对照 | 切块**已落地**（可选依赖、正则回落）；**离线对照未做**，与 Lite 解耦不占基准资源 |
| （可选）阶段 D | 写副作用结构操作 | 维持后置（§7.1.4） |

**全量对照决策规则**（事先写死，防「过评审」变成拍脑杋；产品开关已废除，双轨 on/off 指**基准 runner 配置**，结论作用于「结构车道保留 / 收缩 / 扩展」的产品决策）：

- `on−off` 的 resolved 差值 **> 0**，且时延 / token 成本 / 工具错误率不劣化 → 结构车道现形态**确认保留**，继续 Wave 3 候选评估。  
- 差值 **≈ 0** 但文件级定位命中率显著提升 → 收益卡在落笔或验证车道：先查 `edit_file` span 失败率与 checks 修复率（Wave 2 探针 §7.6），修输出契约后重跑一轮再定。  
- 差值 **< 0** → 复盘并考虑收缩。优先排查两类已知模式：模型过度调用导航（步数被挤占）、references/checks 噪声吃掉上下文预算——对应收紧输出上限与 `structural_max_refs`。

### 9.4 统一输出契约（紧凑行协议）

工具结果走现有 budget（约 4k 截断 + 再读指针），主体用行协议而非肥 JSON：

```text
# diagnostics（read_lints 增强后，去重合并 LSP∪CLI）
<path>:<line>:<col> <severity> [<provider>:<code>] <message>

# locations（goto_definition / find_references）——附单行源码，省一轮 read_file
<path>:<line>:<col> <kind> <symbol> | <该行源码，截断 ~120 字符>   # kind ∈ def|ref|impl
```

- **去重键**：`(path, line, 规范化的 code/message)`；LSP 与 ruff 同点位重复时保留信息量更高的一条（通常是含类型信息的 LSP 条目）并标注双来源，不静默丢弃。  
- **severity 映射**：LSP DiagnosticSeverity 与 ruff 规则级别统一映射到 `error|warning|info` 三档（现实现将 ruff 全记 `warning`，增强时一并修正）。  
- 元数据字段：`provider=lsp|ruff|treesitter` · `cold_start` · `truncated` · `unsupported` · `degraded_reason`，同时进工具事件供 Ops（§11 观测行）。  
- references 超 `structural_max_refs`：按文件聚合计数 + 指针（`path (N hits)`），模型可对单文件再查。

### 9.5 风险与对策

| 风险 | 对策 |
|------|------|
| pyright 大仓冷启动（django 级全量分析分钟级） | openFilesOnly + didOpen 定向；Work 级旁路预热；导航 timeout 15s 强制降级 grep |
| node 运行时依赖 | 构建期打入镜像；jedi-language-server 作无 node 备选；沙箱 deny-by-default env 同纪律启动 |
| `find_references` 结果爆量（数百调用点） | §9.4 聚合 + 指针；单次上限进 settings |
| 基准答案泄漏（agent 默认可出网） | 基准 runner 强制禁网（§8.2）；列入否决清单 |
| 新工具使 agent 前缀变长、cache 失效 | 描述 hygiene（CQ2）+ 前缀稳定测试；加厚须可被 cache 抵消（§6.5 既有要求） |
| LSP 与用户/agent 并发编辑不同步 | 每次工具调用前对目标文件 didChange 同步（以磁盘为准）；不做常驻文档影子状态 |
| **W1 语法门误拦**（文件本身语法坏 / 非支持语言） | 逃生门：旧文本 parse 失败仅警告放行；非支持语言 `syntax=skipped`；拦截数与误拦率单列观测（§7.6 探针 3） |
| **W1 checks 拖慢 `edit_file`** | 语法门毫秒级；增量诊断单文件 openFilesOnly + timeout；超时 `checks.status=timeout` 显式、**不失败 edit** |
| **W2 pager 重定向误伤**复杂 shell | 只匹配无管道 / 多命令 / 写副作用的纯 pager 整条命令；不匹配则原样执行；误伤计数进观测 |
| **W7 outline 膨胀 / 噪声** | 仅截断时附带；上限约 40 条 + 层级折叠；走行协议与统一 budget；非代码 / 解析失败省略字段 |
| **W8 related_tests 误导**（列出无关测试） | 只给路径不执行；≤5 条 + 存在性检查；命中率进观测；空集省略字段，模型回退 repro / 全量 `run_tests` |

---

## 10. 验收与否决清单

### 10.1 门禁（R5）

| 项 | 命令/产物 | 阶段 |
|----|-----------|------|
| 单元：切块/适配器/降级 | `make runtime-test`（或等价） | A–C |
| Agent golden：lint/导航/跨文件 | `make eval-all` 扩展 | A–B |
| Writing 不受影响 | Profile 快照 + writing golden 不回归 | 全程 |
| 延迟对照 | 同剧本 assemble_ms / TTFB / 首 token；结构工具 p95 | 全程 |
| 前缀稳定 | agent tools/system 字节稳定测试 | A–B 加工具时 |
| SWE-bench Lite 双轨 | lite-50 冒烟（合并前）· lite-300（里程碑 M3） | M0 起 |
| `make gate` | 合入前门禁全绿 | 全程 |

### 10.2 否决（全文级）

1. StartTurn / assemble 同步等待 LSP ready 或全库 AST。  
2. 为结构智能在 Engine 增加固定节点或 `if scenario`。  
3. Writing Profile 注册结构工具或启动 language server。  
4. 默认每次 edit 后全仓库诊断。  
5. 无降级路径：server 挂则 Turn 失败。  
6. 运行时下载语言插件/grammar（供应链与速率双重风险）。  
7. 无 golden / 无延迟对照的「质量」合并。  
8. 用结构工具结果预注入替代按需调用。  
9. 宣称替代 `run_tests`。  
10. 基准运行开外网（答案泄漏），或读 gold patch 做题级调优（§8.4）。
11. **语法门无逃生门**：旧文件本身不可 parse 也硬拦编辑——门只许拦「由本次 edit 新引入」的语法错误（§7.3 W1）。
12. **重定向越界**：`run_command` 重定向扩大到含管道 / 多命令 / 写副作用的命令，或以任何方式改变命令语义——只许重定向纯 pager 整条命令（§7.3 W2）。

---

## 11. 安全、多租户与运维

| 主题 | 要求 |
|------|------|
| 文件系统 | server 可见范围 ≤ Work / workspace root；与工具 `_resolve_path` 一致 |
| 环境变量 | 子进程不继承 API 密钥；与现有 deny-by-default 对齐 |
| 配置执行 | 优先只读诊断模式；高风险 server 需 allowlist + 文档 |
| 资源 | 每 Work 进程数/内存上限；空闲回收；防 LSP 僵尸 |
| 镜像 | grammar / language server **构建期**打入；不在请求期拉取 |
| 多 Work | 进程按 Work 隔离；禁止跨 Work 复用 server 状态 |
| 观测 | provider、cold_start、timeout、unsupported、降级原因进工具事件/Ops |

---

## 12. 情况总表（速查）

| # | 情况 | 期望行为 |
|---|------|----------|
| 1 | writing / intel 会话 | 走 RAG（`search_sources`）；无 coding 结构工具、无 LSP；不展示 Agent AST 进度 |
| 2 | agent 会话，未调用结构工具 | 可不预热 LSP；AST 可按 Work 旁路冷建/恢复，GUI 可显示进度但不挡输入 |
| 2b | agent 无 `search_sources` | 不以资料 RAG / `sources/` sync 充当 Locate |
| 2c | GUI 点击切换 Agent↔写作（同 Work） | 只换 Scenario/面板；**不**拆/建索引；进度通道分开订阅 |
| 2d | 同账号切换 Work | AST/RAG 进度与数据切到新 `work_id`；旧 Work DB 行保留至 GC |
| 3 | 首次 `goto_definition`，server 冷 | 工具内等待至 timeout；标 cold_start；失败则显式 failed / 降级提示 |
| 4 | `edit_file` 后 `read_lints` 单文件 | LSP∪CLI；只报该路径（及实现选择的直接依赖，须有上限） |
| 5 | 模型对 `.` 调 `read_lints` | 目录扫描有文件数/深度上限；超限截断并说明 |
| 6 | 语言无 provider | `unsupported`，建议 grep/测试 |
| 7 | LSP 与 ruff 同时有结果 | 合并去重；标注来源；不互相覆盖静默丢弃 |
| 8 | Cancel 于诊断中 | 取消请求；Turn `cancelled` |
| 9 | 审批挂起中 server 崩溃 | 恢复执行后降级或旁路重启；不改 run_id 语义 |
| 10 | RAG 索引 worker 解析失败单文件 | 跳过/回落正则；**仅影响 writing/intel 检索**；任务继续 |
| 10b | Agent 工作区 AST 脏/过期（候选） | 标 `index_stale`；回落 LSP 或单文件即时 parse；禁止假装 Locate 完成 |
| 11 | `search_codebase` 名实 | 符号→LSP；非符号→词面；未来可叠加工作区 AST 候选 |
| 12 | 子 agent verify | 可用增强 `read_lints`；写作子类型不可见 |
| 13 | 用户只要「解释代码不改」 | 只读导航可用；不强制诊断仪式 |
| 14 | 超大 monorepo | 必须有 path 范围与超时；禁止隐式全仓 |
| 15 | stub/eval 环境无 LSP | 固定降级路径，golden 可双轨（structural on/off） |
| 16 | SWE-bench Lite 基准运行 | runner 强制禁外网；双轨开关；过程指标落盘；**默认不建** Agent 全仓 AST（或短 TTL） |
| 17 | 代码 `edit_file` 引入语法错误（W1 后） | 写前语法门拒收 + 出错行回显；旧文件本身坏 → 仅警告放行 |
| 18 | 代码 `edit_file` 成功（W1 后） | 结果必含 `impact` + `checks`（增量诊断；timeout 显式，不失败 edit） |
| 19 | `run_command` 为纯 pager（W2 后） | 内部转 `read_file`，结果带 `redirected_from`；含管道/多命令则原样执行 |
| 20 | `edit_file` span 未命中 / 不唯一（W3 后） | 回显最近候选 / 全部位置（行协议），不裸失败 |
| 21 | Agent Turn 内新建代码文件 | 词面立即可见；LSP 下次 Locate 可读盘；RAG sync **不**因此触发；Agent AST（候选）异步脏更新 |
| 22 | `read_file` 命中截断且为代码文件（W7 后） | 尾部附 `outline[]`（行协议，上限条数）；非代码 / 解析失败省略；未截断读取输出不变 |
| 23 | 代码 `edit_file` 成功（W8 后） | 可附 `related_tests[]`（≤5 真实路径，不执行）；空集省略；Verify 优先复跑相关测试 |

---

## 13. 与现有代码/文档锚点

| 锚点 | 路径/说明 |
|------|-----------|
| R1–R5 | `docs/core/architecture.md` |
| 工具协议 / 组窗 | `docs/core/tools-and-context.md` |
| Engine / 审批取消 | `docs/core/runtime.md` |
| 索引 vs 交互 | `docs/topics/rag.md` |
| agent 纪律 | `services/runtime/app/scenarios/agent/system.md` |
| Profile | `services/runtime/app/scenarios/profiles/agent.yaml` · `writing.yaml` |
| CQ4 切块 | `services/runtime/app/retrieval/chunking.py` |
| 符号启发式 / Locate·Impact | `services/runtime/app/structural/symbols.py` · `tools/core/tools.py` |
| `read_lints` / 导航 | `services/runtime/app/tools/core/tools.py` |
| 工具注册 | `services/runtime/app/tools/bootstrap.py` |
| agent 纪律 | `services/runtime/app/scenarios/agent/system.md` |
| L1 coding prompt | `scripts/official_bench/l1_prompts.py` |
| 子 agent 工具集 | `services/runtime/app/tools/delegate_runner.py` |
| 基准 runner | `eval/swebench/` · `make official-bench-coding-*` |
| Ops 实测过程 | **本文 §6.7**（单一纪要） |

---

## 14. 建议决策（供评审勾选）

- [x] **Agent 工作区异步 AST**：[agent-workspace-ast-index.md](agent-workspace-ast-index.md) A6 旁路已接线；双轨 n5 数字待复跑。  
- [x] **语言矩阵 Python-first**（SWE-bench Lite 全 Python）。  
- [x] **Locate/Impact 揉合**（§6.7）：裸符号 grep 重定向 + edit_file.impact。  
- [x] **N0 官方 harness 可测**：`d459ca51` 首次真测 resolve **0/5**（§6.7.8）；`b3357dd6` 第二跑 resolve **3/5**（§6.7.9）；`patch_rate` 仅代理。  
- [x] **Wave 2 主项（§7.3）**：W1 `checks` · W3 span 候选 · W4/W5 prompt。  
- [ ] **Wave 3 方案（§7.7）**：D1 证据归档（`file_hit` / `repro_rerun` / `tests_before_submit`）· D2 AST 符号供给（姊妹文）· W7 `read_file` 截断折叠 · W8 `edit_file.related_tests`；仍不做 best-of-n / repo map 预注入 / 换模型追分。  
- [ ] **W2 pager 工具级重定向**（N3）：仅纯 pager 整条命令；先软重定向不硬 Ban。  
- [ ] **SWE-bench Lite 双轨协议（§8）** 定论跑（含 AST on/off 若启用）。  
- [ ] **R5**：每阶段至少 1 组 agent golden + 延迟对照 + writing 不回归。  

---

## 15. 修订记录

| 日期 | 修订 |
|------|------|
| 2026-08-10 | 初稿：写入链目标、场景隔离、R1–R5 矩阵、交互逻辑、分阶段与情况总表 |
| 2026-08-10 | v2：核对代码锚点属实；新增 §8 SWE-bench Lite 基准协议（禁外网、双轨、指标分层、反过拟合）与 §9 实际执行方案（provider 选型、文件触点、里程碑 M0–M4、行协议、风险）；语言矩阵 Python-first；A/B 并行分轨；否决新增基准外网泄漏；后续章节重编号 |
| 2026-08-10 | v2.1（执行细节强化）：导航工具改**符号名优先**输入（适配器内 `workspace/symbol` 两跳，模型只见一次调用）；诊断优先 LSP 3.17 pull、push 差异由适配器屏蔽；定义 `structural_enabled` 语义 = 门控工具注册（off 时前缀字节不变）；位置行协议附单行源码；LSP∪ruff 去重键与 severity 三档映射；M3 flag 决策规则写死；§8.2 补 patch 提取 / 每题隔离与墙钟 / 复现存档；§9.1 增 provider 版本纪律 |
| 2026-08-10 | **落地**：`app/structural/`（client/pool/adapters/format）· `read_lints` LSP∪ruff · `goto_definition`/`find_references` · Profile/system/子 agent 白名单 · tree-sitter 切块（可选依赖，正则回落）· `eval/swebench/` 双轨脚手架与 lite-50 · settings `structural_*`（默认 off） |
| 2026-08-10 | **Ops 接线**：compose 注入 `STRUCTURAL_*` / `OPS_EVAL_DENY_NETWORK`；ops_eval Turn 禁网（bwrap `--unshare-net`，fail-closed）；`/health/ready` 暴露 structural；`tool.completed` 带 CSI meta；旁路 prewarm；LSP cancel 轮询；L1 coding 归档 env + 每题墙钟 30min；双轨 README 强制 recreate runtime |
| 2026-08-11 | **融合 agent 流程**：去掉 `STRUCTURAL_ENABLED` 产品开关；Profile 固有；缺 LSP 显式 failed |
| 2026-08-11 | **Locate/Impact 揉合 + §6.7 完整过程纪要**：早期 n5、`01599d49` 工具面、Runtime 调用链、观测读法；取消独立 topics 纪要 |
| 2026-08-11 | **§6.0 当前端到端流程与问题清单**：Ops L1 逐步表、Turn 内①–⑦与 runtime 契约、实测调用形态、P1–P11 已解/未解 |
| 2026-08-11 | **v3（Wave 2 方案，未实施）**：§7 重构为波次视角——Wave 1 落地态归档（原阶段 A–D 压缩为行为契约）+ 成熟 agent 借鉴对照（SWE-agent lint 门控编辑、Cursor/Claude Code edit 后自动 lint 回灌与失配候选、Anthropic/OpenHands 复现纪律、Aider repo map 列 Wave 3 候选）+ W1–W5 设计 + 里程碑 N0–N4 + 探针 §7.6；§6.0.5 增 P12（Verify adoption 趋零）并给 P4/P6/P8/P11 挂方案指针；§9 修正 `structural_enabled` 已废除口径、M 序列状态归档、新增 W1/W2 风险；否决清单增 11–12（语法门逃生门、重定向边界）；§12 增情况 17–20 |
| 2026-08-11 | **§3 场景分型重写**：写作 / 威胁情报 = RAG（`search_sources` + `sources/` sync）；Agent = LSP+词面（已落地）· 工作区旁路 AST 索引（候选，不携带 RAG）· 时效/脏队列/`index_stale` 契约；§4 改为两条旁路索引图；§2/§14 对齐 |
| 2026-08-11 | **§3.3.4–3.3.5**：GUI 模式点击≠重建索引；RAG 异步 embed / 热语料=上传私有库；Agent AST 建议 Work 级 DB 缓存 + 进度条；多账号 ACL / 多 Work 主键；与 `source_chunks` 表隔离 |
| 2026-08-11 | **文档切分**：工作区异步 AST / GUI / Work·DB 拆至 `agent-workspace-ast-index.md`；本文收回 SWE/Ops + LSP 揉合主线 |
| 2026-08-11 | **N0/P6 镜像与看板**：§6.0.5 P6、§6.7.1 时间线、§7.5 N0 出口、新增 §8.5（缺 `sweb.eval` / Hub 挂死 / 空 predictions 误报 / 看板预拉与 `swe_eval_images_progress.json` 实时 n/N）；澄清 infer patch OK ≠ 官方 resolve |
| 2026-08-12 | **§6.7.8 完整 harness n5（`d459ca51`）**：首次真官方 `resolve_rate=0/5`（patch/apply 满分）；P6→已解、P11→部分完成、N0 checklist 勾选；看板 Ops Bench / `start-bench` 记入时间线 |
| 2026-08-13 | **文档回写**：正文 [工具与上下文](../core/tools-and-context.md) 增 Coding 揉合图；Wave 2 主项（W1/W3/W4/W5）标已落地；W2 pager 工具级重定向仍开放；AST 姊妹文 A6 已接线；§14 勾选同步 |
| 2026-08-13 | **§6.7.9 完整 harness n5（`b3357dd6`）**：官方 `resolve_rate=3/5`（对照 §6.7.8 的 0/5）；patch/apply/impact/checks 仍满；locate_fuse≈0.27（主桶 no_ws_symbol）；P11→已有第二跑；§14 N0 勾选补第二跑 |
| 2026-08-14 | **v4（Wave 3 方案，未实施）**：基于 `b3357dd6` 读数确立主攻 = **修复正确性**（交卷链/护栏满分退出主攻；失败全为 `patch_not_resolved`）；新增 §7.7（7.7.0 读数推导 · D1 证据归档 · D2 AST 供给认领 · W7 `read_file` 截断折叠 · W8 `related_tests` + Verify 测试锚定 · 本波仍不做清单）；§7.5 里程碑扩 N5–N7 并定顺序 N5→(N6∥N7)→N3→N4；§7.6 探针 8–11；§7.0 / §7.4 / §9.2 / §9.5 / §12（情况 22–23）/ §14 对齐 |
