# 20 — 上下文压缩完整过程模拟

> 目的：用项目内名词，把一次自动压缩从「窗口将满」走到「模型调用」完整演一遍。  
> 规范对照：工具与上下文工程文档中的多层防线、可观测约定。  
> 说明：本文是**教学模拟**，数字为示意；真实 token 以 `context.reported` / provider 为准。

---

## 1. 先分清三个容易混的词

| 名词 | 是什么 | 谁触发 |
|------|--------|--------|
| **自动压缩链** | 每次模型调用前，上下文引擎整理本窗 `messages` | 组装上下文时 |
| **`/compact`** | 用户 slash：对 **session** 做摘要落库 | 输入侧识别 slash 后走会话压缩 |
| **`Compact: N`（UsageMeter）** | 当前窗口里「压缩产物消息」约占 N tokens | 窗口分项统计里的 compaction |

自动压缩**不删** workspace / `.agent/sessions/.../revisions/` / UI 聊天记录；它只改**本步发给模型的那一窗**。

---

## 2. 默认阈值与关键名词

压缩策略阈值（可配置）：

| 字段 | 默认 | 含义 |
|------|------|------|
| 模型窗口 | 128_000 | 上下文窗口上限 |
| 输出预留 | 16_384 | 给模型输出留空 |
| `fill_collapse` | 0.80 | ≥80% 触发 **collapse** |
| `fill_snip` | 0.90 | ≥90% 触发 **snip** |
| `fill_autocompact` | 0.95 | ≥95% 触发 **autocompact** |
| 热区比例 | 0.35 | collapse 时最近热区约占可用消息预算的 35% |
| 工具结果字符预算 | 约 4_000 字符 | **budget** 截断单条 tool 结果 |

其它名词：

| 名词 | 含义 |
|------|------|
| 本 turn 的 messages | 本轮累积的对话/工具消息（压缩输入） |
| `ContextEnvelope` | 组装后的权威输出：system、message 窗、tools、预算报告、压缩轨迹 |
| `fill_ratio` | 当前窗占用 / 模型窗口 |
| `tokens_before` / `tokens_after` | 压缩前/后估计 |
| `compaction_trace` | 本步触发了哪些策略（UI「压缩: a → b」） |
| `context.reported` | 发给前端的用量事件 |
| 热区（hot zone） | collapse 保留的**最近一段**消息（tail） |
| head | collapse 尽量保留的**第一条 user**（初始任务） |
| middle | 被折叠掉的中间历史 |
| **模型网关（gateway）** | 运行时用来调主模型（或专用 compact 模型）的调用通道；有它才能「再问一次模型写摘要」 |

### 实现中的真实顺序

```text
取 messages
→ budget（截断超长 tool_result）
→ microcompact（折叠连续工具结果）
→ collapse（fill ≥ 0.80）
→ snip（fill ≥ 0.90，可循环）
→ autocompact（fill ≥ 0.95；能调模型时先 pending 再 LLM 摘要，否则确定性摘要）
→ 物化窗口 → 调模型
```

> 注意：早期规范文曾把 snip 写在 microcompact 之前；**以当前运行时组装顺序为准**（上表）。

---

## 2.1 它到底是怎么干的？（核心机制）

这一节回答最容易误会的一点：**`collapse → snip → autocompact` 不是「严重程度一路加重」的渐进压缩**，而是**同一次组窗流水线里的三道独立阈值闸门**。前面两步 `budget` / `microcompact` 也是流水线的一部分，但它们通常「能做就做」，不看 80/90/95 那三道闸。

### 触发时机

每次准备调用模型前，都会重新组装「本步发给模型的那一窗」：

1. 拿出本 turn 当前的 `messages`
2. 按固定顺序跑压缩链
3. 得到压缩后的窗 + `compaction_trace`（UI「压缩: a → b」）
4. 只把压缩后的窗送给模型

所以：**不是会话活得越久就自动升级档位**；而是**每一步组窗都从头检查一遍**。上一轮做过 collapse，这一轮若工具结果又把窗堆满，可能再做 snip；若这一轮 `fill` 已经很低，也可能什么都不做。

### 控制流（伪代码）

把运行时逻辑说成人话：

```text
messages = 本 turn 当前消息副本
trace = []

# —— 前两层：尽量先做，不看 80/90/95 ——
对每条超长 tool_result：按约 4k 字符截断 → 记 budget
把可折叠的连续 tool 结果折成短占位 → 记 microcompact
（紧跟「助手刚发起的工具调用」的配对结果不乱折）

# —— 后面三层：各自看当前 fill，做完立刻重算 ——
重新计算 fill

若 fill ≥ 0.80 且消息足够多：
    collapse：保留 head（尽量第一条 user）+ 热区 tail
              中间换成 [collapsed N earlier messages; …]
    记 collapse
    再算 fill          ← 关键：折完可能已经 < 0.90

当 fill ≥ 0.90 且还能安全删：
    snip：删除最老一组连贯消息（可循环多次）
    每删一次就再算 fill
    直到 fill < 0.90 或无法再删
    记 snip（可能多次）

再算 fill
若 fill ≥ 0.95：
    autocompact：整窗收成一条结构化摘要
      · 有模型网关：可先 pending，再调模型写摘要
      · 无网关：规则拼接摘要
    记 compact

写出 tokens_before / tokens_after / fill / 分项
发出 context.reported → UsageMeter 更新
把压缩后的 messages 送给模型
```

要点只有三句：

1. **顺序固定**：永远按 budget → microcompact → collapse → snip → autocompact 检查。  
2. **执行条件独立**：collapse / snip / autocompact 各自有阈值；不是「做了 A 就必须做 B」。  
3. **每层后重算 `fill`**：前面若已把占用压下去，后面直接跳过。

### 为什么不是「渐进」？

| 若以为是渐进 | 实际 |
|--------------|------|
| 占用慢慢涨，先 mild collapse，再加重 snip，最后才 autocompact | 三种是**不同手段**（折中间 / 删最老组 / 整窗摘要），不是同一动作的三个强度档 |
| 触发后面，就必然已经做过前面 | 顺序上会先检查前面，但**前面可能因条件不满足而没改多少**；真正决定做不做的是**当时的 fill** |
| 会话越长档位越高 | 每轮组窗独立评估；fill 低时整链可空转 |
| 三选一 | 可以只做一层，也可以同轮做多层 |

「渐进」唯一沾边的地方：流水线**故意把更狠的手段放后面**，且要求更高 fill——这是**优先尝试更轻手段**，不是严重度刻度盘。

### 同一次组装，常见四种结果

下面 `fill` 都指「budget / microcompact 之后」的占用（示意）：

| 组装后的 fill 走势 | 实际发生 | UsageMeter「压缩:」常见样子 |
|--------------------|----------|------------------------------|
| 先 0.72，瘦完更低 | 可能只有 budget / microcompact，或什么都不做 | `budget` 或空 |
| 0.86 → collapse 后 0.70 | 只到 collapse | `… → collapse` |
| 0.93 → collapse 后仍 0.91 → snip 几次到 0.85 | collapse + snip | `… → collapse → snip` |
| 前面两层后仍 ≥0.95 | 再上 autocompact | `… → snip → compact` |

也可能出现「看起来像跳层」：某次工具结果极大，budget 后直接 ≥0.90。流水线仍会先问「要不要 collapse」（因为 ≥0.80）；若消息太少或折不动，随后主要靠 snip；若还 ≥0.95，再上 autocompact。本质仍是独立闸门，不是跳级算法。

### 窗口为什么会锯齿波动？

```text
工具返回一大坨  →  fill 冲高  →  可能连续触发多层
压缩一轮结束    →  fill 掉下去 →  后面几步可能什么都不做
下一轮又读大文件 →  fill 再冲高 →  又出现 collapse / snip
```

所以你在 Web 上会看到：一会儿只有 `budget`，一会儿 `budget → collapse`，再过几轮冒出 `snip`。这不是策略乱跳，是 **fill 在涨落，闸门在开关**。

### 和磁盘 / UI 的关系（再强调一次）

| 对象 | 压缩链会不会改 |
|------|----------------|
| 本步发给模型的 `messages` | **会改**（截断 / 折叠 / 删除 / 摘要） |
| Web 聊天记录 | **通常不改**（所以你会「看见」一开始问了什么） |
| workspace / revisions 草稿文件 | **不删** |

模型「忘了」中间原文，不等于文件没了；需要细节应再 `read_file`。

### 一句话

**每步调模型前：先削大块工具结果、再折工具噪音；然后按 80% / 90% / 95% 三道独立闸决定要不要折中间、删最老、整窗摘要；每道闸后重算占用，够瘦就停。不是渐进加重，是同轮流水线 + 可跳层闸门。**

---

## 3. 模拟设定（写作场景）

- **Scenario**：`writing`
- **Session**：`57c50771-…`
- **Turn**：`b6ace915-…`
- **硬约束（用户埋下）**：主角姓赵；禁止出现飞机
- **产物**：`draft_section` →  
  `.agent/sessions/57c50771-…/revisions/b6ace915-…/ch1-full.md`

压缩前，本 turn messages 示意（简化 ID）：

```text
M01 [user]      写第一章；主角姓赵；禁止出现飞机
M02 [assistant] 好，我先检索资料
M03 [assistant] tool_use: search_sources
M04 [tool]      大段检索结果（很长）
M05 [assistant] tool_use: read_file(sources/…)
M06 [tool]      超长正文（数万字）
M07 [assistant] tool_use: draft_section(ch1-full)
M08 [tool]      drafted → revisions/.../ch1-full.md
M09…M40        多轮再读、再改、再工具输出…
M41 [user]      按上一章结尾续写 200 字
```

压缩前估算（示意）：

```text
tokens_before ≈ 112_000
fill_ratio    ≈ 112000 / 128000 ≈ 0.875
```

此时 UI 可能还显示上一轮的用量；本步组装一开始就会跑压缩链。

---

## 4. 完整过程：逐步模拟

### Step 0 — 进入组装

引擎准备调模型前组装上下文：带上 writing 的 system、本 turn 状态、工具表；若本步**能调用模型**（有模型网关），autocompact 会先标记 pending，再真正调一次摘要模型。

组装输入还包括：

- `project_context`（工作区/项目侧注入）
- `runtime_context`（scenario、step、model 等）
- 本轮可见工具列表

先算一版 `tokens_before`，再开压缩。

---

### Step 1 — `budget`：削大块 tool_result

对超长 `tool_result` 按约 4000 字符预算截断；短且重要的目录列举等可保留。

| 消息 | 动作 |
|------|------|
| M04 检索结果超长 | 截断到约 4k 字符 + 截断标记 |
| M06 大文件正文超长 | 同上 |
| 短目录列举等 | 可保留 |

压缩轨迹追加：`budget`，例如截断了 2 条工具结果。

示意窗口：`112k → ~96k`，`fill ≈ 0.75`。

**磁盘**：`ch1-full.md` 不动。  
**UI「压缩:」**：若本步只到这里，会显示 `budget`。

---

### Step 2 — `microcompact`：折叠连续工具噪音

规则要点：

1. 连续多条工具结果可折成一条占位  
2. **紧跟**「助手发起工具调用」的配对结果**不能乱拆**（否则工具调用 ID 对不上）

假设中间有一串已完成、可折的旧 tool 结果：

```text
折叠前：… T1, T2, T3, T4 …
折叠后：…
  [user] [microcompact: folded 4 tool results; re-read with tools if needed]
```

轨迹追加：`microcompact`。该占位消息的 token 计入分项 **`Compact`**。示意：`96k → ~90k`。

---

### Step 3 — 再次堆高（多步工具后）

同 turn 或后续 step 又读了大文件，`fill` 回到 **0.86 ≥ 0.80** → 进入 collapse。

---

### Step 4 — `collapse`：折 middle，保 head + 热区

阈值：`fill ≥ 0.80` 且消息足够多。

切分：

```text
可用消息预算 = 模型窗口 - 输出预留 - system - tools
热区预算     = 可用消息预算 × 约 35%
从最新消息往前凑够热区 → tail
head   = 第一条 user（若存在）→「姓赵 / 禁飞机」
middle = head 之后、热区之前 → 大量中间轮次
tail   = 最近热区 → 含「续写」及附近工具
```

折叠结果：

```text
[user] 写第一章；主角姓赵；禁止出现飞机
[user] [collapsed 28 earlier messages; recent context preserved]
       （可选附带 pinned tool 摘要）
…tail 最近消息原文…
```

示意：`~110k → ~78k`。没有删磁盘草稿；模型暂时看不到中间逐字内容；需要细节应再读文件。UsageMeter 里 **`Compact`** 上升。

---

### Step 5 — `snip`：仍满则丢掉最老组

假设工具结果仍很大，`fill` 回到 **0.92 ≥ 0.90**。

每次删除一组连贯前缀：一个 user 段，或「助手工具调用 + 紧随的工具结果」；避免留下不成对的工具结果。可循环多次，直到 `fill < 0.90` 或无法再安全删除。

**关键细节（会不会删掉「最开始问了什么」）：**

- snip **可以**删掉最老的那一组 user 问答（包含最初那句）。  
- 尤其是 collapse 之后窗变成：`[最初 user] + [collapsed 占位] + [热区]`。下一次 snip 时，最老的是最初 user，下一条 user 往往就是 `[collapsed…]` 占位——于是**一次 snip 就可能只删掉头上的初始问题，留下 collapsed 占位和热区**。  
- 但你体感上「折叠很多轮后它还知道一开始问了什么」，通常是因为：  
  1. 多数会话只到 **budget / collapse**，UsageMeter 常见 `压缩: budget` 或 `budget → collapse`，**还没到 snip**；collapse 会刻意保留 head。  
  2. 最近热区里用户又复述了目标（「续写上一章」「按刚才设定」），模型靠热区也能接上。  
  3. 若已走到 autocompact，摘要里常带「目标 / 约束」字段，初始意图以摘要形式回来。  
  4. Web 聊天记录仍完整——你看见的「一开始问了什么」在 UI 上，不等于模型窗里一定还有原文。  

所以：**snip 理论上会删头部交互；日常体感还记得，多半是还没真正靠 snip 删头，或目标已写进热区/摘要。** 探针题应在出现 `snip` / `compact` 后再问「最初硬约束是什么」。

---

### Step 6 — `autocompact`：整窗摘要兜底

若仍 **`fill ≥ 0.95`**：

这里的 **gateway = 模型网关**：运行时用来向模型服务发请求的通道（主对话用的那套；也可配置成更便宜的 compact 专用模型）。

| | **有网关（常见线上路径）** | **无网关（同步/单测/降级）** |
|--|---------------------------|------------------------------|
| 做什么 | 先标记「待摘要」，再**真的再调一次模型**生成结构化摘要 | **不调模型**，用确定性规则从消息里抽目标/路径/近况拼摘要 |
| 轨迹细节 | `autocompact_pending` → `autocompact_llm` | `autocompact_summary` |
| 质量 | 摘要更像自然语言、更完整 | 更稳、零额外模型费用，但可能更干巴 |
| 何时出现 | 正常 turn 组装且能连上模型时 | 组装时没有可调用通道，或摘要调用失败后的退路 |

摘要消息示意（一条 user）：

```text
[autocompact]
目标：续写第一章约 200 字
约束：主角姓赵；禁止出现飞机
产物：.agent/sessions/…/revisions/…/ch1-full.md
近期动作：draft_section(ch1-full)；用户要求续写
…
```

示意：整窗可落到约十几 k～几十 k；`Compact` 项主要来自这条摘要。

---

### Step 7 — 定稿与可观测

组装结束写入：压缩轨迹、压缩前后 token、fill、system/tools/messages 分项等。打日志后发出 **`context.reported`**。

Web UsageMeter 示意：

```text
上下文窗口 38.0k / 128.0k (30%) · provider
System 1.3k
Tools 1.8k
User …
Assistant …
Tool results …
Compact 1.1k          ← 占位/摘要本身，不是「删了 1.1k」
压缩: budget → microcompact → collapse → snip → compact
模型用量 in=161.9k · out=4.6k   ← 累计计费，≠ 当前窗
```

然后模型只看见压缩后的窗，继续生成 / 调工具。

---

## 5. 一张总时间线

机制总览见 **§2.1**（独立闸门、每层重算 fill、为何不是渐进）。本节用时间线把名词串进一次写作模拟。

还会碰到：每一拍各自改什么？和磁盘草稿是不是一回事？有没有模型网关差在哪？snip 会不会删掉「一开始问了什么」？

先给骨架，下面密集串起来（数字为示意）：

```text
T0  messages 将满（fill≈0.875）
     │
T1  budget        截断超长 tool_result（4k 字符预算）
T2  microcompact  连续 tool → [microcompact: folded N…]
T3  （窗口再次升高）
T4  collapse      head + [collapsed N…] + 热区 tail
T5  snip×k        丢最老消息组，直到 fill < 0.90 或不能再删
T6  autocompact   fill≥0.95 →（有网关则 pending→再调模型摘要；否则确定性摘要）
T7  context.reported → UsageMeter 更新
T8  模型调用（只见压缩后的窗口消息）
T9  若需正文 → read_file(revisions/.../ch1-full.md)
```

1. 名词：`messages` = 本 turn 累积对话/工具结果；`fill` = 占用÷窗口；`tool_result` = 工具回写进窗的内容；`budget` = 单条超长结果先截到约 4k 字符；`microcompact` = 连续多条 tool 折成一条短占位；`collapse` = fill≥0.80 时保留第一条 user（head）+ 最近热区（tail，约 35%），中间换成 `[collapsed N…]`；`snip` = fill≥0.90 时**删除**最老一组（可多次）；`autocompact` = fill≥0.95 整窗摘要；**模型网关** = 能否再调一次模型来写摘要；`Compact: N` = 占位/摘要还在窗里的体积；草稿路径在 revisions 上，压缩不删文件。

2. 模拟：写作 turn 已读过大资料、写过第一章，用户再说「续写 200 字」。开头 user「姓赵/禁飞机」常当 head；中间大量工具；末尾「续写」在热区。fill≈0.875 时开始组装压缩——不改磁盘、不改 Web 聊天记录。

T1 budget：截断超长 tool_result；要全文应再读文件。  
T2 microcompact：连续 tool → `[microcompact: folded N…]`；配对中的 tool 不拆。  
T3：常表示「瘦完又读大文件、fill 再涨」，不是单独策略名。  
T4 collapse：head + `[collapsed …]` + 热区；中间正文副本出窗，文件还在。  
T5 snip×k：删最老一组。**可以删掉最初那句 user**（collapse 之后尤其容易：一次 snip 只删 head，留下 collapsed 占位和热区）。你印象里「还知道一开始问了什么」，多半是：实际只到 collapse、热区又复述了目标、或 autocompact 摘要里写回了目标/约束，再加 UI 历史仍完整造成的错觉——不是 snip「永不删头」。  
T6 autocompact：`fill≥0.95`。**有模型网关**时先 pending，再调模型（可选用更便宜的 compact 模型）生成摘要；**没有网关**时不调模型，用确定性规则拼摘要。差别主要是摘要质量与是否产生额外模型用量，不是要不要压缩。摘要常把「目标/约束/产物路径」写回来，所以即使 head 被 snip 掉，模型仍可能「记得」最初意图。  
T7：报到 UsageMeter；自动压缩几乎没感知，是因为只有一行小字。

3. 组装后模型所见（假设已 collapse、尚未狠 snip）类似：

```text
[system]
… writing 规则 …

[user]
[runtime_context] scenario_id=writing step=8/20 …

[user]
写第一章；主角姓赵；禁止出现飞机

[user]
[collapsed 28 earlier messages; recent context preserved]

[user]
按上一章结尾续写 200 字
…热区里最近的 assistant / tool…
```

同一轮请求还带旁路 tools（name/description/parameters）；那是 function calling 通道，不是写进文本的块。

T9：需要正文就再读 revisions 里的草稿；不要装记得整章。产品含义：T1–T6 瘦窗；T7 勉强可见；T8 在瘦窗上继续；T9 靠磁盘再读恢复。

---

## 6. 压缩后「还在 / 不在」对照

| 对象 | collapse / snip / autocompact 之后 |
|------|-------------------------------------|
| UI 聊天记录 | 通常仍完整（所以你会「看见」一开始问了什么） |
| workspace / revisions 文件 | **仍在** |
| 模型窗口里的中间原文 | **可能不在** |
| 初始硬约束原文 | collapse 常保留在 head；**snip 后可能没了**；autocompact 可能以摘要形式回来 |
| 最近用户句 / 刚发生的 tool | 优先在热区 |
| `Compact: N` | N = 压缩产物在窗内的体积 |

**好压缩**：模型说「草稿在某路径，我再读一下」，或摘要里仍有硬约束。  
**坏压缩**：路径和「姓赵/禁飞机」都丢了，或开始编造正文。

---

## 7. 自动链 vs 手动 `/compact`

| | 自动压缩链 | `/compact` |
|--|------------|------------|
| 入口 | 模型调用前的上下文组装 | 用户输入 slash |
| 作用域 | 本步模型窗 | session 级摘要 |
| UI | 仅「压缩: …」小字 + Compact 分项 | 本地完成 summary，较明显 |
| 与本文关系 | 本文主体 | 另一条路径；不替代逐步 budget/collapse |

用户「没感知」，通常是因为自动链**没有**独立时间线条目，只有 UsageMeter。

---

## 8. Web 端如何对照本模拟做验证

1. 新会话埋硬约束 → 多轮大文件读取 / 工具  
2. 盯 `压缩:` 是否出现 `budget` → `collapse` → …  
3. **若出现 `snip` 或 `compact`**，立刻探针：「最初硬约束是什么？ch1 路径？」——专门验证删头/摘要是否接住  
4. 可选再发 `/compact`，对比手动摘要后的探针表现  
5. 产物区确认 revisions 文件仍在  

机制可用上下文引擎相关单测覆盖；golden 冒烟目前主要证明「会发生 compaction」，不评质量。

---

## 9. 相关阅读

| 主题 | 内容 |
|------|------|
| 工具与上下文工程 | 多层防线规范、可观测约定 |
| Agent 系统问答 | Context 防线与速率相关问答 |
| Web 用量面板 | 窗口分项与「压缩:」展示 |
| 手动 `/compact` | 会话级摘要，与自动链不同路径 |

---

## 10. 一句话收束

**自动压缩 = 每次调模型前的同轮流水线：budget / microcompact 尽量先做；collapse / snip / autocompact 是 80% / 90% / 95% 三道独立闸，每层后重算 fill，够瘦就跳过——不是渐进加重。`Compact: N` 是摘要/占位还留在窗里的大小。你觉得「还记得一开始问了什么」，常见是 collapse 保头、热区复述、摘要写回，或只是 UI 还在——不是 snip 永不删首问。机制细读 §2.1。**
