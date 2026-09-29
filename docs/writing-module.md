# 写作模块：文件索引与空转

导览里的解剖在 `docs/tour/pages/writing-module.html`。目标结构在 [`写作模块-执行方案.md`](写作模块-执行方案.md)：第 2 节是现行差距，第 3 节起是目标，不是第二份实现说明。运行时不读 `docs/writing-chain-snapshot/`。

引擎不读 scenario 名字。写作差在 `scenarios/profiles/writing.yaml`、场景提示和 `app/writing/`。

## 现行数字

| 项 | 现行 |
|----|------|
| 短篇 / 单篇目标 | 2500 / 3500 |
| 长篇章稿 | 3000–5000（`DEFAULT_CHAPTER_MIN/MAX`） |
| `length_short` | 长篇可见字低于 3000，或用户点名 N 字不足 85% |
| 薄纲 | 章纲该章可见字 &lt; 80（`OUTLINE_MIN_VISIBLE`）；用户要目录则跳过 |
| 长篇交付门 | 本章可见字 &lt; 800 才挡「已完成」 |
| `story_state` 进窗 | 作者档 1200 / 严格档 900 |
| 卡片 | 合计 ≤3600；单卡 ≤2000；风格 ≤1800 / 人物 ≤1000 / 情节 ≤600 / 一般 ≤400 |
| 稿面 | `writing_work_surface_max_chars` = 6000 |
| 温度 / 步数 | 0.8 / `max_steps` 40 |

## 十块落到哪里

| 块 | 路径 |
|----|------|
| 场景壳 | `scenarios/profiles/writing.yaml` · `scenarios/writing/system.md` · `scenarios/hooks.py` |
| 稿树 | `writing/book.py` · `writing/occupy.py` · `writing/manuscript.py` |
| 罗盘 | `writing/book_scope.py` · `writing/work_mode.py` · `writing/focus.py` · `writing/writing_pack.py` · `writing/outline_phase.py` |
| 成稿工具 | `tools/core/writing_tools.py` |
| 过程门 | `writing/text_metrics.py` · `writing/delivery_gate.py` · `writing/patch_budget.py` · `writing/patch_hygiene.py` · `writing/commitment.py` |
| L1 评分 | `writing/signals/`（`scorer.py` · `repair.py` · `surface.py`） |
| 开篇点选 | `writing/opening_ponds.py` · `writing/opening.py` |
| 检索特化 | 写作 profile 排除 `seed/intel`；`post_turn` 的 `sources.index_sync` |
| 工作台 | web 作品面板 / signals 弹层；清空走 discard |
| 作品状态 | `writing/story_state.py` · `writing/editor_notes.py` · `writing/author_notes.py` |

稿树在 Work 根，不在 Session：`outline.md`、`drafts/manuscript.md`、`drafts/archive/`、`sources/`、`sources/cards`、`.agent/work/`（`story_state`、`editor_notes`、`author_notes`、`surface`、`manifest`、`patch_budget`）。

## 空转

这些代码还在仓库里，不进产品 Turn 的改稿回路：

- `writing/narrative/`（含 `judge.py`）只供 L2 报告和测试。评委不进 Turn。
- `writing/signals/prefs_store.py` 的 `load_account_prefs` 没有调用方。账户表 `writing_account_prefs` 没有产品入口，评分不读。
- `outline_phase.should_inject_diverge_styles` 恒为假。C0 题材发散块不再注入。
- `writing/signals/` 仍计算 `net_signal`。L1 分数焊在 `tool_result`，奖励只观测；同轮修补只对过程 L0 或 `length_short`。
