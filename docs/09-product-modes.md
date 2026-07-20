# 09 — 场景（Scenario）：写作与通用 Agent

> 对外产品入口为 **写作模式** 与 **Agent 模式**；架构上二者是同一 Runtime 上的 **ScenarioProfile**（场景配置），不是两套系统。  
> 交互标准（对齐 Cursor）：**流式、可打断、过程可见、变更可审（diff）**。

## 0. 架构原则（后续扩展的宪法）

```text
一个 Runtime，多个 Scenario；
一个 Loop，    多组 Tool；
一条事件管道， 多种工作台布局。
```

| 层级 | 内容 | 演进策略 |
|------|------|----------|
| **内核（冻结）** | `AgentEngine` loop、`ContextEngine`、`ToolExecutor`、事件/投影管道、`07`/`09` 领域对象 | Phase 1 后尽量少改 |
| **场景（扩展）** | `ScenarioProfile`：工具白名单、子 agent 角色、prompt、审批、UI 布局 id | **新能力优先加在这里** |
| **工具（扩展）** | `tools/core/*` 实现；Scenario 只 **登记** 工具名 | 新工具 = 注册，不改 loop |
| **展示（扩展）** | 事件类型 + Projection + `web/scenarios/*` 组件 | 新面板 = 新 schema + 组件 |

**禁止（否则每次加功能都要改架构）**：

1. 在 `AgentEngine` / `ToolExecutor` 内 `if scenario == "writing"` 分支业务逻辑  
2. 为每个场景复制一套 loop、事件管道或 runtime 服务  
3. 用新 LangGraph 节点 / 固定 pipeline 阶段承载场景能力  
4. 在 runtime 内拼装 UI 结构；展示只走 Projection + SSE  

**允许**：

1. 新增 `scenarios/profiles/<id>.yaml` + 登记工具名  
2. 新增 `tools/core/<tool>.py` 并在 Profile 中启用  
3. 新增事件类型与 Projection schema（版本化）  
4. 新增 `web/scenarios/<id>/` 布局组件  

详见 [ADR-013](adr/013-dual-product-modes.md)。

---

## 1. 写作与通用 Agent 各需要什么

先分清 **用户要什么**，再映射到 **同一套原语**（工具、事件、投影）。

### 1.1 写作场景（垂直特化，平台默认）

| 需求类别 | 用户要什么 | 架构映射（扩展层，非新 pipeline） |
|----------|------------|-----------------------------------|
| 结构 | 大纲、章节、进度 | 工作区 `outline.md`、`sections/`；工具 `update_outline`；投影 `DocumentOutlineView` |
| 成稿 | 长文流式、按节写 | `draft_section`；事件 `section.draft.delta` |
| 改稿 | 看见 diff、可收可拒 | **共享** `propose_patch` → `patch.proposed` → Accept → `apply_patch` |
| 证据 | 资料、引用、核对 | `search_sources`、`check_citation`；`CitationView` |
| 质量 | 事实、风格、结构 | 按需 `delegate`：researcher / fact_checker / stylist |
| 交付 | 导出、版本 | `export_document`、artifacts |
| 交互 | 跟手、可打断 | 共享 SSE、`CancelTurn`；UI 偏文稿编辑器 |

**默认关闭**：`run_command`、代码库 `grep`（避免干扰写作；需要时用 Agent 场景）。

### 1.2 通用 Agent 场景（全工具面，Cursor 式）

| 需求类别 | 用户要什么 | 架构映射 |
|----------|------------|----------|
| 探索 | 找文件、读上下文 | read、`glob`、`grep` |
| 检索 | 代码库/资料检索 | `search_codebase` / `search_sources`（Phase 1b 最小可用；Phase 2+ 增强为正式语义检索） |
| 执行 | 跑命令、验证 | `run_command`、`run_tests`；强审批 |
| 改动 | 多步改文件 | `propose_patch` 或 `write_file`；时间线可见 |
| 规划 | 复杂任务拆解 | `update_plan`；`delegate(planner)` |
| 协作 | 长任务不爆窗 | `delegate`：explore / verify / edit |
| 交互 | 工具轨、产物 | `TimelineView`、`ArtifactView` |

### 1.3 共享原语（只实现一次，两场景复用）

约占能力 **70%**，不得按场景复制实现：

| 原语 | 说明 |
|------|------|
| Agentic loop | 同一 `AgentEngine` |
| `propose_patch` / `apply_patch` | 写作主路径；Agent 强烈推荐 |
| `read_file`、`list_dir`、`delegate` | 核心工具在 `tools/core/` |
| 流式 + 打断 | `turn.token`、`tool.delta`、`CancelTurn` |
| 上下文治理 | `ContextEngine` 全场景相同 |
| 事件 / SSE / 投影 | [`08-event-projection-pipeline.md`](08-event-projection-pipeline.md) |
| Run / Turn 1:1 | [`07-domain-model.md`](07-domain-model.md) |

---

## 2. 内置场景总览

```text
                 ┌──────────────────────────────────┐
                 │     Agent Runtime 内核（共享）     │
                 └───────────────┬──────────────────┘
                                 │
           ┌─────────────────────┴─────────────────────┐
           v                                           v
  scenario_id: writing                         scenario_id: agent
  文稿 · diff · 大纲 · 引用                    探索 · exec · 时间线
  （平台默认）                                （全工具面 / 通用）
```

| 维度 | `writing` 写作 | `agent` 通用 Agent |
|------|----------------|-------------------|
| 产品名称 | 写作模式 | Agent 模式 |
| 定位 | 长文、报告、方案、交付 | 调研、工程、多步任务 |
| 工作区 | `outline.md`、`sections/`、`sources/` | 任务目录 / 仓库 / 产物 |
| 核心 UI | 对话 + **文稿 diff** + 大纲/证据 | 对话 + **工具时间线** + 产物 |
| 子 agent | researcher、drafter、editor、fact_checker、stylist | explore、retrieve、verify、edit、planner |
| 审批倾向 | 写文稿 **on_write** | `exec` **always** |

**术语**：

- **Scenario**（架构）：`scenario_id` + `ScenarioProfile` 配置  
- **模式**（产品）：用户可见的「写作模式 / Agent 模式」，对应内置 scenario  

新增第三类场景（如 `interview` 访谈纪要）= 新 Profile + 工具登记 + UI 组件，**不改内核**。

---

## 3. ScenarioProfile 与注册

### 3.1 配置结构

```yaml
# 已实现：services/runtime/app/scenarios/profiles/writing.yaml
scenario_id: writing
display_name: 写作模式
system_prompt_template: scenarios/writing/system.md
tool_names:
  - read_file
  - list_dir
  - propose_patch
  - draft_section
  - update_outline
  - update_plan
  - search_sources
  - check_citation
  - export_document
  - delegate
max_steps: 40
approval_overrides: {}
workspace_layout: document
web_layout: writing-workbench
```

```python
# 已实现：services/runtime/app/scenarios/registry.py
@dataclass(frozen=True)
class ScenarioProfile:
    scenario_id: str
    display_name: str
    system_prompt: str
    tool_names: list[str]
    max_steps: int = 40
    approval_overrides: dict[str, str] = field(default_factory=dict)
    workspace_layout: str = "document"
    web_layout: str = "default"
    subagent_types: list[str] = field(default_factory=list)
```

### 3.2 运行时加载（唯一允许的「场景分支」）

```text
StartTurn(scenario_id)
  → ScenarioRegistry.get(scenario_id)   # 仅 TurnController
  → 组装 ToolScope(scenario_id, ...)
  → AgentEngine.run(ToolScope)          # 无 scenario 业务分支
```

`AgentEngine` 只接收 **已裁剪的** `ToolSpec` 列表与 `system` 字符串，**不知道** scenario 名称。

### 3.3 注册表

```python
# 启动时（已实现）
ScenarioRegistry.load()  # 自动加载 profiles/*.yaml
```

已注册场景：`writing`、`agent`、`interview`（`services/runtime/app/scenarios/profiles/`）。

---

## 4. API

```http
POST /api/v1/sessions/{session_id}/turns
Content-Type: application/json

{
  "message": "根据大纲完成第二节初稿",
  "scenario_id": "writing",
  "client_request_id": "uuid"
}
```

| 字段 | 说明 |
|------|------|
| `scenario_id` | 场景 id；内置 `writing` \| `agent` |
| `mode` | **兼容别名**，等同 `scenario_id`（实现可选支持，文档以 `scenario_id` 为准） |
| 省略时 | 使用 Session.`default_scenario_id`（默认 `writing`） |

```json
{ "default_scenario_id": "writing", "title": "Q3 复盘报告" }
```

切换场景 = **新 Turn**（新 Run）；同一 Session 内可先 `writing` 再 `agent`，靠 `session_context` 衔接。

---

## 5. 场景 `writing`（写作模式）

### 5.1 工作区

```text
/workspace/
  project.yaml
  outline.md
  sections/
  sources/
  .agent/revisions/
```

### 5.2 场景专属工具（实现在 `tools/core/`，此处为登记）

| 工具 | 副作用 | 说明 |
|------|--------|------|
| `search_sources` | network | 资料检索 |
| `update_outline` | write | 大纲结构修改，直接作用于 `outline.md` |
| `draft_section` | write | 生成章节草稿，写入 `.agent/revisions/{turn_id}/`，不直接覆盖正式文稿 |
| `check_citation` | read | 引用核对 |
| `export_document` | write | 导出 |

加 **共享 core 工具**：`read_file`、`list_dir`、`propose_patch`、`apply_patch`、`delegate`、`update_plan`。

### 5.2.1 写作场景的标准修改语义

为避免“领域写工具”与通用 patch 工具并行改同一目标，写作场景统一采用以下主路径：

1. **结构修改**：`update_outline` 修改 `outline.md`
2. **内容生成**：`draft_section` 只产出草稿或修订候选，不直接覆盖正式 `sections/*.md`
3. **正式落稿**：对正式文稿的变更统一走 `propose_patch` → 用户确认 → `apply_patch`
4. **导出交付**：`export_document` 必须接收显式章节集合；`source=confirmed` 读取已确认正文，`source=current_draft` 只读取本轮 manifest 指向的草稿，用于用户明确要求的即时草稿交付

约束：

- `draft_section` 产生的内容若要进入正式文稿，必须转成 `propose_patch` 结果
- 草稿导出不等于正式落稿；`current_draft` 不得扫描其他 Turn 的 revisions
- UI 中“接受修改”统一绑定 `apply_patch`，不直接绑定 `draft_section`
- 写作场景禁止把 `write_file` / `edit_file` 作为默认文稿主路径暴露给模型

**Patch 审阅与 Turn 状态**（ADR-015）：`propose_patch` 产出后，若模型无后续 `tool_use`，Turn 正常 **`completed`**。用户在 Turn 结束后通过 `patch/accept` 或 `patch/reject` 决策；**不**引入 `waiting_patch_decision` 执行态。拒稿不等于 `CancelTurn`。

### 5.3 子 agent（仅本场景 Profile 启用）

researcher、drafter、editor、fact_checker、stylist — 见 §2 表。

### 5.4 UI 与事件

- 布局：`web/scenarios/writing/`  
- 投影：`DocumentOutlineView`、`SectionView`、`PatchProposalView`、`CitationView`  
- 事件：`outline.updated`、`section.draft.delta`、`patch.proposed`、`patch.applied`、`patch.rejected`  

### 5.5 场景内策略（非顶层 scenario）

「只聊不改」「只出大纲」等：**不**新增 scenario_id；通过用户指令 + **临时裁剪 tool_names** 或 prompt 完成。

---

## 6. 场景 `agent`（Agent 模式）

### 6.1 工作区

```text
/workspace/          # 任务文件、代码库
/data/artifacts/
```

### 6.2 场景专属工具登记

在 writing 登记基础上 **增加**：`glob`、`grep`、`search_codebase`、`write_file`、`edit_file`、`run_command`、`run_tests`、`read_lints`。

说明：

- `glob`、`grep`、`run_tests`、`read_lints` 为 agent 场景可直接暴露的正式工具名
- `search_codebase` 在 Phase 1b 可由 `grep` + 小索引退化实现，但对模型、事件、审批、Golden 的权威工具名仍为 `search_codebase`

### 6.3 子 agent

explore、retrieve、verify、edit、planner。

### 6.4 UI 与事件

- 布局：`web/scenarios/agent/`  
- 投影：`TimelineView`、`RetrievalView`、`ArtifactView`  
- 共用 ADR-004 核心事件 + `tool.*`  

---

## 7. 共用能力与体验指标

体验 SLO **权威来源**：[`10-product-experience.md`](10-product-experience.md) §1（勿在本表重复定义冲突值）。

| 能力 | 规格 |
|------|------|
| 流式 | `turn.token`、`tool.delta`、`section.draft.delta` |
| 软/硬取消 | `POST /api/v1/turns/{id}/cancel`；`force` 语义见 [`contracts.md`](contracts.md) §2.1、[ADR-015](adr/015-interrupt-cancel-resume.md) |
| UI 主数据源 | 进行中 SSE；重连见 `09` |
| 受理首包（TTFB） | ≤ 300ms P95 → `turn.accepted`（见 `11`） |
| 首模型 token | ≤ 800ms P95 → `turn.token`（Phase 1+；模型排队另计） |
| 事件→客户端 SSE | ≤ 300ms P95（`turn_events` 写入后） |

---

## 8. 扩展新场景检查清单

新增 scenario（如 `interview`）时 **只允许**：

- [x] 新增 `profiles/interview.yaml`
- [x] 在 Profile 中 **登记** 已有或新增 core 工具名
- [x] 如需新工具：仅加 `tools/core/<name>.py` + 注册
- [x] 如需新 UI：加 Projection schema + `web/scenarios/interview/`
- [x] 更新 `packages/contracts` 与 ADR 索引

**必须拒绝**（访谈场景已验证未做）：

- [x] 修改 `AgentEngine` 循环逻辑  
- [x] 新增 pipeline 节点或第二张状态图  
- [x] 复制 `tools/` 或 `realtime/` 整套实现  

---

## 9. Phase 路线图

> **能力融合**：RAG、`delegate`、完整 compact 链不得在 Phase 2 才「首次接线」。Phase **1b** 必须用 golden 证明走主路径（`06` §0.1、`12` §5.2）。

| Phase | writing | agent | 能力融合 |
|-------|---------|-------|----------|
| **0** | stub SSE | stub SSE | — |
| **1** | `propose_patch`、diff、大纲 stub | loop、timeline、patch | ContextEngine 随多 Step **隐式**运行 |
| **1b** | `search_sources` + `check_citation` | `grep` + `search_codebase`（小索引即可） | **阻断**：`shared.04` compact；`delegate` 各 1 条 |
| **2** | 完整资料库索引、多角色 delegate | explore/verify delegate、`live` eval | 向量运维、metrics |
| **3+** | 交付 eval、长 Session | 工程 eval、并发 delegate | 日常自用（`11` §7） |

Phase **1** 完成 = `12` §5.1 + SLO。宣称「能力健全」= 再加 **§5.2 全绿**。

---

## 10. 代码落点

```text
services/runtime/app/
├── engine/                 # 无 scenario 分支
├── tools/
│   └── core/               # 所有工具实现（共享）
├── scenarios/
│   ├── registry.py         # ScenarioRegistry
│   └── profiles/
│       ├── writing.yaml
│       └── agent.yaml

services/web/
├── shared/realtime/        # SSE 客户端（共享）
└── scenarios/
    ├── writing/
    └── agent/
```

---

## 11. 相关 ADR

- [ADR-005](adr/005-agentic-loop-over-pipeline.md) — 单 loop  
- [ADR-006](adr/006-tool-centric-capabilities.md) — 能力即工具  
- [ADR-007](adr/007-subagent-delegation.md) — 子 agent  
- [ADR-013](adr/013-dual-product-modes.md) — Scenario 与 Profile 扩展  
- [ADR-018](adr/018-web-frontend-stack.md) — Web 前端栈与 `scenarios/*` 布局
- [ADR-019](adr/019-model-provider-runtime-config.md) — 模型供应商 Web 管理 + DB 热生效
