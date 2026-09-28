# 写作模块：立意（作品候选）

本文描述 **现行实现** 里「只给题材、先出两本候选」这一段。冲突时以代码为准。路径相对 `services/runtime/`。

立意在本仓是一个程序阶段：用户点名题材或长篇开写 → Parent 空调用工具 → Handler 内部采两个互不可见的 `{title, pitch}` → 交给点选 UI → 停。好不好、像不像一本可以写下去的书，不在 child 里判。

范围到此为止。点选后的 opening / outline / `draft_section`、L1 质地、`excerpt_job` 硬卫生（stub 路径仍可能走）不在本文展开。

---

## 1. 这一阶段要解决什么

用户说「写一篇长篇的都市修真小说」时，产品要的不是第一章，也不是聊天里的两段创意。

要的是：

- 两张卡
- 每张卡一个工作书名 + 一段书页简介（`pitch`）
- 简介是入口，不是第一章，也不是构思过程
- 助手正文应空；卡片才是交卷

程序上把这件事拆成三层，避免同一个模型又当导演又当执笔者：

| 层 | 谁 | 只做什么 |
|----|----|----------|
| Parent | writing 场景主模型 | 本轮被闸进选书 → 空调用 `propose_book_candidates` → 停 |
| Handler | `propose_book_candidates` | 定本句用来抽类型的原文、开两个 sample、校验、落盘、返回两张卡 |
| Child | 每个 sample 的独立补全 | 根据用户原话和至多一条题材参照，交一个 `{title, pitch}` |

Child 不决定「什么时候交卷」。Sample 是 handler 创建的原子 job：一次结构化补全 → 解析一个对象 → 结束。格式失败或撞上旧卡，丢掉当前结果，再新开一发（新 messages、同一条题材参照），每个槽最多一次。两本简介过近时，只重抽第二本，可以换一条题材参照。交出去的张数仍是 2。

---

## 2. 何时进入立意

闸门在 `turn_phase.picking`。`outline_phase.wants_opening_candidates` 只是转调。不是模型自己理解「该选书了」，也不是一份类型词清单。

判定按这个顺序，先命中先返回：

1. 整句 `我要其他的` → 进入。这一句排在 committed pond 之前，用来远离上一组书。
2. 消息在点选某一张（`按开篇候选` / `采用此开篇` / `按此开篇`）→ 退出。
3. 工作区已有 `committed_pond.json` → 退出。
4. 消息已经在点名既有书或写法（`名叫`、`叫` + 一到八字、`像…写`、`风格是`、`凡人流`、`系统流`、`克系`、`灵异`、`探案`）→ 退出。
5. 大纲里已经有章段任务（`has_chapter_jobs`）→ 退出。
6. 尺度不是长篇 → 退出。短篇、单篇即使说「我看看」也不进。`写一篇都市故事` 判成单篇，不进。`写一部小说`、`写一篇长篇…` 判成长篇。
7. 浏览口令（`看看` / `发散` / `几种` / `换个开` / `什么风格` / `先看` / `我要其他的` / `都不合适`）→ 进入。风格契约已经写进大纲时，这一支仍然进入。
8. 中途续写（`续写` / `接着写` / `继续写` / `往下写` / 第二章及以后）→ 退出。
9. 其余长篇：大纲里还没有风格契约（`outline_style_committed` 为假）→ 进入。所以「写一部小说」不必再带类型词。

进入后：

- `should_gate_opening_choice` 为真时，本轮工具白名单只剩 `propose_book_candidates`。别名 `propose_opening_ponds` 不在这份白名单里。`stub_echo` 仍注册给测试，不交给模型。
- volatile 灌 `opening_choice.md`：只触发空调用。
- 点选成功后引擎 `TERMINATE`，原因 `opening_ponds_awaiting_choice`。
- outline 相位记成 `open`，说明是长篇开写、工具内部两本独立采样、不要写进聊天。

`「我看看」` 不是「再采一组」。只有整句 `我要其他的` 才会把当前池记入拒池再采新的两本。

---

## 3. 总链

```
用户：写一篇长篇的都市修真小说
        │
        ▼
picking → opening_choice 闸
parent 只调用 propose_book_candidates(items=[])
助手消息保持空
        │
        ▼
handler  沿用会话里点过名的那一句（本句已点名则用本句）
        │
        ▼
题材池：宽泛都市超凡 → 两个不同书架各抽一条参照
        具体方向或没有都市池的长篇 → 不塞参照，按原话采
        │
        ▼
fresh sample c01          题材参照 A（或无）
structured out title+pitch
        │
        │  把 c01 的书名放进排除集
        ▼
fresh sample c02          题材参照 B（或无）
structured out title+pitch
        │
        ├─ 两本简介过近 → 换书架重抽 c02（仍看不见第一本正文）
        ▼
硬校验 / 书名与指纹排除
        │
        ▼
落盘 opening_ponds.json
        │
        ▼
返回两张卡  STOP
```

生产路径交卷写死 **N = 2**。没有第三张卡，没有 child 侧 selector。第二本过近时可以多一次补全，那一次仍写进 `c02`，不增加张数。不够两张合法卡：`stop_retry=True`，不再让 parent 把整轮「生成候选」重跑一遍。

两本顺序采样，互相看不见。`c02` 的提示里没有第一本的书名和简介。第一本的书名只进排除集：交卷撞上才丢掉这一发，同一参照再试一次。

---

## 4. 工具构成

### 4.1 对外工具

注册在 `tools/bootstrap.py`。

**`propose_book_candidates`**

- 描述：触发采样两本长篇网文候选；`items` 传空；不要在 parent 上下文里编书名和简介。
- 参数：`items` 数组，`maxItems` 3。live 路径忽略内容，只认空调用。
- Schema 里仍写了 `title`「二到八字」、`pitch`「约100–220字」——那是 **stub / 旧调用方** 的字段说明。live child 的硬约束是 `CANDIDATE_SCHEMA`（书名 2–16 字，pitch 非空）。
- timeout 600s。
- 成功：`status=ok`，`awaiting_choice=true`，`items` 为两张卡，摘要「N 本作品候选，待你点选或说「我要其他的」」。
- 失败（live 不够两张）：`error=ponds_fresh_retry`，`stop_retry=true`，`fresh_retry=false`，摘要「开篇候选这轮没交成。请再说一次「我看看」」。

**`propose_opening_ponds`**

- 旧名，直接转调 `propose_book_candidates`。
- 仍接受 legacy `opening` 作为 `pitch` 别名。
- 选书相位不把它放进模型可见工具。

### 4.2 live 与 stub

`_use_independent_candidate_sample`：

- `MODEL_MODE=live`，或测试钩子 `sample_complete` / `force_independent_sample` → **工具内部采样**
- 否则 stub：仍吃调用方交来的 `items`，可走 `excerpt_job` 闸（`ponds_excerpt_gate` 默认开）、held 合并、相似度挑对

本文其余默认讲 live。stub 在两张太像、或和拒池过近时可以 `fresh_retry=true`、`stop_retry=false`，让 parent 再调一次；同一 `turn_id` 上这种重采最多两次（`_POND_REPAIR_MAX = 2`），再失败才停。live 采样失败不走这条。

### 4.3 引擎对工具结果

`agent_engine.py`：

- 成功且 `awaiting_choice` → 结束 Turn（`opening_ponds_awaiting_choice`）
- `stop_retry` 错误 → 结束 Turn（`opening_ponds_retry_exhausted`）
- `fresh_retry` 且非 `stop_retry` → 丢掉这次 tool 尝试、灌 `previous_attempt_discarded`，让 parent 再调一次。**live 采样失败不再走这条**，避免「整轮生成候选」循环。

---

## 5. 采样构成

实现：`writing/candidate_sample.py`，题材参照在 `writing/subject_pool.py`。

### 5.1 一个 sample 是什么

`sample_one_candidate`：

1. 打 thinking 分隔 `—— 独立采样 ——`
2. `form_messages(user_text, subject=…)` 得到 **全新** messages（用户原话 + 类型参考 + 至多一条题材参照；不带上一发、不带另一本的简介、不带 A 的草稿）
3. `form_generation()` 带 `response_schema=CANDIDATE_SCHEMA`
4. 一次 complete
5. `parse_card`；pitch 以元话语开头则当格式失败
6. 合法则排除旧书名 / 内容指纹；命中则丢弃
7. 否则打成卡片返回

思考流在尚无正文时超过 `_FORM_THINK_CHAR_BUDGET`：abort 这一发，直接返回空，不再重试。

格式失败或排除命中：丢掉本次文本，**不把失败稿送回模型编辑**，再跑步骤 2–6，最多 `_SLOT_RETRIES=1`。重试仍用同一条题材参照。失败的 A 永远不会变成 A2。

### 5.2 两个 sample

`sample_independent_pair` 先把本轮 thinking 标成 `candidate-sample`，并给当前 turn 的事件写入开流存活。然后：

1. `resolve_sample_user_text`：本句已经点出类型就用本句。本句只是「我看看」或「我要其他的」这类换卡令牌时，从本会话最近 20 条用户话里找上一句点过名的，不把换卡令牌当成类型名。
2. `select_seeds` 抽参照。抽不满两本时：
   - 这句话是长篇，或仍落在都市超凡池上 → 两本都不塞参照，按用户原话各采一次
   - 否则这次不交卡
3. 打 thinking 分隔 `—— 题材池 ——`
4. 先采 `c01`，再采 `c02`。`c02` 的排除集多含 `c01` 的书名；这条书名不写进 `c02` 的 messages
5. 两张都在、且 `pitches_too_close` → 只重抽 `c02`。重抽的提示里仍然没有第一本简介

过近的两条判据，先向量、再词法：

- `compute_pond_similarity(..., shadow=False)`。embedder 可用且不是词法回退时，组内余弦 ≥ `ponds_similarity_intra`（默认 0.96）算同一本书。这次检查不看 `ponds_similarity_shadow`。
- 否则去空白后，连续相同达到 40 字（窗口 12–48）也算同一本书。

重抽时若这次用过参照，再 `select_seeds` 一条，排除已经用过的正文和书架。抽到新书架就用新参照；抽不到就仍用原来的第二条。重抽后的第二本仍看不见第一本简介。

汇合后按 title / pitch 指纹再去重，丢掉和排除集或彼此撞车的卡。槽位名 `c01`/`c02` **不是作品身份**：旧池若把 `id` 写成 `c01`，不得把新采样整槽扔掉。`_is_excluded` 不读 `exclude_ids`。

返回至多 `_SAMPLE_POOL = 2` 张。Handler 再用当前池和拒池的书名滤一遍（`drop_seen_pond_items`）。仍不够两张就停。

常数：

| 名 | 值 | 含义 |
|----|----|------|
| `_URBAN_SEEDS` | 75 条 | 都市超凡参照；19 个书架，条数不均 |
| `_SAMPLE_POOL` | 2 | 交卷张数；也是一次要抽的参照数 |
| `_SLOT_RETRIES` | 1 | 单本格式失败或撞车再试 1 次 |
| `_FORM_MAX_OUTPUT_TOKENS` | 1024 | child 输出上限 |
| `_FORM_THINK_CHAR_BUDGET` | 4000 | 思考字符预算，超了且尚无正文则 abort |
| `_THINKING_DELTA_MAX` | 8192 | 单次 thinking delta 截断 |
| pitch clip | 800 字 | 解析后裁切（`_OPENING_MAX`） |
| title | 2–16 字 | 解析硬门槛 |
| `ponds_similarity_intra` | 0.96 | 两本简介的组内余弦门槛 |
| 词法过近 | 40 字 | 向量不可用时的连续相同 |

### 5.3 题材参照池

池子只服务**宽泛的都市超凡**请求（`uses_reference_pool`）。都市修真、都市异能、都市玄幻、异能，以及「都市/城市 + 修真/玄幻/异能/系统/金手指/超凡」，还有系统文、面板、念能力、都市文这一类，进这个池。长篇本身不够：`写一部历史小说` 不进池。

每条是 `SubjectSeed`：一个书架名 + 一段对一本书的缩影（世界已经如何，谁从何处踏入，这本书要问的是什么）。条目不保留原作专名。书架名只用于抽样，**不进模型上下文**，也不规定候选必须采用什么结构。

`select_seeds`：

- 先丢掉已用正文和已用书架
- 用户话里的关键词只缩小书架，不写进 prompt：
  - 横练 / 极道 / 加点武道 → 异途武道、个人面板
  - 「只有主角有异能/系统」→ 独有异能、个人面板、都市生活
  - 能力体系 / 念能力 → 规则能力、公开超凡、游戏冒险
  - 系统 / 面板 / 金手指 / 模拟器 → 个人面板、异途武道、公开超凡、末世生存、游戏冒险、现代人生
  - 异能 → 都市隐秘、公开超凡、都市异变、末世生存、规则能力、个人面板、异途武道
  - 都市文 / 都市小说 → 现代人生、都市生活、都市隐秘、都市异变
- 在剩下的书架里无放回抽两个书架，每个书架随机一条
- 剩下的书架不足两个 → 返回空。调用方按 5.2 回退到「不塞参照」

用户已经给出具体方向时不塞随机作品（`我期望` / `我想要` / `偏向` / `类似` / `参考` / `不要` / 金手指、念能力、只有主角有能力、世界平凡 等）。此时若仍是长篇或都市超凡，两本都按原话采。

参照的用法写在 child prompt 里：用户原话优先；题材只供参照；另起人物、世界和故事，不要换名复述。

### 5.4 Child 生成参数

`scenario_id=None`：不继承 writing 场景温度 / 主 system。

- `thinking_enabled=False`
- `reasoning_effort=none`（DeepSeek 会显式 `thinking: disabled`，否则默认思考模式不能强制 `tool_choice`）
- `tool_choice=none`（随后由 `response_schema` 覆盖成结构化约束）
- `response_schema=CANDIDATE_SCHEMA`
- `max_output_tokens=1024`

模型若仍吐出 reasoning，`consume_complete` 会把片段打进本轮 `turn.thinking.delta`，并受 4000 字预算约束。预算是后盾，不是要求 child 先想一轮。

### 5.5 结构化输出（不要靠「请输出 JSON」）

`GenerationParams.response_schema` → `apply_response_schema`：

| 族 | 约束 |
|----|------|
| OpenAI / gpt-5 | `response_format.json_schema`，name `book_candidate`，`strict` |
| DeepSeek | 强制函数 `book_candidate`，parameters 即该 schema |
| Anthropic | 强制工具 `book_candidate`，`input_schema` 即该 schema |

DeepSeek 若 400「Thinking mode does not support this tool_choice」，兼容层补 `thinking: disabled` 再试。`json_schema` 不被吃时，降级为强制函数，**不剥成自由生成**。

Child 流结束时：优先从 `tool_calls[].input`（或 `arguments`）取对象，否则用文本里的 JSON。

---

## 6. 提示词（三套，职责不同）

### 6.1 Parent system（`scenarios/writing/system.md`）

主模型仍拿完整 writing system。立意相关只有 WORK STATE / TOOLS 里几句，用来禁止它自己编候选、禁止把草稿状态带进构思：

> 用户只给题材或说「看看」时，进入作品候选阶段。  
> 这一阶段只负责产生若干个新的作品候选，不写第一章，不进入 opening / outline / draft，也不要把当前章节、author_state 或其他写作状态带入候选构思。  
> 调用 `propose_book_candidates` 时不要自己编候选。工具会为每个候选建立独立的最小上下文并分别采样；每次采样只产生一个候选，不进行候选之间的比较、连续 brainstorm 或二次创作。  
> 候选只是一个大概成立、值得继续发展的作品概貌。形成后立即停止，由后续选择阶段负责判断。  
> 候选的 `pitch` 是书页入口，不是第一章开头。

TOOLS：

> 只给题材或说看看 → `propose_book_candidates`（工具内部两本独立采样，交两张书页简介；卡片是交卷，不要写进聊天；停下来等用户点选或说「我要其他的」）

Parent 不负责写出两本书。它只负责调用工具。真正的闸在 `picking`，不在这几句提示。

### 6.2 Parent volatile（`templates/opening_choice.md`）

本轮只触发采样。全文：

```
## Book choice

This turn only triggers sampling. Call `propose_book_candidates` once with empty `items`.
Do not invent the two books in this context. The tool samples each book in a fresh context.

Leave the assistant message empty; the cards are the deliverable.
Do not call `draft_section` or `update_outline`.
Do not list the candidates in chat.

Stay inside the genre the user named.
不要把简介写成第一章。
不要在这一轮聊天里构思两本。

卡片交卷是 `title` + `pitch`。
```

灌入条件：`should_gate_opening_choice` 为真。同时工具白名单只剩选书工具，避免主模型去 `draft_section`。

### 6.3 Child（真正产候选的 prompt）

`work_reconstruction.form_messages`。**不**继承 writing system，**不**带 `opening_choice`，**不**带旧卡，**不**带书架名。

System（`_FORM_SYSTEM`）：

```
根据用户原话，借题材参照交一本新书的书名和简介。

用户原话优先。题材只供参照，不是模板；另起人物、世界和故事，不要换名复述。

简介按书页上的作品介绍来写，让人知道这本书主要写什么。不要解释创作思路，不要罗列卖点，也不要写成预告片。

只交一本。
```

User：

```
用户原话：{用户原话}
类型参考：{genre}
题材：{抽到的那一条}

交这本书的书名和简介。
```

没有抽到参照时，不写「题材」那一行。`genre` 由 `genre_of` 从用来抽类型的那句话剥出。例：`写一篇长篇都市修真小说` → 类型参考 `都市修真`。两路 child 的「题材」行不同，所以不是「一次 brainstorm 切两段」。

这里的「书页介绍 / 不要卖点 / 不要预告片 / 不要换名复述」是交卷形式。好坏、值不值得写，仍不在 child 里打分。

故意不写的：

- 「请输出 JSON」——由 `response_schema` 约束
- 和另一张卡比较、连续 brainstorm、二次创作
- 「看起来像一本可以认真写下去的小说」——会被读成优化到足够优秀
- 质量、套路、连载潜力

---

## 7. 上下文投影

`project_candidate_context`：只返回 `{genre, fresh_work=True}`。它不读文件。真正进 child 的，是 `form_messages` 在这个投影之外拼上的用户原话和题材参照。

不读、不注入：

- `writing_context` / `focus=ch1` / `outline_phase` / `plot_progress`
- `outline.md`、draft、manuscript
- `author_state`
- 上一组卡片的正文、拒池正文
- 书架名
- 长篇 / 网文 / 工作模式标签（除了从用户句里剥类型时用到的「长篇」前缀；`topic_of` 会把「长篇」加回类型，采样 prompt 本身用的是 `genre_of`）

抽取规则（`genre_label`）：去掉「请/帮我/写一篇/写一本/写一章/写部」「长篇」「小说/网文」外壳，剩下的当类型。`genre_of` 在剥完仍空时回退整句，再空则默认 `都市修真`。

`names_genre`：换卡令牌（`我看看` / `看看` / `先看` / `我要其他的` / `我要其他`）不算点名。剥壳之后和原句不同，或剥出来的词能对上题材池，才算点出了类型。

`sample_user_text`：本句点了类型就用本句；否则沿用先验列表里第一句点过名的；都没有则仍用本句。Handler 的先验来自本会话最近 20 条用户输入。

---

## 8. 对象、解析、排除

### 8.1 Schema

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["title", "pitch"],
  "properties": {
    "title": {"type": "string", "minLength": 2, "maxLength": 16},
    "pitch": {"type": "string", "minLength": 1}
  }
}
```

Handler 只接受能解析成这个形状的结果。采样卡把同一段简介写入 `pitch` 和 `opening`，并带上 `id` / `sample_id`（`c01` 或 `c02`）、`raw`、`work`。`flavor` 解析器仍认，live schema 不要求模型填，空则落空串。

### 8.2 解析

`parse_card`：JSON 对象（含 fence）优先；否则 `title:` / `书名:` / `pitch:` / `简介:` / `opening:` 行。`flavor` / `这本书` 仍可解析。书名长度不在 2–16、或没有简介 → `None`。简介裁到 800 字，flavor 裁到 400 字。

`obvious_meta_text`：pitch 以「我觉得 / 我认为 / 我先 / 首先 / 接下来 / 这个故事可以 / 这部小说可以 / 分析：/ 比较：/ 创作过程 / 先想 / 先比较」开头 → 当格式失败。空 pitch 同样失败。这是「这是在分析，不是候选」，不是文学评分。

### 8.3 排除旧卡

`load_candidate_excludes`：当前 `opening_ponds.json` + `opening_ponds_rejected.jsonl`。

排除键：书名（casefold）、以及 raw / work / opening / pitch 的指纹。指纹是空白折叠后的 sha256 前 24 位。槽位 id 匹配 `c` + 至少两位数字时不进入 id 排除集；采样侧的 `_is_excluded` 反正不看 id。

`我要其他的`：先把当前组 `append_rejected_ponds`，再采新的两本。新采样看不到旧卡正文，只在交卷后按指纹/书名丢掉撞车项。live 路径不用向量去比拒池。这只在同一会话里成立。

新会话的第一轮、并且还没有已选书时，先删掉 `opening_ponds.json`、`opening_ponds_rejected.jsonl` 和 ledger 里的候选书名行，再采样。点选令牌「采用此开篇」不删，这一轮还要对上卡片。已经点中的书留给新会话继续写。

不够两张：直接停，不因为「内容不够好」再想一轮。

---

## 9. 落盘与 UI

成功路径 `save_opening_ponds` → `.agent/work/opening_ponds.json`。live 把采样卡原样写入，并带 `job_signals`。每张卡 `append_pond_fingerprint` 进 ledger。成功后清掉本轮的拒计和 held。

读回时 `normalize_pond_item` 把 `pitch` 折进 `opening`，不再保留 `pitch` 字段。点选 UI（`openingPonds.ts`）读 `title` + `opening`，简介展示裁到 800 字。Parent 被要求不要把两张卡抄进聊天。

`opening.ponds` 事件只投影 schema 允许的字段（含 `opening` / `flavor`），自述类字段不进事件。

点选之后才进入 opening / 第一章。那是另一条链：committed pond、大纲这一段写入书名和简介、章段任务。立意 child 看不到那些块。

---

## 10. 职责边界（刻意不放进 child）

| 事情 | 谁做 |
|------|------|
| 要不要进入选书 | `turn_phase.picking` |
| 采几本 | handler，交卷 `N=2` |
| 用不用题材参照、两本是否换书架 | `subject_pool.select_seeds` |
| 第二本是否过近并重抽 | handler，`pitches_too_close` |
| 何时停 | sample job 结束；不够两张则 `stop_retry` |
| 对象形状 | `response_schema` + parser |
| 简介写成书页介绍、不换名复述 | child prompt 的形式约束 |
| 好不好、值不值得写 | 用户点选 |
| 第一章怎么开 | 点选后的章，不在立意 child |
| 旧卡不要再出现 | 指纹/书名硬排除，不靠 prompt 黑名单 |

---

## 11. 文件地图

| 文件 | 职责 |
|------|------|
| `app/scenarios/writing/system.md` | Parent：何时调工具、不要自己编 |
| `app/scenarios/writing/templates/opening_choice.md` | Parent volatile：空调用、空助手消息 |
| `app/tools/bootstrap.py` | 工具 schema；选书相位白名单只有 `propose_book_candidates` |
| `app/tools/core/writing_tools.py` | `propose_book_candidates` live/stub 分流 |
| `app/writing/turn_phase.py` | `picking`：进不进选书 |
| `app/writing/outline_phase.py` | `wants_opening_candidates` 转调；开写 note |
| `app/writing/opening_ponds.py` | 闸工具、volatile 块、normalize、落盘、`我要其他的` |
| `app/writing/subject_pool.py` | 75 条参照、书架抽样、具体方向绕过池 |
| `app/writing/work_reconstruction.py` | 类型投影、child prompt、schema、解析 |
| `app/writing/candidate_sample.py` | 顺序两个 sample、过近重抽、格式重试 |
| `app/writing/pond_similarity.py` | 组内余弦；`same_book_reject` |
| `app/writing/pond_history.py` | 拒池、排除集 |
| `app/writing/ledger.py` | 候选指纹落账 |
| `app/model/generation.py` | `response_schema`、DeepSeek thinking/tool 兼容 |
| `app/engine/agent_engine.py` | awaiting_choice / stop_retry 结束 Turn |

核对时以这些文件为准。旧文里的「开篇第一段 + excerpt 五类硬拒 + 标题 2-gram 必须出现在正文」属于 **stub / 点选后章** 的另一套卫生，不是当前 live 立意 child 的交卷合同。`asyncio.gather` 并行两发、51 条共用名单、child 只收一行「题材：类型」也都已不在这条 live 路径上。
