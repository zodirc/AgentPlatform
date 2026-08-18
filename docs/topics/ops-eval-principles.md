# Ops L1 评测原理（审阅用）

本文约定：官方题面、物化到 Work 的范围、执行路径、命中定义与审阅偏差。Wiki 同文在「评测原理」页。数字仍以 [`RESULTS.md`](../../eval/official/baseline/RESULTS.md) 为准。

冲突时：**计分代码 > 本文**。检索：`metrics_ir.py` · `agent_path_extract.py`。上下文：`context_run.py`。编码：`swebench.harness` + `suite_coding.py`。

---

## 0. 这套评测在回答哪句话

**产品同一条 Turn 路径，面对官方题集，能不能交出官方指标。**

不是：旁路脚本直接 embed、直接喂 completion、或空补丁通管道。那些是 L0 对照，不进效果主栏。

因此三套件共用三条硬纪律：

1. `eval_path=agent`：真实 Session / Turn / 真实工具。拒则整场不跑。
2. **金标永不进模型窗**。检索的 qrels、LongBench 的 `answers`、SWE 的 `FAIL_TO_PASS` / gold patch 都不写进 Work（编码只写 GitHub issue → `problem.md`）。
3. 主指标必须是**该领域的官方尺子**，平台探针只观测「我们有没有把信号塞给模型」。

若不同意某把尺子（各节已标偏差），应修改指标契约，而不是改 loop 去拟合分数。

---

## 1. 检索：融合排序中的 `doc_id` 是否落入 qrels，不计终答

### 1.1 官方字段

题集为 **BEIR**（英：SciFact / NFCorpus / FiQA）与 **C-MTEB**（中：Covid / Medical / Ecom）。BEIR 落盘形态：

| 官方文件 | 字段 | 进 Work？ |
|----------|------|-----------|
| `queries.jsonl` | `_id`、`text`（query 原文） | `text` → 用户消息 Information need |
| `corpus.jsonl` | `_id`、`title`、`text` | 是：`sources/<doc_id>.txt` |
| `qrels/test.tsv` | `qid` · `doc_id` · `rel` | **否** |

| 子集 | query 形态 | 语料 | qrels |
|------|------------|------|-------|
| SciFact | 科学 **claim**（陈述句） | 论文摘要；文件名 = corpus `doc_id` | SUPPORT/REFUTE 该 claim 的摘要 ID |
| NFCorpus | 营养/医学信息需求 | 相关论文 | 相关文档 ID |
| FiQA | 金融论坛问句 | 帖子/回答 | 相关文档 ID |
| Covid / Medical / Ecom | 中文检索问句 | 中文文档 | 相关文档 ID |

smoke：每个子集取 **qrels 出现顺序的前 20 条**（`head_slice`，无 RNG）。第4轮 BEIR 三个子集 ×20 宏均；C-MTEB 同口径。中英分库、分指针，不得混栏。

Agent 场景为 `writing`。qrels 不在磁盘、不在 prompt。free 臂（SCORECARD 主臂）用户消息：

> Answer the information need using the local sources library. First action must search with the information need **copied verbatim**. Cite documents. Do not invent.
>
> Information need: `<官方 query 原文>`

forced 臂（L2 诊断）锁死单次 search。主栏不用 forced。

#### 示例：SciFact `_id=3`（命中）

字段取自 AllenAI SciFact / BEIR SciFact（Wadden et al., EMNLP 2020）。claim 与 corpus 的 `doc_id` 为 Semantic Scholar CorpusId，不是 PubMed PMID。物化：标题+摘要写入 `sources/14717500.txt`。

| 字段 | 值 | 进 Work？ |
|------|-----|-----------|
| 子集 / query `_id` | BEIR SciFact · `3`（smoke 切片第二条 qrels query） | case id `beir.scifact.q-3` |
| `text`（claim） | `1,000 genomes project enables mapping of genetic sequence variation consisting of rare variants with larger penetrance effects than common variants.` | 是：Information need |
| 金标 `doc_id` / `rel` | `14717500` / `1`（SciFact `evidence_label=SUPPORT`，evidence sentences 2、5） | **否** |
| 语料 `title` | *Rare Variants Create Synthetic Genome-Wide Associations*（Dickson et al., 2010；DOI `10.1371/journal.pbio.1000294`） | 是：文件正文 |

语料节选（Agent 可检索到；全文约 1849 字符）：

```text
Rare Variants Create Synthetic Genome-Wide Associations

A large number of different common variants has been associated with very modest increases of risk for various common diseases. A simulation study shows that rare variants with much greater impacts on disease risk may be responsible for some of these associations.
```

本题金标位于融合 rank 1：nDCG@10=1，R@10=1，R@100=1。

对照 SciFact `_id=1`。Information need：`0-dimensional biomaterials show inductive properties.` 金标 `31715818`（*New opportunities: the use of nanotechnologies to manipulate and track stem cells.*）不进模型窗。融合 top-10 不含该 ID → nDCG@10=0、R@10=0；52 条融合列表内含该 ID → **R@100=1.0**，nDCG@100=0.193，`bucket=weak_hits`。第一验收位取 R@100：本题是排序问题，不是零召回。

### 1.2 执行与计分

1. pull zip/HF → 物化成 Work 私有库 → 写入 **bench-postgres**（`retrieval_ops` / `retrieval_ops_zh`），与产品资料库隔离。
2. 每条 query 开一条 **writing** Session/Turn。
3. 模型按需调用 `search_sources`（每 Turn ≤3）。店内 hybrid 自己做向量∥BM25→RRF，**一次搜索的顺序评测侧不改**。
4. 评测进程读 `retrieval.completed` 里的 `ranked`/`hits` 路径，用文件名还原 `doc_id`。
5. 若模型搜了多轮：评测侧再做一次 RRF（k=60）：`score[d] += 1/(60+rank)`。单轮则顺序保持。
6. 对该 query 的 qrels 算 nDCG@k / Recall@k / MAP@k，再对 query **宏平均**。

没有 Docker harness。裁判就是 qrels + 上述公式。

### 1.3 命中定义

对一条 query：

- qrels 里 `rel > 0` 的 `doc_id` 是金标集合 G。
- 融合后的排序列表前 k 个文档是 R_k。
- **Recall@k** = |R_k ∩ G| / |G|。金标有 3 篇、top-100 里出现 2 篇 → 该 query 得 2/3。再对所有 query 平均。
- **nDCG@k**：把 qrels 的等级当分，按排序位置折现（` (2^rel-1)/log2(rank+1) `），再除以理想 DCG。排在越前的金标越值钱。
- **MAP@k**：每个命中位置的 precision 再对 |G| 平均。

**为什么第一验收位是 BEIR R@100，而不是 nDCG@10 或模型终答？**

- 金标若不进前 100，后面精排、cite、终答都是空转。R@100 先回答「池子里有没有」。
- 模型终答是否正确**故意不计分**。否则会把「会搜」和「会写摘要」缠在一起，改切块/嵌入时无法归因。
- 不把 `read_file` 读过金标当命中（那是 RET-14 旁路统计）。命中只认 **搜索排序里的文档 ID**。

**归因分桶（不得跨桶归因）：**

| 桶 | 含义 | 不该当成 |
|----|------|----------|
| `no_search` | 未调用 `search_sources` | 召回失败 |
| `query_drift` | 首次未复制官方 query | 嵌入模型失败 |
| `weak_hits` | 已检索但金标不在前列 | （此桶才是检索面） |
| infra | 超时/通道 | 模型零分 |

### 1.4 审阅时该盯的偏差

- smoke 前 20 条可能比全集更容易或更难；n=20 噪声大。
- 多轮 RRF 抬高后轮改写才召回的文档，有利于 iterative search，也会掩盖首次检索质量。
- 路径→`doc_id` 只看文件名。物化约定破了会整场假零分。
- **不测**终答 cite 是否等于金标文档。RAG 生成质量是另一把尺。

---

## 2. 上下文：抽取 `Answer:` 之后相对 LongBench `answers` 的 F1 / EM，不测检索

### 2.1 官方字段

题集为 **LongBench**（Bai et al.）。物化见 `pull.py` 的 `_normalize_longbench_row`。smoke：三类任务各最多 20 条，合计 n=60。

| 官方字段 | 含义 | 进 Work？ |
|----------|------|-----------|
| `task` / slice `idx` | `multifieldqa_en` · `hotpotqa` · `narrativeqa`；idx 为该任务切片内序号 | case id |
| `input` | 问题原文 | 是：用户消息 `Question:` |
| `context` | 长文 | 是：仅 `sources/passage.md` |
| `answers` | 可接受短答案列表 | **否** |

| 任务 | 题型 |
|------|------|
| `multifieldqa_en` | 多字段/多段英文阅读问答 |
| `hotpotqa` | 多跳短答（多篇已拼进单一 `passage.md`） |
| `narrativeqa` | 长叙事（小说/剧本）问答 |

Agent 场景为 `agent`，无 `search_sources`。用户消息（free 臂）：

> 材料在 `sources/passage.md`。先读（截断就 `offset` 续读）。grep 只用来跳，不能代替读。短短语作答，最后一行：`Answer: <phrase>`
>
> Question: `<官方问题>`

oracle 臂强制读完；主栏用 free。hotpotqa 本套件不测「自行找第二篇」。

#### 示例：`multifieldqa_en` idx 0（EM=1）

字段取自 LongBench `multifieldqa_en` 切片首条。物化：`context` → `passage.md`；`answers` 留在评测进程。

| 字段 | 值 | 进 Work？ |
|------|-----|-----------|
| `task` / `idx` | `multifieldqa_en` · `0` | case id |
| `input` | `What is the name of the most active fan club?` | 是 |
| `context` | FC Urartu（Yerevan）条目；含 Fans 段 | 是：`passage.md` |
| `answers` | `["South West Ultras fan club."]` | **否** |

`passage.md` 节选（金标句约在 offset 3043）：

```text
Football Club Urartu, commonly known as Urartu, is an Armenian professional
football team based in the capital Yerevan …

Fans
The most active group of fans is the South West Ultras fan club, mainly
composed of residents from several neighbourhoods within the
Malatia-Sebastia District of Yerevan, since the club is a de facto
representer of the district.
```

本题预测 `South West Ultras fan club`，去句号后与 gold 相等 → **EM=1，F1=1**（`n_reads=0` 仍满分：主指标不计量阅读次数）。

对照 idx 1：`input` = `Is the ISR necessary for transgene reactivation?`；`answers` = `["No, it is not necessary."]`（context 约 45634 字符）。预测 `No` → token 袋 `{no}` 对五词金标，P=1、R=1/5 → **EM=0，F1=0.333**。语义成立，EM 仍为零。idx 2 为 STM/STS 同义改写：**EM=0，F1=0.8**。

### 2.2 执行与计分

1. pull LongBench → 每题一个 Work，写入 `passage.md`。
2. agent Turn：模型 `read_file`（可多次）→ 终答。
3. 评测取终答文本，跑 `extract_pred_answer`：最后一条非空、非 `<phrase>` 占位的 `Answer:` 行；没有则整段当预测。
4. `score_prediction`（scorer **v2**）对 `answers_list` 取 max。
5. infra 失败剔除，不得记为模型零分。

没有 harness。裁判是字符串规范 + 重合。

### 2.3 命中定义

先规范化（小写、去冠词/标点、压空白；含 CJK 的金标改走按字）。

- **EM = 1** 当且仅当规范化后的预测 **等于** 任一条 gold（v2 **不做**「gold 是 pred 子串就算对」——那是 v1，会把啰嗦解释判成全对）。
- **F1** = 预测 token 与 gold token 的 bag 重合（2PR/(P+R)）；多条 gold 取最高。中文按**字**，因为空白分词对中文无意义。

**为什么必须抽 `Answer:` 行？**

模型常先写推理。若不抽，预测为 `Answer: berlin`、gold 为 `berlin` 时，v2 EM **必为 0**，F1 被标签稀释。第2轮入账 EM=0 即该口径事故。对照锚钉死为同题重打 **F1 0.5479 / EM 0.30**。

**为什么测短答案而不是「是否读到了相关段落」？**

LongBench 官方就是 QA F1/EM。读没读完是过程（`read_file` 统计），不是主指标。主指标回答：组窗被卫生/截断之后，模型还能不能从长文里拿出那个短语。

### 2.4 审阅时该盯的偏差

- 短答案 QA 惩罚正确但措辞不同的回答（EM 尤甚）；F1 给部分分，故 F1 高于 EM（0.53 vs 0.27 是尺子形态，不必然表示「半对」）。
- hotpotqa 的多篇已拼进单一 `passage.md`，不测 Agent 自行找第二篇。
- n=60、每任务 head 切片，不得当作 LongBench 全文成绩。

---

## 3. 编码：官方隐藏测是否通过；裁判为 `swebench.harness`

### 3.1 官方字段

**SWE-bench Lite** test 300 题。smoke **n5** = HF 顺序前 5 个 ID，**全是 astropy**：

`12907, 14182, 14365, 14995, 6938`

每题官方字段包括：`repo`、`base_commit`、`problem_statement`（GitHub issue）、`FAIL_TO_PASS` / `PASS_TO_PASS`（隐藏测）、`patch`（金标补丁）。后三项 **不写入 Work**（`hints_text` 同样不进）。

Agent 可见：

- 仓库 checkout 在 `base_commit`（出 issue 当时的坏树）。
- 根上 `problem.md` = `problem_statement` 全文。
- 用户消息要求：读 issue → 复现 → `search_codebase` 找定义 → `edit_file` → 再验。禁止靠网络。

官方隐藏测名称不可见（除非 issue 正文自行写到某失败测）。平台从 issue 抽取的例子覆盖义务仅来自 `problem.md`，故意不泄漏 F2P。

#### 示例：n5 未过题的官方一行（`astropy__astropy-14365`）

字段取自 HuggingFace `princeton-nlp/SWE-bench_Lite` **test** 第 3 行（与切片 `eval/official/swe_lite_slices/swe_lite_slice_5.txt` 相同）。物化见 `scripts/official_bench/repo_materialize.py`。

| 字段 | 值 | 进 Work？ |
|------|-----|-----------|
| `instance_id` | `astropy__astropy-14365` | 仅 `.agent_swe_instance.json` |
| `repo` | [`astropy/astropy`](https://github.com/astropy/astropy) | 是 |
| `base_commit` | [`7269fa3e33e8d02485a647da91a5a2a60a06af61`](https://github.com/astropy/astropy/tree/7269fa3e33e8d02485a647da91a5a2a60a06af61) | 是：坏树 |
| GitHub issue | [astropy/astropy#14365](https://github.com/astropy/astropy/issues/14365)（2023-02-06；dataset `version=5.1`） | 正文 → `problem.md` |
| `FAIL_TO_PASS` | `astropy/io/ascii/tests/test_qdp.py::test_roundtrip[True]` | **否** |
| 金标 `patch` | 命令 `IGNORECASE` **且** `v.upper() == "NO"` | **否** |
| `test_patch` | 参数化 `test_roundtrip(lowercase=True\|False)`；`True` 时非注释行全小写 | **否** |

`problem.md` 里 Agent 实际读到的题面（节选，与官方 `problem_statement` 一致）：

```text
ascii.qdp Table format assumes QDP commands are upper case
### Description
ascii.qdp assumes … they must be "READ SERR 1 2" whereas QDP …
can use "read serr 1 2".
### Expected behavior
read serr 1 2
1 0.5 1 0.5
### How to Reproduce
Table.read('test.qdp', format='ascii.qdp')
→ ValueError: Unrecognized QDP line: read serr 1 2
```

issue 例子只有小写**命令**，没有数据 token `NO`。第6轮模型仍只加 `re.IGNORECASE` 时，harness 的 `test_roundtrip[True]` 把数据行里的 `NO` 变成 `no`，F2P 失败。P2P 全绿不算通过。

对照会过的 `astropy__astropy-12907`：同一 `repo`；`base_commit` [`d16bfe05a744909de4b27f5875fe0d4ed41ce607`](https://github.com/astropy/astropy/tree/d16bfe05a744909de4b27f5875fe0d4ed41ce607)；issue [#12907](https://github.com/astropy/astropy/issues/12907)。题面是嵌套 `Pix2Sky_TAN() & cm` 的 `separability_matrix` 把后两维粘成不可分；REPL 与 F2P `test_separable[compound_model6/9]` 同向，第4–6轮均 resolved。

### 3.2 执行路径与 harness 职责

```text
checkout base_commit + 写 problem.md
  →（仅评测）等符号表 ready|stale
  → 产品 agent Turn（无人值守：写盘/exec 预批准）
  → 模型改树
  → 平台 git diff（排除 problem.md）→ predictions.jsonl
  → swebench.harness.run_evaluation
```

**Harness 职责（与 SWE-bench 论文/排行榜定义一致）：**

1. 拉起该题的 **sweb.eval Docker 镜像**（里面才是评委用的解释器、依赖、`/testbed`）。
2. 把模型补丁 apply 到与 `base_commit` 对应的树。
3. 跑两组测：
   - **FAIL_TO_PASS**：金标修复后应该由红转绿的测（「这题要修的那个」）。
   - **PASS_TO_PASS**：修之前就该绿的测（回归）。
4. **resolved** 当且仅当 F2P **全部**过 **且** P2P **全部**过。
5. 镜像内断网。缺镜像或 harness 进程崩溃 → 套件 `failed`，**禁止**写成 `resolve_rate=0`（那会把基础设施失败记成模型零分）。

平台在 Turn 里改道 `pytest` 进同一张镜像，是为了让模型在**评委环境**里复现，避免在裸工作区 `pip` / `pytest | tail`。那是解题辅助，**仍然不是**分数。分数只在 harness 终局。

`patch_rate`：git diff 非空的比例。第4–6轮都是 1.0——五题都交得出补丁，但 14365 仍 unresolved。所以交补丁 ≠ 修对。

### 3.3 命中定义

| 信号 | 是不是命中 | 为什么 |
|------|------------|--------|
| 非空 git diff | 否（只是 patch_rate） | 乱改也能有 diff |
| `fuse_ok` / 找到定义 | 否 | 找对文件不等于修对隐藏测 |
| issue 例子再跑过 | 否 | 例子在 issue 里；隐藏测可以是 issue 没写的 `test_roundtrip[True]` |
| verify_receipt | 否 | 平台催验，模型可以不理 |
| harness resolved | **是** | 与 SWE-bench 论文/排行榜同一把尺 |

**为什么不自己在工作区跑测试当分数？** Lite 每题环境不同；工作区只是源码 checkout。在错误解释器上绿，评委镜像里仍红。14365 第5–6轮就是：issue 样例没有小写 `NO`，模型只加了 `IGNORECASE`，隐藏参数化测仍红。

### 3.4 审阅时该盯的偏差

- **n5 全 astropy**，不能外推到 django 占多数的 Lite。升锚要求 n25（顺序前 25，才开始有 django）。
- 评测 `wait_ready` 让 Locate 比产品对话更乐观（产品不等索引）。
- 无人值守预批准写盘，比真实用户少一道审批摩擦。
- 同分异题：4/5 可以是「换了一题过、一题回落」，不是能力稳定在 80%。第6轮换 `gpt-5.6-luna` 后仍是同一题未过。

---

## 4. 三套件对照（审阅总表）

| | 检索 | 上下文 | 编码 |
|--|------|--------|------|
| 官方题 | BEIR / C-MTEB query | LongBench 长文+问 | GitHub issue + 坏树 |
| 可见范围 | `sources/<doc_id>.txt` + Information need | 仅 `passage.md` + Question | 工作树 + `problem.md` |
| Agent 场景 | writing | agent | agent |
| 主工具 | `search_sources` | `read_file` | `edit_file` / `run_command` |
| 裁判 | qrels + nDCG/R/MAP | 抽 Answer: 后 F1/EM | **harness** F2P∧P2P |
| 金标是否可见 | 否 | 否 | 否（issue 可见，隐藏测不可见） |
| 不测什么 | 终答是否正确 | 会不会检索 | issue 例子 / 探针 |
| smoke 偏差 | 前 20 query | 每任务 20 条 | 前 5 题全 astropy |

Wiki：`#ops-eval-why` · `#ops-eval-walk`（实例与图）· `#ops-eval-retrieval` · `#ops-eval-context` · `#ops-eval-coding`。实例原文见 [`ops-eval-walkthrough.md`](ops-eval-walkthrough.md)。
