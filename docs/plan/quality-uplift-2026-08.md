# 方案：三线质量提升（Coding / Retrieval / Context）

> **状态（2026-08-15）**：批 1–3 **代码已落地** · R-5 仍关 · INDEX 13 第2轮冒烟已对照 · **不升 SCORECARD 主栏**  
> **第2轮冒烟**（对照第1轮 INDEX 12 · 2026-08-15 12:14–13:01 CST）：coding resolve 仍 0.6 · C-MTEB nDCG@10 0.643→0.696 · **BEIR R@100 0.530→0.495（第一验收位未过）** · LongBench F1 0.558→0.456 / **EM 0.30→0**  
> **基线**：`eval/official/baseline/RESULTS.md`（第1轮 INDEX 12 · 2026-08-15 12:14–13:01 CST：coding resolve 0.6 · BEIR ndcg@10 0.4547 · LongBench agent_f1 0.5579）  
> **姊妹**：[Coding 结构智能](coding-structural-intelligence.md)（轨道 M/T/Q/L 承接）· [工作区异步 AST](agent-workspace-ast-index.md)  
> **硬原则**：不改 AgentEngine while；不新增模型必须学会的工具名；**所有改动不得进 StartTurn / assemble 热路径加重活**（速率红线 R1–R5）；成熟参照优先（Cursor / Anthropic contextual retrieval / SWE-agent / OpenHands 已验证做法）

---

## 0. 一句话

**三线的主要瓶颈都不在「再造一个索引」：coding 缺的是验证信号回灌（test_summary=0）与执行环纪律；retrieval 缺的是 chunk 预算与 embedding 截断（4000 字符 vs 512 token）的对齐；context 缺的是长文导航（markdown 无 outline）与证据保留（旧读窗被整体 fold 掉）。全部改动落在索引期 / 组装期 / 结果契约，不碰交互逻辑与交互速率。**

---

## 1. 基线读数与归因总表

以下归因均已对照代码核实（锚点见各节），非推测。

| 线 | 关键读数（第1轮 · 2026-08-15 12:14–13:01 CST · smoke） | 主因定位 | 结论 |
|----|------------------------------|----------|------|
| coding | resolve 0.6（3/5 同题稳态）；`file_hit=1.0`；`n_testish=50` 而 `test_summary_attach_rate=0`；`edit_related_tests_coverage=0.22`；`locate_fuse_ok≈0.42`（P15 修后自 0.17 回升）、`definition_null=0` | **修复正确性 + 验证信号弱**；执行环（pager / update_plan）拖时长 | **不是 AST/LSP/CST 的锅**（见 §2.1） |
| retrieval (BEIR) | ndcg@10 0.4547；**recall@100 仅 0.5296**（召回天花板压死一切重排） | chunk 4000 **字符**滑窗硬切 vs bge-m3 **512 token** 截断（INDEX 12）→ 向量只代表 chunk 前 1/3 不到；标题只认 H1–H3；宽表 detach 后单元格不可检 | **chunk 切分确实不好**，用户观测成立（见 §3.1） |
| context (LongBench) | agent_f1 0.5579 / em 0.30（gap 大） | `passage.md` 截断**无 outline**（outline 仅认 .py）；同 path 旧读窗被 fold 成 `[omitted]`、非最新 tool_result 砍 4k → 早期证据丢失；终答冗长伤 EM | 组装策略与长文导航问题，非模型能力问题（见 §4.1） |

另：三线样本量均为 smoke（BEIR n=20 / LongBench 60 / SWE n5），**本表数字只用于归因方向，不作效果结论**；效果验收一律按 §6 放大后对照。

---

## 2. 轨道 C — 编码质量

### 2.1 先回答「是不是 AST / LSP / CST 需要优化」

| 证据 | 读数 / 代码锚点 | 推论 |
|------|-----------------|------|
| 找文件从不失手 | `file_hit_rate=1.0`（历史多跑一致） | 定位不是 resolve 瓶颈 |
| Locate 调用占比极低 | 工具账 <3%（`7f235e7c` 复核） | 即使 fuse 全绿也救不动 resolve |
| P15 修后结构车道已回正 | `fuse_ok` 0.17→0.42；`definition_null=0`；`lsp_failed/timeout=0` | 剩余 `no_ws_symbol` 9/12 多为 **P16 结构边界**（模块 stem / 形参这类非定义名，defs-only 索引本就答不了） |
| 失败题失败在测试 | 14182 / 14365 均 `patch_not_resolved`（F2P 未过），非 no_patch / patch_no_apply | 瓶颈在**修复逻辑正确性**与**改完是否知道错在哪** |

**结论：不做 CST、不做 call-graph、不扩全仓 LSP indexing（维持姊妹文否决）。** AST/LSP 只做两个低成本收尾（§2.3 C-5/C-6）。真正的抓手是把「测试失败的结构化事实」焊回模型上下文——这正是当前完全断掉的一环。

### 2.2 主打项（按优先级）

#### C-1 · test_summary 解析修复（最高优先级，直接打 Q2）

现状：`n_testish_tool=50` 但 `n_test_summary=0`。代码核实（`structural/test_summary.py`）：`_parse_pytest` 要求输出里存在 pytest 尾行 `===== … =====` 且含 passed/failed 计数，否则**静默不挂字段**。三个现实杀手：

1. 模型常写 `pytest … | tail -20` / `| head`，footer 可能被管道吃掉或位置漂移；
2. `run_shell_command` 输出截断（`MAX_OUTPUT_CHARS=32000`）截头留尾或截尾丢 footer；
3. `pytest -q` / unittest 的短格式不匹配现有正则。

方案（全部在工具结果契约内，不动交互）：

| 步 | 做法 |
|----|------|
| a | **全量输出旁路解析**：`run_shell_command` 把完整 stdout/stderr 落临时文件（已有输出捕获，只加落盘），`attach_test_summary_for_run_command` 改从**未截断全文**解析，进上下文的仍是截断文本。解析在结果构造期、单次 regex 扫描，不加热路径 |
| b | **解析器扩容**：支持 `-q` 短摘要（`N passed, M failed in …s`）、unittest（`FAILED (failures=N)`）、`ERRORS` 段；failure 首条带 `test_id + assert 摘要`（≤400 字符，已有 `max_failures` 参数） |
| c | **失败回灌**（原 H2 的具体化）：`test_summary.failures[0]` 以固定小节写进 tool_result（模型无法绕开的位置），W9 交卷回执要求引用同一失败首条；不新增工具名 |

出口：`test_summary_attach_rate ≥ 0.6`（testish 命令中有 pytest/unittest 输出者）；失败题事件流里可见「失败测试 → 下一轮编辑」的因果链。

#### C-2 · W2 pager→read_file 硬重定向（打 Q1 时长，欠账落地）

现状核实：`misc_tools.run_command` **无任何拦截**，只有工具描述与 system.md 的软文案；`7f235e7c` 中 pager 类命令每题 13–35 条。方案照抄已验证的 grep→Locate 揉合手法：

- 纯 pager 整条命令（`sed -n 'a,bp' f` / `head -n N f` / `tail -n N f` / `cat f` / `nl f`，单文件、无管道、无重定向、无副作用）→ 内部转 `read_file(path, offset, limit)`，结果带 `redirected_from="run_command"`；
- 含管道 / 通配 / 写副作用 → 原样执行，绝不猜；
- 同步修探针口径：`n_pager_run_command` 与 turn 命令文本分类对齐（现在恒 0，是 reserved 字段）。

出口：pager 重定向命中数 > 0 且 `run_command` 工具占比下降；同题墙钟对照下降。

#### C-3 · update_plan 事件预算（打 Q1）

现状：软纪律，无配额，占 15–26% 工具事件。方案：在 `update_plan` 结果构造处做**幂等去抖**——items 状态与上次完全相同则返回 `unchanged=true` 且不落新事件（引擎不感知，事件层薄改）；system.md 补一句「仅状态变化时更新」。不做硬配额（会顶撞模型已有习惯，违反交互逻辑红线）。

#### C-4 · related_tests 覆盖提升（辅助 C-1）

现状：coverage 0.22 但 adoption 0.75——**给了就用，问题是给得太少**。`related_tests_for_path` 只有 `test_{stem}*.py` 命名 + import 反查两招。低成本扩容：

- 命名规则补 `{stem}_test.py`、`tests/test_{package}.py`、同名目录 `tests/{module}/`；
- import 反查现依赖 AST 索引 `lookup_importers`——评测已默认 `wait_ready=true`，把反查从「有余量才做」提为必做；
- 对 astropy 这类大仓，按**包路径就近**排序（同包 tests 优先于顶层 tests）。

出口：`edit_related_tests_coverage ≥ 0.5`，adoption 维持 ≥0.7。

### 2.3 结构车道收尾（小步，不承诺 resolve）

| 项 | 做法 | 说明 |
|----|------|------|
| C-5 AST 索引扩到顶层赋值 | `parse.py` `_KIND_BY_NODE` 增加模块级 `assignment`（常量 / 单例 / TypeAlias），kind=`variable` | ctags 同样收录；直接消一部分 P16 的 `no_ws` 桶；索引体积增量小、仍 defs-only |
| C-6 P16 分桶显式化 | Locate 对「模块 stem / 点分包名」这类查询，`fuse_fail_reason` 单列 `non_definition_query`，与真故障分开 | 让 `locate_fuse_ok_rate` 不再被结构边界稀释，可证伪性更好 |

维持不做：CST、call-graph、references 入索引、全仓 LSP indexing（理由与姊妹文 §0 一致：权威在 LSP，索引只买粗筛）。

---

## 3. 轨道 R — 检索质量

### 3.1 已核实的切分缺陷（用户观测成立）

实现锚点：`services/runtime/app/retrieval/chunking.py`；默认 `retrieval_chunk_max_chars=4000` / `overlap=400`（`settings.py:77-82`）。

| # | 缺陷 | 代码证据 | 危害 |
|---|------|----------|------|
| D1 | **chunk 预算与 embedding 截断严重错配**：chunk 按 4000 **字符**切，bge-m3 在 INDEX 12 下 `max_seq≈512` **token** 截断 | `_chunk_limits` + `embedder.py effective_index_version`（注释明言 12 = truncate 512） | 英文 4000 字符 ≈ 900–1000 token → **向量只代表 chunk 前一半不到**；chunk 尾部内容「存在于库里但不存在于向量空间」→ 直接解释 recall@100 只有 0.53 |
| D2 | 超长 section **任意字符位硬切**，无句子 / 换行 / 词边界 | `_split_oversized`（chunking.py:268-279）：`text[start:end]` | 句子、代码语句、URL 被拦腰切断；overlap 400 也是字符回溯，不保证语义完整 |
| D3 | 标题只认 `#`–`###` | `HEADER_RE`（chunking.py:12） | H4+ 长文、Setext 标题、无标题纯段落文档整体成一个巨 leaf，再被 D2 硬切 |
| D4 | 宽表 detach 成 pointer（≥6 行或 ≥800 字符） | `detach_wide_tables` | 表格单元格内容**完全不可检索**，只剩表头词 |
| D5 | oversized 子块 `line_start` 恒等于 section 起点 | `chunk_source_text`（:597-607） | 命中后引用行号错误，下游读定位失真 |
| D6 | 注释写「≈2000 token」实际是 4000 char | settings.py:77 注释 | 配置语义漂移，中英文预算含义完全不同（CJK 1 char≈1 token，英文 ≈4 char/token） |

另核实：embedding 无 query/passage instruction（bge-m3 本身 instruction-free，**这点不是问题**）；hybrid = 向量 ∥ BM25 → RRF → 词法 rerank，cross-encoder 默认关；bge-m3 sparse/ColBERT 未用（§3.3 定为暂缓）。

### 3.2 方案（全部落在异步索引期，零热路径影响）

#### R-1 · token 对齐的 chunk 预算（主打，直接抬 recall）

- 索引期用**真实 tokenizer 计数**（bge-m3 tokenizer 已随模型在容器内；chunking 本就声明 async-only，不在热路径），chunk 预算改为 **`retrieval_chunk_max_tokens=450`**（≤512 留 headroom），overlap **64 token**；
- 保留 char 上限作 tokenizer 不可用时的回退（en≈1800 char / 自动按 CJK 占比折算）；
- **INDEX 版本 bump（12→13）**，全量重建走既有 `index_scheduler` 单飞 sync，不影响查询面。

这是三线里**单项预期收益最大**的改动：把「向量看不见的 chunk 尾部」清零。

#### R-2 · 边界感知滑窗（修 D2/D5）

`_split_oversized` 改为分隔符优先级回退（成熟做法，Recursive splitter 语义，不引第三方库）：

```text
切点搜索顺序：\n\n（段落）→ \n（行）→ 。！？!?.（句末，含 CJK）→ 空格 → 兜底原字符位
搜索窗口：目标切点前 15% 预算内找最近边界；找不到才硬切
```

同时修 D5：滑窗推进时累计 `part` 前文行数，`line_start` 随子块正确偏移（有测试基线 `test_retrieval_hybrid.py` 可扩）。

#### R-3 · 标题全深度 + 上下文化 embed 文本（修 D3，Anthropic contextual retrieval 的轻量版）

- `split_markdown_sections` 认 `#`–`######` 与 Setext（`===`/`---`）；叶子过小（<200 char）向上归并，避免碎片化；
- `build_embed_text` 在向量文本前加**标题面包屑**（`H1 > H2 > H3\n\n` + body；只进 embed 文本，不改存库 body 与展示）——低成本给每个 chunk 补全局语境，对「章节内代词/省略主语」类 query 提升显著且已被工业验证；
- 面包屑同时喂 BM25 车道（现有 tags 机制顺延）。

#### R-4 · 表格行线性化（修 D4）

宽表 detach 保留（防大表撑爆 chunk），但 pointer 旁**新增派生 chunk**：每 N 行（如 8 行）生成一条「`表标题 | header: cell; header: cell …`」线性化文本，`chunk_id` 指回原表行区间。单元格内容重新可检，原文展示不变。

#### R-5 · 重排序（受速率红线约束，分两步）

- **第一步不动**：先落 R-1~R-4 重建索引，用同一 BEIR/C-MTEB 对照——召回天花板不抬，rerank 是无用功；
- **第二步条件启用**：召回上去后若 ndcg@10 仍拖后，开已接线的 `bge-reranker-base`（pool=20）；先离线量 P95 延迟，**只有 GPU 环境实测 <150ms 才默认开**，否则仅评测态开。`search_sources` 是 writing/intel 的用户可感路径，此处是唯一可能触碰交互速率的项，故设硬门。

#### 暂缓 / 不做

- bge-m3 sparse / ColBERT：需换 FlagEmbedding 推理栈 + 存储三向量，工程面大；现有 BM25 已覆盖词面车道，等 R-1~R-4 的对照数据出来再议；
- 不引 LangChain 等切分依赖（现实现自持，改造点小）。

### 3.3 检索度量补齐

- BEIR n=20 是 smoke；结论一律以 **n≥100 query** 对照（改前/改后同题集同 qrels）为准；
- 新增离线 **chunk 质检脚本**（一次性工具）：对 seed 语料输出「硬切率（切点非边界比例）/ chunk token 分布 / 超 512 token 占比 / 表格覆盖」，改前改后各跑一次入档——让「切得好不好」从体感变成数字。

---

## 4. 轨道 X — 上下文质量

### 4.1 已核实的组装缺陷

LongBench L1 agent-path：passage 落盘 `sources/passage.md`，agent 用 `read_file`/`grep` 阅读（无 `search_sources`，隔离红线，不改）。

| # | 缺陷 | 代码证据 | 危害 |
|---|------|----------|------|
| X-D1 | **markdown 无 outline**：`language_for_path` 只认 `.py/.pyi`，`attach_outline_if_truncated` 对 .md 恒空 | `structural/providers.py:18-22` · `outline.py:35` | 长文截断后模型只能盲分页 / 盲 grep，多跳题（hotpotqa）导航成本极高 |
| X-D2 | **旧证据整体蒸发**：同 path 旧 `read_file` 结果 fold 成 `[omitted]`；非最新 tool_result 砍 4000 字符 | `context/engine.py` `_fold_stale_read_file_results` / `_apply_tool_result_budget` | 答案在早期窗口时，读到后面终答时证据已不在窗内——直接压 F1 |
| X-D3 | 终答冗长 | scorer v2 无子串 EM、F1 罚多余 token；em 0.30 vs f1 0.56 的 gap 形态吻合 | 会答但表达不合规 |
| X-D4 | system.md 提及 `search_sources` 但 agent profile 未挂载 | `scenarios/agent/system.md` vs `profiles/agent.yaml` | 误导模型调不存在的工具，浪费步数 |
| X-D5 | 超长单行按字符截 `line[:max_chars]` | `read_tools.py` | 低频，顺手修 |

### 4.2 方案（全部在组装期 / 结果契约，正则级开销）

#### X-1 · markdown outline（主打，改动最小收益直给）

`attach_outline_if_truncated` 对 `.md/.markdown/.txt`（有标题结构者）走**标题扫描 provider**：正则抽 `#`–`######`/Setext 标题 + 行号，格式与现有 Python outline 一致（≤40 条）。与 R-3 共用标题识别逻辑。截断的 `read_file` 结果立即变成「带目录的分页」，模型可以直接跳段——这是把 coding 里已验证的 `read_outline_coverage=1.0` 手法复制到长文阅读。

#### X-2 · 证据保留：fold 从「全丢」改「留摘要」

- `_fold_stale_read_file_results`：旧窗不再替换为纯 `[omitted]`，改为保留**首尾各 ~300 字符 + 覆盖行号范围**（`[lines 120-480 read earlier; head: … tail: …]`）；
- 非最新 tool_result 的 4000 字符预算从「截尾」改「**头尾各半保留**」（middle-truncate，代码库 L0 已有同型函数可复用语义）；
- 两处都是 assemble 期字符串操作，无额外 IO / 无模型调用，token 成本几乎不变（fold 本来就要写占位文案）。

#### X-3 · 终答纪律（EM 抓手）

L1 free-arm prompt 已写 short phrase，但无格式锚。补两处软约束（不加工具）：

- prompt 末尾加「以 `Answer: <短语>` 单行结束」；
- system.md「Long materials」小节补一句同样式要求。

提取侧 `final_assistant_text` 仍存原文；scorer 对**预测**抽末行 `Answer:` 后再走 v2 规范化相等（金标不改）。没有该行则整段对照，与补全式 LongBench（prompt 已吃掉 `Answer:`）对齐。第2轮 EM=0 是这条口径缺口，不是阅读崩了。

#### X-4 · 文案对齐（顺手修）

system.md 的 Sources/`search_sources` 段按 profile 实际挂载条件改为条件文案（或移入 writing/intel 专属段）；X-D5 超长行截断补省略标记与 `next_offset` 语义。

#### 明确不做

- 不给 agent profile 挂 `search_sources`（§1.4 场景隔离是硬红线；长文导航靠 X-1 outline + grep 覆盖）；
- 不上 LLM autocompact 默认化（`context_hard_autocompact_allow_llm` 维持关，避免摘要幻觉进证据链）。

---

## 5. 与交互红线的对照（逐项自证）

| 项 | 落点 | 热路径影响 |
|----|------|------------|
| C-1/C-3/C-4 | 工具结果构造期（regex / 目录扫描已有预算） | 无新增阻塞 |
| C-2 | run_command 入口的命令形态判断（一次 regex） | 微秒级 |
| C-5/C-6 | 异步 indexer / 探针口径 | 无 |
| R-1~R-4 | **仅异步索引期**（chunking.py 本就声明 async-only）+ 索引重建 | 查询面零变化 |
| R-5 | 唯一可能触碰查询延迟的项 → 设 P95<150ms 硬门，否则仅评测态 | 有门 |
| X-1/X-2/X-4 | assemble / 结果构造期字符串操作 | 正则级 |
| X-3 | prompt 文案 + 预测侧 `Answer:` 抽取 | 无 |

不改 AgentEngine while；不新增工具名；模型可见变化只有「结果里多了它本来就该看到的信息」。

---

## 6. 落地顺序与验收出口

依赖关系：R-1~R-4 需 INDEX bump 全量重建（一次）；C-1 是 C-1c 回灌的前置；其余互相独立、可并行。

| 批 | 项 | 验收出口（对照口径） |
|----|----|----------------------|
| 批 1（一周内可完成的确定性修缺） | C-1a/b · C-2 · X-1 · X-4 · C-6 | `test_summary_attach_rate ≥0.6`；pager 重定向命中>0 且 `run_command` 占比↓；.md 截断读 100% 附 outline；fuse 分桶含 `non_definition_query` |
| 批 2（索引重建窗口） | R-1 · R-2 · R-3 · R-4 → INDEX 13 全量重建 → chunk 质检脚本改前后对照 | 硬切率 ≈0；超 512 token chunk 占比 ≈0；BEIR（n≥100）**recall@100 显著↑** 为第一验收位，ndcg@10 次之 |
| 批 3（依赖批 1 数据） | C-1c 失败回灌 · C-4 · C-3 · X-2 · X-3 | n25+harness：失败题事件流可见失败测引用；`related_tests_coverage ≥0.5`；LongBench（放量）f1/em 对照↑，em gap 收窄 |
| 批 4（条件项） | R-5 rerank 硬门评估 | P95<150ms 才默认开；否则评测态 |

度量纪律（承接姊妹文轨道 M）：smoke 数字不作结论；coding 用 n25+harness 立锚、retrieval 用 n≥100 query、context 放量后对照；harness 基建红时 `resolve_rate=null`。

### 6.1 代码落地对照（2026-08-15）

| 项 | 代码 | 效果验收 |
|----|------|----------|
| C-1a/b/c | **已落** | 第2轮：`test_summary_attach_rate 0→**0.217**`（5/23）· 未达 ≥0.6；n_testish 50→23 |
| C-2 | **已落** | 无 `n_pager_run_command` 进本表；coding steps/elapsed −42% 同向 |
| C-3 | **已落** | 同上（空转计划预期贡献步数下降） |
| C-4 | **已落** | 第2轮：`related_tests_coverage **0.556**`（过 ≥0.5）；adoption 0.75→0.60 |
| C-5 | **已落** | fuse_ok 0.42→0.58、no_ws 9→6，与扩顶层赋值同向 |
| C-6 | **已落** | 第2轮：`non_definition_query=0`（本 n5 未进桶；6 条仍 no_ws） |
| R-1~R-4 | **已落** · INDEX 13 | **C-MTEB n=20**：nDCG@10 0.643→**0.696**、R@10 平。**BEIR n=20**：nDCG@10 0.455→0.451、**R@100 0.530→0.495（第一验收位未过）** |
| R-5 | **未开** | 召回未抬，维持关 |
| X-1~X-4 | **已落** | 第2轮表仍记 F1 0.456 / EM **0**（当时未抽 `Answer:`）。scorer 已改为预测侧抽末行；数字不回溯，下次 context 套件才用新口径 |

---

## 7. 明确不做什么（本文口径）

- 不做 CST / call-graph / references 入 AST 索引；不全仓 LSP indexing（维持既有否决）。  
- 不给 agent 挂 `search_sources`、不给 writing/intel 挂结构工具（隔离红线）。  
- 不引入 LangChain/LlamaIndex 切分栈；不换 FlagEmbedding 推理栈（sparse/ColBERT 暂缓）。  
- 不做 LLM 摘要式上下文压缩默认化。  
- 不在任何一线用 smoke 数字宣布效果。

---

## 修订记录

| 日期 | 修订 |
|------|------|
| 2026-08-15 | 初稿：基于 `RESULTS.md`（2026-08-15 smoke）与代码核实（chunking / engine / test_summary / locate）定稿三线方案 |
| 2026-08-15 | 批 1–3 代码落地；R-5 仍关；INDEX 13 待同步重建后进召回面 |
| 2026-08-15 | 第2轮冒烟（17:12 CST 入账）：coding 同题 0.6、steps −42%、C-4 过线、C-1 0.217；C-MTEB 排序抬、R@10 平；BEIR R@100 0.530→0.495；LongBench EM 0.30→0 |
| 2026-08-15 | context scorer：预测抽末行 `Answer:`（金标/v2 相等规则不动）；第2轮 EM=0 不回溯改写 |
| 2026-08-15 | 评测日记改按轮次+时间（第1轮 12:14–13:01 CST / 第2轮 17:12 CST），不再用上下午 |
