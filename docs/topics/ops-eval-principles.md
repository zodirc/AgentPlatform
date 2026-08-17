# Ops L1 评测原理（审阅用）

本文回答：怎么评测、给了什么题、怎么跑完、harness 干什么、什么叫命中、为什么这样算。Wiki 同文在「评测原理」页。数字仍以 [`RESULTS.md`](../../eval/official/baseline/RESULTS.md) 为准。

冲突时：**计分代码 > 本文**。检索：`metrics_ir.py` · `agent_path_extract.py`。上下文：`context_run.py`。编码：`swebench.harness` + `suite_coding.py`。

---

## 0. 这套评测在回答哪句话

**产品同一条 Turn 路径，面对官方题集，能不能交出官方指标。**

不是：旁路脚本直接 embed、直接喂 completion、或空补丁通管道。那些是 L0 对照，不进效果主栏。

因此三套件共用三条硬纪律：

1. `eval_path=agent`：真实 Session / Turn / 真实工具。拒则整场不跑。
2. **金标永不进模型窗**。检索的 qrels、LongBench 的 `answers`、SWE 的 `FAIL_TO_PASS` / gold patch 都不写进 Work（编码只写 GitHub issue → `problem.md`）。
3. 主指标必须是**该领域的官方尺子**，平台探针只观测「我们有没有把信号塞给模型」。

你可以不同意某把尺子（下面每节都标了偏差）。不同意时改的是**定义**，不是改 loop 去刷分。

---

## 1. 检索：测「搜没搜到金标文档」，不测「答对没有」

### 1.1 给了什么题目

官方来源 **BEIR**（英）和 **C-MTEB**（中），不是产品用户随口问。

| 子集 | 题长什么样 | 库里是什么 | 金标 qrels |
|------|------------|------------|------------|
| SciFact | 一条科学 **claim**（陈述句，不是「请检索」） | 论文摘要，文件名 = corpus `doc_id` | 哪些摘要 SUPPORT/REFUTE 该 claim |
| NFCorpus | 营养/医学信息需求 | 相关论文 | 相关文档 ID |
| FiQA | 金融论坛问句 | 帖子/回答 | 相关文档 ID |
| Covid / Medical / Ecom Retrieval | 中文检索问句 | 中文文档 | 相关文档 ID |

smoke 不是随机抽：每个子集取 **qrels 顺序的前 20 条**（`head_slice`，无 RNG）。第4轮 BEIR 三个子集 ×20 ≈ 宏均；C-MTEB 同口径。

Agent **看不到** qrels。它看到的是：该 Work 的 `sources/<doc_id>.txt` 整库，外加用户消息（free 臂，SCORECARD 主臂）：

> Answer the information need using the local sources library. First action must search with the information need **copied verbatim**. Cite documents. Do not invent.
>
> Information need: `<官方 query 原文>`

forced 臂（L2 诊断）会命令「只 search 一次、query 锁死」。主栏不用 forced。

### 1.2 怎么跑完

1. pull zip/HF → 物化成 Work 私有库 → 写入 **bench-postgres**（`retrieval_ops` / `retrieval_ops_zh`），与产品资料库隔离。
2. 每条 query 开一条 **writing** Session/Turn。
3. 模型按需调用 `search_sources`（每 Turn ≤3）。店内 hybrid 自己做向量∥BM25→RRF，**一次搜索的顺序评测侧不改**。
4. 评测进程读 `retrieval.completed` 里的 `ranked`/`hits` 路径，用文件名还原 `doc_id`。
5. 若模型搜了多轮：评测侧再做一次 RRF（k=60）：`score[d] += 1/(60+rank)`。单轮则顺序保持。
6. 对该 query 的 qrels 算 nDCG@k / Recall@k / MAP@k，再对 query **宏平均**。

没有 Docker harness。裁判就是 qrels + 上述公式。

### 1.3 什么叫命中，为什么这样算

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

**不命中的典型原因（先分桶再改系统）：**

| 桶 | 含义 | 不该当成 |
|----|------|----------|
| `no_search` | 模型没点 `search_sources` | 「召回差」 |
| `query_drift` | 第一下没有复制官方 query | 「嵌入模型差」 |
| `weak_hits` | 搜了但金标不在前列 | 才是检索面问题 |
| infra | 超时/通道 | 模型零分 |

### 1.4 审阅时该盯的偏差

- smoke 前 20 条可能比全集更容易或更难；n=20 噪声大。
- 多轮 RRF 会抬「后轮改写 query 才搜到的文档」，对 iterative search 友好，也会掩盖第一下检索有多差。
- 路径→`doc_id` 只看文件名。物化约定破了会整场假零分。
- **不测**终答 cite 是否等于金标文档。RAG 生成质量是另一把尺。

---

## 2. 上下文：测「读完长文后短答案对不对」，不测检索

### 2.1 给了什么题目

**LongBench** 小切，任务三类（每类最多 20 条，合计 n=60 smoke）：

| 任务 | 题型 |
|------|------|
| `multifieldqa_en` | 多字段/多段英文阅读问答 |
| `hotpotqa` | 多跳问答（答案仍是短短语） |
| `narrativeqa` | 长叙事（小说/剧本）问答 |

每题官方带：`context`（长文）+ `input`（问题）+ `answers`（一个或多个可接受短答案）。

Agent 看到的 **不是** 检索库。Work 里只有 `sources/passage.md` = 该题 context。用户消息（free 臂）：

> 材料在 `sources/passage.md`。先读（截断就 `offset` 续读）。grep 只用来跳，不能代替读。短短语作答，最后一行：`Answer: <phrase>`
>
> Question: `<官方问题>`

没有 `search_sources`（agent 场景）。oracle 臂会更死地要求读完；主栏用 free。

### 2.2 怎么跑完

1. pull LongBench → 每题一个 Work，写入 `passage.md`。
2. agent Turn：模型 `read_file`（可多次）→ 终答。
3. 评测取终答文本，跑 `extract_pred_answer`：最后一条非空、非 `<phrase>` 占位的 `Answer:` 行；没有则整段当预测。
4. `score_prediction`（scorer **v2**）对 `answers_list` 取 max。
5. infra 失败剔除，不算模型零分。

没有 harness。裁判是字符串规范 + 重合。

### 2.3 什么叫命中，为什么这样算

先规范化（小写、去冠词/标点、压空白；含 CJK 的金标改走按字）。

- **EM = 1** 当且仅当规范化后的预测 **等于** 任一条 gold（v2 **不做**「gold 是 pred 子串就算对」——那是 v1，会把啰嗦解释判成全对）。
- **F1** = 预测 token 与 gold token 的 bag 重合（2PR/(P+R)）；多条 gold 取最高。中文按**字**，因为空白分词对中文无意义。

**为什么必须抽 `Answer:` 行？**

Agent 会先写推理。若不抽，预测是 `Answer: berlin`，gold 是 `berlin`，v2 EM **必 0**，F1 被标签稀释。第2轮入账 0.000 EM 就是这个口径事故。对照锚钉死为同题重打 **F1 0.5479 / EM 0.30**。

**为什么测短答案而不是「是否读到了相关段落」？**

LongBench 官方就是 QA F1/EM。读没读完是过程（`read_file` 统计），不是主指标。主指标回答：组窗被卫生/截断之后，模型还能不能从长文里拿出那个短语。

### 2.4 审阅时该盯的偏差

- 短答案 QA **惩罚**正确但换了一种说法（EM 尤甚）；F1 给部分分，所以 F1 会高于 EM（0.53 vs 0.27 是尺子形态，不一定是模型「半对」）。
- 多跳题（hotpotqa）在「单文件 passage」里已经把多篇拼好了，测的不是 Agent 自己找第二篇。
- n=60、每任务 head 切片，不能当 LongBench 全文成绩。

---

## 3. 编码：测「隐藏测过不过」，harness 才是裁判

### 3.1 给了什么题目

**SWE-bench Lite** test 300 题。smoke **n5** = HF 顺序前 5 个 ID，**全是 astropy**：

`12907, 14182, 14365, 14995, 6938`

每题官方字段包括：`repo`、`base_commit`、`problem_statement`（GitHub issue）、`FAIL_TO_PASS` / `PASS_TO_PASS`（隐藏测）、`patch`（金标补丁）。后三项 **不写入 Work**。

Agent 看到的：

- 仓库 checkout 在 `base_commit`（出 issue 当时的坏树）。
- 根上 `problem.md` = issue 正文。
- 用户消息要求：读 issue → 复现 → `search_codebase` 找定义 → `edit_file` → 再验。禁止靠网络。

它 **看不到** 官方隐藏测名字（除非 issue 正文自己写了某个失败测）。平台从 issue 抽的「例子覆盖」也只来自 `problem.md`，故意不泄漏 F2P。

### 3.2 怎么跑完；harness 承担什么

```text
checkout base_commit + 写 problem.md
  →（仅评测）等符号表 ready|stale
  → 产品 agent Turn（无人值守：写盘/exec 预批准）
  → 模型改树
  → 平台 git diff（排除 problem.md）→ predictions.jsonl
  → swebench.harness.run_evaluation
```

**Harness 的角色（这是官方定义，不是我们发明的）：**

1. 拉起该题的 **sweb.eval Docker 镜像**（里面才是评委用的解释器、依赖、`/testbed`）。
2. 把模型补丁 apply 到与 `base_commit` 对应的树。
3. 跑两组测：
   - **FAIL_TO_PASS**：金标修复后应该由红转绿的测（「这题要修的那个」）。
   - **PASS_TO_PASS**：修之前就该绿的测（回归）。
4. **resolved** 当且仅当 F2P **全部**过 **且** P2P **全部**过。
5. 镜像里断网。缺镜像或 harness 进程崩溃 → 套件 `failed`，**禁止**写成 `resolve_rate=0`（那会冤枉模型）。

平台在 Turn 里改道 `pytest` 进同一张镜像，是为了让模型在**评委环境**里复现，避免在裸工作区 `pip` / `pytest | tail`。那是解题辅助，**仍然不是**分数。分数只在 harness 终局。

`patch_rate`：git diff 非空的比例。第4–5轮都是 1.0——五题都交得出补丁，但 14365 仍 unresolved。所以交补丁 ≠ 修对。

### 3.3 什么叫命中，为什么这样算

| 信号 | 是不是命中 | 为什么 |
|------|------------|--------|
| 非空 git diff | 否（只是 patch_rate） | 乱改也能有 diff |
| `fuse_ok` / 找到定义 | 否 | 找对文件不等于修对隐藏测 |
| issue 例子再跑过 | 否 | 例子在 issue 里；隐藏测可以是 issue 没写的 `test_roundtrip[True]` |
| verify_receipt | 否 | 平台催验，模型可以不理 |
| harness resolved | **是** | 与 SWE-bench 论文/排行榜同一把尺 |

**为什么不自己在工作区跑测试当分数？** Lite 每题环境不同；工作区只是源码 checkout。在错误解释器上绿，评委镜像里仍红。14365 第5轮就是：issue 样例没有小写 `NO`，模型只加了 `IGNORECASE`，隐藏参数化测仍红。

### 3.4 审阅时该盯的偏差

- **n5 全 astropy**，不能外推到 django 占多数的 Lite。升锚要求 n25（顺序前 25，才开始有 django）。
- 评测 `wait_ready` 让 Locate 比产品对话更乐观（产品不等索引）。
- 无人值守预批准写盘，比真实用户少一道审批摩擦。
- 同分异题：4/5 可以是「换了一题过、一题回落」，不是能力稳定在 80%。

---

## 4. 三套件对照（审阅总表）

| | 检索 | 上下文 | 编码 |
|--|------|--------|------|
| 官方题 | BEIR / C-MTEB query | LongBench 长文+问 | GitHub issue + 坏树 |
| Agent 场景 | writing | agent | agent |
| 主工具 | `search_sources` | `read_file` | `edit_file` / `run_command` |
| 裁判 | qrels + nDCG/R/MAP | 抽 Answer: 后 F1/EM | **harness** F2P∧P2P |
| 金标是否可见 | 否 | 否 | 否（issue 可见，隐藏测不可见） |
| 不测什么 | 终答是否正确 | 会不会检索 | issue 例子 / 探针 |
| smoke 偏差 | 前 20 query | 每任务 20 条 | 前 5 题全 astropy |

Wiki：`#ops-eval-why` · `#ops-eval-walk`（实例与图）· `#ops-eval-retrieval` · `#ops-eval-context` · `#ops-eval-coding`。实例原文见 [`ops-eval-walkthrough.md`](ops-eval-walkthrough.md)。
