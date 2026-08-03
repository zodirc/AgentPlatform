# Free-L1 Retrieval Tuning Brief（交给后续模型的完整上下文）

> **受众**：高级模型 / 下一轮调优负责人  
> **日期戳记**：2026-08-03（含 soft 二次冒烟 + 回滚后确认复测）  
> **唯一验收温度计**：自由搜（`eval_path=agent` · `arm=free` · L1 产品 Turn）  
> **不作为验收**：forced 臂、纯 Index L0、coding（本轮不可信）  
> **本文自含**：不依赖阅读其他专题文档即可理解流程、历史与问题

---

## 0. 当前裁决（先读）

| 项 | 结论 |
|----|------|
| 第五刀（soft lexical rerank + `search_sources` default limit 10→50） | **已回滚**；运行时已重建为回滚代码（容器内 `amp_weak` 不存在 · `limit=10`） |
| 回滚提交 | `cf87911` 还原覆盖测；`4189325` 还原功能改动（对应原 `f8f583b` / `07b4e3e`） |
| 初判回滚理由 | soft#1 free nDCG@10 **0.434 → 0.395** |
| **修订后证据** | soft#2 再跑得 **0.411**；回滚后确认跑 **0.409**。soft 两次均值 ≈ **0.403**，与回滚后几乎同带 → **20q 噪声大**；第 4 轮 **0.434 可能是偏高单次**，不能当「回滚后必回」的锚 |
| 回滚是否仍成立 | **是**——没有稳定正 Δ，无入库理由；但 **不要期待回滚本身抬 IR** |
| 当前工作平台（冒烟） | free nDCG@10 **~0.41**（非 ~0.43）；下一刀以此为对照，勿再默认 0.434 |
| SCORECARD / baseline | **未更新、不入库** |
| 行为侧前几刀（verbatim 首搜、≤2 搜次） | **保留**；但近几次复测 cap/drift 有回潮（见 §3.6） |
| 下一轮硬约束 | 继续只认 free；勿用 forced 洗白；20q 单次不作效果入库；重要刀至少 **N≥2** 同条件复跑 |

---

## 1. 系统与评测立场（必须对齐）

### 1.1 产品形态

- 平台是 **一个 AgentEngine while-loop × 多个 ScenarioProfile**。
- 用户路径：创建 Session → Turn → Runtime loop → 工具（含 `search_sources`）→ 流式事件 → 终态**。
- 检索质量进入 **Index plane**（切块 / embed / hybrid+RRF / 可选 lexical rerank）与 **静态工具契约 / system 文案**；**禁止**为刷分改 loop、强制每轮检索、或评测专用质量分支。

### 1.2 本轮评测立场（团队已确认）

1. **主臂 = 自由 agent**：题面只说明「答案在本地资料库，请给出依据」；**不**规定工具名、次数、`limit`、query 原文。
2. **只跑 / 只信 free**。forced（强制单搜隔离 Index 上限）与纯 Index 网格可以存在于代码，但**不是本团队的验收尺**。
3. **分数上涨只是工程变好的间接结果**；禁止为刷分伪造路径、注入答案、或把诊断臂分数写进主栏。
4. **行为改善 ≠ 入库**：分桶（怎么搜）可以判「正向」；宏 IR（nDCG/R）不涨则 **不** `update-baseline` / 不写 SCORECARD 主栏。

### 1.3 两轨判定（怎么读一次跑分）

| 轨 | 看什么 | 成功意味着什么 | 能否入库 |
|----|--------|----------------|----------|
| **行为桶** | `no_search` / `query_drift` / `search_cap` / `weak_hits` / `ok` | Runtime「怎么搜」更接近成熟 agent | 否（只证明行为刀） |
| **宏 IR** | nDCG@k · Recall@k · MAP@k（套件宏平均） | 排序/召回真的更好 | **仅当同协议 free 全量或明确锚点档** |

匹配优先级（确定性，无 LLM 判官）：

```text
no_search → query_drift → search_cap → weak_hits → ok
```

| bucket | 规则（摘要） | 通常对应的工程层 |
|--------|--------------|------------------|
| `no_search` | 全程未调用 `search_sources` | 搜不搜的纪律 |
| `query_drift` | 已搜，但首 query 相对原 claim 归一化编辑距离 **> 0.35** | 搜什么（keyword bag / 乱改写） |
| `search_cap` | `n_search ≥ 3` 且末两次 query 仍在换词 | 搜几次 / 何时停 |
| `weak_hits` | 行为过关，但该 case nDCG 低于套件中位 | Index / embed / fusion / 排序 |
| `ok` | 行为过关（**不论** nDCG 高低） | 行为合格 |

---

## 2. 端到端运行流程（完整细节）

### 2.1 协议与套件

| 项 | 值 |
|----|-----|
| L1 协议戳记 | `official-small-2026-08-m3`（自由主臂） |
| 历史对照 | m2 多为 **forced** 冒烟，**不可与 free 直接比绝对分后入库** |
| 检索题集 | BEIR 小量：SciFact · NFCorpus · FiQA |
| 上下文题集 | LongBench 小量（本轮旁证；非第五刀目标） |
| 编码题集 | SWE-bench Lite（本轮 **coding 跑挂/尺不稳，忽略**） |
| 冒烟档 | 每集 **`n_queries=20`**（Ops「20q/集」）；**统计噪声大，不作效果结论** |
| 锚点档（尚未入库 m3） | 全量 qrels（约 1.3k Turn 量级）才可进主栏 |

### 2.2 基础设施拓扑

```text
浏览器 / Make
    → api（Ops 编排：official_runner）
        → L1：official_agent_path
              → 产品 Session/Turn
              → runtime AgentEngine（真实工具面）
              → postgres（产品库）+ 本机/卷上的 BEIR 物化 sources
        → （可选）L0：agent-bench + bench-postgres
              → 组件旁路，不进本 brief 的验收
    → 产物：eval/reports/official/runs/<uuid>/
         manifest.json · result.json · process.jsonl · report.html
    → publish → ops_eval_runs（suite=official）
```

要点：

- L1 分数来自 **Turn 里真实 `search_sources` 返回的 ranked hits**（事件合并：first-seen union，按合并序取前 100 计 nDCG@100；未搜计 0）。
- 模型可见 excerpt 较短；**IR 计分用完整 ranked 列表**，与 excerpt 窗口无关。
- 评测用 Ops 表单里的 **BENCH 模型**（如 `deepseek-v4-flash`），不是用户「设置 → 模型」热路径配置。

### 2.3 推荐操作路径（Ops）

1. `make up`（栈健康；含 api / runtime / web / postgres；Official 相关常开 bench profile）。
2. `.env` 中有非空 `OPS_TEST_SECRET`；浏览器打开  
   `http://localhost/ops/<OPS_TEST_SECRET>/official`。
3. 选择目标 **检索（BEIR）**；评测路径 **L1 agent**；臂 **free**（不要选 forced 当验收）。
4. 冒烟：每集 query 上限 **20**；填齐评测模型（provider / base_url / model / api_key）。
5. 开始 → 看阶段条：Pull（可缓存）→ Eval → Regress。
6. 结束后读：宏指标条、分桶计数、`report.html`、Run 历史。

### 2.4 推荐操作路径（Make，等价）

```bash
# 仓库根；已 make up；已 source .env
make official-bench-retrieval-agent QUERY_LIMIT=20
# 需要 BENCH_MODEL_*（或 Ops 等价模型字段）已可用
```

对照上次：

```bash
make official-bench-compare   # 仅同 protocol + 同 eval_path + 同档才比 Δ
# 认可后才：make official-bench-update-baseline   # 本轮明确禁止
```

### 2.5 单题 L1 检索执行步骤（自由臂）

```text
1. Pull：BEIR 子集进 BENCH_DATA_DIR（或容器内 /data/ops-official/data）；已有则 skip。
2. 物化：该 query 的语料进隔离 Work 的 sources/（题面 = claim / 问题文本）。
3. 开 Session + Turn（scenario 走 agent 工具面；ops_eval 标记）。
4. 模型自由行动：可 search_sources / read_file / grep / list_dir …
5. 收集本 Turn 所有 retrieval.completed：按 first-seen 合并 doc 序。
6. 用官方 IR 指标对 qrels 打分（nDCG@1/10/100、R@k、MAP@k）。
7. 写 L2 探针：searched、n_search、queries[]、query_drift、steps、tools、bucket。
8. 套件宏平均；写 result/manifest；可选 publish。
```

### 2.6 产物与指标键名

`TEST.log` 一类导出常见键（L1 free 时两套相等）：

```text
official.retrieval.ndcg_at_10
official.retrieval.recall_at_10
official.retrieval.recall_at_100
official.retrieval.agent.ndcg_at_10   # 与上同值（agent 路径）
…
official.context.agent_f1
official.context.agent_em
```

分库（例）在 `result.json` 的 `cases`：`beir.scifact.agent` / `beir.nfcorpus.agent` / `beir.fiqa.agent`。

---

## 3. 优化时间线与对照结果

### 3.1 总览表（检索 · free L1 · 冒烟 20q/集，除非另行标注）

| 轮次 | 标识 | 改动摘要 | 行为桶（要点） | nDCG@10 | R@10 | R@100 | 裁决 |
|------|------|----------|----------------|---------|------|-------|------|
| 参考 | m2 `4996145f` | **forced** 单搜冒烟（非 free） | （强制搜） | 0.403 | 0.365 | 0.602 | 历史尺；**不可当 free 锚** |
| 0 | `ccad8723` | m3 free 基线分桶 | drift **83%** | （见后轮） | — | — | 行为极差 → 拧契约 |
| 1 | `caf49721` | C-2：收紧首搜忠实度 | drift 83%→**67%**；ok→25% | **0.418**（对照前序约 0.489↓） | — | — | 行为↑ IR↓/噪 → **不入库** |
| 2 | 二次补强 | 契约：query **近乎原文**；禁搜前反复 `list_dir` | （落地后进第 3 轮测） | — | — | — | 针对 keyword bag |
| 3 | `8a6b5814` | 复测 verbatim | drift **5%**；ok **77%**；search_cap **18%** | **0.427** | **0.454** | **0.565** | 原文首搜成立；cap 仍高 |
| 4 | `0526901a` | ≤2 搜；有 hit 则停搜改读 | cap **18%→2%**；ok **77%→92%** | **0.434** | ≈持平 | 略降 | **行为验收通过；IR 平台期 → 不入库；停拧搜次** |
| C-3 | `c3_grid_…` | Index fusion 8 点网格；**rerank=0** | （非 L1） | macro **0.54552 全相同** | — | — | **保持 `RETRIEVAL_PROFILE=default`**；打平=无证据改 fusion |
| 5 | `07b4e3e` + 测 `f8f583b` | soft lexical rerank（bonus 按 \|score\| 缩放）+ default limit **10→50** | 意图：抬排序天花板，间接抬 free | 目标：相对 0.43 **上升** | — | — | 假设：长 claim overlap 洗 RRF |
| 5a | `a6de7860` soft#1 | 热部署后 free 20q（仍 soft 代码） | ok 为主；fail 7；少量 drift/no_search | **0.395** | **0.437** | **0.504** | 初看相对第 4 轮 −0.039 |
| 5b | `f7fc1b1a` soft#2 | **同 soft 代码再跑**（回滚部署前） | ok 54；search_cap 3；drift 2；no_search 1；57/6 | **0.411** | **0.466** | **0.517** | 相对 soft#1 **+0.016**（噪声）；仍低于 0.434 |
| 回滚 | `4189325` / `cf87911` | 还原第 5 刀；随后 `make up-runtime` 类重建 | — | — | — | — | **已执行** |
| 5c | `689cfe71` 回滚后 | 容器确认 soft=False · limit=10；free 20q | ok 54；search_cap 3；drift 3；59/4 | **0.409** | **0.412** | **0.468** | **未回到 0.434**；与 soft#2 同带 |

### 3.2 同温度计多跑对照（free · 20q · 修订结论）

| 标签 | run_id | nDCG@10 | R@10 | R@100 | vs 第 4 轮 0.434 |
|------|--------|---------|------|-------|------------------|
| 第 4 轮高峰 | `0526901a` | 0.434 | ~0.45 | ~0.56 | — |
| soft#1 | `a6de7860` | 0.395 | 0.437 | 0.504 | −0.039 |
| soft#2 | `f7fc1b1a` | 0.411 | 0.466 | 0.517 | −0.023 |
| soft 两次均值 | — | **0.403** | — | — | **−0.031** |
| **回滚后确认** | `689cfe71` | **0.409** | **0.412** | **0.468** | −0.026 |

**修订读法（重要）：**

1. soft#1 的 0.395 **偏悲观**；同配置 soft#2 拉回 0.411 → 单次 20q 抖动约 **1.5–4pp** 量级。
2. 回滚后 **0.409 ≈ soft#2**，**没有**「一回滚就回到 0.434」。回滚证明的是「第五刀无稳定增益、可丢」，不是「第五刀造成了可逆的稳定回归」。
3. 第 4 轮 **0.434 不宜再当硬锚**；当前诚实冒烟平台按 **~0.41** 记。
4. 回滚后 R@10/R@100 反而略弱于 soft#2 → 深度/行为噪声仍在，勿过度解读单点。

### 3.2b 分库快照（三次邻近 free 跑）

| 子集 / 跑次 | soft#1 nDCG@10 | soft#2 | 回滚后 |
|-------------|----------------|--------|--------|
| SciFact | 0.516 | 0.544 | 0.536 |
| NFCorpus | 0.307 | 0.276 | 0.336 |
| FiQA | 0.362（R10=R100≈0.49） | 0.412（R10=R100≈0.54） | 0.353（R10=R100≈0.49） |

NFCorpus / FiQA 仍是宏平均拖累；FiQA 多次出现 **R@10≈R@100**（合并 hit 有效深度不足）。

soft#1 失败轨迹特征（7 fail）：多数已搜 1 次后大量 `list_dir`/`grep`/`read_file`；另有 `no_search`、`query_drift`。free 分数仍耦合搜后行为。

### 3.3 第 5 刀设计意图（为何后来想动 Index）

当时叙事：

- 行为桶已干净 → 再拧 prompt/搜次 **收益递减**。
- free nDCG@10≈0.43，而 Index 冒烟（fusion、rerank 关闭）≈0.55；**R@10 已接近** → 猜「排序」而非「漏检」。
- 假设：lexical rerank 对长 claim 的 token-overlap 加分淹没 RRF（量级 ~0.01）。
- 改法：weak/strong bonus 按 `max(|score|)` 缩放 + `tanh`；`search_sources` 默认 limit 10→50；agent system 文案改为 prefer limit≥50。

**与团队最终立场的冲突**：该刀虽自称 Index/排序，但验收写的是「热部署后 **Ops free L1 20q**」。团队后来明确 **只认自由搜** → 不以 forced 洗白；多跑之后进一步改为：**无稳定正 Δ 即丢刀**，同时承认冒烟噪声，不以单次 0.395 叙事「深度回归」。

### 3.4 Context 旁证（非第 5 刀目标）

| 跑次 | F1 | EM | 备注 |
|------|----|----|------|
| m2 forced 冒烟 `ebc6abfd` | 0.315 | 0.05 | 旧尺 |
| free `48c4aee1`（与第 5 刀同日） | 0.331 | 0.25 | 60/60 pass；桶：ok 35 / verbose 15 / gave_up_early 10 |

**不要**用 context 微升为 soft-rerank 背书（改动面几乎纯 retrieval）。

### 3.5 Coding

本轮最新 coding official run **failed**；历史 patch_rate 在无 repo/无 harness 下 **无效果含义**。后续思考 **忽略 coding**，直至尺修干净。

### 3.6 行为桶近况（相对第 4 轮高峰有回潮）

| 跑次 | ok（约） | search_cap | query_drift | no_search | pass/fail |
|------|----------|------------|-------------|-----------|-----------|
| 第 4 轮 `0526901a` | **92%** | **2%** | 低 | 2 | — |
| soft#1 `a6de7860` | 高（58 ok 量级） | 低 | 1 | 1 | 56/7 |
| soft#2 `f7fc1b1a` | 54 | **3** | **2** | 1 | 57/6 |
| 回滚后 `689cfe71` | 54 | **3** | **3** | 0 | 59/4 |

结论：契约刀仍在代码里，但 **近三次 free 冒烟的 cap/drift 不如第 4 轮干净**；行为「保持」不能假设为永远 92% ok。

---

## 4. 当前问题清单（给下一模型）

### P1 — 宏 IR 工作平台下修到 ~0.41

- 不宜再写「停在 0.42–0.43」；**当前诚实冒烟中枢 ≈ 0.41**（soft 均值 0.403；回滚后 0.409）。
- 第 4 轮 0.434 视为 **历史高峰单次**，不是可复现基线。
- **尚未**有「同协议 free、改动可归因、IR 显著正 Δ、N≥2」的入库候选。

### P2 — 分库极不均衡

- **NFCorpus** 长期拖宏平均（R@10 极低是官方多 qrels 特性 + 深度/排序问题缠在一起）。
- **FiQA** 多次 **R@10≈R@100** → 合并 hit 列表有效深度不够（模型 `limit`、停搜过早、或合并策略）。

### P3 — free 分数 ≠ 纯 Index

- free nDCG 含 **是否搜、query 忠实、搜几次、读哪些、hit 合并序**。
- 第 5 刀把「排序」和「default limit」绑在同一 commit，已整包回滚，**未拆因**。

### P4 — 冒烟噪声（已用三次邻近跑钉死）

- soft#1→#2 同配置 **+0.016**；回滚后与 soft#2 差 **<0.003**（nDCG@10）。
- 单次 −4pp **不够**证明「稳定回归」；**N≥2 同条件**才谈刀的去留与入库。
- 仍不足以分辨 0.01 级 fusion（C-3 八点打平已提示）。

### P5 — 弱命中桶信号不足

- 应用 `weak_hits` 驱动 Index/embed 票；强制输出分桶直方图 + 低 nDCG case 列表。

### P6 — 行为桶回潮（已部分证实）

- 回滚后确认跑仍见 **search_cap×3、query_drift×3**，未回到第 4 轮 92% ok / 2% cap。
- 搜后 `list_dir`/`grep` 逛目录问题在 soft#1 fail 中仍在；需单独观察，勿与 IR 刀绑死。

### P7 — Embed / INDEX 升级未做

- 生产仍 MiniLM-L6-v2 @384；升级需 Turn 外重建 + `INDEX_VERSION` bump + free 配对；**未开工**。
- Fusion 默认保持；无证据切 `vector_heavy`。

---

## 5. 回滚后代码与运行时状态（已确认）

Git 与容器（2026-08-03 确认复测时）一致：

- `rerank.py`：原 lexical 加分（`score + overlap*0.15 + …`），**无** `amp_weak` / `tanh` 缩放（`docker exec`：`'amp_weak' in source` → False）。
- `search_sources`：**default `limit=10`**。
- agent `system.md`：prefer limit ≥20（非 50）类表述。
- soft 边界覆盖测随 revert 移除。

**仍保留**：verbatim 首搜契约、≤2 搜次 / 有 hit 停搜、C-1 读预算、C-3「保持 default」、m3 free runner 与分桶探针。

---

## 6. 建议的下一轮思考框架（不规定具体补丁）

请后续模型在 **只认 free** 的约束下推演，优先回答：

1. **基线重钉**：以回滚后 `689cfe71`（≈0.409）为冒烟对照，是否再跑 1–2 次取均值当「当前平台」？
2. **IR 若要动**：如何在 free 轨迹上可观测（`weak_hits` hit 序 vs qrels）？**禁止**再把排序假设与 limit/行为绑同一 commit；重要刀 **N≥2**。
3. **NFCorpus / FiQA**：分治还是统一杠杆？深度（limit/合并）vs 相关性（embed）怎么用 free 证据拆开？
4. **行为回潮**：cap/drift 从 2%/低 → 再出现 3+，要不要单独开契约/预算刀，还是先当噪声？
5. **embed 升级票**：前置测量、回滚条件、R1–R5（热路径无同步重嵌）如何写死？
6. **入库门禁**：何种 free 跑量 + 重复次数才允许碰 SCORECARD？

禁止项提醒：

- 不要把 forced/Index 涨分写成主栏成功。
- 不要在 free 掉分时用诊断臂「上限涨了」否决回滚。
- 不要在 20q **单次**噪声上 `update-baseline`。
- 不要假设「回滚后 IR 应回到 0.434」。

---

## 7. 关键原始读数附录

### 7.1 soft#1 · `a6de7860`（第 5 刀首次 free 复测）

```text
official.retrieval.ndcg_at_10 = 0.3950
official.retrieval.recall_at_10 = 0.4371
official.retrieval.recall_at_100 = 0.5037
official.retrieval.ndcg_at_1 = 0.3556
official.retrieval.map_at_10 = 0.2627
official.retrieval.n_queries = 20
official.context.agent_f1 = 0.3305
official.context.agent_em = 0.2500
```

context 旁证 run：`48c4aee1-7149-4be2-8ea3-5e95cef3f661`。

### 7.2 soft#2 · `f7fc1b1a`（同 soft 代码再跑 · 回滚部署前）

```text
official.retrieval.ndcg_at_10 = 0.4107
official.retrieval.recall_at_10 = 0.4658
official.retrieval.recall_at_100 = 0.5166
official.retrieval.ndcg_at_1 = 0.3556
official.retrieval.map_at_10 = 0.2821
official.retrieval.n_queries = 20
# 本次 TEST.log 无 context 段
```

pass/fail 57/6；桶：ok 54 · search_cap 3 · query_drift 2 · no_search 1。

### 7.3 回滚后确认 · `689cfe71`（容器 soft=False · limit=10）

```text
official.retrieval.ndcg_at_10 = 0.4085
official.retrieval.recall_at_10 = 0.4116
official.retrieval.recall_at_100 = 0.4680
official.retrieval.ndcg_at_1 = 0.3944
official.retrieval.map_at_10 = 0.2746
official.retrieval.n_queries = 20
```

pass/fail 59/4；桶：ok 54 · search_cap 3 · query_drift 3。  
分库：SciFact 0.536 / NFCorpus 0.336 / FiQA 0.353。

### 7.4 第 4 轮行为验收数字（历史高峰 · 非当前可复现锚）

```text
search_cap: 18% → 2%
ok:         77% → 92%
nDCG@10:    0.427 → 0.434（持平级，不入库；其后多次复测未再现）
```

### 7.5 C-3 fusion 冒烟

```text
8 个 fusion 配置 macro nDCG@10 全为 0.54552（rerank 关闭）
结论：不改生产 RETRIEVAL_PROFILE=default
```

---

## 8. 一页决策树（给后续模型）

```text
改动候选
  ├─ 只改善行为桶、IR 持平     → 可合入产品；不入库；记录「行为正向」
  ├─ free IR 显著↑（同协议·N≥2）→ 才考虑 compare + update-baseline
  ├─ free IR ↓ 但 N=1 噪声带内 → 同配置再跑；勿单次定生死
  ├─ free IR 无稳定正 Δ（N≥2） → 丢刀 / 回滚；禁止 forced 洗白
  └─ 仅 Index/L0/forced ↑      → 对本团队 = 未验收；最多当假说，不进主栏
```

**当前节点**：第五刀 **已回滚**；回滚确认跑完成 → IR **未**回到 0.434，与 soft 二次冒烟同处 **~0.41 平台**；行为桶较第 4 轮有回潮。下一轮从 **~0.41 + 分桶回潮** 出发设计杠杆，不要从 0.434 出发。
