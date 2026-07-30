# 34 — 读文件降本与缓存优化方案（速率安全）

> **状态**：✅ RC1–RC5 + Web「已跳过」已落地（2026-07-26）；RC6 守线复测仍建议定期做。  
> **触发**：Agent 场景长 Turn（如 `2048.html` 检查优化）累计 **in≈1.2M**，结束窗口仅 ~68k；时间线在 `(complete)` 后仍用不同 `offset` 重叠 `read_file`。  
> **目标**：在 **不伤交互速率、不改主循环语义** 的前提下，用 **确定性闸门 + 分层缓存** 砍掉重复读与逐步重传账单。  
> **非目标**：加同步 LLM judge / 预分类模型；改工具对外参数形状；把 Ops / 审计塞进工作台热路径。

关联：[13](../core/13-rate-redlines.md)（R1–R5）· [06](../core/06-tools-and-context.md) · [12](../core/12-model-harness.md) §5.1（prompt cache）· [20](../learn/context-compaction-walkthrough.md) · [21](../learn/agent-system-qa.md)（读契约 / soft ban）· [24](writing/token-economy.md) WT5 · [33](../archive/33-harness-maturity-backlog.md) HM1/HM6 · [30](../archive/30-quality-and-agility.md)。

证据备忘：工作区 `TEST.log`（工具时间线 · 压缩 · 累计 in/out）与提供商日用量差分（cache hit/miss · output）。

---

## 0.1 流程图（详图）

路径：[`docs/assets/tools/read-file-tokenize-flow-zh.png`](../assets/tools/read-file-tokenize-flow-zh.png)

![读文件降本：硬闸 · 折叠 · 已跳过](../assets/tools/read-file-tokenize-flow-zh.png)

**读图要点：**

| | |
|--|--|
| **易混** | Intake `@` prereread ≠ 本图；本图是 loop 内 `read_file` 硬闸 |
| **硬闸** | `read_after_complete` / `read_overlap` / 次数上限 → `skipped`（不读盘） |
| **豁免** | edit 失败后允许再读 |
| **折叠** | assemble 侧旧 read 结果指针化（RC4） |
| **UX** | `status=skipped` → Web「已跳过」；模型侧非 error |

---

## 0.5 落地结论与实测（2026-07-26）

### 做了什么

| 层 | 内容 |
|----|------|
| **RC1 / RC3** | Turn 内 `read_registry`：整文件 complete 后再读 → `read_after_complete`；行区间已覆盖 → `read_overlap`；**0 次磁盘 I/O** |
| **RC2** | `(complete)` 仅当从 offset=1 读到 EOF；否则 `(eof_from_offset)` + `whole_file_complete=false` |
| **RC4** | assemble 对旧 `read_file` 结果折叠为指针（`_fold_stale_read_file_results` / `read_fold`） |
| **RC5** | `read_file_max_per_turn` 默认 16 |
| **UX** | 策略拒绝发 `tool.completed.status=skipped`（非 `error`）；Web 显示「已跳过」中性样式；模型侧 `is_error=false` + 中文 summary / 英文 hint |
| **持久化** | checkpoint 序列化 `read_registry` |

### 手测对照（同场景：2048 审改）

| 阶段 | 时间线特征 | 面板累计 in（provider） | 结束窗口 | 备注 |
|------|------------|-------------------------|----------|------|
| **优化前** | ~19 步，`(complete)` 后仍多 offset 重叠读 | **≈1.2M** | ~68k / 128k | Soft ban 拦不住 |
| **RC 后 · 续写/优化 Turn** | 1×完整读 + **2×已跳过** + 多 `edit_file` + lint/grep | **≈267k** · out≈17k | **28k / 128k（25%）** | 闸门命中；UI 非红字 |
| **同段提供商日账单差分** | — | 计费输入 **≈78k**（命中缓存 ≈33k / 未命中 ≈45k）+ 输出 ≈5.7k → 合计 **≈84k** | — | 面板 Σ(prompt) ≠ 控制台计费；对照时两边口径分开看 |

**结论（可对外说）：**

1. **硬闸有效**：complete 后再 `read_file` 不再灌 content；时间线可见「已跳过」。  
2. **窗口健康**：结束占用从「小窗大账单」里的 ~68k 进一步压到 **~28k**，且步数可控（约 10 步完成审改）。  
3. **账单量级下降一个数量级**：同任务从 **百万级 in** 落到 **十万级面板 / 更低计费差分**（具体以提供商为准）。  
4. **速率红线未破**：闸门为内存查找；拒绝路径快于读盘；无同步 LLM judge。  
5. **仍须注意**：面板「本回合累计 in」偏发送体积累加；日缓存命中率（RC6）看全天 L0，不单看本 Turn；校验命令失败时模型仍可能 `completed`（质量闸，非本票范围）。

### 关键落点（代码）

| 模块 | 路径 |
|------|------|
| Registry / 文案 | `services/runtime/app/engine/read_registry.py` |
| 闸门 | `services/runtime/app/engine/agent_engine.py` |
| 折叠 | `services/runtime/app/context/engine.py` |
| 事件契约 | `packages/contracts/schemas/events/payloads/tool.completed.json`（`skipped` + `policy`） |
| 投影 | `services/api/app/services/projection/projector.py` |
| Web | `AgentTimelinePanel.tsx` · `AgentChatPanel.tsx` |
| 单测 | `services/runtime/tests/test_read_registry.py` |

---

## 0. 原则与准入（必须同时满足）

与 [33](../archive/33-harness-maturity-backlog.md) §0、[31](sandbox.md) 同构：

### 0.1 不影响交互逻辑

| 允许 | 禁止 |
|------|------|
| Turn 内对 **违规再读** 返回确定性短错误 / 短提示（工具仍叫 `read_file`） | 改 `AgentEngine` while / 终止条件 / 事件主语义 |
| 修正 summary 中 `(complete)` 的**文档与布尔语义**（仍返回 `truncated`/`next_offset`） | 换一套工具名或强制模型先走另一条「规划工具」 |
| 扩大 **只读工具结果缓存** 命中面（path / 区间覆盖） | 为省 token 取消 `edit_file` 或改审批门 |
| assemble 侧对 **旧** `read_file` 结果更激进截断 / 指针化 | 每步同步再问一轮模型「该不该读」 |

### 0.2 不影响交互速率（R1–R5）

| # | 对本方案的含义 |
|---|----------------|
| **R1** | 读闸门 / 缓存查找 **不得** 推迟 `turn.accepted`；逻辑只在已进入的 tool 执行段 |
| **R2** | **禁止** 为「是否允许再读」加同步 LLM |
| **R3** | 热路径：dict/set 查找、区间覆盖判断、字符串截断 → **μs～ms**；禁止热路径精确 tokenizer / CE / 全文件哈希扫描（大文件哈希仅在首次读时可选、可预算） |
| **R4** | misuse 计数、Ops 报表、对比评测 → 异步或环外；不挡 tool_result → 下一轮模型 |
| **R5** | 单测：complete 后再读被拒；区间缓存命中；豁免（edit 失败）仍可再读；延迟类有断言或「无额外 await I/O」约束 |

**速率安全默认：** 闸门失败时 **立即返回短 JSON**（不读盘），比「再读一遍磁盘 + 灌 32k content」更快，不伤体感。

---

## 1. 问题拆解（为何窗口小、账单大）

```text
模型换 offset 再读
    → 精确 arguments 缓存 miss（现状）
    → 全量 content 进 state.messages
    → 每步 assemble 再打 provider
    → 累计 input = Σ(各步窗口) ≫ 结束窗口占用
```

| 层 | 现状 | 速率相关？ | Token 相关？ |
|----|------|------------|--------------|
| Soft ban | `system.md` / tool 描述禁止 read-after-complete；[21](../learn/agent-system-qa.md) 曾 **有意不做硬拒** | 否 | 是（拦不住） |
| Tool cache | `_tool_cache_key` = 工具名 + **整份 arguments JSON** | 命中则跳过读盘 → **更快** | 仅相同参数命中 |
| 消息 | `json.dumps(result)` 含全文；assemble 才 `TOOL_RESULT_CHAR_BUDGET≈4k` | 截断在 assemble，CPU 轻 | 近期多份大结果仍贵 |
| 计费 | 逐步 provider round-trip | 步数↑ → 墙钟↑ | 累计 in 爆炸 |
| Prompt cache | HM6 / WT5 稳定前缀分家 | 命中降 TTFT/费用 | miss 时整段重算 |

**结论：** 主损在 **「可执行的重复读 + 逐步重传」**，不是 TTFB 前的额外逻辑。优化应优先 **少执行、少灌、少步**，且闸门本身要比读盘更便宜。

---

## 2. 缓存分层（本方案核心视角）

把「缓存」拆成四层，避免混谈：

| 层 | 名称 | 作用域 | 命中时做什么 | 对速率 | 对 Token |
|----|------|--------|--------------|--------|----------|
| **L0** | Provider prompt cache | 跨请求前缀 | 提供商跳过前缀计费/计算 | 常降 TTFT | 降 input 费用 |
| **L1** | Turn 内只读工具结果缓存 | 单 Turn / `AgentEngine` | **不读盘**，复用 JSON | **加快** tool 段 | 避免重复 content 入消息（若仍 append 需配合 L2） |
| **L2** | Assemble 视图缓存 / 截断 | 每步 assemble | 旧 tool_result 只带摘要/指针 | CPU 毫秒级 | 直接砍窗口与逐步账单 |
| **L3** | Session 预压缩缓存 | Turn 间隙（HM1 已有） | 硬路径用缓存摘要 | 不挡 accepted | 长会话 |

**本方案新增重点：加厚 L1（path/区间），并让 L2 对 `read_file` 友好；L0 继续靠 HM6 前缀稳定，不在本票重做。**

---

## 3. 方案总览（速率安全排序）

| ID | 名称 | 杠杆 | 速率影响 | 建议优先级 |
|----|------|------|----------|------------|
| **RC1** | Path 读状态机（硬闸） | 拒绝对已 complete path 的再读 | 负延迟（少 I/O） | **P0** |
| **RC2** | `(complete)` 语义收紧 | 消除假续读 | 无 | **P0** |
| **RC3** | L1 区间覆盖缓存 | 重叠 offset 不读盘、短响应 | 负延迟 | **P0/P1** |
| **RC4** | L2 read 结果指针化 / 更早折叠 | 历史步窗口变瘦 | assemble CPU 可控 | **P1** |
| **RC5** | 每 Turn read 次数/字符预算 | 硬顶 | 负延迟 | **P2** |
| **RC6** | L0 前缀稳定守线 | 提高日缓存命中率 | 降 TTFT（提供商侧） | **P2**（延续 HM6） |
| **RC7** | 再扩 system prompt / 离线 rubric | 软约束 | 涨一点 system tokens | **P3**（不单独当主方案） |

---

## 4. 分票设计

### RC1 — Turn 内 path 读状态机（硬闸）

**动机：** Soft ban 已被 TEST.log 证伪；`search_sources` 已有 per-turn budget 先例。

**行为（确定性）：**

```text
state.read_registry[path] =
  { covered_lines, whole_file_complete, allow_reread_once }

read_file(path, offset, limit):
  if whole_file_complete and not allow_reread_once:
      return status=skipped (not error), policy=read_after_complete:
        short Chinese summary for Web + English hint for the model
      # 不读盘；tool_result is_error=false（避免误当失败重试）
  if allow_reread_once and edit/patch just failed for path:
      consume flag → 允许一次
  else: 正常读 → 更新 registry
```

**豁免（保持可编辑性）：**

- 最近一次对该 path 的 `edit_file` / `propose_patch` / `apply_patch` **失败**（如 `old_text not found`）→ 置 `allow_reread_once`。
- `truncated=true` 且 `offset == next_offset`（真续读）→ 始终允许。

**速率：** 纯内存 dict；拒绝路径 **0 次磁盘 I/O**。  
**逻辑：** 工具名/参数不变；仅结果从「大 content」变为「短 tip」。Web 时间线显示 **已跳过**（非红字 error）。  
**可观测：** `record_tool_misuse(kind="read_after_complete")`；Ops / UX signals 可后续挂接（R4）。

**单测：**

- complete 后再 `read_file(same path, offset=100)` → skipped、无 content。
- edit 失败后允许再读一次，第二次再拒。
- `next_offset` 续读成功。

---

### RC2 — `(complete)` 语义收紧

**现状问题：** `offset>1` 读到 EOF 也标 `(complete)`，模型以为「整文件已在手」。

**提案：**

| 条件 | `truncated` | summary 标记 |
|------|-------------|---------------|
| `offset==1` 且读到文件末且未触字符顶 | `false` | `(complete)` — **整文件** |
| `offset>1` 且读到 EOF | `false` | `(eof_from_offset)` — **非**整文件 complete |
| 未读到 EOF 或触顶 | `true` | `(truncated; next_offset=…)` |

**速率：** 无额外成本（改 summary 字符串）。  
**注意：** 更新 `system.md` / `bootstrap` 描述与 [21](../learn/agent-system-qa.md) 口诀，避免文案与代码分叉；**RC1 以 registry 为准**，不依赖模型理解新词。

---

### RC3 — L1 区间覆盖缓存（缓存优化主票）

**现状：** 只有 **arguments 完全一致** 才命中 → 重叠窗口全部 miss。

**提案（Turn 内）：**

```text
key 主维: normalized_path
value: { mtime_or_size, blob_or_lines_ref, covered: [(start,end), ...] }

新请求窗口 [offset, end]:
  if 窗口 ⊆ 已覆盖 ∪ 且文件未变:
      从内存切片返回（或返回「已覆盖，见先前 tool_call_id=…」短指针）
      标记 _cached=true
  else:
      读盘 → 合并 covered
```

**两种命中响应（选一，推荐 A→B）：**

| 模式 | 返回 | 速率 | Token |
|------|------|------|-------|
| **A 切片复用** | 与真读相同 shape 的 content（从内存切） | 快于读盘 | 仍可能大；需配 RC4 |
| **B 指针拒绝重叠** | 短 JSON：已覆盖行范围 + 请 edit | 最快 | **最优** |

**速率约束：**

- 文件变更检测：优先 `size + mtime`（stat），**不要** 热路径全文件 hash。
- 缓存只活在 **当前 Turn 的 Engine 实例**（与现 `_tool_result_cache` 同生命周期）；不写 Redis、不跨用户。
- 并行只读 batch：registry 更新需简单锁或「先读后合并」（保持现有并行只读语义）。

**与 RC1 关系：** RC1 管「整文件 complete 后禁止」；RC3 管「未标整文件 complete 但行区间已覆盖」的重叠读。可同 PR 落地，测例分开。

---

### RC4 — L2：`read_file` 结果在 assemble 侧降本

**动机：** 即使 L1 少读盘，若历史里已有多份大 content，逐步 Σ 仍贵。

**提案（在现有 budget → microcompact → collapse 管道上增量）：**

1. **识别** `read_file` tool_result（path + 大 `content` 字段）。  
2. **热区**：仅保留 **最近 1～2 次** 该 path 的全文（或最近一次）。  
3. **冷区**：替换为  
   `{"path","offset","end_line","total_lines","summary","content":"[omitted; re-read if edit fails]"}`  
4. 不提高 collapse 阈值依赖；可对 `read_file` **提前** microcompact（填满度 &lt; 0.80 也缩旧读）。

**速率：** 仅字符串替换/截断；禁止在 assemble 同步 LLM（HM1 已否决硬路径 LLM）。  
**验收：** 同剧本 golden：累计 `usage.input_tokens` 下降；`assemble_ms` 不显著变差（R5 对照）。

---

### RC5 — 每 Turn `read_file` 预算（硬顶）

对标 `search_sources_max_per_turn`：

| 设置 | 建议默认 | 说明 |
|------|----------|------|
| `read_file_max_per_turn` | 如 12～20 | 防极端循环；正常 Turn 够用 |
| `read_file_max_chars_per_turn` | 可选 | 按返回 content 累计 |

超限 → 短错误，不读盘。  
**速率：** 计数器 +1。  
**注意：** 预算是安全带，**不能替代** RC1/RC3；否则模型会在限额内把重叠读打满。

---

### RC6 — L0 Prompt cache 守线（延续 HM6 / WT5）

日用量缓存命中偏低时，检查：

- 稳定前缀（system / tools / 少变场景块）是否仍与 transcript 分家。  
- Turn 内是否因「每次 tools 列表或 system 微调」导致前缀打破。  
- Ops envelope（旁路）只读，**不**为省 token 在热路径改工具表顺序（会打 L0）。

本票 **不** 新增热路径逻辑；只在评测与文档中列为「改 RC1–4 后复测 hit rate」。

---

### RC7 — Prompt / rubric（明示降级）

- 可随 RC2 改一句 system 口诀。  
- 离线 `read_thrift` 已有 → 可进 Ops/CI 报表，**不进**热路径裁判。  
- **单独扩写 Ban 列表不作为本里程碑完成标准。**

---

## 5. 推荐落地顺序（1～2 个 PR）

```text
PR-A（P0，速率正收益）
  RC2 语义 + RC1 硬闸 + 单测
  可选：misuse 计数

PR-B（P0/P1，缓存）
  RC3 区间覆盖（先模式 B 短指针，或 A+RC4）
  RC4 assemble 对旧 read 提前折叠
  同一 2048「再优化」剧本：对比累计 in / 步数 / assemble_ms

PR-C（P2，安全带）
  RC5 预算 + 设置项
  RC6 复测提供商 cache hit（文档记录）
```

**对比实验（环外，R4）：**

| 指标 | 基线（TEST.log 类） | 目标 |
|------|---------------------|------|
| 同 path `(complete)` 后再读次数 | ≥4 | 0（或仅 edit 失败豁免） |
| Turn 累计 `input_tokens` | ~1.2M | 数量级下降（先盯 &lt;300k 同任务形态） |
| 结束窗口占用 | ~68k | 不上升 |
| `assemble_ms` / 步墙钟 | 基线 | 不显著变差；拒绝路径应更快 |
| 任务成功 | 可玩 / 可改 | 不回退 |

---

## 6. 有意不做（与速率/交互冲突）

| 做法 | 原因 |
|------|------|
| 同步 LLM「判断是否该再读」 | 打 R2；增延迟 |
| 热路径精确 token 计数后再截断 | 打 R3；已有字符预算足够 |
| 跨 Turn / 跨用户文件内容 Redis 缓存 | 一致性与租户隔离复杂；收益不如 Turn 内 L1 |
| 为降本取消并行只读 batch | 伤墙钟；与「速率优先」相反 |
| 把 Ops 审计页挂进工作台导航 | 与 [29](ops-eval-console.md) 旁路纪律冲突 |

---

## 7. 面试口述（30 秒）

> 我们不是缺 Ban 文案，是缺 **Turn 内读状态机 + 区间缓存**。  
> Soft rule 拦不住换 offset 的重叠读；每步又把大 tool_result 重传，所以窗口 60% 满、累计 input 上百万。  
> 优化服从 R1–R5：闸门是 **内存查找，拒绝时比读盘更快**；缓存分 L0 前缀 / L1 工具结果 / L2 assemble 视图；不做热路径 LLM 裁判。

---

## 8. 文档与代码落点（实施时）

| 项 | 落点 |
|----|------|
| Registry + 闸门 + L1 | `services/runtime/app/engine/agent_engine.py` · `TurnState` |
| summary 语义 | `services/runtime/app/tools/core/tools.py` · `bootstrap.py` · `scenarios/agent/system.md` |
| L2 | `services/runtime/app/context/engine.py` |
| 设置 | `services/runtime/app/settings.py` |
| 单测 | `services/runtime/tests/test_agent_engine.py`（或新建 `test_read_registry.py`） |
| 原理修订 | [21](../learn/agent-system-qa.md)「刻意不做硬拒」→ 改为「RC1 已硬拒；豁免见上」 |

---

## 9. 状态

| 票 | 状态 |
|----|------|
| RC1–RC7 方案 | ✅ 本文 |
| **RC1** 硬闸 | ✅ `deny_redundant_read` / `read_after_complete` → **`skipped`** |
| **RC2** complete 语义 | ✅ `whole_file_complete` / `(eof_from_offset)` |
| **RC3** 区间重叠拒绝 | ✅ `read_overlap`（模式 B） |
| **RC4** assemble 折叠旧 read | ✅ `_fold_stale_read_file_results` · trace `read_fold` |
| **RC5** 每 Turn 预算 | ✅ `read_file_max_per_turn` 默认 16 |
| **UX skipped** | ✅ 契约 + 投影 + Web「已跳过」 |
| **RC6** L0 hit 复测 | 📋 定期对照提供商日用量（无热路径改动） |
| **RC7** prompt/rubric | ✅ 随 RC2 已改 system；离线 rubric 仍不进热路径 |
| 手测结论 | ✅ 见 **§0.5**（1.2M → ~267k 面板 / ~84k 账单差分；窗口 28k） |
| 对比评测剧本 | ⏳ 可再固化为 Ops/golden 环外用例 |
