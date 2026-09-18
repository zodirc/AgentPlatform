# 写作模块：立意（作品候选）

本文描述 **现行实现** 里「只给题材、先出两本候选」这一段。冲突时以代码为准。

立意在本仓不是文学课，也不是「找一个更好的方向」。它是一个程序阶段：用户点名题材 → 工具内部采两个互不可见的 `{title, pitch}` → 交给点选 UI → 停。好不好、像不像一本可以写下去的书，不在 child 里判。

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
| Parent | writing 场景主模型 | 认出「只要题材」→ 空调用 `propose_book_candidates` → 停 |
| Handler | `propose_book_candidates` | 抽题材、开两个 sample job、校验、落盘、返回两张卡 |
| Child | 每个 sample 的独立补全 | 根据题材交一个 `{title, pitch}` 对象 |

Child 不决定「什么时候交卷」。Sample 是 handler 创建的原子 job：一次结构化补全 → 解析一个对象 → 结束。格式失败只丢弃当前结果，再新开一发（新 messages），每个槽最多一次。

---

## 2. 何时进入立意

闸门在 `wants_opening_candidates`（`outline_phase.py`），不是模型自己理解「该选书了」。

进入的典型条件（同时满足「长篇近池未立」）：

- 整句 `我要其他的`
- 或 `看看` / `发散` / `几种` / `换个开` 等浏览口令
- 或消息命中尺度/类型词：`长篇`、`第一章`、`写一章`、`修真`、`玄幻`、`都市`、`仙侠`、`修仙`

不进入或退出：

- 大纲里已经订了风格契约（`outline_style_committed`）
- 已有 committed pond
- 用户在点选某一张（`按开篇候选` / `采用此开篇` 等）
- 消息已经在点名既有书（`名叫`、流派标签等）

进入后：

- 工具集闸成 `propose_book_candidates`（及 alias / `stub_echo`）
- volatile 灌 `opening_choice.md`：只触发空调用
- 点选成功后引擎 `TERMINATE`，原因 `opening_ponds_awaiting_choice`

`「我看看」` 不是「再采一组」。只有整句 `我要其他的` 才会把当前池记入拒池再采新的两本。

---

## 3. 总链

```
用户：写一篇长篇的都市修真小说
        │
        ▼
parent（writing system + opening_choice）
  只调用 propose_book_candidates(items=[])
  助手消息保持空
        │
        ▼
handler  extract genre
        │
        ├──────────────┐
        ▼              ▼
  fresh sample #1  fresh sample #2
  structured out   structured out
  title+pitch      title+pitch
        │              │
        └──────┬───────┘
               ▼
        硬校验 / 排除旧卡
               ▼
        落盘 opening_ponds.json
               ▼
        返回两张卡  STOP
```

生产路径写死 **N = 2**。没有 adaptive 补采，没有第三发，没有 child 侧 selector。不够两张合法卡：`stop_retry=True`，不再让 parent 把整轮「生成候选」重跑一遍。

---

## 4. 工具构成

### 4.1 对外工具

注册在 `tools/bootstrap.py`。

**`propose_book_candidates`**

- 描述：触发采样两本长篇网文候选；`items` 传空；不要在 parent 上下文里编书名和简介。
- 参数：`items` 数组，live 路径忽略内容，只认空调用。
- Schema 里仍写了 `title`「二到八字」、`pitch`「约100–220字」——那是 **stub / 旧调用方** 的字段说明。live child 的硬约束是 `CANDIDATE_SCHEMA`（书名 2–16 字，pitch 非空）。
- timeout 600s。
- 成功：`status=ok`，`awaiting_choice=true`，`items` 为两张卡。
- 失败（live 不够两张）：`error=ponds_fresh_retry`，`stop_retry=true`，`fresh_retry=false`，摘要「开篇候选这轮没交成。请再说一次「我看看」」。

**`propose_opening_ponds`**

- 旧名，直接转调 `propose_book_candidates`。
- 仍接受 legacy `opening` 作为 `pitch` 别名。

### 4.2 live 与 stub

`_use_independent_candidate_sample`：

- `MODEL_MODE=live`，或测试钩子 `sample_complete` / `force_independent_sample` → **工具内部采样**
- 否则 stub：仍吃调用方交来的 `items`，可走 `excerpt_job` 闸、held 合并、相似度挑对

本文其余默认讲 live。

### 4.3 引擎对工具结果

`agent_engine.py`：

- 成功且 `awaiting_choice` → 结束 Turn（`opening_ponds_awaiting_choice`）
- `stop_retry` 错误 → 结束 Turn（`opening_ponds_retry_exhausted`）
- `fresh_retry` 且非 `stop_retry` → 丢掉这次 tool 尝试、灌 `previous_attempt_discarded`，让 parent 再调一次。**live 采样失败不再走这条**，避免「整轮生成候选」循环。

---

## 5. 采样构成

实现：`writing/candidate_sample.py`。

### 5.1 一个 sample 是什么

`sample_one_candidate`：

1. 打 thinking 分隔 `—— 独立采样 ——`
2. `form_messages(user_text)` 得到 **全新** messages（不带上一发、不带 A 的草稿）
3. `form_generation()` 带 `response_schema=CANDIDATE_SCHEMA`
4. 一次 complete
5. `parse_card`；pitch 以元话语开头则当格式失败
6. 合法则排除旧书名 / 内容指纹；命中则丢弃，**不再为「换一本」加采**
7. 否则打成卡片返回

格式失败：丢掉本次文本，**不把失败稿送回模型编辑**，再跑步骤 2–5，最多 `_SLOT_RETRIES=1`。失败的 A 永远不会变成 A2。

### 5.2 两个 sample

`asyncio.gather(c01, c02)`。两路并行、互不可见。

汇合后再按 title / pitch 指纹去重。槽位名 `c01`/`c02` **不是作品身份**：旧池若把 `id` 写成 `c01`，不得把新采样整槽扔掉。排除只看书名和内容指纹。

常数：

| 名 | 值 | 含义 |
|----|----|------|
| `_SAMPLE_POOL` | 2 | 每次只采两本 |
| `_SLOT_RETRIES` | 1 | 每槽格式失败再试 1 次 |
| `_FORM_MAX_OUTPUT_TOKENS` | 1024 | child 输出上限 |
| `_FORM_THINK_CHAR_BUDGET` | 4000 | 思考字符预算，超了且尚无正文则 abort |
| pitch clip | 800 字 | 解析后裁切 |
| title | 2–16 字 | 解析硬门槛 |

### 5.3 Child 生成参数

`scenario_id=None`：不继承 writing 场景温度 / 主 system。

- `thinking_enabled=False`
- `reasoning_effort=none`（DeepSeek 会显式 `thinking: disabled`，否则默认思考模式不能强制 `tool_choice`）
- `tool_choice=none`（随后由 `response_schema` 覆盖成结构化约束）
- `response_schema=CANDIDATE_SCHEMA`

### 5.4 结构化输出（不要靠「请输出 JSON」）

`GenerationParams.response_schema` → `apply_response_schema`：

| 族 | 约束 |
|----|------|
| OpenAI / gpt-5 | `response_format.json_schema`，name `book_candidate`，`strict` |
| DeepSeek | 强制函数 `book_candidate`，parameters 即该 schema |
| Anthropic | 强制工具 `book_candidate`，`input_schema` 即该 schema |

DeepSeek 若 400「Thinking mode does not support this tool_choice」，兼容层补 `thinking: disabled` 再试。`json_schema` 不被吃时，降级为强制函数，**不剥成自由生成**。

Child 流结束时：优先从 `tool_calls[].input` 取对象，否则用文本里的 JSON。

---

## 6. 提示词（三套，职责不同）

### 6.1 Parent system（`scenarios/writing/system.md`）

主模型仍拿完整 writing system。立意相关只有 WORK STATE / TOOLS 里几句，用来 **禁止它自己编候选、禁止把草稿状态带进构思**：

> 用户只给题材或说「看看」时，进入作品候选阶段。  
> 这一阶段只负责产生若干个新的作品候选，不写第一章，不进入 opening / outline / draft，也不要把当前章节、story_state、author_state 或其他写作状态带入候选构思。  
> 调用 `propose_book_candidates` 时不要自己编候选。工具会为每个候选建立独立的最小上下文并分别采样；每次采样只产生一个候选，不进行候选之间的比较、连续 brainstorm 或二次创作。  
> 候选只是一个大概成立、值得继续发展的作品概貌。形成后立即停止，由后续选择阶段负责判断。  
> 候选的 `pitch` 是书页入口，不是第一章开头。

TOOLS：

> 只给题材或说看看 → `propose_book_candidates`（工具内部两本独立采样，交两张书页简介；卡片是交卷，不要写进聊天；停下来等用户点选或说「我要其他的」）

Parent 不负责「写出一本优秀的都市修真」。它只负责调用工具。

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

`work_reconstruction.form_messages`。**不**继承 writing system，**不**带 `opening_choice`，**不**带旧卡。

System：

```
根据题材直接生成一个小说候选。

只交一个结果，不需要寻找更好的方向。
```

User：

```
题材：{genre}
```

`genre` 由投影函数从用户话里抽出。例：`写一篇长篇都市修真小说` → `都市修真`。

故意不写的：

- 「请输出 JSON」——由 `response_schema` 约束
- 「想到一个成立的方向就直接写」——「方向」会诱发搜索与比较
- 「看起来像一本可以认真写下去的小说」——会被读成优化到足够优秀
- 质量、套路、连载潜力、与另一张卡比较

Child 的工作是：题材 → 随手产一个对象。不是：研究都市修真 → 比较创意 → 交卷。

---

## 7. 上下文投影

`project_candidate_context`：只返回 `{genre, fresh_work=True}`。

不读、不注入：

- `writing_context` / `focus=ch1` / `outline_phase` / `plot_progress`
- `outline.md`、draft、manuscript
- `story_state`、`author_state`
- 上一组卡片、拒池正文
- 长篇 / 网文 / 工作模式标签（除了从用户句里剥题材时用到的「长篇」前缀）

抽取规则（`genre_label`）：去掉「请/帮我/写一篇/写一本/写一章/写部」「长篇」「小说/网文」外壳，剩下的当题材。空则回退整句，再空则默认 `都市修真`。

两路 child 拿到的 user 正文相同（同一题材），messages 实例各自独立，所以不是「一次 brainstorm 切两段」。

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

Handler 只接受能解析成这个形状的结果。卡片落盘时 `pitch` 同时写入 `opening`（UI / 旧字段兼容）。`flavor` 解析器仍认，live 不再要求模型填。

### 8.2 解析

`parse_card`：JSON 对象（含 fence）优先；否则 `title:` / `书名:` / `pitch:` / `简介:` 行。书名长度不在 2–16、或没有简介 → `None`。

`obvious_meta_text`：pitch 以「我觉得 / 我先 / 首先 / 分析：/ 先比较…」开头 → 当格式失败。这是「这是在分析，不是候选」，不是文学评分。

### 8.3 排除旧卡

`load_candidate_excludes`：当前 `opening_ponds.json` + `opening_ponds_rejected.jsonl`。

排除键：书名（casefold）、pitch 指纹、title+pitch 指纹。槽位 id `c01`/`c02` 不进入排除集。

`我要其他的`：先把当前组 `append_rejected_ponds`，再采新的两本。新采样看不到旧卡正文，只在交卷后按指纹/书名丢掉撞车项。

不够两张：直接停，不因为「内容不够好」再想一轮。

---

## 9. 落盘与 UI

成功路径 `save_opening_ponds` → `.agent/work/opening_ponds.json`。每张卡 `append_pond_fingerprint` 进 ledger。

前端 picker 吃 `items[].title` + `items[].pitch`（或 `opening`）。Parent 被要求不要把两张卡抄进聊天。

点选之后才进入 opening / 第一章。那是另一条链：committed pond、大纲这一段写入书名和简介、`SERIAL_AFTER_LOCK_CRAFT` 等。立意 child 看不到那些块。

---

## 10. 职责边界（刻意不放进 child）

| 事情 | 谁做 |
|------|------|
| 要不要进入选书 | `wants_opening_candidates` |
| 采几本 | handler，`N=2` |
| 何时停 | sample job 结束；不是模型「想够了」 |
| 对象形状 | `response_schema` + parser |
| 好不好、模板、值不值得写 | 用户点选；以后若有 selector 也在 handler 之后 |
| 第一章怎么开 | 点选后的章，不在立意 child |
| 旧卡不要再出现 | 指纹/书名硬排除，不靠 prompt 黑名单 |

---

## 11. 文件地图

| 文件 | 职责 |
|------|------|
| `app/scenarios/writing/system.md` | Parent：何时调工具、不要自己编 |
| `app/scenarios/writing/templates/opening_choice.md` | Parent volatile：空调用、空助手消息 |
| `app/tools/bootstrap.py` | 工具 schema / 选书相位白名单 |
| `app/tools/core/writing_tools.py` | `propose_book_candidates` live/stub 分流 |
| `app/writing/outline_phase.py` | `wants_opening_candidates`；开写 note |
| `app/writing/opening_ponds.py` | 闸工具、volatile 块、normalize、落盘、`我要其他的` |
| `app/writing/work_reconstruction.py` | 题材投影、child prompt、schema、解析 |
| `app/writing/candidate_sample.py` | 两个原子 sample、gather、格式重试 |
| `app/writing/pond_history.py` | 拒池、排除集 |
| `app/model/generation.py` | `response_schema`、DeepSeek thinking/tool 兼容 |
| `app/engine/agent_engine.py` | awaiting_choice / stop_retry 结束 Turn |

核对时以这些文件为准。旧文里的「开篇第一段 + excerpt 五类硬拒 + 标题 2-gram 必须出现在正文」属于 **stub / 点选后章** 的另一套卫生，不是当前 live 立意 child 的交卷合同。
