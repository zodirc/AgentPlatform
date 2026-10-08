# 写作内核独立宿主设计说明

| 项 | 内容 |
|----|------|
| 状态 | 已实现。A1–A10 在 `services/runtime`；Android 壳仍不在本部分 |
| 定位 | 写作 Android 客户端的第一部分。不依赖 Android，但需求来自 Android，验收也以 Android 能直接使用为准 |
| 所在仓库 | 本仓库，`services/runtime` |
| 下游 | `docs/android-writing-client.md`（第二部分） |
| 交付物 | 可独立运行的写作内核、宿主协议、桌面命令行宿主、签名的内核包 |
| 不包含 | Android 壳、界面、APK 构建与分发 |

---

## 1. 目的

让写作回合离开服务器基础设施也能完整运行：不需要 Postgres、Redis、检索进程或 api 服务。只要有一个稿树目录和一个 OpenAI 兼容的模型地址，就能跑完一回合，且行为与服务器同源。

本部分完成后：

- 服务器写作回合的编排从 controller 中抽出，变得可测；行为不变。
- 任何宿主（Android、桌面命令行，以及将来可能的桌面应用）都通过同一份宿主协议驱动写作内核。
- 写作内核可以打成一个版本化、带签名的包，供下游按版本消费，并支持单独热更新（第 8 节）。

## 2. 为什么不是"与 Android 无关"

以下需求都来自手机端，但实现完全在 Python 侧。如果这一部分不承担它们，第二部分就只能在壳里绕路，或者回头再改内核：

| 需求 | 来自 | 落在本部分的哪里 |
|------|------|------------------|
| 无 C 扩展的依赖闭包 | Chaquopy 只能装其提供 wheel 的原生包；内核热更新要求纯 Python | 第 7 节依赖规则 |
| 进程被杀后可恢复 | 系统回收后台进程 | 本地断点端口、格式版本 |
| 内核单独升级后旧断点仍可用 | 内核热更新 | 第 6 节格式版本与迁移 |
| 花费可预期、可中止 | 用户自带 key | 宿主协议中的用量回调与回合预算 |
| 配置时发现模型不可用 | 用户只填 key | 宿主协议中的 `probe_model` |
| 进度可展示、可取消 | 移动端界面 | 宿主协议中的事件回调与取消 |

---

## 3. 开工时的耦合

下表是开工前核对的源码。A1–A10 已经把这些耦合从写作热路径挪到端口和宿主包。

| 耦合 | 位置 |
|------|------|
| 写作回合编排（相位判定、工具裁剪、系统提示与 volatile 组装、hook 调用）在 controller | `app/controller/turn_controller.py` 中的 `_tools_for_turn`，以及组装 `AgentEngine` 之前的提示拼接段 |
| 引擎顶层依赖 asyncpg | `app/engine/agent_engine.py` → `app.controller.event_writer`（顶层 `import asyncpg`） |
| 写作信号顶层依赖数据库与 controller | `app/writing/signals/{persist,prefs_store}.py` 顶层 `from app.db.pool`；`signals/assemble.py` 顶层 `from app.controller.session_context` |
| 工具注册表全量聚合 | `app/tools/core/tools.py` 顶层导入 `sources_search`、`codebase_search`、`lsp_tools`、`edit_tools` |
| 断点只有 Postgres 实现 | `app/controller/checkpoint_store.save_checkpoint` → `checkpoints` 表 |
| 模型窗口来自数据库配置 | `app/model/config.py: resolve_context_window_tokens` |
| 偏好结构按仓库路径加载 | `app/writing/signals/prefs_loader.py` → `packages/contracts/python/agent_contracts/writing_prefs.py` |
| 跨回合拍晋升依赖评分表 | `app/writing/signals/beats.py: maybe_promote_local_beats` → `writing_fragment_evaluations` |

---

## 4. 工作项

按依赖顺序排列。每项单独合入，服务器行为不变，由现有单测与 A9 的对照测试证明。

| 编号 | 内容 | 验收 |
|------|------|------|
| A1 | **抽取回合组装**。把 controller 中写作专属的编排抽成 `app/writing/turn_assembly.py`：输入用户消息、Profile、稿树根、Plan 相位；输出工具名单、系统提示、volatile、待发事件。controller 改为调用它 | controller 写作分支只剩调用；`tests/test_turn_controller.py` 断言不变 |
| A2 | **端口协议**。写作、引擎、组窗只经由端口访问外界：`CheckpointStore`、`EventSink`、`EvaluationStore`、`PrefsSource`、`Embedder \| None`、`ModelConfig`。服务器提供 Postgres 实现，另提供文件实现 | `app/writing/`、`app/engine/`、`app/context/` 中无顶层 `app.db`、`app.controller`、`asyncpg` 导入 |
| A3 | **按场景构建注册表**。写作注册表只导入写作所需的 handler，不经过 `tools.py` 全量聚合；`rename_file`、`export_document` 从重依赖模块中拆出 | 构建写作注册表后，`sys.modules` 中无 `app.retrieval.store`、`app.structural.adapters` |
| A4 | **偏好结构正式化**。`writing_prefs` 改为随内核打包的模块，去掉按路径探测 | 不依赖仓库目录结构即可加载 |
| A5 | **格式版本**。断点、侧车、事件文件带 `schema_version`，提供向前迁移（第 6 节） | 旧版本断点经迁移后可恢复 |
| A6 | **用量与预算**。引擎按步累计 `ModelResponse` 中已有的 token 字段；回合预算触顶时走交付门的收尾路径 | 预算触顶的回合正常交付并报告原因 |
| A7 | **宿主协议**。新增 `app/writing_host/`：协议定义、文件端口实现、无 embedder 配置（第 5 节） | 协议有类型定义、单测、版本号 |
| A8 | **桌面命令行宿主**。`python -m app.writing_host.cli --work <dir>`：用真实 key 或回放文件跑回合，支持中断与恢复 | 在无 `DATABASE_URL` 的干净虚拟环境中跑完一回合 |
| A9 | **对照测试**。用 `app/model/recorded_provider.py` 回放固定模型响应，分别经服务器配置与宿主配置跑同一组写作回合，比较交付结果、补丁、信号、终态 | 差异只出现在第 9 节所列项 |
| A10 | **内核包构建**。CI 按导入图选取模块，打出带清单与签名的内核包（第 8 节） | 包可在 A8 的环境中被加载运行 |

A2 与 A3 完成后，CI 增加一条**导入图检查**：在只安装第 7 节依赖白名单的环境中导入宿主入口，`sys.modules` 中不得出现被禁模块。它防止服务器开发时重新引入顶层服务端依赖。

---

## 5. 宿主协议

宿主协议是两部分之间唯一的接口。Android 壳（经 Chaquopy）和桌面命令行都只调用它。

### 5.1 入口

```python
PROTOCOL_VERSION = "1.0"

async def start_turn(
    *,
    work_root: Path,
    message: str,
    model: ModelConfig,          # base_url, api_key, model, context_window_tokens, capabilities
    budget: TurnBudget,          # max_input_tokens, max_output_tokens, max_steps
    plan_phase: str | None,
    on_event: Callable[[HostEvent], None],
) -> TurnResult: ...

async def resume_turn(
    *,
    work_root: Path,
    turn_id: str,
    model: ModelConfig,
    budget: TurnBudget,
    on_event: Callable[[HostEvent], None],
) -> TurnResult: ...

def cancel_turn(turn_id: str) -> None: ...

async def probe_model(model: ModelConfig) -> ProbeReport: ...

def list_resumable(work_root: Path) -> list[ResumableTurn]: ...

def core_info() -> CoreInfo:     # core_version, protocol_version, schema_versions
    ...
```

### 5.2 事件

| 事件 | 时机 | 载荷 |
|------|------|------|
| `step_started` | 每步开始 | 步号 |
| `tool_finished` | 每个工具返回 | 工具名、摘要、改动的文件 |
| `step_committed` | 断点落盘之后 | 步号、累计用量 |
| `usage` | 模型流结束 | 本步输入 / 输出 / 缓存 token |
| `delivery` | 交付门通过 | 交付摘要 |
| `turn_finished` | 终态 | 结果类别、原因 |

宿主只能在收到 `step_committed` 之后才把磁盘上的稿当作"已提交"展示。

### 5.3 错误分类

`AuthError`、`RateLimited`、`QuotaExceeded`、`ContextOverflow`、`NetworkError`、`BudgetExhausted`、`Cancelled`、`ResumeIncompatible`、`InternalError`。每类都带一条可直接展示给用户的中文说明，宿主不需要解析异常文本。

### 5.4 探测

`probe_model` 依次校验鉴权、流式、带工具定义的请求能否解析出 tool_call，以及返回的模型名。报告逐项给出通过或失败，并附原因。

### 5.5 协议版本

- 新增可选字段或新事件：次版本号加一。
- 删除或改变语义：主版本号加一。
- 宿主声明自己支持的协议主版本；内核主版本不匹配时拒绝加载（第 8 节的热更新依赖这条规则）。

---

## 6. 本地格式与版本

| 文件 | 位置（相对稿树根） | 写入方式 |
|------|--------------------|----------|
| 断点 | `.agent/checkpoints/<turn>.json` | 每步原子写（临时文件加 rename） |
| 事件 | `.agent/events/<turn>.jsonl` | 追加；按回合滚动，保留最近 32 回合 |
| 评分 | `.agent/evaluations/<turn>.jsonl` | 首版只写不读（为日后在本地恢复拍晋升预留） |
| 记忆 | `memory/memories.json` | 沿用 `memory_backend` 的文件后端 |
| 侧车 | `.agent/work/` | 沿用现有布局 |

每类文件带 `schema_version`。内核只负责**向前迁移**：新内核能读旧格式。遇到比自己新的格式时，返回 `ResumeIncompatible`，不尝试读取。这保证内核回滚时不会破坏数据，只是无法恢复由新内核产生的断点。

---

## 7. 依赖规则

内核包只能包含纯 Python 代码。原生依赖由宿主提供，并在内核清单中声明版本范围。

| 类别 | 依赖 |
|------|------|
| 允许，宿主提供 | pydantic、pydantic-settings、httpx、pyyaml（是否可装由 Android 文档的门禁验证） |
| 禁止进入导入图 | asyncpg、psycopg、redis、fastapi、uvicorn、langgraph、sentence-transformers、numpy、tree-sitter、opentelemetry 导出器 |

新增依赖须同时满足两条：有纯 Python 实现，或已列入宿主提供清单；并通过导入图检查。

---

## 8. 内核包

### 8.1 构成

```text
writing-core-<core_version>.zip
  manifest.json
  app/...                  # 按导入图选取的 .py
  scenarios/writing/...    # 系统提示与模板
  data/...                 # 包内范例、技能文件
manifest.json.sig          # Ed25519 签名
```

`manifest.json` 包含：`core_version`（来自 `app/writing/VERSION`）、`protocol_version`、`schema_versions`、`python`（主次版本）、`host_requires`（原生依赖及版本范围）、每个文件的 sha256、构建提交号。

### 8.2 版本

- `app/writing/VERSION` 为语义化版本。写作行为变化时递增次版本或修订号；宿主协议主版本变化时递增主版本。
- 判断要不要递增放在发布内核包时：内核文件哈希相对上一个已发布的包有变化而 VERSION 未变，则发布失败。平时的提交不受影响。
- 服务器启动时记录同一个版本字符串，便于对照"手机与服务器是否为同一写作实现"。

### 8.3 签名

- 签名私钥只存在于发布流水线中，公钥内置在宿主里。
- 宿主加载内核包前依次校验：签名、文件哈希、`protocol_version` 主版本、`python` 版本、`host_requires`。任何一项失败都拒绝加载，继续使用当前内核。

---

## 9. 宿主配置与服务器的行为差异

本部分只保证代码同源，不保证行为逐字一致。以下差异由 A9 的对照测试固定下来，下游须在产品内说明。

| 项 | 服务器 | 宿主配置 |
|----|--------|----------|
| `search_sources`、`check_citation` | 提供 | 不注册 |
| `delegate` 与子 Agent | 提供 | 不注册 |
| 近池相似度 | embedder | 已有的非向量退路 |
| 范例叠层 | Postgres overlay | 仅包内范例 |
| 片段评分与跨回合拍晋升 | 开启 | 只写不读，晋升关闭 |
| 写作偏好 | 账户偏好 | 平台默认 |
| 长期记忆 | Postgres | 文件后端 |
| `post_turn_jobs` | `sources.index_sync` | 无 |
| 模型窗口 | provider 配置表 | 由宿主经 `ModelConfig` 传入 |

---

## 10. 验收

- A1–A10 全部合入，`scripts/preflight_unit.sh` 通过。
- 在只安装依赖白名单的干净 CPython 3.11 环境中，桌面命令行宿主能用至少两家服务商的真实 key 跑完 40 步回合；中途杀进程后能恢复。
- 内核包由 CI 产出并签名；用旧版本内核产生的断点能被新内核恢复。
- 导入图检查与对照测试进入 runtime 的 CI。
