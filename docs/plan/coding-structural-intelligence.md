# 方案：Coding 结构智能（LSP / AST）

> **状态**：草案（待评审）· 2026-08-10  
> **范围**：`agent`（及确需写代码的协作向 Profile）写入链路  
> **非范围**：默认不进入 `writing` / 纯资料向场景  
> **约束权威**：[架构 · R1–R5](../core/architecture.md) · [工具与上下文](../core/tools-and-context.md) · [Runtime](../core/runtime.md) · [RAG 两平面](../topics/rag.md)  
> **相关现状**：CQ4 正则代码切块（`retrieval/chunking.py`）· `read_lints`≈ruff · `search_codebase`≈转义 grep · OpenCode「LSP/结构化导航」曾作产品备案  

本文回答三件事：

1. Coding **写入时**应具备怎样的结构能力（不以「够用」为终点）。  
2. 如何与 **速率红线 R1–R5**、**现有交互逻辑**共存。  
3. 各种接入方式、失败、降级、场景边界下的具体行为。

---

## 0. 一句话立场

**LSP / AST 是 coding 写入链的一等结构车道（定位 · 落笔几何 · 验证），不是 Turn 主链上的固定流水线，也不是写作场景的负担。**

形态必须是：

```text
能力 = 工具（按需） + 旁路索引（异步）
差异 = ScenarioProfile 白名单（agent 开 / writing 关）
Engine = 禁止 if scenario；禁止为结构智能加固定 pipeline 节点
```

---

## 1. 问题与目标

### 1.1 问题（写入链视角）

Agent 改代码的质量，不只取决于模型「会不会写」，还取决于三条结构车道是否存在：

| 写入阶段 | 今天大致靠什么 | 结构层缺失时的典型失败 |
|----------|----------------|------------------------|
| **改前定位** | `grep` / `glob` / `search_codebase`(词面) / `read_file` | 假阳性、漏调用点、跨文件符号找不到、多跳靠猜 |
| **改时落笔** | `edit_file` 唯一 span / `propose_patch` | 切碎函数、span 不唯一、边界落在字符串/注释里、整文件重写诱惑 |
| **改后验证** | `read_lints`(ruff) / `run_tests` | 非 Python 弱或无诊断；类型/未解析引用靠测试偶然抓住 |

CQ1–CQ3（system 纪律、工具描述、golden/rubric）解决的是 **行为闭环**；本文解决的是闭环里 **传感器与手术刀是否够结构化**。两者叠加，不以互斥。

### 1.2 目标

| ID | 目标 | 可观测 |
|----|------|--------|
| G1 | Coding Profile 具备符号级定位（definition / references） | 工具可调用；golden 命中跨文件引用 |
| G2 | 写入后验证具备多语言/项目级 diagnostics（优先经统一 `read_lints`） | 非仅 ruff；受影响路径诊断回灌 |
| G3 | 索引面按真实语法边界切代码（AST/tree-sitter 升级 CQ4） | 异步；查询热路径不重建；切块对照指标 |
| G4 | Writing 场景零感知（无新工具、无新进程、无前缀膨胀） | Profile 对比 + cache/组装对照 |
| G5 | 全程合宪 R1–R5；失败可降级；可测才合并 | 门禁矩阵见 §8 |

### 1.3 非目标

- 不对齐 Cursor「全 IDE 能力」宣传口径。  
- 不在首 token 前同步起全语言 Language Server / 全库 parse。  
- 不把 LSP/AST 做成强制 pipeline（parse → lint → 才允许模型说话）。  
- 不在 `AgentEngine` / `ToolExecutor` 写 `if scenario == "agent"`。  
- 不默认开启 rename / code action 等写副作用结构操作（见 §7 阶段 D）。  
- 不替代 `run_tests`：类型绿 ≠ 任务完成。

### 1.4 设计原则

1. **写入一等，不是凑合**：结构导航与结构诊断是 coding 应有能力，不是「检索再增强一点」。  
2. **场景隔离**：只挂 coding 向 Profile；写作不背成本。  
3. **两平面**：重活在索引面（R4）；交互面只有按需工具调用。  
4. **能力即工具**：与 [工具与上下文](../core/tools-and-context.md) 一致——注册 `ToolSpec`，不改 while。  
5. **降级合法**：无 server / timeout / 不支持语言 → 回落 grep/ruff/正则切块，Run 不卡死。  
6. **证明优先（R5）**：无 agent 质量 golden / 延迟对照，不合并「感觉更好」。

---

## 2. 概念澄清：LSP 与 AST 各买什么

### 2.1 AST / tree-sitter

| | |
|--|--|
| **是什么** | 把源码解析成语法树；按节点（函数、类、方法）理解边界 |
| **买入链路** | 索引切块几何；可选：校验 `edit_file` span 是否落在干净节点；符号名抽取 |
| **不直接买** | 跨文件引用图、类型错误、项目配置感知 |
| **成本特征** | 单文件解析相对可控；全库同步 parse 伤 R3；适合 **异步索引** 与 **单次工具内** 使用 |

本仓 CQ4 现状：`retrieval/chunking.py` 用 `_CODE_SYMBOL_RE` 按顶层符号头切块，注释已写明 *not a full AST*。AST 是该车道的正确升级，不是新发明一条热路径。

### 2.2 LSP（Language Server Protocol）

| | |
|--|--|
| **是什么** | IDE ↔ 语言服务协议：定义跳转、引用、诊断、补全、重命名等 |
| **买入链路** | 项目级符号图、跨文件 references、多语言 diagnostics（常强于单 CLI linter） |
| **不直接买** | 「写出更好业务逻辑」；也不能免除测试 |
| **成本特征** | 进程生命周期、冷启动、内存、工作区同步（didOpen/didChange）、部分 server 会执行项目配置 |

### 2.3 和现有工具的映射（目标态）

| 能力 | 现实现 | 目标态 |
|------|--------|--------|
| 词面搜索 | `grep` | 保留（精确字符串仍需要） |
| 「语义/代码库搜索」 | `search_codebase` = `re.escape` + grep | 正名或升级：符号索引 / 混合；避免名实不符长期误导模型 |
| 诊断 | `read_lints` → `ruff check` | **同一工具名** 背后：LSP diagnostics ∪ CLI；模型侧纪律不变 |
| 定义/引用 | 无 | 新只读工具（或并入导航族） |
| 代码切块 | CQ4 正则 | 索引面 tree-sitter（可选，按语言逐步） |

---

## 3. 场景边界：为什么不影响写作

### 3.1 Profile 事实

| Profile | 与结构智能相关的现有工具 |
|---------|--------------------------|
| `writing` | 无 `edit_file` / `read_lints` / `search_codebase` / `run_tests` |
| `agent` | 具备上述编码工具面 |
| `collab` 等 | 仅当白名单含编码工具时启用结构能力 |

### 3.2 隔离规则（硬）

1. **工具白名单**：结构工具 **只** 写入 `agent.yaml`（及明确 coding 的 Profile）。  
2. **进程**：Language Server / tree-sitter worker **不** 因 writing Session 启动。  
3. **前缀**：writing 的 `system.md` + `tools[]` 字节布局不变（AQ1/WT5 不受影响）。  
4. **索引**：资料库 Markdown 切块路径不变；代码 AST 切块仅作用于代码扩展名（延续 CQ4 `is_code_path`）。  
5. **Engine**：禁止场景分支；「无工具注册 = 无能力」即隔离。

### 3.3 边界情况

| 情况 | 行为 |
|------|------|
| 用户在 writing 工作区里放了 `.py` | 仍无结构工具；可用 `grep`/`read_file`；不偷偷起 LSP |
| 同一 Work 先 writing 后切 agent Session | agent Session 可按 §5 软预热；writing Session 不受影响 |
| `delegate` 子 agent | 仅当子类型工具集包含结构工具时可用（如 `explore`/`verify`）；drafter 等写作子类型不可见 |
| intel 场景 | 默认不开；若未来要「读代码库做情报」再单独开只读导航，仍不开写副作用结构操作 |

---

## 4. 架构放置：三层模型

```text
┌─────────────────────────────────────────────────────────────┐
│  Turn 交互面（AgentEngine loop）                             │
│  模型按需调用只读/验证工具；写盘仍走 edit_file + 审批         │
│  ✗ 禁止：assemble 内同步全库 AST / 强制起 LSP 再首 token    │
└─────────────────────────────────────────────────────────────┘
        │ tool_result（预算截断、紧凑行协议）
        ▼
┌─────────────────────────────────────────────────────────────┐
│  结构服务（Session/Work 级，可热可冷）                        │
│  Language Server 池 · 单次 tree-sitter parse · 降级适配器     │
│  生命周期与 Turn 解耦；Cancel 不要求 ResumeTurn               │
└─────────────────────────────────────────────────────────────┘
        │ 符号/切块产物（可选）
        ▼
┌─────────────────────────────────────────────────────────────┐
│  索引面（R4，与 RAG index_scheduler 同构）                   │
│  代码文件 → AST/tree-sitter 切块 → embed / FTS / 符号表      │
│  ✗ 禁止：search / StartTurn 同步重建                         │
└─────────────────────────────────────────────────────────────┘
```

与 RAG「索引面 vs 交互面」同构：热路径只 **使用** 已有结构，不 **重建** 结构。

---

## 5. 速率红线 R1–R5：放置矩阵

权威定义见 [架构 §4](../core/architecture.md)。

| 红线 | 含义 | 结构智能如何遵守 | 违规示例 |
|------|------|------------------|----------|
| **R1** | 不挡受理 / TTFB | StartTurn 路径不 await LSP initialize；不 await 全库 parse | `turn.accepted` 前 `await language_servers.ready()` |
| **R2** | 首 token 前无同步模型 | 结构层是工具/索引，不加「先摘要代码再答」的模型调用 | 用 LLM 做符号提取当热路径 |
| **R3** | 热路径 CPU 毫秒级 | assemble / intake 不做重解析；重活在工具 handler 或旁路 | ContextEngine 每步 tree-sitter 整仓 |
| **R4** | 重活异步 | AST 切块、符号导出、server 预热均旁路 | 每次 `search_codebase` 先 rebuild index |
| **R5** | 可测才合并 | §8 门禁；无对照不合入 | 「本地手感好」无 golden |

### 5.1 允许的速率形态

| 形态 | 延迟落点 | 是否合宪 |
|------|----------|----------|
| 旁路软预热（Work 进入 agent 后后台 initialize） | 不挡 TTFB；首次工具可能已热 | ✅ |
| 首次结构工具冷启动 | 该次 tool 墙钟变长；结果标 `cold_start=true` | ✅（需 timeout） |
| edit 后对 **受影响路径** 调 `read_lints` | 单次工具延迟 | ✅（现有 CQ1 纪律） |
| edit 后默认全仓库 LSP diagnostics | Turn 墙钟与上下文膨胀 | ❌ 默认禁用 |
| 索引面 tree-sitter 切块 | 查询路径不变 | ✅ |

### 5.2 超时与预算

- 每个结构工具必须有 `timeout_s`（建议导航 5–15s，诊断 15–60s，可配置）。  
- `tool_result` 继续走统一 budget（约 4k 截断 + 再读指针）；推荐 **紧凑行协议**，避免肥 JSON。  
- 并行：只读结构工具可与 `grep`/`read_file` 并行（现有只读并行规则）。

---

## 6. 交互逻辑：长在现有树上

权威：能力即工具；只读可并行；写盘审批；取消是终态；无 ResumeTurn。

### 6.1 工具族（建议）

| 工具 | side_effect | 审批 | 说明 |
|------|-------------|------|------|
| `read_lints`（增强） | read | 默认无 | **保留原名**：背后接 LSP∪CLI；CQ1「edit 后 read_lints」零改纪律文案 |
| `goto_definition` | read | 无 | 路径+位置 → 定义位置列表 |
| `find_references` | read | 无 | 路径+位置/符号 → 引用列表 |
| `search_codebase` | read | 无 | 短期可仍词面；中期接符号表或混合，并改描述诚实化 |
| （阶段 D）`rename_symbol` 等 | write | always | 显式写副作用；默认不开 |

不新增 Engine 相位；不新增「结构阶段」事件类型也可先做——若需观测，可在现有 tool 事件上增加 `meta.structural=true` / `provider=lsp|ruff|treesitter`。

### 6.2 写入闭环（agent `system.md` 目标纪律）

在现有 Default loop / Verify 上加厚，**不加节点**：

```text
1. 定位：优先结构导航（有则用）；否则 grep / search_codebase
2. 读取：read_file（完整或续读规则不变）
3. 编辑：edit_file 最小 span（默认）；禁止无故 write_file 整文件
4. 验证：read_lints(受影响路径) → 必要时 find_references 扫调用点
5. 测试：有测试或用户要求则 run_tests
6. 结束：交付物 + 简要 what-changed
```

### 6.3 审批与沙箱

| 点 | 规则 |
|----|------|
| 只读导航 / 诊断 | 不打断用户；不进 write 审批 |
| 文件编辑 | 仍走现有 `edit_file` / `write_file` 审批覆盖 |
| Language Server 进程 | 跑在 Work 边界内；**deny-by-default env**（与 shell 子进程同纪律）；不继承宿主机密钥 |
| 会执行项目配置的 server | 威胁模型单列（§9）；可先 allowlist 语言（如 pyright 只读诊断模式） |
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

---

## 7. 分阶段落地（详细）

阶段可并行准备，但 **合并门禁按序收紧**。每阶段默认 **仅 agent Profile**。

### 阶段 A — 验证车道升级（优先服务「写入后」）

**做什么**

- 增强 `read_lints`：对支持语言走 LSP diagnostics；否则保留 ruff/CLI；再否则显式降级信息。  
- 默认范围：调用方传入的 path；目录则有上限（文件数/深度），禁止无界全仓。  
- system 纪律可强调「受影响路径」，不必改工具名。

**各种情况**

| 情况 | 期望 |
|------|------|
| 仅 Python + ruff 可用 | 行为 ≈ 今天 |
| Python + pyright LSP | 诊断可含类型；输出统一成 issues[] |
| 编辑了 `foo.ts` 但无 tsserver | `unsupported` 或 CLI fallback；不失败整 Turn |
| path 出 Work 根 | 与现有工具同样拒绝 |
| 沙箱无网络、需下加载插件 | 不允许运行时下载体；镜像预装 |

**验收**：golden「edit → read_lints → 修新增问题」；ruff-only 基线不回归；writing Profile 工具列表不变。

### 阶段 B — 只读导航（服务「改前定位 / 改后扫引用」）

**做什么**

- 增加 `goto_definition` / `find_references`（名称可微调，但语义稳定）。  
- 输入：path + line/col 或 path + symbol；输出：紧凑位置列表。  
- system：定位优先用导航；连续失败两次换策略（对齐现有失败恢复）。

**各种情况**

| 情况 | 期望 |
|------|------|
| 符号有唯一定义 | 返回定义；模型再 `read_file` |
| 多定义（重载/同名） | 列表返回，不擅自选 |
| 未打开过的文件 | server didOpen 后查询；计冷路径 |
| 仅词面同名、非引用 | 不得把 grep 结果伪装成 references |
| server 不可用 | 错误 + 提示用 grep；禁止空 hits 装成功 |

**验收**：跨文件改签名类 golden：references 覆盖调用点；工具误选类不回归。

### 阶段 C — 索引面 AST（升级 CQ4）

**做什么**

- `chunking.py`：代码路径优先 tree-sitter（按语言 grammar 逐步）；失败回落正则。  
- 仍只在 `index_scheduler` / sync-sources 等旁路执行。  
- chunk 元数据保留/增强 `symbol` / `section_title` / 行列。

**各种情况**

| 情况 | 期望 |
|------|------|
| 支持语言 | AST 边界切块 |
| 不支持/解析失败 | 正则 CQ4 或整文件滑窗；索引任务不因单文件失败崩溃 |
| 超大生成文件 | 预算上限；跳过或降级，可观测 |
| 查询热路径 | **零** 新增同步 parse |

**验收**：离线切块对照（同 query 命中率/边界完整率）；`search_sources`/代码检索相关评测不因切块变差；R1–R3 延迟对照持平。

**说明**：阶段 C 主要提升 **资料/索引检索叶子**；对「当前 workspace 即时写入」的帮助弱于 A/B，故排序在验证与导航之后（若产品以 workspace 即时编码为主，可与 B 并行开发、合并仍分轨验收）。

### 阶段 D — 写副作用结构操作（可选，后置）

**做什么**

- `rename_symbol` / 有限 code action；`approval=always`。  
- 与 `edit_file` 审批模型对齐；生成的编辑仍应可被用户理解（diff）。

**各种情况**

| 情况 | 期望 |
|------|------|
| 重命名影响多文件 | 单次工具返回 patch 集或多次 edit；须可审批、可取消 |
| server 部分成功 | 明确失败集；禁止静默半应用 |
| 与用户手工编辑冲突 | 应用前再校验；冲突则失败回读 |

**验收**：单独黄金集；默认 Profile 可先关闭，feature flag 打开。

---

## 8. 验收与否决清单

### 8.1 门禁（R5）

| 项 | 命令/产物 | 阶段 |
|----|-----------|------|
| 单元：切块/适配器/降级 | `make runtime-test`（或等价） | A–C |
| Agent golden：lint/导航/跨文件 | `make eval-all` 扩展 | A–B |
| Writing 不受影响 | Profile 快照 + writing golden 不回归 | 全程 |
| 延迟对照 | 同剧本 assemble_ms / TTFB / 首 token；结构工具 p95 | 全程 |
| 前缀稳定 | agent tools/system 字节稳定测试 | A–B 加工具时 |
| `make gate` | 合入前门禁全绿 | 全程 |

### 8.2 否决（全文级）

1. StartTurn / assemble 同步等待 LSP ready 或全库 AST。  
2. 为结构智能在 Engine 增加固定节点或 `if scenario`。  
3. Writing Profile 注册结构工具或启动 language server。  
4. 默认每次 edit 后全仓库诊断。  
5. 无降级路径：server 挂则 Turn 失败。  
6. 运行时下载语言插件/grammar（供应链与速率双重风险）。  
7. 无 golden / 无延迟对照的「质量」合并。  
8. 用结构工具结果预注入替代按需调用。  
9. 宣称替代 `run_tests`。

---

## 9. 安全、多租户与运维

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

## 10. 情况总表（速查）

| # | 情况 | 期望行为 |
|---|------|----------|
| 1 | writing 会话 | 无结构工具、无 LSP 进程 |
| 2 | agent 会话，未调用结构工具 | 可不预热；或旁路预热但不挡 TTFB |
| 3 | 首次 `goto_definition`，server 冷 | 工具内等待至 timeout；标 cold_start；失败则降级提示 |
| 4 | `edit_file` 后 `read_lints` 单文件 | LSP∪CLI；只报该路径（及实现选择的直接依赖，须有上限） |
| 5 | 模型对 `.` 调 `read_lints` | 目录扫描有文件数/深度上限；超限截断并说明 |
| 6 | 语言无 provider | `unsupported`，建议 grep/测试 |
| 7 | LSP 与 ruff 同时有结果 | 合并去重；标注来源；不互相覆盖静默丢弃 |
| 8 | Cancel 于诊断中 | 取消请求；Turn `cancelled` |
| 9 | 审批挂起中 server 崩溃 | 恢复执行后降级或旁路重启；不改 run_id 语义 |
| 10 | 索引 worker 解析失败单文件 | 跳过/回落正则；任务继续 |
| 11 | `search_codebase` 名实 | 阶段 B/C 前至少改描述诚实化；后接符号/混合 |
| 12 | 子 agent verify | 可用增强 `read_lints`；写作子类型不可见 |
| 13 | 用户只要「解释代码不改」 | 只读导航可用；不强制诊断仪式 |
| 14 | 超大 monorepo | 必须有 path 范围与超时；禁止隐式全仓 |
| 15 | stub/eval 环境无 LSP | 固定降级路径，golden 可双轨（structural on/off） |

---

## 11. 与现有代码/文档锚点

| 锚点 | 路径/说明 |
|------|-----------|
| R1–R5 | `docs/core/architecture.md` |
| 工具协议 / 组窗 | `docs/core/tools-and-context.md` |
| Engine / 审批取消 | `docs/core/runtime.md` |
| 索引 vs 交互 | `docs/topics/rag.md` |
| agent 纪律 | `services/runtime/app/scenarios/agent/system.md` |
| Profile | `services/runtime/app/scenarios/profiles/agent.yaml` · `writing.yaml` |
| CQ4 切块 | `services/runtime/app/retrieval/chunking.py` |
| `read_lints` / `search_codebase` | `services/runtime/app/tools/core/tools.py` |
| 工具注册 | `services/runtime/app/tools/bootstrap.py` |
| 子 agent 工具集 | `services/runtime/app/tools/delegate_runner.py` |

---

## 12. 建议决策（供评审勾选）

- [ ] **采纳三层模型**（交互工具 / 结构服务 / 索引面），否决主链强制流水线。  
- [ ] **仅 coding Profile 启用**；writing 零感知列为硬验收。  
- [ ] **落地序：A 诊断 → B 导航 → C 索引 AST → D 写副作用**（A/B 可准备并行，合并分轨）。  
- [ ] **`read_lints` 保留原名增强**，避免破坏 CQ1 文案与 golden。  
- [ ] **冷启动旁路 + 工具内 timeout + 强制降级** 写进实现契约。  
- [ ] **R5**：每阶段至少 1 组 agent golden + 延迟对照 + writing 不回归。  

---

## 13. 修订记录

| 日期 | 修订 |
|------|------|
| 2026-08-10 | 初稿：写入链目标、场景隔离、R1–R5 矩阵、交互逻辑、分阶段与情况总表 |
