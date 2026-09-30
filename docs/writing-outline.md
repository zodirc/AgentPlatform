# 产生大纲

长篇大纲不是第二条推理循环，也不是模型在聊天里交的一份稿。它是 Work 根上的 `outline.md`：点选时机械种入书名和简介，随后由 `update_outline` 写成章段，写完这一轮就停。短篇和单篇不走这条链，直接 `draft_section`。

`structural/outline.py` 是另一件事：长文件被截断时抽出标题，供模型跳读。它不写 `outline.md`。

引擎仍不读 scenario 名字。差在工具白名单、volatile 文案和 `update_outline` 的返回值。

## 文件

| 职责 | 路径 |
|------|------|
| 相位谓词（选书 / 等人写纲 / 章职够不够） | `writing/turn_phase.py` |
| 相位标签 `open` / `ready` / `continue` | `writing/outline_phase.py` |
| 纲的形状与软事实 | `writing/outline_arc.py` |
| 薄纲（章段可见字 &lt; 80） | `writing/text_metrics.py` |
| 落盘 | `tools/core/writing_tools.py` 的 `update_outline` |
| 本 Turn 只留哪些工具 | `tools/bootstrap.py` 的 `tool_scope` |
| 点选令牌种入「这本书」 | `writing/opening_ponds.py` 的 `seed_outline_from_pond` |
| 点选后灌给模型的句子 | `writing/pond_prompts.py` · `writing/cards.py` |
| 写完停转 | `engine/agent_engine.py`（`outline_awaiting_direction`） |
| 成章前硬拒 | `draft_section` 调用 `draft_need_outline_error` / `draft_need_chapter_job_error` |
| 耐久事件 | `outline.updated`（path / content / summary / mode） |

场景提示在 `scenarios/writing/system.md`：规划写入大纲；短篇不必先订纲。

## 三条相位

`turn_phase.snapshot` 在 Turn 开头读用户消息和磁盘上的 `outline.md`。工具白名单用它；`draft_section` 也用它。

```text
长篇？
  否  short / single → outline_phase=ready，纲可选，不闸工具
  是
    还在选书（picking）→ 只留 propose_book_candidates，交卡片后 TERMINATE
    还没有正文，也没有章职，也不是中途续写
      且本轮没有「写第一章 / 开始写 / 成章」
        → outline_wait：只留 update_outline 与 read_file
    否则 → 写作工具仍在；但没有章职时 draft_section 会被 need_outline 拒绝
```

`picking` 为真的条件：尺度是长篇，还没有已选书，大纲里还没有章职，用户没有点名主角或风格。用户说「看看 / 发散 / 几种 / 换个开 / 我要其他的 / 都不合适」时，即使风格段已经写上，仍回到选书。

白名单优先级：Plan `planning` &gt; 选书 &gt; `outline_wait` &gt; 编辑 &gt; 回读。`outline_wait` 在 Controller 组工具时就算好，不随本轮后来写入的纲改口。

`resolve_outline_phase` 只给 spec 一个词（`outline_phase: open|ready|continue`）。说明句函数 `outline_phase_spec_line` 没有调用方。

## 点选只种书名，不生成章段

用户勾选卡片后，下一回合的消息是令牌 `采用此开篇「书名」`（`format_select_pond_message`）。聊天不画这条气泡。

组窗时 `format_committed_pond_block` 调用 `find_committed_pond`。对上书名就 `save_committed_pond`，副作用三件：

1. 已选书写入 sidecar。
2. `seed_identity_from_pond` 写入 `story_state`。
3. `seed_outline_from_pond` 把 `## 这本书`、书名、简介写入 `outline.md`。文件本为空时再附一行 `## 主线一句话` 占位。不写世界入口，不写章段。

同一块 volatile 告诉模型：简介不是正文；用 `update_outline` 的 `documents` 一次提交作品纲（核心处境、叙事承诺、长程边界，不抄简介）、卷问题，以及第一章便条；写完停。远处不排章节。discovery 可以不写卷内节点。

层模板（`outline_arc._OUTLINE_LAYER_TEMPLATE`）不在这一步灌入。它挂在 `update_outline` 的返回值上，近池身份还没立定、或第一章章段还缺时，以 `style_contract_template` / `opening_trilogy_template` 交回模型。模板要求的段是：这本书、世界入口、当前阶段、远处、近处（章节作用 + 当前章段，通常一百二十到二百五十字）。

## `update_outline` 写什么

路径固定 `outline.md`。`mode=replace` 或 `append`。`occupy=fresh` 时先把已占用稿归档到 `drafts/archive/`，再整文件替换。

硬拒绝只有一条：旧文不少于 500 字，且新文短于 `max(200, 旧文×0.4)`，又没有 `force=true`。这时不落盘。

其余都落盘，再把软事实贴进 `summary`（模型看得见；不因此拒绝写入）：

| 事实 | 条件 | 作用 |
|------|------|------|
| `outline_thin` | 某章标题下可见字 &lt; 80，且用户没说只要目录 | 点明太薄 |
| 开篇备忘 | 长篇且第一章当前章段不足 16 字 | 附层模板 |
| 近池未立 | 「这本书」段还不是书名/简介 | 附层模板 |
| 编排 | 主线、顶点、开篇写进结局、章首是机构专名 | 句子，不拒 |
| `outline_over_planned` | 至少 3 章已经写死具体事件，卷问题还没定 | 只观测 |
| `style.lock` | 契约够长且长篇有主线痕迹，或近池已立 | 写入 `writing/style.lock`；不够则删掉旧锁 |

用户说「只要目录 / 标题列表 / 短纲」时，薄纲和开篇备忘都不记。

带 `volume` 参数时，把 `## 卷 N` 并进纲，并 `sync_volume_patch` 到 `story_state`。

## 写完就停

`should_await_outline_direction`：长篇、还没有正文、不在选书、本轮没有成章意图，并且纲里已经有章职。`update_outline` 成功时设 `awaiting_direction`。Engine 见到它就 `TERMINATE`，`termination_reason=outline_awaiting_direction`。同一轮不会接着 `draft_section`。

章职的判定（`has_chapter_jobs`）：标题像 `ch1` 或「第 N 章」，且不是「这本书 / 主线 / 世界入口 / 当前阶段 / 远处」。去掉「往哪走即可」这类占位后，可见字不少于 16。点选种下的「这本书」和「主线一句话」不算章职，所以种入之后这一轮仍然是写纲轮。

本轮用户已经说「写第一章 / 开始写 / 成章」，或纲已在且只回「继续 / 好 / 开始写」时，`write_intent` 为真：不设 `awaiting_direction`，工具白名单也不收成只剩大纲。`draft_section` 仍可能因下面两道门失败，模型可以先补纲再写正文。

## 成章前的两道硬门

`draft_section` 开头：

1. `need_outline`：长篇、无正文、无章职、不是中途续写。摘要要求先 `update_outline` 写下这一章的事实。
2. `need_chapter_job`：要新开的那一章，其可见字 &lt; 80（`OUTLINE_MIN_VISIBLE`）。这只说明便条还没有写出来，不说明便条合格。

下一章且 `mode=append` 另有 `next_chapter_not_append`，与大纲形状无关。

## 写完之后大纲怎么被用

写作包（`writing_pack.py`）只投影眼前要写的事：核心处境与叙事承诺、当前卷问题、当前章便条、上一章经证据确认的结果、后一章若写了「依赖」则只给一句。`planned` 才多带卷内「关键依赖」。候选简介、世界入口和远处阶段不进包。

spec 用章段推断章职和 `outline_phase`，整段说明不超过 620 字。另起一篇时旧纲不进本轮 spec。

耐久事件 `outline.updated` 带 path、content（截断）、summary、mode。分层写入另带 `changed_files`（path、scope，以及章 id 或卷号）。`awaiting_direction` 和软事实留在当轮 `tool_result`。

## 分层文件

旧的 `content` 仍只写 `outline.md`。`documents` 或 `scope` 才写入：

```text
outline.md
volumes/volume-001.md
chapters/ch-001.md
```

读取走 `outline_store.project_outline`。首次显式使用分层合同时，旧纲里的章段才惰性迁到 `chapters/`；平时不自动改旧 Work。候选简介不再进入写作包；包里要有「核心处境 / 叙事承诺」才带作品级句子。章结果只有证据能在正文里对上才进 `canon_facts.json`。

候选形成采用有界搜索：先在一个短响应里同时铺开四个作品方向（像书城并列开书那样各有卖点），再用只看单个方向的全新 messages 把四个方向分别写成候选卡，最后根据成文结果选择至多两个。候选卡停留在商业网文书页级的泛化简介。成文用正例条件化下一 token，拉向书页口吻；终审后若两本骨架过近，会从已成文卡中改挑差异更大的一对。内部长 thinking 关闭；短方向不展示给用户。

宽泛题材先按读者通常理解校准，不把城市职业、设施、行政登记或合同整体魔法化来冒充题材创新；也不强制深刻议题、亲属创伤、自我牺牲或代价公式。成文后“是……还是……”与过细梗概只进入软亲和度排序；终审仍可少选或不选。不足两本时只启动一次完全独立的第二轮搜索，不把拒绝意见送回旧卡修补。对象级静态题材参照池保持关闭。

设置页可以为 `writing / book_candidates` 单独选择一份已保存的模型配置；未选择、配置失效或配置被删除时，安全继承当前 active 模型。方向搜索、方向筛选和候选成文共同走该路由，shadow 评委仍走当前模型，以免无意放大调用成本。这个路由解决的是能力分工，不承诺仅靠换模型消除套路化；候选质量仍须用固定题材集和人工盲评判断。

## 不在这条链上

- `should_inject_diverge_styles` 恒为假。题材发散不再灌进组窗。
- `work_mode.format_after_lock_craft_block` 没有调用方。点选后的句子以 `pond_prompts.format_committed_pond_block` 和 `cards.py` 那一行为准。
- 账户 `writing_account_prefs` 不参与大纲。
