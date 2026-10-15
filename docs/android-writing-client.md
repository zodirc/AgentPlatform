# 写作客户端设计说明（Android 单机壳，兼顾 Web）

| 项 | 内容 |
|----|------|
| 状态 | 草案，未开工。SDK 的 A11–A17 已合入，本地接头协议 1.0 已冻结，可以开始原型 |
| 定位 | 单机写作 Agent APK。用户自带模型 key，直连用户的模型服务；不依赖本平台服务器 |
| 现状 | 平台是服务器形态：Web（`services/web`）经 `services/api` 调 runtime；写作 SDK 与本地接头（`app/writing_host`）已落地，命令行壳已接 |
| 上游 | `docs/writing-core-standalone.md`（写作 SDK、本地接头、内核包）、`packages/contracts`（事件、命令、投影） |
| 所在仓库 | 原型在本仓库 `clients/android/`；协议冻结后迁出为 `writing-android`（第 12 节） |
| 交付物 | 三个渠道的安装包、更新服务的静态清单、服务商预设、客户端核心的契约夹具 |
| 不包含 | 写作规则与回合编排（属于 SDK）、账号、云同步 |

---

## 1. 目标与非目标

**目标**

1. 安装后只需选择服务商、填入 key，即可开始写作。断网以外不需要任何服务器。
2. 写作行为完全由 SDK 内核提供。壳里没有写作规则，也不知道稿树的内部布局。
3. Web 与 Android 用**同一套客户端分层**：同一份契约、同一种「事件 → 视图」投影、同一组夹具验收。差别只在传输层和界面层。
4. 稿子可完整导出，不因卸载、换机、进程被杀或回合中断而丢失。
5. 每回合的花费在开始前可预期，进行中可见、可中止。
6. 写作内核可单独更新（受渠道政策限制，第 9 节）；安装包更新尽量走差分。

**非目标**

- 不追求与服务器写作逐字等价（差异见 SDK 文档第 9 节，须在「关于」页说明）。
- 首版不做账号、云同步、多设备协同；手机上不做 embedding、资料库、子 Agent。
- 首版不连本平台服务器。第 4 节的分层允许以后加「远程后端」，但不在首版范围。
- 不在 Kotlin 里重写引擎或写作规则。

---

## 2. 系统分层

### 2.1 五层与依赖方向

```text
层            Web                              Android
───────────────────────────────────────────────────────────────────────────
L4 界面       React 组件                        Compose 页面
                 │ 只读视图状态、只发意图             │
L3 客户端核心  TurnStore · WorksRepo（TS）       TurnStore · WorksRepo（Kotlin，纯 JVM）
                 │ WritingBackend 接口               │ WritingBackend 接口
L2 后端适配    RemoteBackend：HTTP + SSE         LocalBackend：绑定 :agent 进程
                 │                                  │
L1 接头        服务器接头（api + controller）     本地接头（app/writing_host，经 Chaquopy）
                 └──────────────┬───────────────────┘
L0 SDK + 契约  app/writing · app/engine · 端口   packages/contracts（事件 · 命令 · 投影 · 错误码）
```

依赖只能向下。三条硬规则：

| 规则 | 含义 | 违反的样子 |
|------|------|------------|
| 契约是唯一共享物 | 两只壳与两只接头之间只共享 `packages/contracts` 里的事件名、载荷、命令、错误码、投影 | 壳里出现 `app.writing` 的模块名；Kotlin 里硬编码 `drafts/manuscript.md` |
| 意图结构化 | 用户点选（开篇、Plan、修订候选）以结构化意图发出，SDK 负责把意图变成模型能读的消息 | 壳拼「采用此开篇「…」」这样的句子，SDK 再用正则拆回来 |
| 稿树不透明 | 壳只经接头读写作品：列文档、读文档、导出、撤销回合。目录布局属于内核 | 壳按路径快照「大纲、正文、侧车、风格锁」 |

第三条对 Android 尤其重要：内核可以热更新而壳不变，壳里任何关于稿树布局的知识都会在某次内核更新后失效。

### 2.2 两只壳的对称

| 关注点 | Web | Android |
|--------|-----|---------|
| 回合在哪跑 | runtime 容器 | 本机 `:agent` 进程里的 CPython |
| 事件从哪来 | SSE / WebSocket（`TurnStreamClient`） | 绑定服务回调 |
| 断线后补齐 | 按 `last_event_sequence` 重放 | 按同一个 `sequence` 从本地事件日志重放 |
| 作品存哪 | Postgres + Work 根（服务器） | `files/works/<id>/`（本机） |
| 密钥 | 服务器 provider 配置 | Keystore |
| 能力集 | 全量（检索、子 Agent、账户偏好） | 本地接头子集（SDK 文档第 9 节） |

本地后端刻意做成「本机上的一台小服务器」：持久事件带递增序号、实时投递、断开后按序号补齐。这样客户端核心只写一份逻辑，Web 与 Android 只差传输。

---

## 3. 依赖的 SDK 工作项

SDK 文档第 4 节的 A11–A17 已合入。定义与现状在那份文档里，本节只说明壳依赖它们的哪一点。原型仍按第 14 节的门禁开工。

| 编号 | 内容 | 壳依赖的点 |
|------|------|------------|
| A11 | 契约事件与信封 | 两只壳共用一套「事件 → 视图」规则；`step.completed` 是唯一的提交信号 |
| A12 | 壳生成 `turn_id` | 第一步开始前就能取消；重复提交不开第二个回合 |
| A13 | 结构化意图 | 开篇、Plan、修订候选的点选不拼句子 |
| A14 | 作品读写入口与回合快照 | 壳不知道稿树布局；撤销、导出、手动编辑都经接头 |
| A15 | 事件补齐 | UI 进程重启后按 `sequence` 补齐视图 |
| A16 | 单回合约束 | 全应用同一时刻一个回合（第 5.3 节） |
| A17 | 契约夹具 | 门禁 G0：Web 与 Android 的 reducer 用同一批夹具验收 |

Web 已按 A13 在 StartTurn 里带 `intent`。折叠函数是 `reduceTurn`，`useWorkbench` 在 `busy` 期间读它。见第 4.2 节。

---

## 4. 客户端核心（两端同构）

### 4.1 接口

客户端核心对上只暴露视图状态和意图，对下只依赖一个后端接口。下面是 Kotlin 形状；Web 的 TS 形状逐字段对应。每个方法对应 SDK 文档第 5.1 节的一个入口（作品列表除外，它由壳自己的索引提供）。

```kotlin
interface WritingBackend {
    suspend fun coreInfo(): CoreInfo
    suspend fun probe(model: ModelConfig): ProbeReport

    suspend fun listWorks(): List<WorkSummary>                // 壳的 Room 索引
    suspend fun workView(workId: WorkId): WorkView
    suspend fun readDocument(workId: WorkId, docId: DocId): Document
    suspend fun writeDocument(workId: WorkId, docId: DocId, text: String, baseRevision: String): Document
    suspend fun turnHistory(workId: WorkId): List<TurnRecord>
    suspend fun revertTurn(workId: WorkId, turnId: TurnId)
    suspend fun exportWork(workId: WorkId, target: Uri)
    suspend fun importWork(source: Uri): WorkView

    suspend fun startTurn(cmd: StartTurn): TurnId             // turnId、message、intent、planPhase、budget
    suspend fun resumeTurn(workId: WorkId, turnId: TurnId)
    suspend fun cancelTurn(turnId: TurnId)
    fun events(workId: WorkId, turnId: TurnId, afterSequence: Long): Flow<EventEnvelope>  // 先补齐，再实时
    suspend fun listResumable(workId: WorkId): List<ResumableTurn>
}
```

| 实现 | 位置 | 说明 |
|------|------|------|
| `LocalBackend` | Android `:backend-local` | 绑定 `:agent` 进程的服务（第 5 节） |
| `RemoteBackend` | Web 现有 `shared/api` + `shared/realtime` | 首版 Android 不实现；以后若要「连自己的服务器」，只加这一个模块 |
| `ReplayBackend` | 两端测试 | 读契约夹具，供 reducer 与界面测试 |

### 4.2 TurnStore：事件到视图的纯函数

```text
TurnView = fold(reduce, TurnView.empty, events 按 sequence 排序去重)
```

- `reduce(view, envelope) -> view` 是无副作用的纯函数。相位（开篇待选、Plan 待确认、修订候选、交付）从事件推出，不由界面自己判断。
- 客户端投影就是夹具里的 `view`：`status`、`opening_ponds`、`plan`、`patch_candidates`、`pinned_cards`、`usage`、`last_event_sequence`。服务器的 `projections/turn_view.json` 另有会话、工具时间线等字段，不拿来生成这层视图。
- 提交只认 `step.completed`；终态只认 `turn.completed` / `turn.failed` / `turn.cancelled`，每回合恰好一条。
- 高频增量（`turn.token`、`turn.thinking.delta`、`section.draft.delta`）先进合并缓冲，按帧（约 50 ms）一次性折叠，与 Web 的 `streamDeltaBuffer.ts` 同理。
- 进程重启、页面重进、断线：从最后一个已知 `sequence` 调 `events()` 补齐，再继续实时。无需另存 UI 状态。

**共享的是夹具，不是代码。** 两端的 reducer 各自实现，都以 A17 的「事件日志 → 期望视图」夹具（`packages/contracts/tests/fixtures/turns/`）为单测输入。新增事件时先加夹具，再改两边 reducer。

Web 上的函数是 `services/web/src/shared/workbench/reduceTurn.ts` 的 `reduceTurn`。单测读 `packages/contracts/tests/fixtures/turns/`，输入 `events`，期望同文件的 `view`。`useWorkbench` 把订阅到的事件列表交给它。`busy` 为真时，界面上的 Plan、开篇、用量、修订候选、钉住卡片用这份结果。回合结束后，GET TurnView 的 `artifacts` 非空则改用 `artifacts`。`turn.token`、`turn.thinking.delta`、`section.draft.delta` 进 `streamDeltaBuffer.ts`。审批、失败文案、历史补丁留在 `useWorkbench`。采纳和放弃调用 `handleAcceptPatch` / `handleRejectPatch`，请求体带 `intent`，不调用 `client.ts` 里的 `acceptPatch` / `rejectPatch`。

### 4.3 意图与命令

界面只发意图，由 TurnStore 翻成命令：

| 界面动作 | 意图 | 命令 |
|----------|------|------|
| 发送输入 | `Send(text)` | `startTurn(message=text)` |
| 选开篇 / 换一组 | `PickPond(pondsId, itemId)` / `MorePonds(pondsId)` | `startTurn(intent=select_pond / more_ponds)` |
| 确认 Plan | `ConfirmPlan(planId)` | `startTurn(intent=confirm_plan, planPhase=executing)` |
| 采纳 / 放弃修订 | `AcceptPatch(id)` / `RejectPatch(id)` | `startTurn(intent=accept_patch / reject_patch)` |
| 中止 | `Cancel` | `cancelTurn(turnId)` |
| 撤销本回合 | `Revert(turnId)` | `revertTurn` |

`turnId` 在发命令前由客户端生成（A12），所以「点了发送立刻点中止」也能对上号。接头抛出的 `Busy`、`Conflict`、`InvalidIntent` 由 TurnStore 转成界面提示，不重试。

---

## 5. Android 运行模型与 Agent 结构

### 5.1 进程

```text
┌─ 主进程（UI）─────────────────────────┐      ┌─ :agent 进程 ──────────────────────────────┐
│ Compose 页面                          │      │ AgentService（前台服务）                     │
│ ViewModel ← TurnStore（client-core）  │ AIDL │   命令队列（单消费者）                       │
│ LocalBackend ─────────────────────────┼──────┼─▶ PythonBridge：一条线程 + 一个 asyncio 循环  │
│ WorksRepo（Room 索引，可重建）        │◀─────┼── 事件泵：信封 JSON 字符串，批量回调          │
│ update/ · security/ · presets/        │      │ Chaquopy：CPython 3.11 + 原生依赖 + 内核     │
└───────────────────────────────────────┘      └──────────────────────────┬─────────────────┘
                                                                          │ HTTPS：用户的模型服务
```

| 决策 | 理由 | 代价 |
|------|------|------|
| Python 放独立进程 `:agent` | 解释器与内核的内存（以 G7 实测为准）不压 UI；内核崩溃不带走界面，崩溃计数（第 9.4 节）也更准；系统回收 UI 进程时回合继续 | 一层 IPC；冷启动多一个进程 |
| 前台服务只在回合进行中存在 | 符合 Android 14+ 对前台服务类型与时长的要求；空闲时不常驻 | 恢复回合须重新拉起 |
| 跨进程只传 JSON 字符串 | 信封本来就是 JSON schema，不需要为每种事件写 Parcelable；两端用同一份解析代码 | 解析开销（事件量小，可忽略） |
| 事件先落盘再投递 | 由接头写 `.agent/events`，再回调；UI 断开时只丢实时，不丢事件 | 无 |

### 5.2 Agent 结构

手机上跑的就是服务器上的写作 Agent，只是换了接头和端口实现。不另设计一套 Agent。

| 部件 | 手机上 | 来源 |
|------|--------|------|
| 循环 | `AgentEngine` 的 while 环：组窗 → 模型流 → 工具 → 步断点 | SDK `app/engine` |
| 场景 | 只有 `writing` profile；系统提示与 volatile 由 `assemble_writing_turn` 组装 | SDK `app/writing/turn_assembly.py` |
| 工具 | `build_writing_registry(host=True)`：成稿、大纲、改稿、卡片、导出等写作工具；不注册 `search_sources`、`check_citation`、`delegate` | SDK `app/tools/writing_registry.py` |
| 过程门 | 交付门、补丁预算、补丁卫生、`length_short` 同轮修补 | SDK `app/writing/` |
| 端口 | 文件断点、文件事件、文件评分（只写）、平台默认偏好、无 embedder、无数据库 | 本地接头 `files.py` |
| 人在环 | 开篇点选、Plan 确认、修订候选都是「本回合结束、等用户意图、下一回合带意图开始」，不是回合内阻塞等待 | 契约事件 + A13 意图 |
| 预算 | `TurnBudget` 传入；触顶走交付门收尾，发 `turn.completed`，`termination_reason` 标明 | SDK A6 |

不在手机上做的：子 Agent、检索、跨回合拍晋升、`post_turn_jobs`。它们依赖服务器资源，且对单机写作不是必需项。

### 5.3 并发与线程

- 全应用同一时刻只有一个回合（A16 的接头约束），不是「每部作品一个」。第二个请求在 UI 上表现为「另一部作品正在写」。
- `PythonBridge` 持有唯一一条 Python 线程和事件循环。`cancelTurn` 是跨线程调用，只置标志，在步边界生效，当前模型流立即中止。
- 事件回调在 Python 线程上发生，桥只做入队，不在回调里做 IPC。另一条线程按批（如 50 ms 或 32 条）把信封推给 UI 进程。
- 主线程不碰 Python，不碰文件。

---

## 6. 模型接入

### 6.1 服务商预设

设置页先选服务商，再填 key。预设随 APK 内置，也可单独更新（第 9.1 节）。

| 字段 | 用途 |
|------|------|
| 根地址 | `chat/completions` 端点 |
| 推荐模型与可选模型 | 下拉选择；标注「工具调用可靠」 |
| 上下文窗口 | 填入 `ModelConfig.context_window_tokens` |
| 能力 | 是否支持流式 tool_call、并行工具、thinking 开关 |
| 计价（可选） | 费用估算；缺失时只显示 token |

另设「自定义 OpenAI 兼容」，要求用户手填窗口大小。

### 6.2 探测

保存配置时调用 `probe_model`，逐项展示鉴权、流式、tool_call、模型名的结果。任一项失败都不允许开始回合。

### 6.3 预算与用量

| 机制 | 说明 |
|------|------|
| 回合预算 | 设置中可调的 token 与步数上限，作为 `TurnBudget` 传入 |
| 开始前 | 按上一回合实际用量与预设计价给出区间估计 |
| 实时用量 | TurnStore 从 `usage.reported` 累计；`step.completed` 处对账 |
| 累计统计 | Room 中按日、按作品汇总，来源是 `turn.completed` 的 `token_usage` |
| 中止 | `cancelTurn`；已落盘的步保留 |

---

## 7. 作品与数据

**文件是真相，数据库只是索引。** `work_root` 由内核拥有；Room 只存作品列表、标题、最近修改、用量汇总、导出位置，全部可从 `work_view` 与事件日志重建。

| 要求 | 做法 |
|------|------|
| 多作品 | 每部作品一个 `work_root`：`files/works/<id>/`。内部布局见 SDK 文档第 6 节，壳不依赖 |
| 读稿 | 稿页按 `work_view` 的文档角色分组展示，内容经 `read_document` 读取 |
| 不因卸载丢稿 | `export_work` / `import_work` 打成 zip，经 SAF 选位置；首回合完成后引导设置自动导出位置 |
| 系统备份 | 只作补充（有容量上限，部分 ROM 不提供） |
| 密钥不进备份 | 密文从备份规则中排除；恢复后无法解密时引导重填 |
| 可回退 | 每回合开始前由接头留内容寻址快照（A14）；稿页提供「撤销本回合」与按回合的版本列表（`list_turn_history`）。撤销某回合会丢弃其后所有回合，历史是线性的 |
| 编辑冲突 | 回合进行中稿页只读；手动编辑在回合之间经 `write_document` 写入，带 `base_revision`，冲突时提示重新载入 |
| 提交语义 | 只有收到 `step.completed` 后，磁盘上的稿才算已提交。`opening.ponds`、`patch.proposed` 是候选 |
| 清理 | 设置中可清理旧断点、事件与归档稿（经接头，不直接删目录） |

---

## 8. 回合生命周期

```text
Idle ─send/intent─▶ Starting ─turn.accepted─▶ Running ─┬─ turn.completed ─▶ Done(awaiting_choice?)
  ▲                    │                                ├─ turn.failed ────▶ Failed(error_kind)
  └──── Busy / InvalidIntent                cancel ─────┼─ turn.cancelled ─▶ Cancelled
                                                        └─ 进程被杀 ───────▶ Interrupted ─resume─▶ Running
```

| 项 | 设计 |
|----|------|
| 承载 | `:agent` 进程里的前台服务。类型按 targetSdk 要求声明，核实 Android 14/15 上的时长限制，准备上架审核的用途说明 |
| 恢复 | 启动时 `listResumable`。被打断的那一步要重新请求模型，会产生额外花费，恢复前提示 |
| 网络 | 断网时在步边界暂停，恢复后由用户确认继续 |
| 错误 | 按 SDK 文档第 5.4 节的错误类别展示其自带中文说明，壳不解析异常文本；回合内错误取 `turn.failed` 的 `error_kind` |
| 通知 | 完成、失败、预算触顶各一条；点击回到该作品的回合页 |
| 与更新互斥 | 有进行中或待恢复的回合时，不切换内核槽位、不安装 APK |

---

## 9. 更新

### 9.1 分层

| 层 | 内容 | 频率 | 典型体积 | 方式 |
|----|------|------|----------|------|
| 预设 | 服务商预设 JSON | 高 | KB 级 | 签名数据文件，全渠道 |
| 内核 | 写作内核包（纯 Python） | 中高 | MB 级（以实测为准） | 签名包，整包下载，A/B 槽位 |
| 安装包 | 壳、CPython、原生依赖、内置内核 | 低 | 数十 MB 级（以实测为准） | 按渠道；侧载渠道走差分 |

写作行为的迭代绝大多数只涉及内核层。第 2.1 节「稿树不透明」和 A14 保证这类更新不需要同时改壳。

### 9.2 渠道

| 渠道（flavor） | 安装包更新 | 内核热更新 | 预设更新 |
|----------------|------------|------------|----------|
| `play` | 只走 Google Play（In-App Updates 提示） | **关闭**。Play 限制从 Play 以外下载可执行代码，解释型代码的豁免边界不清，不冒险 | 开启 |
| `store`（国内商店） | 交给各商店 | 默认关闭；逐家核对政策后按渠道开启 | 开启 |
| `direct`（官网侧载） | 自建，差分优先（第 9.3 节） | 开启 | 开启 |

`play` 渠道不含 `REQUEST_INSTALL_PACKAGES` 权限和自更新代码，构建时排除 `:update-apk` 模块。

### 9.3 安装包差分（`direct` 渠道）

1. 读取更新清单，比较 `versionCode`。
2. 计算已安装 `base.apk` 的 sha256，在清单中查找「从该哈希到新版本」的补丁。
3. 有补丁就用 HDiffPatch 在本地合成；没有或合成失败就下载整包。
4. 校验合成结果的整包 sha256 与清单一致。
5. 用 `PackageInstaller` 会话安装；首次需用户授权「安装未知应用」。

发布侧：每个新版本针对最近 K 个版本各生成一个补丁。签名密钥不得更换。

### 9.4 内核热更新

**兼容条件**（任一项不满足就跳过该内核，必要时提示先更新 APK）：签名与文件哈希；`protocol_version` 主版本在壳支持范围内；`python` 版本与 APK 内解释器一致；`host_requires` 由当前 APK 满足。

**槽位与切换**

```text
files/core/
  slot-a/   slot-b/   state.json   # active、pending、上一个可用版本、启动失败计数
```

1. 下载到非活动槽位并校验，标记 `pending`。
2. 下次拉起 `:agent` 进程时，若没有进行中或待恢复的回合，加载 `pending` 并自检：导入协议入口、读 `core_info`、用最小回放夹具读断点并重放一步。
3. 自检通过标为 `active`；失败回到原槽位。
4. 切换后若干次启动内，内核加载阶段崩溃达到阈值则回滚；所有槽位都不可用时回到 APK 内置内核。

**选择规则**：内置内核与两个槽位中，选兼容且版本最高的。APK 更新后若内置更新，以内置为准。

**数据兼容**：内核只做向前迁移。回滚后遇到新内核写下的断点返回 `ResumeIncompatible`，提示「该回合无法继续」，已提交的稿不受影响。改变断点或侧车含义的内核必须抬高 `schema_version`。

### 9.5 更新服务

- 只托管静态文件：`<channel>/manifest.json` 及签名，含 APK 版本、整包与补丁、内核包、预设。
- 只有 GET，不带设备标识、作品信息或 key。
- 这是除模型服务外唯一的出站地址，列入隐私说明；设置中可选「自动检查」「仅手动」「关闭」。
- 清单签名公钥内置于 APK，与内核签名使用不同密钥。

---

## 10. 安全

| 项 | 设计 |
|----|------|
| API key | Keystore 生成的 AES-GCM 密钥加密，密文存 DataStore；不用已弃用的 EncryptedSharedPreferences |
| key 跨进程 | 每次 `startTurn` 由主进程解密后经 AIDL 传入 `:agent`，只留在内存；`:agent` 不读 DataStore |
| key 去向 | 只发往用户配置的模型地址 |
| 明文 HTTP | 默认禁止；仅对用户显式标为「局域网」的地址放行 |
| 日志 | 写入前脱敏 key 与 Authorization 头；诊断导出同样脱敏 |
| 代码来源 | 只加载内置内核，或签名校验通过的槽位内核 |
| 服务导出 | `AgentService` 不导出（`exported=false`），只接受本应用绑定 |

---

## 11. 信息架构

| 页面 | 内容 |
|------|------|
| 作品 | 列表、新建（引导到开篇 / 大纲）、导入、导出、删除 |
| 稿 | 按 `work_view` 角色分组：大纲、章节、卡片、笔记；本回合改动高亮；撤销与版本列表 |
| 回合 | 输入框与 TurnView。相位决定画什么：开篇卡片、Plan 确认、修订候选、交付摘要。默认只显示进度与稿的变化，工具轨迹折叠到「回合详情」 |
| 设置 | 服务商与 key、探测、回合预算、用量、更新、诊断日志、版本（APK 与内核）、与服务器差异说明 |

Web 的写作工作台按同一套页面划分演进；检索、资料库、signals 弹层这些服务器专属能力保留在 Web。

---

## 12. 仓库与模块

### 12.1 仓库

原型在本仓库 `clients/android/`，与 SDK 同仓，方便改协议时一并改壳。协议 1.0 冻结、G0–G7 通过后迁出为独立仓库 `writing-android`。迁出理由：工具链（Gradle、JDK 17、Android SDK）与 runtime 的 Python CI 互不干扰；签名密钥与渠道配置只属于客户端；内核以版本化产物消费。代价是内核升级要单独提「升级内核版本」PR，跨仓排查靠契约夹具与回放夹具缓解。

### 12.2 模块与依赖规则

```text
writing-android/
  app/                    # Activity、导航、依赖注入装配；不含业务
  feature-works/          # 作品页
  feature-draft/          # 稿页
  feature-turn/           # 回合页
  feature-settings/       # 设置页
  client-core/            # 纯 Kotlin/JVM：契约模型、WritingBackend、TurnStore、意图；无 Android 依赖
  backend-local/          # LocalBackend、AIDL、:agent 进程的 AgentService 与 PythonBridge
  data/                   # Room 索引、DataStore
  security/               # Keystore 封装
  update-core/            # 清单、内核槽位、预设（全渠道）
  update-apk/             # 差分与 PackageInstaller（仅 direct）
  presets/                # 服务商预设 JSON 与 schema
  build-logic/            # 渠道、签名、契约代码生成
  core.lock               # 内核版本、sha256、签名公钥指纹
  contracts.lock          # 所消费的 packages/contracts 版本
```

| 规则 | 检查方式 |
|------|----------|
| `feature-*` 只依赖 `client-core`，互不依赖 | Gradle 依赖约束 |
| `client-core` 不依赖 Android SDK、Chaquopy、任何 `backend-*` | 作为纯 JVM 模块编译 |
| 只有 `backend-local` 知道 Python 存在 | 依赖约束 |
| 契约模型由 `packages/contracts/schemas` 生成，不手写 | `build-logic` 代码生成任务；生成物与 `contracts.lock` 对齐 |

### 12.3 内核与契约接入

1. `core.lock` 写明内核版本与 sha256；Gradle 任务拉取 `writing-core-<ver>.zip`，校验签名与哈希，放入 assets 作为内置内核。
2. `contracts.lock` 写明契约版本；生成 Kotlin 模型，并拉取「事件日志 → 视图」夹具给 `client-core` 单测。
3. 升级内核或契约即改对应 lock 并提 PR。CI 跑 `client-core` 夹具单测，并在模拟器上用内核包附带的回放夹具跑一回合，通过后才能合入。

---

## 13. 技术选型

| 层 | 选择 |
|----|------|
| 解释器 | Chaquopy，CPython 主版本与内核清单一致（当前 3.11） |
| 界面 | Kotlin、Jetpack Compose、Navigation；单向数据流（ViewModel 暴露 `StateFlow<TurnView>`） |
| 依赖注入 | Hilt 或手写装配，二选一，原型阶段定 |
| 跨进程 | 绑定服务 + AIDL，载荷为 JSON 字符串 |
| 本地索引 | Room（可重建） |
| 配置 | DataStore |
| 密钥 | Android Keystore（AES-GCM） |
| 网络 | 模型流由内核内的 httpx 负责；若 G3 失败，改为 OkHttp 实现的模型传输端口，经协议注入 |
| 差分 | HDiffPatch（`direct` 渠道） |
| ABI | 仅 `arm64-v8a` |
| 系统版本 | minSdk 取 Chaquopy 要求与 26 中较高者；targetSdk 跟随商店当年要求 |
| 构建 | Gradle Kotlin DSL，JDK 17；CI 用 cmdline-tools 无头构建 |

---

## 14. 开工门禁

前提：SDK 文档第 10 节验收通过（含 A11–A17）。原型在 `clients/android/` 中完成。

| 编号 | 验证项 | 通过标准 |
|------|--------|----------|
| G0 | 契约夹具 | Web 的 `reduceTurn` 与 Kotlin `TurnStore` 跑同一批夹具全部通过 |
| G1 | 原生依赖 | `host_requires` 的每个包在 Chaquopy 上都有可用 wheel |
| G2 | 回放一致 | 内核包附带的回放夹具在真机上跑一回合，事件序列与桌面命令行壳一致 |
| G3 | 真实长流 | 至少两家服务商完成 40 步真实回合，无流中断 |
| G4 | 断点恢复 | 回合中途分别杀 UI 进程与 `:agent` 进程：前者回合继续且视图补齐，后者恢复正确且无重复补丁 |
| G5 | 内核热切换 | 槽位切换、自检失败回滚、崩溃回滚三条路径在真机上走通 |
| G6 | 差分安装 | 侧载包从旧版本差分升级，合成哈希一致且安装成功 |
| G7 | 基线 | 记录 APK 大小、内核包大小、冷启动耗时、回合期间两个进程的内存峰值 |

---

## 15. 风险

| 风险 | 影响 | 处置 |
|------|------|------|
| 用户选用工具调用能力弱的模型 | 回合质量差，被归咎于应用 | 预设标注、探测、推荐模型 |
| 花费超预期 | 流失、差评 | 回合预算、开始前估计、实时用量 |
| 稿丢失 | 不可接受 | 导出 / 导入、回合快照、首回合后引导设置导出 |
| 两只壳的相位逻辑漂移 | Web 与手机对同一事件画出不同界面 | 相位只从事件推导；契约夹具是两端共同验收（G0） |
| 壳暗中依赖稿树布局 | 某次内核热更新后稿页空白 | A14 作品读写入口；`client-core` 不出现路径常量 |
| 坏内核推送到用户 | 无法写作 | 签名、兼容检查、自检、崩溃回滚、内置内核兜底；小比例灰度 |
| 签名密钥泄露或丢失 | 恶意更新，或无法覆盖安装 | APK、清单、内核三把密钥分离，离线保管并备份 |
| 渠道政策变化 | 下架 | 内核热更新按渠道开关；`play` 渠道不含自更新 |
| 前台服务被厂商策略终止 | 回合中断 | 步级断点与恢复；主流 ROM 的保活设置引导 |
| 上架合规（国内应用备案、生成式 AI 相关审核） | 无法上架 | 首版只出 `direct`；上架前单独评估用户自带 key 形态下的合规要求 |
