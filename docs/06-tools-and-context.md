# 06 — 工具与上下文工程

> agent 的质量高度取决于两件事：**模型能调哪些工具**、**每一轮往窗口里放什么**。
> 本文定义工具协议 `Tool Registry` 与上下文引擎 `Context Engine`。

## 0. 设计基线

本文件遵循与 [`docs/02-architecture.md`](docs/02-architecture.md) 和 [`docs/05-agent-runtime.md`](docs/05-agent-runtime.md) 相同的原则：

- 参考 Cursor、Claude Code、Copilot Agent 等成熟编码 agent 的已验证经验
- 工具系统必须增强能力，但不能把运行时重新做成臃肿平台
- 上下文工程必须保证长会话可持续，而不能靠不断扩大窗口硬撑
- 工具协议与上下文策略必须让错误边界更清晰，而不是更隐蔽
- 性能优先于概念完美，任何工具和上下文机制都要接受主路径成本审视

### 0.1 能力主路径（禁止摆设）

以下能力 **必须融合进运行时主路径**，不得实现为独立子系统后从不调用：

| 能力 | 融合方式 | 禁止 |
|------|----------|------|
| **上下文编排** | 每 Step `ContextEngine.assemble`（§6）；工具结果经 budget（§7） | 仅初始化时跑一次；无日志的「空 assemble」 |
| **RAG** | 仅 `search_sources` / `search_codebase` 等 **工具** → `tool_result` → 下一轮 assemble（§10） | 每轮预注入向量包；独立 retrieval 服务不被 loop 调用 |
| **多 agent** | 仅 `delegate` 工具 → 子 `AgentEngine` run → 摘要回灌（`05` §10） | supervisor 图节点；子会话整包倒灌主 messages |

**验收**：[`12-eval-and-golden-turns.md`](12-eval-and-golden-turns.md) §5.2 为 **Phase 1b 阻断项**——无 golden 覆盖不得进入 Phase 2。

## 1. 原则：能力即工具

旧项目把 `retrieval`、`verify`、`writing` 做成流水线节点。新项目里它们都是**工具**，由模型在循环中按需调用。

工具是 agent 唯一的执行扩展点。加一个能力等于注册一个工具，**不动循环、不改图**。

这也是成熟编码 agent 的共同经验：

- 核心 loop 保持小而稳定
- 能力增长集中在工具层
- 检索、验证、编辑、执行统一抽象为模型可调用能力

## 2. 工具协议 Tool Registry

旧 `tool_registry.py` 是同步、按角色校验、无流式、无副作用分级的最小实现。新协议补齐 agent 所需字段。

```python
# packages/contracts/python/tools.py 或 runtime/tools/spec.py
class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict
    side_effect: SideEffect
    approval: ApprovalPolicy
    required_role: str = "user"
    timeout_s: float = 60
    handler: Callable[[ToolCall, ToolContext], AsyncIterator[ToolEvent]]
```

```python
class ToolCall(BaseModel):
    tool_call_id: str
    name: str
    arguments: dict

class ToolResult(BaseModel):
    tool_call_id: str
    status: Literal["ok", "error", "denied", "timeout"]
    content: list[ContentBlock]
    is_error: bool = False
```

要点：

- `description` 与 `input_schema` 同时属于 prompt 的一部分，必须像产品接口文案一样认真编写
- `handler` 必须支持 async 与流式输出，长工具执行可以产生增量事件
- 工具结果进入 `messages` 前，必须统一经过预算控制
- 工具协议应对模型友好，但更要对运行时友好，避免单次调用把系统拖入高成本状态

## 3. 工具系统的性能与复杂度约束

这是吸收源项目问题后的硬规则。

### 3.1 默认按需暴露工具

- 不把所有工具在每轮完整暴露给模型
- 工具清单可按角色、场景、agent 类型、路径上下文裁剪
- 高成本工具必须具备更高准入门槛

### 3.2 默认工具结果可截断

- 大文件读取、海量搜索结果、长命令输出必须支持截断
- 截断后要保留可重新获取的指针、范围或摘要
- 禁止把原始大输出无脑塞回 `messages`

### 3.3 默认错误边界靠近工具入口

工具调用必须优先在以下阶段失败：

- `input_schema` 校验失败
- 路径越权失败
- 审批未通过
- 超时或资源配额超限
- provider 或外部依赖不可用

不要让错误延后到模型下一轮“自己猜为什么失败”。

### 3.4 默认工具可观测

每次工具调用至少要可记录：

- `tool_call_id`
- `tool_name`
- `trace_id`
- `latency_ms`
- `status`
- `approval_result`
- `retry_count`

### 3.5 RAG 与检索是必须能力

成熟 agent 在真实工程任务中必须具备稳定的 RAG 与检索能力，但这类能力必须作为工具体系的一部分，而不是回到固定检索阶段。

阶段口径：

- **Phase 1b** 要求的是：`search_sources` / `search_codebase` 作为正式工具进入主路径，并能被 Golden 断言调用与消费
- **Phase 1b** 不要求完整 embedding 基础设施常驻镜像或完整向量平台启动
- **Phase 2** 才要求 `/data/models`、`/data/vectorstore` 与更完整的 embedding / rerank / 索引运维架构全面到位

最小要求：

- 支持代码库与文档的结构化检索与语义检索
- 支持 embedding 模型加载、缓存与版本管理
- 支持检索结果重排、截断、证据引用与结果预算
- 支持将检索结果以 `tool_result` 方式进入上下文，而不是每轮预注入整包 RAG 内容
- 支持索引更新与 embedding 构建走异步路径，避免阻塞主执行链路

## 4. 副作用分级与审批门

这是旧 `policy_node` 与 `human_review_node` 的替代物：审批**绑定到单个工具调用**，而不是图里的终态节点。

| 级别 | 含义 | 示例工具 | 默认审批 |
|---|---|---|---|
| `read` | 只读，无外部影响 | `read_file`、`grep`、`glob`、`search_codebase` | never |
| `write` | 修改工作区文件或受管文稿 | `propose_patch`、`apply_patch`、`write_file`、`edit_file`、`update_outline`、`draft_section` | on_write |
| `exec` | 执行命令或代码 | `run_command`、`run_tests` | always |
| `network` | 访问外部网络 | `web_fetch`、`http_request`、`search_sources` | on_write 或 always |
| `delegate` | 派生子 agent，消耗独立预算并产生间接副作用 | `delegate` | always |

### 4.1 权威工具命名与别名规则

为避免 prompt、运行时、文档、前端卡片使用不同称呼，工具命名按以下规则统一：

- **权威工具名**：进入 `ToolSpec.name`、事件、日志、审批、Golden 的唯一名字
- **实现别名**：仅允许作为兼容层存在，不进入新文档与新 schema
- **场景登记**：`ScenarioProfile.tool_names` 只能登记权威工具名

当前统一结果：

| 权威工具名 | 类别 | 说明 | 兼容别名策略 |
|---|---|---|---|
| `read_file` | core | 读取文件 | 无 |
| `list_dir` | core | 列目录 | `glob` 为独立工具，不是别名 |
| `propose_patch` | core write | 生成可审 diff，不直接落盘 | 不再与 `edit_file` 混称 |
| `apply_patch` | core write | 接受已提议 patch 并落盘 | 不与通用 patch executor 混称 |
| `write_file` | agent write | 整体新建或覆盖文件 | 无 |
| `edit_file` | agent write | 精确替换既有文件片段 | 无 |
| `run_command` | agent exec | 执行命令并流式返回 | 无 |
| `search_sources` | retrieval | 文档/资料检索 | 无 |
| `search_codebase` | retrieval | 代码库检索，Phase 1b 最小可退化到 grep + 小索引 | 无 |
| `delegate` | delegation | 派生子 agent | 无 |
| `update_plan` | planning | 更新 TODO / 计划投影 | 无 |

审批流：

```text
模型产出 tool_use run_command
  → ToolExecutor 查 approval 策略
  → 发 approval.requested 事件
  → loop 在 Step 边界挂起
  → 用户 allow 或 deny
  → allow 执行
  → deny 回灌 ToolResult denied，模型改道
```

规则：

- `exec` 与 `write` 工具必须走路径白名单与租户隔离
- 被拒绝的调用要记入 `permission_denials`
- 审批策略可按租户、环境、agent 类型覆盖
- 高风险工具授权不得仅靠模型自判断

## 5. 工具执行规范

### 5.1 超时与重试

- 每个工具必须声明 `timeout_s`
- 默认不无限重试
- 是否重试由工具类型决定，不是所有错误都应自动重试
- 超时结果必须显式回灌为 `timeout` 或等价状态

### 5.1.1 可取消性（ADR-015）

以下工具类型 **必须** 响应父 Run 的 cancel（轮询 `cancel_requested_at` / `TurnState.cancelled`）：

| 类型 | `force: false` | `force: true` |
|------|--------------|---------------|
| `run_command` | 优雅停子进程（默认 500ms） | `SIGTERM` → 超时 `SIGKILL` |
| 流式网络工具 | 关闭连接 | 立即关闭 |
| `delegate` | 级联 abort 子 Engine | 同左 |
| 其他长耗时 handler | 在输出循环内检查 abort | 尽快退出 |

### 5.1.2 可取消性与超时（交叉引用）

- 取消：ADR-015、`06` §5.1.1
- 超时默认值：ADR-016（model 120s、tool `timeout_s`、Step 300s）

### 5.2 流式输出

以下工具类型应优先支持流式：

- `run_command`
- 长时间网络请求
- 可能产生持续 stdout 的验证工具

流式输出规则：

- 流式内容进入 `tool.delta`
- 最终摘要进入 `tool.completed`
- 前端显示流式过程，但运行时只把必要摘要回灌 `messages`

### 5.3 返回结构标准化

所有工具输出推荐收敛为统一结构：

- `summary`
- `payload`
- `artifacts`
- `is_truncated`
- `retry_hint`

这样做的目的：

- 模型更容易稳定消费
- 前端更容易统一渲染工具卡片
- debug 更容易区分摘要、正文和产物引用

## 6. 上下文引擎 Context Engine

> 这是真正的护城河。成熟编码 agent 在调模型之前都会对上下文做多层整理，我们采用相同方向，但保持实现克制。

`ContextEngine.assemble(state)` 在**每一轮 Step 调模型之前**执行，产出当前轮的消息窗口。它不是一次性治理阶段，而是每轮都跑。

### 6.1 最小输入输出契约

输入最小面：

- `TurnState.messages`
- `step_index`
- `ScenarioProfile`
- 当轮可见 `ToolSpec` 列表
- `session_context`
- `project_context`
- `runtime_context`
- 预算配置 `ContextBudgetPolicy`

输出最小面：

```python
class ContextEnvelope(TypedDict):
    system_blocks: list[ContentBlock]
    message_window: list[Message]
    included_tools: list[str]
    budget_report: dict
    compaction_trace: list[dict]
```

约束：

- `system_blocks` 仅用于当轮模型调用，不回写 `TurnState.messages`
- `message_window` 必须可直接送入模型层，不再做二次拼接
- `included_tools` 必须与当轮真实可见工具一致，供日志与 debug 对齐
- `budget_report` 至少包含压缩前后 token 估计、触发的策略名、被截断块计数
- `compaction_trace` 只记录策略摘要与引用，不复制大段原文

## 7. 上下文工程的多层防线

### 7.1 budget

> 某一类内容最多占多少窗口。

最典型的是工具结果预算：读大文件、grep 海量结果、网页抓取都可能瞬间撑爆上下文。

```python
def apply_tool_result_budget(result: ToolResult, budget: int) -> ToolResult:
    if token_len(result) > budget:
        return truncate_with_pointer(result)
    return result
```

预算分项：

- 工具结果预算
- 单轮上下文预算
- thinking 预算
- 最终输出预算

### 7.2 snip

轻量裁边，适合历史略超时快速缩短窗口。

### 7.3 microcompact

局部压缩，在大压缩前先整理局部高噪音内容。

### 7.4 collapse

把一段历史折叠成更紧凑、可重建的视图，例如：

- 多文件读取折叠为文件清单加重新读取指针
- 多轮命令输出折叠为关键结果加日志引用
- 多个重复失败折叠为失败摘要和禁止重复提示

### 7.5 autocompact

整体摘要重写，作为窗口将满时的最后兜底。

## 8. 上下文工程的性能约束

上下文工程不是越复杂越好，必须满足：

- 整理成本必须小于不整理带来的模型成本
- 默认优先保留最近轮次、高价值证据、当前任务约束
- 不能每轮做重型全历史总结
- 压缩与折叠必须可解释，不能让模型突然失去必要上下文而无迹可循
- compact 与 collapse 的输出要尽量稳定，降低模型行为抖动

## 9. 执行顺序 多层防线

```text
取消息窗口
→ apply_tool_result_budget
→ snip
→ microcompact
→ collapse
→ autocompact 兜底
→ 调模型
```

原则：

- 先处理最危险的大块内容
- 再逐层瘦身
- 不依赖单一万能摘要器

## 10. 长上下文与 RAG 编排

长上下文编排与 RAG 必须协同设计，而不是各自独立叠加。

### 10.1 检索结果进入上下文的规则

检索结果只能通过以下方式进入模型窗口：

- 作为 `search_codebase`、`search_sources` 等工具的 `tool_result`
- 以摘要、证据片段、文件路径、命中分数、重读指针等结构化形式进入
- 严格受工具结果预算控制

禁止行为：

- 每轮模型调用前无条件预注入大量检索片段
- 把完整检索日志、完整 embedding 元信息直接塞进窗口
- 因为检索能力增强而放弃上下文预算控制

### 10.2 embedding 模型与索引架构

embedding 能力必须是正式架构的一部分，而不是实现时临时补丁。

要求如下：

- embedding 模型由 `runtime` 或专门检索组件消费，不进入 `api`
- embedding 模型必须支持本地缓存与版本标识
- `/data/models` 保存模型缓存，`/data/vectorstore` 保存向量索引
- 索引构建、增量更新、重建、迁移必须与主执行链路分离
- 检索组件必须可替换底层实现，例如 Chroma、Qdrant 或其他向量存储

### 10.3 检索链路最小流程

```text
内容变更或知识导入
  → 异步切分 chunk（markdown 标题优先，INDEX v3）
  → embedding 生成
  → 写入 vectorstore（JSON；经 SourceRetrievalStore 可替换 Chroma/Qdrant）
  → 查询：BM25 + 向量双路召回
  → RRF 融合
  → lexical rerank（默认）/ 可选 cross-encoder rerank（retrieval profile）
  → 结果预算裁剪（excerpt + section 元数据）
  → 作为 tool_result 回灌
```

写作场景额外约束：`search_sources` 每 Turn 默认最多 3 次；已知 `sources/` 路径时优先 `read_file`。
人物/风格**写定**放在 `sources/cards/`，Turn 开始时按任务选中并 pin 进 system（默认 ≤2k 字），不走 RAG、不做重审流水线。

### 10.4 长上下文与检索协同原则

1. 检索用于引入外部或历史证据，不替代上下文治理
2. 长上下文用于维持连续推理，不替代检索能力
3. 若窗口压力高，优先保留当前高价值证据与任务约束，而不是保留大量低置信检索片段
4. 子 agent 检索到的大量材料，返回主循环时必须先摘要化

## 11. 场景与工具集

平台通过 **ScenarioProfile** 为每个 Turn 裁剪工具与子 agent（见 [`10-product-modes.md`](10-product-modes.md)）。工具**实现**均在 `tools/core/`；场景只 **登记** 工具名。

- **`writing`**：文稿、diff、大纲、引用  
- **`agent`**：在 core 工具上增加 exec、代码库检索等  

`ToolRegistry.list_tools(scope)` 的 `scope.scenario_id` 决定当轮可见工具；**禁止**在 Registry 内写场景业务逻辑。

### 11.1 能力与 Phase 绑定（实施顺序）

| 能力 | 首次必经 Phase | 触发方式 | Golden（`12`） |
|------|----------------|----------|----------------|
| budget + snip | **1**（多 Step 即触发） | `read_file` 大文件等 | `shared.04` |
| compact 链 | **1b** | 长 tool 历史 / 压力用例 | `shared.04` 断言策略字段 |
| `search_sources` | **1b** | writing 资料写作 | `writing.05` |
| `grep` / `search_codebase` | **1b** | agent 探索（先 grep，再语义） | `agent.04` |
| `delegate` | **1b** | Profile 白名单角色 | `writing.06` 或 `agent.05` |
| 向量索引运维 | **2** | 异步索引 + retrieval profile | `12` §5.3 |

### 11.2 Phase 1b 检索最小能力定义

为统一 [`docs/03-docker-runtime.md`](docs/03-docker-runtime.md) 的依赖约束与本文件的主路径要求，Phase 1b 的检索最小能力定义如下：

| 工具 | Phase 1b 最小实现 | 不要求 | Phase 2 增强 |
|---|---|---|---|
| `search_sources` | 基于 workspace 文档库的关键词检索，可附带小规模元数据索引 | 不要求完整 embedding pipeline 常驻启动 | 可接向量索引、rerank、远程资料库 |
| `search_codebase` | 先 `grep` / 路径过滤，再可选接小型本地索引；结果必须预算裁剪 | 不要求 torch / sentence-transformers 常驻在 Phase 0–1 镜像 | 可升级为正式 embedding 检索 |

规则：

- Phase 1b 的目标是让检索**走主路径并可 golden**，不是一次到位部署完整向量平台
- 若无 embedding 依赖，`search_codebase` 仍必须以权威工具名存在，并返回结构化 `tool_result`
- Phase 2 才要求 `/data/models`、`/data/vectorstore` 与正式 embedding 架构全面到位

## 12. 上下文注入分层

模型每轮收到的窗口由 ContextEngine 分层组装（**不等于**全部写入 `TurnState.messages` 历史）。跨 Turn 策略见 [`07-domain-model.md`](07-domain-model.md) §5。

| 层 | 内容 | 来源 |
|---|---|---|
| system prompt | agent 角色、行为准则、工具清单 | 静态模板加动态工具表 |
| project context | 项目说明、目录结构、约定 | 工作区读取 |
| runtime context | 日期、git 状态、打开文件、近期编辑、错误摘要 | 运行时采集 |
| message history | 经整理后的对话与工具结果 | `TurnState.messages` |
| retrieved evidence | 检索工具结果 | 按需，作为 `tool_result` 进入 |

关键差异：**检索是工具结果，不是预注入**。模型决定何时查、查什么、查几次。

## 13. 共享 core 工具（`tools/core/`）

以下工具**只实现一次**，由 ScenarioProfile 按需登记：

| 工具 | 副作用 | writing | agent | 说明 |
|------|--------|:-------:|:-----:|------|
| `read_file` | read | ✓ | ✓ | |
| `list_dir` | read | ✓ | ✓ | |
| `propose_patch` | write | ✓ | ✓ | **diff-first，两场景共用** |
| `apply_patch` | write | ✓ | ✓ | Accept 后落盘 |
| `delegate` | delegate | ✓ | ✓ | `agent_type` 由 Profile 限定 |
| `update_plan` | read | ✓ | ✓ | 更新受管计划投影或 TODO 展示；不直接修改工作区、执行命令或访问外网 |

## 14. 场景 `writing` 登记的工具

| 工具 | 副作用 | 说明 |
|------|--------|------|
| `search_sources` | network | 资料检索 |
| `update_outline` | write | 大纲 |
| `draft_section` | write | 流式小节；按 Turn 写入受管 revisions 并更新 manifest |
| `check_citation` | read | 引用核对 |
| `export_document` | write | 按显式 `section_ids` 从正式稿或本轮草稿导出 |

## 15. 场景 `agent` 额外登记的工具

| 工具 | 副作用 | 说明 |
|---|---|---|
| `read_file` | read | 读文件，带行号 |
| `list_dir` | read | 目录读取 |
| `glob` | read | 模式匹配 |
| `grep` | read | 内容搜索；可作为 `search_codebase` 的最小退化实现之一 |
| `search_codebase` | read | 代码库检索；Phase 1b 可由 `grep` + 小索引退化实现 |
| `edit_file` | write | 精确替换既有文件片段 |
| `write_file` | write | 新建或覆盖文件 |
| `run_command` | exec | 终端命令，流式 stdout，可取消 |
| `run_tests` | exec | 验证测试命令 |
| `read_lints` | read | 读取 lint/诊断结果 |
| `update_plan` | read | 维护 TODO 投影 |
| `delegate` | delegate | 派生子 agent |

## 16. 日志与 debug 规范

为了方便 debug，工具与上下文系统必须有可追踪日志。

### 16.1 工具日志

每次工具调用至少输出：

- `trace_id`
- `turn_id`
- `tool_call_id`
- `tool_name`
- `status`
- `latency_ms`
- `is_truncated`

### 16.2 上下文日志

每轮上下文组装至少输出：

- `trace_id`
- `turn_id`
- `step_index`
- 压缩前 token 估计
- 压缩后 token 估计
- 触发了哪些 budget 或 compact 策略

### 16.3 Debug 原则

- 能定位是工具错误、上下文膨胀、审批等待还是模型理解偏差
- 能定位是哪一次压缩导致信息丢失或行为变化
- 工具日志与运行时事件通过 `trace_id` 对齐

## 17. 从 agent-langraph 迁移

见 **[`appendix-migration.md`](appendix-migration.md)**。

## 18. 本文档对应的 ADR

- ADR-006：能力以工具暴露
- ADR-008：上下文工程多层防线
- ADR-009：四层协议
- ADR-011：Run 与 Turn 1:1
- ADR-012：事件 Pull 模型
- ADR-013：Scenario 与 Profile 扩展
