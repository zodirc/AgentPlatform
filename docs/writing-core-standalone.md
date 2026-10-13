# 写作 SDK 与本地接头

| 项 | 内容 |
|----|------|
| 状态 | SDK 与两只接头已落地（A1–A10）。A11–A17 是单机壳开工的前提，全部合入后协议 1.0 冻结 |
| 定位 | 共用写作 SDK，加上给单机壳用的本地接头。Web 走服务器接头，不走本协议，但与本协议共用契约事件、意图与夹具 |
| 所在仓库 | 本仓库，`services/runtime`；契约在 `packages/contracts` |
| 壳 | 命令行已接本地接头。Android 壳与两端共用的客户端分层见 `docs/android-writing-client.md`。Web 壳在 `services/web`，经 `services/api` |
| 交付物 | 写作 SDK、本地接头协议、桌面命令行壳、签名的内核包、「事件日志 → 视图」契约夹具 |
| 不包含 | 任何壳的界面、账号、APK 构建与分发 |

---

## 1. 目的

写作行为只放在 SDK 里。壳只选择一只接头。两只接头对壳说同一种语言：契约事件、结构化意图、错误类别。

```text
壳          Web（services/web）     命令行（已有）      Android（以后）
              │                      │                    │
接头        服务器接头              本地接头              本地接头
            controller + api         app/writing_host      同一份协议（经 Chaquopy）
              │                      │                    │
SDK         app/writing/  ·  app/engine/  ·  端口
契约        packages/contracts：事件 · 信封 · 命令 · 意图 · 投影 · 错误码 · 夹具
```

服务器接头服务 Web：账号、Postgres、检索、子 Agent 留在这一侧。本地接头服务单机壳：一个稿树目录、一个 OpenAI 兼容的模型地址，即可跑完一回合，写作规则与服务器同源。本地接头不依赖 Postgres、Redis、检索进程或 api 服务。

设计约束：

- 服务器写作回合的编排从 controller 中抽出，变得可测；经服务器接头的行为不变。
- 命令行、Android，以及将来的桌面单机壳，都只调用本地接头。它们不导入 `app.writing` 的内部模块，也不依赖稿树的目录布局（第 6 节）。
- 本地接头的对外形状尽量与服务器接头一致：同名事件、同一个信封、同样按 `sequence` 补齐。壳的「事件 → 视图」逻辑因此只写一份规则，两端用同一批夹具验收。
- 写作 SDK 可以打成一个版本化、带签名的包，供单机壳按版本消费，并支持单独热更新（第 8 节）。Web 使用同一份源码，不消费这个 zip。

## 2. 单机壳的需求落在 SDK 与本地接头

以下需求来自手机壳，实现放在 Python 侧。壳若自己做，就要重写写作规则，或者在内核热更新后失效：

| 需求 | 来自 | 落在哪里 |
|------|------|----------|
| 无 C 扩展的依赖闭包 | Chaquopy 只能装其提供 wheel 的原生包；内核热更新要求纯 Python | 第 7 节依赖规则 |
| 进程被杀后可恢复 | 系统回收后台进程 | 本地断点端口、格式版本 |
| 内核单独升级后旧断点仍可用 | 内核热更新 | 第 6 节格式版本与迁移 |
| 花费可预期、可中止 | 用户自带 key | 用量事件与回合预算（A6） |
| 配置时发现模型不可用 | 用户只填 key | `probe_model` |
| 进度可展示、可取消，且两端画法一致 | 壳要画回合 | 契约事件与信封（A11）；壳生成 `turn_id`（A12） |
| 用户点选不靠拼句子 | 开篇、Plan、修订候选 | 结构化意图（A13） |
| 壳不知道稿树布局 | 内核热更新可能改布局 | 作品读写入口（A14） |
| UI 进程重启后补齐视图 | 手机壳把 Python 放在独立进程 | 事件补齐（A15） |
| 并发约束明确 | 宿主运行时会写进程级设置 | 单回合约束（A16） |
| 两只壳的相位画法不漂移 | Web 与 Android 各写一份 reducer | 契约夹具（A17） |

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

A1–A10 之后，对壳仍然可见的耦合如下，由 A11–A17 处理：

| 耦合 | 位置 |
|------|------|
| 本地事件另起名字、不带 `turn_id`、不转发相位事件 | `app/writing_host/runner.py: _map_engine_event` 把 `step.started` 等改名为 `step_started`、`tool_finished`、`usage`；终态用私有名 `step_committed`、`delivery`、`turn_finished` |
| `step.completed` 先于断点落盘 | `app/engine/agent_engine.py` 的步循环 `finally` 中，`_complete_step` 在 `_on_step_checkpoint` 之前 |
| 终态事件不在引擎里 | `turn.completed` / `turn.failed` / `turn.cancelled` 由 `turn_controller.py` 发出，本地接头没有对应物 |
| 用户点选靠魔法句子 | Web `shared/workbench/openingPonds.ts: formatSelectPondMessage` 拼「采用此开篇「…」」；`app/writing/opening_ponds.py`、`turn_phase.py`、`text_metrics.py` 用正则解析 |
| 壳须知道稿树布局才能读稿、快照、撤销 | 协议没有作品读写入口 |
| 宿主改进程级设置 | `runner._run` 写 `settings.workspace_root`、`settings.recordings_dir`；两个回合并发会互相覆盖 |

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
| A7 | **本地接头**。新增 `app/writing_host/`：协议定义、文件端口实现、无 embedder 配置（第 5 节） | 协议有类型定义、单测、版本号 |
| A8 | **桌面命令行壳**。`python -m app.writing_host.cli --work <dir>`：用真实 key 或回放文件跑回合，支持中断与恢复 | 在无 `DATABASE_URL` 的干净虚拟环境中跑完一回合 |
| A9 | **对照测试**。用 `app/model/recorded_provider.py` 回放固定模型响应，分别经服务器接头与本地接头跑同一组写作回合，比较交付结果、补丁、信号、终态 | 差异只出现在第 9 节所列项 |
| A10 | **内核包构建**。CI 按导入图选取模块，打出带清单与签名的内核包（第 8 节） | 包可在 A8 的环境中被加载运行 |
| A11 | **契约事件与信封**。本地接头原样转发引擎的契约事件（含相位事件），不改名；每条包成 `events/envelope.json` 形状，`sequence` 为本回合事件日志的行号。接头扣住 `step.completed`，断点落盘后再发，并补上累计用量。终态由接头补发 `turn.completed` / `turn.failed` / `turn.cancelled`。删除 `step_committed`、`delivery`、`turn_finished`（第 5.2 节）。契约侧在 `payloads/step.completed.json` 增加可选 `usage`、`payloads/turn.failed.json` 增加可选 `error_kind`（两者现为 `additionalProperties: false`），同步 `packages/contracts/tests` | 每条事件通过 `packages/contracts` 的信封与载荷校验；`step.completed` 的到达晚于对应断点文件写入；A9 对照两只接头的事件类型序列一致（第 9 节所列除外） |
| A12 | **壳生成 `turn_id`**。`start_turn` 接受可选 `turn_id`；接头先发 `turn.accepted`，再进引擎。同一 `turn_id` 重复调用返回 `Busy` 或原结果，不开第二个回合 | 第一步开始前调用 `cancel_turn` 能取消；重复提交不产生第二个回合 |
| A13 | **结构化意图**。新增 `app/writing/intents.py`：把 `TurnIntent`（第 5.3 节）解析成本回合的用户消息与相位输入。本地接头的 `start_turn` 与契约 `commands/start_turn.json` 同时增加可选 `intent`，服务器接头调用同一函数。旧的魔法句子保留解析一个次版本，之后删除 | 同一意图经两只接头得到相同的组装结果；Web 改发意图后 `openingPonds.ts` 不再拼句子 |
| A14 | **作品读写入口**。新增 `work_view`、`read_document`、`write_document`、`list_turn_history`、`revert_turn`、`export_work`、`import_work`（第 5.1 节）。回合开始前接头留快照（第 6 节） | 壳侧代码中不出现稿树路径常量；`revert_turn` 后 `work_view` 与回合开始前一致 |
| A15 | **事件补齐**。新增 `read_events(work_root, turn_id, after_sequence)`，从事件日志读出已落盘事件 | 杀掉回调方后按 `after_sequence` 补齐，与不中断时收到的序列一致、无重复 |
| A16 | **单回合约束**。接头在进程内同时只跑一个回合，第二个 `start_turn` 抛 `Busy`。随后把 `settings.workspace_root`、`settings.recordings_dir` 的写入改为经租户上下文传入，去掉进程级写入 | 并发调用得到 `Busy`；去掉全局写入后，`runner.py` 中无 `settings.* =` 赋值 |
| A17 | **契约夹具**。`packages/contracts/tests/fixtures/turns/` 放「事件日志 → 期望视图」的 JSON：开篇点选、Plan 确认、修订候选、预算触顶、取消、失败、恢复后重复事件。`projections/turn_view.json` 增加写作扩展字段（开篇候选、Plan、修订候选、钉住的卡片、用量）。夹具由 A9 的回放跑出，不手写事件序列 | Web 的 `reduceTurn` 与 Android 的 `TurnStore` 都以这批夹具为单测输入 |

A2 与 A3 完成后，CI 增加一条**导入图检查**：在只安装第 7 节依赖白名单的环境中导入宿主入口，`sys.modules` 中不得出现被禁模块。它防止服务器开发时重新引入顶层服务端依赖。

A11–A17 都只新增可选参数、入口或事件，对已有调用方是次版本变化。它们合入前尚无壳依赖本地接头的事件名，所以 A11 的改名也不升主版本。

---

## 5. 本地接头协议

本地接头是单机壳与 SDK 之间的唯一接口。命令行壳和 Android 壳（经 Chaquopy）只调用 `app/writing_host`。Web 壳不调用本协议，它经服务器接头用 HTTP / SSE 收到同名、同信封的事件，用同一组意图发命令。

需要新能力时，先改本协议或契约，再改壳。壳不导入 SDK 内部模块。

### 5.1 入口

```python
PROTOCOL_VERSION = "1.0"

# 回合
async def start_turn(
    *,
    work_root: Path,
    message: str = "",
    intent: TurnIntent | None = None,  # message 与 intent 至少给一个
    turn_id: str | None = None,        # 缺省由接头生成
    model: ModelConfig,                # base_url, api_key, model, context_window_tokens, capabilities, timeouts
    budget: TurnBudget,                # max_input_tokens, max_output_tokens, max_steps
    plan_phase: str | None,
    on_event: Callable[[EventEnvelope], None],
) -> TurnResult: ...

async def resume_turn(
    *,
    work_root: Path,
    turn_id: str,
    model: ModelConfig,
    budget: TurnBudget,
    on_event: Callable[[EventEnvelope], None],
) -> TurnResult: ...

def cancel_turn(turn_id: str) -> None: ...
def list_resumable(work_root: Path) -> list[ResumableTurn]: ...
def read_events(work_root: Path, turn_id: str, after_sequence: int = 0) -> list[EventEnvelope]: ...

# 作品
def work_view(work_root: Path) -> WorkView: ...                 # 文档列表与作品元信息
def read_document(work_root: Path, doc_id: str) -> Document: ...
def write_document(work_root: Path, doc_id: str, text: str, *, base_revision: str) -> Document: ...
def list_turn_history(work_root: Path) -> list[TurnRecord]: ...
def revert_turn(work_root: Path, turn_id: str) -> None: ...
def export_work(work_root: Path, dest: Path) -> None: ...       # 写出 zip
def import_work(src: Path, work_root: Path) -> WorkView: ...

# 模型与内核
async def probe_model(model: ModelConfig) -> ProbeReport: ...
def core_info() -> CoreInfo: ...                                # core_version, protocol_version, schema_versions
```

作品入口的约定：

| 类型 / 入口 | 约定 |
|-------------|------|
| `WorkView` | `work_id`、标题、`core_version`、文档列表。每个文档有 `doc_id`（不透明字符串）、`role`（`outline` / `chapter` / `manuscript` / `cards` / `notes` / `archive`）、标题、可见字数、`revision`、修改时间 |
| `write_document` | 回合之间的手动编辑。`base_revision` 不等于当前版本时抛 `Conflict`；有回合进行中时抛 `Busy` |
| `revert_turn` | 把作品恢复到该回合开始前，并丢弃该回合及其后所有回合的快照、断点与事件。历史是线性的，不做分支 |
| `export_work` / `import_work` | zip 是唯一对外的作品格式：稿树加一份 `export.json`（`core_version`、`schema_versions`、导出时间）。导入走第 6 节的向前迁移 |

### 5.2 事件

**一律用契约名。** 类型字符串与 `packages/contracts/schemas/events/types.json` 一致，载荷满足 `payloads/` 下的 schema，外层是 `envelope.json`：

| 信封字段 | 本地接头的取值 |
|----------|----------------|
| `event_id` | 每条新生成 |
| `stream_id`、`turn_id` | 本回合 id |
| `run_id`、`trace_id` | 取自 `TurnState` |
| `sequence` | 本回合事件日志的行号，从 1 起，单调递增 |
| `live` | 恒为 `false`：事件先写日志再回调，回调到的都是已落盘事件 |
| `step_index`、`ts`、`payload` | 引擎原值 |

壳关心的事件：

| 事件 | 谁发 | 壳用它做什么 |
|------|------|----------------|
| `turn.accepted` | 接头，进引擎前 | 回合已受理；`turn_id` 已确定 |
| `step.started` | 引擎 | 步号 |
| `tool.started` / `tool.completed` | 引擎 | 工具名、摘要、改动的文件 |
| `usage.reported` | 引擎 | 本步输入 / 输出 / 缓存 token |
| `opening.ponds` | 引擎 | 开篇候选（`ponds_id` 与各项 `id` 供意图引用） |
| `outline.updated` | 引擎 | 大纲已写入 |
| `patch.proposed` | 引擎 | 修订候选（`patch_id`），选定前不是已提交稿 |
| `turn.plan` | 引擎 | Plan 清单（`plan_id`） |
| `cards.pinned` | 引擎 | 本回合钉住的卡片 |
| `turn.token`、`turn.thinking.delta`、`section.draft.delta`、`context.reported` | 引擎 | 流式内容与组窗信息 |
| `step.completed` | 接头转发，**断点落盘之后** | 该步已提交；载荷加 `usage`（累计 token） |
| `turn.completed` | 接头 | 终态：`summary`、`termination_reason`、`step_count`、`delivery_status`、`token_usage` |
| `turn.failed` | 接头 | 终态：`termination_reason`、`message`、`error_kind`（第 5.4 节） |
| `turn.cancelled` | 接头 | 终态 |

规则：

- 引擎在 `_on_step_checkpoint` 之前写 `step.completed`。本地接头把这条扣在缓冲里，断点原子写成功后再写日志并回调。服务器接头不受影响。
- 壳只能在收到 `step.completed` 之后才把磁盘上的稿当作已提交。`opening.ponds` 与 `patch.proposed` 是候选，不是落盘。
- 每回合恰好一条终态事件，并且是该回合的最后一条。
- `step.completed` 加 `usage`、`turn.failed` 加 `error_kind`，是对契约载荷的可选字段增补，按契约包的规则记入 `CHANGELOG.md`。

### 5.3 意图

用户在界面上的点选以结构化意图发出。意图到用户消息、相位输入的转换只在 `app/writing/intents.py` 里，两只接头共用。

| 意图 | 字段 | 来源事件 |
|------|------|----------|
| `select_pond` | `ponds_id`、`item_id` | `opening.ponds` |
| `more_ponds` | `ponds_id` | `opening.ponds` |
| `confirm_plan` | `plan_id` | `turn.plan` |
| `accept_patch` / `reject_patch` | `patch_id` | `patch.proposed` |

引用的 id 不是当前作品最近一次候选时抛 `InvalidIntent`，不猜测。`message` 与 `intent` 同时给出时，`message` 作为用户附言。

### 5.4 错误分类

`AuthError`、`RateLimited`、`QuotaExceeded`、`ContextOverflow`、`NetworkError`、`BudgetExhausted`、`Cancelled`、`ResumeIncompatible`、`Busy`、`Conflict`、`InvalidIntent`、`InternalError`。每类都带一条可直接展示给用户的中文说明，壳不需要解析异常文本。回合进行中发生的错误同时以 `turn.failed` 的 `error_kind` 送出。

### 5.5 探测

`probe_model` 依次校验鉴权、流式、带工具定义的请求能否解析出 tool_call，以及返回的模型名。报告逐项给出通过或失败，并附原因。

### 5.6 并发

- 一个进程同时只跑一个回合（A16）。第二个 `start_turn` 抛 `Busy`；作品写入口在回合进行中也抛 `Busy`。
- `on_event` 在接头的事件循环线程上调用。回调必须立即返回，不做阻塞 IO；壳自行入队、合并、跨线程投递。
- `cancel_turn` 可从任意线程调用，只置标志，在步边界生效，当前模型流立即中止。

### 5.7 协议版本

- 新增可选字段、入口或事件：次版本号加一。
- 删除或改变语义：主版本号加一。
- 壳声明自己支持的协议主版本；内核主版本不匹配时拒绝加载（第 8 节的热更新依赖这条规则）。
- A11–A17 合入后，1.0 冻结。

---

## 6. 本地格式与版本

一个 `work_root` 就是一部作品。壳的「多作品」是多个这样的目录。

**布局属于内核。** 下表供 SDK 与接头实现参考。壳只经第 5.1 节的作品入口读写，不按路径访问；内核热更新可以改变这张表而不影响壳。对外的作品格式只有 `export_work` 的 zip。

| 文件 | 位置（相对稿树根） | 写入方式 |
|------|--------------------|----------|
| 大纲 | `outline.md` | 写作工具落盘 |
| 正文 | `drafts/manuscript.md` | 写作工具落盘 |
| 归档稿 | `drafts/archive/` | `occupy=fresh` 时整文件归档 |
| 断点 | `.agent/checkpoints/<turn>.json` | 每步原子写（临时文件加 rename） |
| 事件 | `.agent/events/<turn>.jsonl` | 先追加再回调；一行一条信封；按回合滚动，保留最近 32 回合 |
| 快照 | `.agent/snapshots/objects/<sha256>`、`.agent/snapshots/turns/<turn>.json` | 回合开始前写清单；内容寻址，未变文件不重复存；与事件同步保留最近 32 回合 |
| 评分 | `.agent/evaluations/<turn>.jsonl` | 首版只写不读（为日后在本地恢复拍晋升预留） |
| 记忆 | `memory/memories.json` | 沿用 `memory_backend` 的文件后端 |
| 侧车 | `.agent/work/` | `story_state`、审读笔记、作者笔记、声口等 |
| 风格锁 | `writing/style.lock` | 大纲契约够长时写入 |
| 身份 | `.agent/host.json` | 本地接头首次运行时写入 `work_id` 与 `owner_user_id` |

快照覆盖稿与侧车、风格锁、记忆，不含 `.agent/checkpoints`、`.agent/events`、`.agent/snapshots` 本身。

`sources/` 可以随作品导入。本地接头不注册 `search_sources`，这些文件不会被检索工具读到。

断点、事件、快照清单、评分、记忆、侧车带 `schema_version`。大纲和正文是稿本身，不带这份版本戳。内核只负责**向前迁移**：新内核能读旧格式。遇到比自己新的格式时返回 `ResumeIncompatible`，不尝试读取。这保证内核回滚时不会破坏数据，只是无法恢复由新内核产生的断点。

---

## 7. 依赖规则

内核包只能包含纯 Python 代码。原生依赖由壳提供，并在内核清单中声明版本范围。

| 类别 | 依赖 |
|------|------|
| 允许，壳提供 | pydantic、pydantic-settings、httpx、pyyaml（是否可装由 Android 文档的门禁 G1 验证） |
| 禁止进入导入图 | asyncpg、psycopg、redis、fastapi、uvicorn、langgraph、sentence-transformers、numpy、tree-sitter、opentelemetry 导出器 |

新增依赖须同时满足两条：有纯 Python 实现，或已列入壳提供清单；并通过导入图检查。

---

## 8. 内核包

### 8.1 构成

```text
writing-core-<core_version>.zip
  manifest.json
  app/...                  # 按导入图选取的 .py
  scenarios/writing/...    # 系统提示与模板
  data/...                 # 包内范例、技能文件
  fixtures/...             # 回放夹具（模型录制响应 + 期望事件序列）
manifest.json.sig          # Ed25519 签名
```

`manifest.json` 包含：`core_version`（来自 `app/writing/VERSION`）、`protocol_version`、`schema_versions`、`python`（主次版本）、`host_requires`（原生依赖及版本范围）、`contracts_version`、每个文件的 sha256、构建提交号。

回放夹具随包发布，供命令行壳与 Android 壳对照同一回合，也供壳在内核热切换时自检。`scripts/build_writing_core.py` 目前尚未把夹具打进 zip，A17 一并补上。

### 8.2 版本

- `app/writing/VERSION` 为语义化版本。写作行为变化时递增次版本或修订号；本地接头协议主版本变化时递增主版本。
- 判断要不要递增放在发布内核包时：内核文件哈希相对上一个已发布的包有变化而 VERSION 未变，则发布失败。平时的提交不受影响。
- 服务器启动时记录同一个版本字符串，便于对照「手机与服务器是否为同一写作实现」。

### 8.3 签名

- 签名私钥只存在于发布流水线中，公钥内置在单机壳里。
- 壳加载内核包前依次校验：签名、文件哈希、`protocol_version` 主版本、`python` 版本、`host_requires`。任何一项失败都拒绝加载，继续使用当前内核。校验逻辑的参考实现在 `app/writing_host/trust.py` 与 `loader.py`。

---

## 9. 两只接头的行为差异

两只接头共用 SDK、契约事件与意图，不保证行为逐字一致。以下差异由 A9 的对照测试固定下来。单机壳须在产品内说明。

| 项 | 服务器接头 | 本地接头 |
|----|--------|----------|
| `search_sources`、`check_citation` | 提供 | 不注册 |
| `delegate` 与子 Agent | 提供 | 不注册；不发 `subagent.*` 事件 |
| 工具审批 | 按 profile 可发 `approval.*` | 写作工具不需要审批，不发 |
| 近池相似度 | embedder | 已有的非向量退路 |
| 范例叠层 | Postgres overlay | 仅包内范例 |
| 片段评分与跨回合拍晋升 | 开启 | 只写不读，晋升关闭 |
| 写作偏好 | 账户偏好 | 平台默认 |
| 长期记忆 | Postgres | 文件后端 |
| `post_turn_jobs` | `sources.index_sync` | 无；`turn.completed` 中该字段为空 |
| 模型窗口 | provider 配置表 | 由壳经 `ModelConfig` 传入 |
| 事件实时通道 | 可有 `live=true` 的实时扇出 | 只有已落盘事件，`live` 恒为 `false` |
| 作品读写与撤销 | api 的作品接口 | 第 5.1 节作品入口 |

---

## 10. 验收

- A1–A17 全部合入，`scripts/preflight_unit.sh` 通过。
- 本地接头的每条事件通过契约的信封与载荷校验；`step.completed` 晚于对应断点落盘；每回合恰好一条终态事件且位于最后。
- 同一意图经两只接头产生相同的组装结果；Web 不再拼魔法句子。
- `revert_turn` 后 `work_view` 与回合开始前一致；导出再导入后作品可继续写。
- 在只安装依赖白名单的干净 CPython 3.11 环境中，桌面命令行壳能用至少两家服务商的真实 key 跑完 40 步回合；中途杀进程后能恢复，按 `read_events` 补齐的序列与不中断时一致。
- 内核包由 CI 产出并签名，含回放夹具；用旧版本内核产生的断点能被新内核恢复。
- 导入图检查、对照测试、契约夹具测试进入 runtime 与 contracts 的 CI。
