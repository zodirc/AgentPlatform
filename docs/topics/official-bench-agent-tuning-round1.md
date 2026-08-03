# Official Bench · Round 1 — 归因 + 执行方案（Phase B → C 施工蓝图）

> **状态**：M1 立尺已接线 · **C-1/C-2 产品落地** · **C-4 离线面已落** · **C-3 冒烟网格已跑**（保持 `default`）· free 行为桶已干净（drift/cap）· **第五刀 soft-rerank+limit50 已回滚**（free nDCG@10 0.434→0.395）  
> **下一硬门**：回滚后同条件 free 20q 确认回到 ~0.43；另机 **M2** m3 全量锚；官方 Δ / `update-baseline` 仍禁止用冒烟叙事  
> **完整自含简报（流程 + 历次对照 + 问题，供高级模型续作）**：`docs/topics/retrieval-free-l1-tuning-brief.md`  
> **输入**：`eval/official/baseline/official-small-2026-08-m2.json` · `m1.json` · `eval/reports/official/c3_grid_latest.json` · `eval/reports/official/retrieval_bucket_latest.json`  
> **纲领**：[official-bench-agent-tuning](official-bench-agent-tuning.md)（本文是其 §9「Phase B 归因 + 本轮工程调优方案」交付物，并细化为可施工计划）  
> **流程图（含数字释义）**：[retrieval-tuning-flowchart.png](retrieval-tuning-flowchart.png) — 分桶怎么读、为何 drift↓/ok↑/cap↓ 算行为正向、C-3「8 点 macro 打平」、search_cap 复测后 IR 平台期  
> **纪律**：评测面已 bump → **m3**；**验收温度计 = free L1 only**（不用 forced 为 free 掉分开脱）；**宣称由 official 驱动**的合入仍须 M2 分桶 + L2 验证（纲领 §0.2）；纯产品痛点票可先行，**不得**用 m2/冒烟分作涨分叙事
本方案受三条原则约束，全篇按此裁剪：

| # | 原则 | 在本方案中的落点 |
|---|------|------------------|
| **P-速率** | 不影响 agent 交互速率与交互逻辑 | 评测全部在 Ops / 隔离 Work / bench 面运行，不进用户热路径；所有 C 票逐票过 R1–R5（[13](../core/13-rate-redlines.md)），不改 `AgentEngine` while、不加同步模型调用；评测代码不得在 runtime 留任何影响质量/速率的分支（§5.4 审计清单） |
| **P-同构** | 评测跑真实主链路，分数提高只是调优的间接结果 | 主臂一律 `Session → Turn → loop → 工具 → assemble → 终态`，用**产品默认参数**（不为评测特调温度/预算/profile）；旁路与脚本化臂只作 L0/L2 探针 |
| **P-成熟** | 不以「够用」为主导，建立成熟合理的评测方式 | 对齐成熟 agent 评测八要素（§2），补齐轨迹探针、统计协议、自动归因、防作弊审计四块基建（§5），主栏只认全量锚 + 官方裁判 |

---

## 0. TL;DR

1. **尺子先于杠杆**：m2 的 L1 实现与纲领 §4 契约有 4 处实质偏差（retrieval 强制单搜、context 强制单读、coding 无 repo 无 harness、全部冒烟档样本量），当前三个主栏分数**均不宜作调优 Δ 的锚** → 里程碑 M1 落 5 张立尺补票（§3，bump `m3`），M2 全量立真锚。
2. **生产面最确定的一刀已经找到**：ContextEngine 对单条 tool_result 的 **4000 字符无条件预算截断**把大 `read_file`（120k 字符长文）打穿到只剩开头 ~3%——既是 context L1 F1=0.31 的主导因，也是用户长文任务的真实痛点 → C-1 票。
3. Retrieval 在强制单搜下 L1 ≈ Index plane 上限，差距不在 loop/工具，而在 **RQ1e 融合标定与 embed 档位** → C-3。
4. Coding 的 `patch_rate=0.4` 在无 repo、无 harness 的尺下**没有效果含义**，不作任何调优目标 → 先 A-3 修尺，再 C-4。
5. 与「够用」的分界（§2）：本轮同时补上**评测基建**——L2 探针 schema、失败桶自动分类、统计复现协议、同构性防作弊审计（§5）。没有这四块，后续每一轮调优都要重新人肉归因。

---

## 1. 基线读数与可信度

| 套件 | m2 L1（主栏） | m1 L0（对照） | L1 样本量 | 可信度评注 |
|------|---------------|---------------|-----------|------------|
| retrieval | nDCG@10 **0.4030** · R@100 0.6019 | hybrid 0.4123 · R@100 0.5525 | **20 q/集** × 3 集（冒烟档） | L0 为全量 qrels，**样本不同，Δ 不可比**；20q 档统计噪声大（SciFact 0.569 vs L0 0.647 的落差主要是采样 + query 传真，见 §4.1） |
| context | F1 **0.3149** · EM 0.05 | full 0.4057 / compact 0.2728 | 仅 `multifieldqa_en` 前 **20** 条 | L0 为 3 task × 40；L1 的 full/budget/compact 三字段是**同一 `agent_f1` 的别名**（`official_agent_path.py:894-900`），非三臂同分；EM 偏低另有 judge 形态因素 |
| coding | patch_rate **0.4000** | patch 0.667 @n3 | n5，无 harness | **无效果含义**：无 repo checkout、patch 仅判「非空 + 像 unified diff」、resolve 未跑 |

样本量注：基线 `n_queries=20` 是**每集**上限（Ops preset「20q/集」，`ops_official.py:173`）；context 的 `context_limit=20` 是全局前 20 行，恰好全落在 slice 首个 task `multifieldqa_en`，`hotpotqa` / `narrativeqa` **完全没跑**。

---

## 2. 目标形态：成熟 agent 评测的八要素

成熟编码/助手 agent（Cursor、Claude Code、SWE-bench 官方实践）评测的共性要素，对照本仓现状与补齐票：

| # | 要素 | 含义 | 本仓现状 | 缺口 → 票 |
|---|------|------|----------|-----------|
| E1 | **同构执行** | 题面进真实会话/workspace，走与用户完全相同的执行路径 | ✅ L1 runner 已走 Session/Turn/工具/assemble | 保持；`ops_eval` 分叉收敛进审计清单（§5.4） |
| E2 | **自由主臂** | 不给模型写交互剧本；模型自决搜/读/改 | ❌ retrieval 强制单搜、context 强制单读、coding 禁 repo | A-1 / A-2 / A-3 |
| E3 | **官方裁判** | 排序指标 / 官方 judge / harness resolve，不自造宽松判据 | 部分：IR 指标 ✅；coding 只数非空 patch ❌ | A-3（harness 进锚）；A-2（答题约定对齐官方 judge） |
| E4 | **轨迹一等公民** | 每题落盘完整轨迹与探针字段，支撑自动归因 | 部分：turn_events/process.jsonl 有，但无归因字段 | A-5（L2 schema，§5.1） |
| E5 | **归因自动化** | 失败桶由确定性规则从轨迹自动分类，不靠人肉读日志 | ❌ 本文 §4 即为人肉归因 | A-6（分类器，§5.2） |
| E6 | **统计可靠** | 样本量、重复次数、配对比较、方差报告；同条件才比 Δ | 部分：fingerprint/协议戳记 ✅；冒烟档当锚 ❌、无重复/CI ❌ | A-4 + 复现协议（§5.3） |
| E7 | **可复现配置指纹** | manifest 记录模型/参数/索引版本/检索 profile，环境漂移可检 | 部分：model/tier/fingerprint ✅；INDEX_VERSION、retrieval_profile、关键 Settings 未入 manifest | A-5 |
| E8 | **防作弊纪律** | 评测不注入答案、生产无 bench 专用分支、题面无泄漏 | 大体 ✅（物化仅语料/题面）；未成文、无审计清单 | §5.4 成文 + 评审项 |

> **裁决规则（纲领 §3）在八要素下的重申**：只涨 L0 探针、L1 自由臂不动 → 无效；L1 涨但违 R1–R5 → 否决；主栏永远 = 全量锚 + 自由臂 + 官方裁判。

---

## 3. 立尺补票（Phase A 修正 · 评测面 · 协议 bump `official-small-2026-08-m3`）

改的是评测链路（`services/api .../official_agent_path.py` + `scripts/official_bench/`），按纲领定义**不算调优成功**，但不修则 Phase C 无法归因。每票附实施要点与验收标准（DoD）。

### A-1 Retrieval 主臂改自由 agent

| 项 | 内容 |
|----|------|
| 现状 | prompt 强制 `Call search_sources exactly once with query={qtext!r} and limit=100`（`official_agent_path.py:627-632`）——违反纲领 §4.2「主臂 = 自由 agent」与 §1.1「forced 注入却宣称 agent 检索能力」红线 |
| 实施要点 | ① 主臂 prompt 改为自然任务描述（告知「答案在本地资料库，请给出依据」，不出现工具名与次数指令）；② 多轮 `retrieval.completed` 合并沿用 first-seen union（`agent_path_extract.py:59-82`），规则写进协议正文；③ 未搜 = 0 分计入（现行为保留，`:647-653`）；④ 现 forced-once 文案降级为 `--arm forced` **L2 诊断臂**（隔离 Index plane 上限，不进主栏）；⑤ 排名深度：自由臂模型自定 limit，协议按合并序取前 100 计 nDCG@100，不足即不足（如实反映） |
| 影响 | 自由臂分数预计**下降**（不搜 / query 改写 / `search_sources_max_per_turn=3` 闸），是尺变真，纲领 §6 已预期 |
| **DoD** | 主臂 prompt 无工具指令字样；`--arm free|forced` 两臂可跑且 manifest 区分；合并/零分规则有单测（扩 `test_official_bench_agent_path_extract.py`）；L2 字段 `searched/n_search/queries[]` 落盘；协议 stamp m3 |

### A-2 Context 主臂改自由多步读 + 补 oracle 臂

| 项 | 内容 |
|----|------|
| 现状 | prompt 强制 `read_file once … Minimize tool calls`（`:829-833`）——违反 §4.3「多 Step 交互」，封死 `offset`/`next_offset` 续读；oracle 臂（§4.3 辅指标）未实现；三臂字段为同值别名（`:894-900`） |
| 实施要点 | ① 主臂：给问题 + 指出材料在 `sources/passage.md`，答题约定对齐官方（"answer with a short phrase only"），**不限制读法**（分段读 / grep 均可）；② oracle 臂：同模型 + 显式「把材料读完整后再答，可多次续读」，报 `retention = agent_f1 / oracle_f1`（L2，不进主栏）；③ 指标字段改为显式 `agent_f1` / `agent_em` 主字段，删除 full/budget/compact 别名（baseline 抽取器与 SCORECARD 模板同步改）；④ 并行模式沿用每样本独立 Work（`:787-820`），串行复用 Work 的 passage 覆写路径废弃（避免 read 缓存串题） |
| **DoD** | 主臂无「once/minimize」类指令；oracle 臂可跑且 manifest 标 `arm=oracle`；`agent_f1` 为唯一主字段（compare/update-baseline/SCORECARD 全链路适配 + 单测）；L2 字段 `read_bytes/n_reads/truncation_hits/answer_len` 落盘；3 task 均可跑（限档逻辑改为**每 task 上限**而非全局前 N 行） |

### A-3 Coding 挂 repo 工作树 + harness resolve 进 L1

| 项 | 内容 |
|----|------|
| 现状 | 物化只写 `problem.md`，prompt 明言 `NO repository checkout`（`:994-1008`）；`harness: False` 写死（`:970`）；模型凭题面空想 diff，resolve 恒 0 |
| 实施要点 | ① 物化：实例 repo 按 `base_commit` 检出进隔离 Work（浅克隆 + 本地 mirror 缓存进 `BENCH_DATA_DIR`，避免重复拉取；跑完清理工作树，保留 mirror）；② prompt 改为真实修复任务（复现 → 定位 → 修改 → 建议 `run_tests` 验证），不指定工具序列；③ patch 抽取优先「工作树 `git diff`」（真实改动），events/fenced 抽取降为 fallback；④ resolve：Turn 全部结束后批量走官方 `swebench.harness`（Docker，评测面离线步骤），锚点档 **n25** + `instance_fingerprint`；`patch_rate` 降为辅指标；⑤ 审批已由 `ops_eval` 预批（`turn_controller.py:1229-1231`、`context/engine.py:44-49`），无需改动 |
| **DoD** | n3 冒烟档可端到端出 resolve（挂 repo → Turn → git diff → harness）；manifest 含 `harness=true` + resolve 指标；repo 缓存命中日志（二次跑不重拉）；工作树磁盘用后即清有验证；`git diff` 抽取有单测；C-4 全部票以本票为前置 |

### A-4 全量档立锚 + 双档 SCORECARD

| 项 | 内容 |
|----|------|
| 实施要点 | ① 锚点档（唯一入主栏）：retrieval 全量 qrels（~1.3k Turn）· context 3 task × 40 · coding n25 + harness；② 冒烟档（20q/集、context 每 task 10、n5）保留为迭代方向盘，SCORECARD 单列「smoke 趋势」并显著标注**不作效果结论**；③ `make official-bench-compare` 增加档位一致性校验（锚只跟锚比） |
| **DoD** | SCORECARD 双档展示且主栏仅锚点档；compare 在档位不一致时拒绝打 Δ；m3 锚点三套全量入库 |

### A-5 探针、指纹与一致性

| 项 | 内容 |
|----|------|
| 实施要点 | ① L2 探针 schema（§5.1）作为 `process.jsonl` per-case 记录落盘；② manifest 增配置指纹：`model + 生产默认参数快照（temperature 等 provider 参数）+ INDEX_VERSION + retrieval_profile + 关键 Settings 哈希`（评测**读取并记录**产品默认，不为评测改动，P-同构）；③ `suites.small.yaml:6` 协议字段仍写 m1 → 拆为 `protocol_version_l0` / `protocol_version_l1` 或加注释；④ 文档漂移顺手修：stall 阈值 docs/05 写 120s、代码 180s（`settings:163`）；`INDEX_VERSION` docs 写 7、代码 8（`vector_index.py:16`） |
| **DoD** | 任一 L1 run 的 manifest 可单独回答「什么模型/什么索引/什么 profile/什么题集指纹」；两次同条件 run 的指纹字段一致可机检 |

### A-6 失败桶自动分类器（评测面新增）

| 项 | 内容 |
|----|------|
| 动机 | E5：归因不能每轮人肉读日志。本文 §4 的桶表即分类器的规则规格 |
| 实施要点 | 离线脚本（`scripts/official_bench/` 内）：输入 run 的 process.jsonl（含 L2 字段）+ turn_events 快照，按 §5.2 确定性规则给每 case 打 `bucket` 标签；输出分桶计数进 `result.json` / report.html / Ops Run 详页。**纯离线、无 LLM 判官**（评测面也不引入模型判官，保持确定性可复现） |
| **DoD** | m3 锚点 run 自动产出分桶报告；§4 的 ⚠ 项由该报告直接回答；规则有单测（构造合成轨迹逐桶命中） |

---

## 4. Phase B 归因（失败桶 → 证据 → 置信度）

> 本节为**静态归因**（代码链路 + 基线数据推断）。标 ⚠ 的结论由 M2 的 A-6 分桶报告复核后落锤，对应 C 票才可合并。

### 4.1 Retrieval（nDCG@10 0.4030 @20q/集）

| 失败桶（纲领 §5.2） | 判定 | 证据 |
|--------------------|------|------|
| 未调用 search | **不适用**（m2 尺强制单搜；未搜按 0 分计入，`official_agent_path.py:647-653`） | A-1 后此桶才有意义 |
| query 漂移 | ⚠ 疑似次因 | prompt 已给 `query={qtext!r}`，但 query 参数由模型转写填入；SciFact L1 0.569 vs L0 0.647 的落差 = 采样（20q vs 全量）+ 转写损耗，占比待 L2（事件里 query 参数 vs 原 query 的 diff 率） |
| hits 弱（Index plane） | **主导**（高置信） | 强制单搜下 L1 ≈ `store.search(hybrid)` 经工具面的直接读数；NFCorpus R@10 仅 0.077（qrels 均值 ~424 条/查询，depth 不够是官方特性，nDCG 才是可动指标） |
| excerpt 裁没证据 | **不影响 IR 计分** | 计分走 `retrieval.completed` 事件完整 ranked（`agent_path_extract.py:59-82`），与模型可见 excerpt（200 字符）无关；excerpt 只影响 A-1 后自由臂「搜完是否会再搜」的行为 |
| 搜次打满 | 不适用（单搜） | A-1 后关注 `search_sources_max_per_turn=3`（`settings:65`）是否成为约束 |

**结论**：本套件当前差距落在 **RAG/Index plane（纲领 §5.3 杠杆 2）**，不在工具契约与 loop → C-3。

### 4.2 Context（F1 0.3149 · EM 0.05，仅 multifieldqa_en×20）

| 失败桶 | 判定 | 证据 |
|--------|------|------|
| tool_result 被 snip 打穿 | **主导**（高置信） | `TOOL_RESULT_CHAR_BUDGET=4000` 字符**无条件**截断（`context/engine.py:24, 372-376, 753-784`），例外仅 pinned-short（≤800）与 `writing_section_extract`；passage 最长 120k 字符（`suites.small.yaml:52`）→ 模型只见开头 ~3% + `[budget_truncated]`。F1=0.31 与「答案恰在文首」的样本占比相合 ⚠（L2：per-case 答案位置 vs F1 相关性） |
| 一次读爆窗 | 排除 | `read_file` 行窗硬顶 32k 字符（tool 侧），但 budget 在 assemble 再截到 4k——瓶颈在后者 |
| 未读文件臆答 / 步数耗尽 | 排除（m2 尺下） | prompt 强制 read once；`agent max_steps=50` 远未触及 |
| 续读机制被封 | 次因（评测面） | `Minimize tool calls; do not re-index` 禁止 `next_offset` 续读 → A-2 修尺；修完后若模型仍不续读，才轮到 C-2 的提示纪律 |
| EM 异常低 | judge 形态 | 模型答句子、gold 是短语；EM 判「全等或子串」（`context_run.py:64`），长答稀释 → A-2 答题约定 |

**结论**：一半是尺（A-2），一半是真实生产缺陷——**大 read 的预算策略（杠杆 3）** → C-1；agent 场景读长文的提示纪律 → C-2。

### 4.3 Coding（patch_rate 0.4 @n5）

| 失败桶 | 判定 | 证据 |
|--------|------|------|
| 未挂 repo | **主导**（确定） | prompt 明言 `NO repository checkout`（`:1003`）；resolve 恒 0，patch 是凭题面空想的 diff → A-3 |
| 审批卡住 | **排除** | `ops_eval=True` → `writes_preapproved` / `exec_preapproved`（`turn_controller.py:1229-1231`），engine 明确不 block（`context/engine.py:44-49`） |
| 不出 patch / 格式不可 apply | ⚠ 待复盘 | 3/5 空 patch：候选因 = 模型以纯文字解释代替 diff、或产出形态落在 `patch_from_events` 三级抽取（`agent_path_extract.py:129-186`）之外；L2：逐例复盘 5 条 turn_events 的工具调用与输出形态 |
| 未跑/跑不过测 | 尺缺失 | 无 harness、Work 内无代码可跑 `run_tests` → A-3 后才可归因 |

**结论**：本套件当前唯一有效动作是修尺（A-3）；生产面票（C-4）全部后置。

---

## 5. 评测基建规格（E4–E8 的落地件）

### 5.1 L2 探针 schema（process.jsonl per-case 记录）

| 字段 | 类型 | 说明 | 套件 |
|------|------|------|------|
| `case_id` / `turn_id` / `arm` | str | 链到 Ops Raw 快照 | 全部 |
| `steps` / `wall_ms` / `tokens_in` / `tokens_out` | int | 交互开销（同时是 P-速率的观测面） | 全部 |
| `terminal_state` | str | completed / step_timeout / stall / cancelled | 全部 |
| `searched` / `n_search` / `queries[]` / `query_drift`（原 query 与参数的归一化编辑距离） | — | 搜索行为 | retrieval |
| `n_reads` / `read_bytes` / `used_next_offset` / `truncation_hits`（budget_truncated 命中次数） | — | 阅读行为 | context / coding |
| `answer_len` / `extraction_path`（events/final_text/fallback） | — | 作答形态 | context |
| `patch_source`（git_diff/propose/write/fenced/none）/ `patch_applies`（apply --check）/ `ran_tests` | — | 补丁形态 | coding |
| `bucket` | str | A-6 分类器输出 | 全部 |

### 5.2 失败桶确定性分类规则（A-6 的规格）

| 套件 | bucket | 规则（全部来自轨迹字段，无模型判官） |
|------|--------|--------------------------------------|
| retrieval | `no_search` | `searched=false` |
| | `query_drift` | `searched` 且 `query_drift > 阈值`（阈值在 m3 首跑上标定后写死进协议） |
| | `weak_hits` | 搜了、query 忠实，但 case nDCG 低于套件中位 |
| | `search_cap` | `n_search == 3`（打满闸）且末次搜索仍换词 |
| context | `truncated_unread` | `truncation_hits > 0` 且 `used_next_offset=false` |
| | `gave_up_early` | 读入字节 < passage 的 x% 且 F1=0 |
| | `verbose_answer` | F1 > 0 且 EM=0 且 `answer_len` 超阈 |
| | `steps_exhausted` | `steps ≥ max_steps` 或 `terminal_state != completed` |
| coding | `no_patch` | `patch_source=none` |
| | `patch_no_apply` | 有 patch 且 `patch_applies=false` |
| | `patch_not_resolved` | apply 成功、harness 未 resolve |
| | `no_verify` | resolve 失败且 `ran_tests=false`（供 C-4 提示纪律归因） |

### 5.3 复现与统计协议

| 规则 | 内容 |
|------|------|
| 参数来源 | 一律用**产品默认**（温度、检索 profile、预算等），评测只记录不改动（P-同构）；改产品默认 = C 票，走门禁 |
| 同条件 Δ | 同 `protocol_version` + 同档位 + 同题集指纹 + 同模型 + 同配置指纹（A-5）才可比；compare 机检 |
| 配对比较 | Δ 一律按 case 配对（同 qid/样本/instance），报 win/tie/loss + 宏 Δ；工程票复测报告附配对表，不允许只报宏均值 |
| 重复与方差 | 冒烟档跑 **N=3** 报 mean±sd（模型行为随机性观测）；锚点档 N=1（成本），但锚点更新前后各附一次冒烟 N=3，方差大于宏 Δ 时结论降级为「不显著」 |
| 显著性 | 结论口径：配对 win-loss 差 + 冒烟方差护栏；不引入重型统计库，规则写进 compare 输出 |
| 失败重跑 | runner 支持按 case 级断点续跑（terminal 异常的 case 单独重试一次并标 `retried`），避免整锚重跑 |

### 5.4 同构性与防作弊审计清单（评审必核）

| 项 | 规则 | 现状 |
|----|------|------|
| 生产分叉 allowlist | runtime 内 `ops_eval` 分支仅允许：审批预批、per-Turn model override、visibility_seed——均不改质量/速率路径；新增分叉须在本清单登记并评审 | 现有三处符合（`turn_controller.py:345-360, 1229-1231`、`context/engine.py:44-49`） |
| 无答案泄漏 | 物化只进语料/题面：BEIR 语料 ✅；LongBench passage 本身含答案（任务性质）✅；SWE 物化**不得**包含 `patch` / `test_patch` / `hints_text` 字段（A-3 实施时列入 DoD 检查） | A-3 落地时核 |
| 无剧本化 | 主臂 prompt 禁止出现工具名、调用次数、顺序指令（A-1/A-2/A-3 修正后由评审维持） | m2 违反 → M1 修 |
| 无评测特调 | 不为评测改产品默认参数/profile/预算；bench 专用 env 只允许影响评测编排（并行度、档位、超时） | 符合 |
| 判据不放水 | coding 只认 harness resolve；context judge 对齐官方；retrieval 只认 qrels | m2 coding 违反 → A-3 修 |

---

## 6. Phase C 工程票（生产面 · 按纲领 §5.3 菜单点菜）

> 每票动的都是**用户路径上的生产代码**（`services/runtime`），官方分只作复测。合并前置：M2 分桶报告确认对应 ⚠ 项。

### C-1 Context/预算：大 read 保留策略 + snip 地板 （杠杆 3 · 优先级 1）

> **落地（产品票 · 2026-08）**：`Settings.tool_result_char_budget=4000` / `tool_result_latest_read_char_budget=32000` / `context_snip_protect_latest_read`；`ContextEngine` 差分预算 + fold→budget + snip/collapse 地板。单测：`test_latest_read_file_keeps_large_body` / `test_snip_floor_keeps_latest_read_and_instruction` / `test_assemble_ms_large_latest_read_stays_bounded`。**官方 DoD（配对 L1 / `truncated_unread`）仍挂 M2 后复测。**

| 项 | 内容 |
|----|------|
| 现状 | （施工前）单条 tool_result 一律 4000 字符；最近一次 read 仍被 4k 截断；snip 无保护地板 |
| 改法 | ① 最近一次 `read_file` 独立更高预算（32k，Settings）；旧 read 沿用 read_fold + 4k；② snip/collapse 地板保护当前指令 + 最近 read 周期；③ 预算 Settings 化 |
| 用户价值 | 长文阅读/审阅类任务不再「读了等于没读」 |
| L1 预期 | context F1 0.31 → **0.38–0.45**（配合 A-2 自由读）；retrieval/coding 中性 — **待 m3 锚后验证** |
| R1–R5 | 纯字符串/预算逻辑（R3 ✅）；无新模型调用（R2 ✅）；未改 `AgentEngine` while（R1 ✅）；单测 + assemble_ms 护栏；✅ stub `agent.*` + `shared.04`（40k 触发预算） |
| 否决条件 | fill 提前触顶致 autocompact 频率显著上升；golden 回归；assemble_ms 劣化 |
| **DoD** | ✅ 预算/地板单测；✅ assemble_ms 护栏；✅ stub golden（agent + shared.04）；⏳ context L1 同协议配对 |
### C-2 工具契约 / 系统提示薄说明 （杠杆 1 · 优先级 2）

> **落地（产品票 · 2026-08）**：agent `system.md` 补 `[budget_truncated]`/续读/禁止臆造未读内容 + unified diff + Bugfix；`search_sources` / `search_codebase` 弱命中换词。stub golden **`agent.*` 12/12 绿**。  
> **分桶驱动补强（2026-08-03）**：基线 free L1（`ccad8723`）`query_drift` **83%** → 收紧首搜忠实度文案。  
> **复测（Ops · `caf49721` · deepseek-v4-flash · 20q · debug.log）**：`query_drift` **67%**（−16pp）· `ok` **25%**（+12pp）· `no_search`≈2% · nDCG@10 **0.418**（基线 0.489，−7pp）· fail_turns 14/60。报告：`eval/reports/official/retrieval_bucket_after_c2.json`。**行为改善成立；宏 IR 未涨且有失败噪声 → 不入库。**  
> **二次补强（2026-08-03）**：分桶对照原句显示主因是**首搜被压成 keyword bag**（相对 claim 全文 Levenshtein >0.35），非乱搜无关题。已改 `search_sources` 契约 + agent/writing：`query` **近乎原文**；禁搜前反复 `list_dir`。热部署 runtime。  
> **三次复测（Ops · `8a6b5814` · debug.log）**：`query_drift` **5%**（3/60，←67%）· `ok` **77%**（46/60）· `search_cap` **18%**（11/60）· `no_search` 0 · nDCG@10 **0.427**（↑自 0.418；仍 < 改前 0.49）· R@10 **0.454** / R@100 **0.565**（明显回升）。报告：`retrieval_bucket_after_verbatim.json`。**原文首搜成立。**  
> **四次补强（search_cap）**：达 cap 轨迹多为「首搜已有 hit 仍同义换词 3–5 次」。契约改为默认 ≤2 搜；首搜有 on-topic path 则停搜改 `read_file`。已热部署 runtime。  
> **四次复测（Ops · `0526901a` · debug.log）**：宏指标几乎持平（nDCG@10 **0.434**，←0.427）；**行为** `search_cap` **18%→2%**（1/60）· `ok` **77%→92%**（55/60）· drift 仍低 · `no_search` 2 · R@100 略降。报告：`retrieval_bucket_after_search_cap.json`。**搜次文案生效；IR 未明显跟涨 → 不入库。下一刀不宜再拧搜次。**  
> **五次 Index/排序刀（`07b4e3e` + 覆盖测 `f8f583b`）**：假设长 claim 的 lexical overlap 淹没 RRF；改 `rerank.py`（bonus 按 `|score|` 缩放）+ `search_sources` default limit **10→50**。意图抬排序并间接抬 free nDCG。  
> **五次复测（Ops · `a6de7860` · free · 20q · `TEST.log`）**：nDCG@10 **0.395**（←0.434，**−0.039**）· R@10 **0.437** · R@100 **0.504**（↓）· 分库 NFCorpus/FiQA 仍拖后腿。团队确认 **只认自由搜、不跑 forced 洗白** → **判定失败**。  
> **回滚（2026-08-03）**：`cf87911` / `4189325` 还原上述两提交；**不入库**。完整对照与运行流程见 `docs/topics/retrieval-free-l1-tuning-brief.md`。

| 项 | 内容 |
|----|------|
| 现状 | （施工前）agent 长文阅读与 RAG 面薄；diff 输出规范未写 |
| 改法 | ① 分段读纪律（配合 C-1 标记）；② 弱命中换词重试（闸内）；③ 优先 `edit_file`/`propose_patch` + 标准 unified diff；④ Bugfix 纪律 |
| L1 预期 | context/coding 间接小幅 +；retrieval 自由臂行为改善 — **待 m3 锚后验证** |
| R1–R5 | 纯静态文案（R1–R4 ✅）；✅ stub `agent.*` |
| 否决条件 | golden 中 writing/agent 行为漂移（多余工具调用增步） |
| **DoD** | ✅ stub agent golden；⏳ L1：`used_next_offset` / `no_search` 可见改善 |
### C-3 RAG / Index plane 标定 （杠杆 2 · 优先级 3）

> **冒烟标定（2026-08-03）**：`make c3-retrieval-grid C3_QUERY_LIMIT=20`（scifact+nfcorpus · Index L0 ST+pgvector · **rerank=0** 量纯 fusion；prod-bench default/vector_heavy 均 19/19）。报告：`eval/reports/official/c3_grid_latest.json`（`c3_grid_20260803T075929Z`）。  
> **结论**：`recommend_switch_default=false` · **保持生产 `RETRIEVAL_PROFILE=default`**；8 个 fusion 点 macro nDCG@10 **无差异**（拧 rrf_k/doc_boost/车道/`vector_heavy` 在本档分不出）；SciFact vs BM25 Δ≈−0.03（冒烟噪声，不作切默认依据）。**未改** runtime 默认、未 bump INDEX、未 `update-baseline`。  
> **仍欠**：全量三集（含 FiQA）网格；自由臂 L1 配对（本结论不宣称 official Δ）；embed 升级单独开票。

| 项 | 内容 |
|----|------|
| 现状 | RRF `k=60`、default profile 1:1 等权、`doc_boost=0.35`（`profile.py:35-57`）；生产 embed = MiniLM-L6-v2 @384（compose:101-105）；`vector_heavy` profile 已备；**冒烟网格已标定 → 维持 default** |
| 改法 | ① BEIR Index 诊断（`scripts/official_bench/c3_grid.py` / forced 臂）+ prod-bench 网格（RQ1e，[rag-and-sources §9](rag-and-sources.md)）；② embed 升级候选（bge-small-en-v1.5 / gte-small）单独开票：`INDEX_VERSION` bump + Turn 外全量重建 + prod-bench 通过才切 |
| L1 预期 | retrieval nDCG@10 **+0.02–0.06**（纲领 §6 C 档预测）；SciFact 不得显著负于词法 — **冒烟未支撑切默认** |
| R1–R5 | 索引重建离线（R4 ✅）；查询路径无新同步模型（R2/R3 ✅）；cross-encoder 保持默认关 |
| 否决条件 | 仅诊断臂/L0 涨、自由臂 L1 不动（纲领 §3 裁决）；检索延迟 P95 劣化 |
| **DoD** | ✅ 冒烟网格报告 + 保持 default 记录；⏳ 全量网格（可选）；⏳ 自由臂 L1 配对（仅当切默认时）；embed 升级另票 |

### C-4 执行面 / 护栏 （杠杆 4 · 优先级 4 · **前置 = A-3**）

> **离线已落（2026-08）**：① extract/分桶单测扩齐（fenced/none/`patch_apply_check` + §5.2 全桶）；② `propose_patch` span 唯一性预检 + `.patch` 写盘 `git apply --check` 回帖（`patch.proposed` 事件剥离 `applies`/`apply_check` 以免 schema 炸）；③ agent Bugfix。**官方 resolve / `patch_no_apply` 仍挂 A-3 首锚 + M2。**

| 项 | 内容 |
|----|------|
| 现状 | （施工前）无「补丁可 apply」预检；抽取回归面不全 |
| 改法 | ① 抽取回归集；② 工具内 apply 预检回帖；③ Bugfix 进 system.md |
| L1 预期 | resolve@n25 从首锚（预计 0–5%）**+5–15pp** — **待锚后验证** |
| R1–R5 | 工具内/评测面外围（✅）；预检超时纳入 tool 预算（R3） |
| 否决条件 | 沙箱逃逸；步数显著上升致超时率涨 |
| **DoD** | ✅ 抽取/分桶单测；⏳ `patch_no_apply` 桶 + resolve@n25 配对 |
---

## 7. 里程碑执行计划

```text
M0 规格冻结 ──► M1 立尺施工(A-1..A-6) ──► M2 m3 诚实锚 + 自动归因 ──► M3 工程第一轮(C-1,C-2) ──► M4 工程第二轮(C-3,C-4)
（每个里程碑独立可验收；M2 之前不合并任何「宣称由 official 驱动」的生产改动 — 纲领 §0.2 纪律）
```

| 里程碑 | 内容 | 交付物 | 验收（DoD 汇总） | 跑量/成本 |
|--------|------|--------|------------------|-----------|
| **M0 规格冻结** | 本文 §5 三份规格（L2 schema、分桶规则、复现协议）+ §5.4 审计清单定稿评审 | 本文档 v2 评审通过；分桶阈值留 TBD 项清单 | 规格无歧义可直接写测试 | 零跑量 |
| **M1 立尺施工** | A-1/A-2/A-3/A-5/A-6 开发（评测面，可并行）；A-3 的 repo 缓存与 harness 通路优先打通 | m3 runner + 分类器 + manifest 指纹；每票单测 | 各票 DoD；三套**冒烟档**端到端跑通（含 coding n3 + harness） | 冒烟：~60 检索 Turn + 30 context Turn（含 oracle）+ 3 coding 实例 |
| **M2 诚实锚 + 归因** | A-4 全量立锚（free 主臂 + forced/oracle 诊断臂）+ 冒烟 N=3 方差 + A-6 分桶报告 → **Phase B 正式归因报告**（勾掉本文 ⚠ 项，必要时修订 C 票优先级） | m3 baseline JSON + SCORECARD 双档 + 归因报告（附录到本文或另开） | 锚可复现（指纹一致）；每个 ⚠ 项有分桶数据结论；纲领 §9 勾选 Phase B | retrieval ~1.3k Turn + context ~240 Turn（含 oracle）+ coding n25×harness；并行 Turn 下数小时级 |
| **M3 工程第一轮** | C-1、C-2：**代码已落**（产品票）；余 = golden/延迟对照 + 同协议配对复测（context 全量 + 冒烟方向盘） | 复测报告 + `update-baseline`（门禁过后） | C-1/C-2 官方 DoD；纲领 §5.4 四条门禁全过 | context 全量 ~120 Turn + 冒烟 N=3 |
| **M4 工程第二轮** | C-3（诊断臂网格 + prod-bench 先行，再切生产）→ 自由臂复测；C-4（依赖 A-3）→ resolve 复测 | 标定报告 + 两票 PR + 新锚 | C-3/C-4 DoD；SciFact 非负约束；resolve Δ 正向 | 网格走诊断臂（可 20q/集×多配置）+ 一次全量自由臂 + coding n25 |

里程碑间的硬门：**M2 未出分桶报告 → 不得以 official Δ 叙事合入/update-baseline**（防止未确认归因驱动调优）；**产品痛点票（如 C-1/C-2）可先行**，官方验收仍走 M3 复测门禁；**M3 复测未过 → 不开 M4**。
---

## 8. 效果预测（修正纲领 §6，以 m3 实测为准）

| 阶段 | Retrieval nDCG@10（自由臂） | Context agent F1 | Coding resolve@n25 |
|------|------------------------------|------------------|--------------------|
| m2 现值（冒烟档，尺有偏） | 0.4030 | 0.3149 | —（patch_rate 0.40 无效果含义） |
| M2 诚实锚（全量） | 预计 **≤0.40**，可能更低 | 自由读下 **0.30–0.40**（4k 截断仍在） | 预计 **0–5%** |
| M3 后（C-1+C-2） | 持平–小幅 +（间接） | **0.38–0.45** | 小幅 + |
| M4 后（C-3+C-4） | **0.43–0.48** | 持平 | **+5–15pp** |

---

## 9. 风险与开放项

| 风险 | 缓解 |
|------|------|
| 自由臂后模型「不搜 / 不续读」占比过高，L1 被行为噪声主导 | A-6 分桶率（`no_search` / `truncated_unread`）单列跟踪；行为问题归 C-2 提示面，不动 loop；冒烟 N=3 方差护栏（§5.3） |
| 评测模型（deepseek-v4-flash）波动使 Δ 失真 | 配置指纹（A-5）+ 同模型才比 Δ；重要结论配对比较 + 冒烟重复 |
| C-1 提高 read 预算 → 上下文占用变大 | fill 闸（0.80/0.90/0.95）不变，collapse/snip 仍兜底；prod-bench 盯 assemble_ms 与 autocompact 频率 |
| A-3 repo 物化的磁盘/网络成本 | mirror 缓存进 `BENCH_DATA_DIR`（一次拉取）、浅检出、用后清工作树；n25 档 ~25 个仓可控 |
| 全量锚成本高，迭代慢 | 冒烟档 + 诊断臂做方向盘；仅入库动作要求全量；case 级断点续跑（§5.3） |
| oracle 臂定义含糊 | 最小定义已锁（A-2）：同模型 + 「读完再答」+ 不限续读；retention 只作 L2 辅指标不进主栏 |
| 分桶阈值（drift/超长答案等）拍脑袋 | M2 首跑上标定后**写死进协议**；改阈值 = bump 协议 |
