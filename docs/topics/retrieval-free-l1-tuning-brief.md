# Free-L1 Retrieval Tuning Brief（交给后续模型的完整上下文）

> **受众**：高级模型 / 下一轮调优负责人  
> **日期戳记**：2026-08-03  
> **唯一验收温度计**：自由搜（`eval_path=agent` · `arm=free` · L1 产品 Turn）  
> **不作为验收**：forced 臂、纯 Index L0、coding（本轮不可信）  
> **本文自含**：不依赖阅读其他专题文档即可理解流程、历史与问题

---

## 0. 当前裁决（先读）

| 项 | 结论 |
|----|------|
| 第五刀（soft lexical rerank + `search_sources` default limit 10→50） | **已回滚** |
| 回滚提交 | `cf87911` 还原覆盖测；`4189325` 还原功能改动（对应原 `f8f583b` / `07b4e3e`） |
| 回滚原因 | 唯一温度计 **free L1 20q** 上 nDCG@10 **0.434 → 0.395**（符号与目标相反） |
| SCORECARD / baseline | **未更新、不入库** |
| 行为侧前几刀（verbatim 首搜、≤2 搜次） | **保留**（行为桶显著变好；宏 IR 平台期） |
| 下一轮硬约束 | 继续只认 free；勿用 forced 为 free 掉分开脱；20q 冒烟不作效果入库 |

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
| 5 复测 | `a6de7860` / `TEST.log` | 热部署后 free 20q | ok 为主；仍有 fail / 少量 drift·no_search | **0.395** | **0.437** | **0.504** | **相对第 4 轮 −0.039 → 失败** |
| 回滚 | `4189325` / `cf87911` | 还原第 5 刀代码与覆盖测 | — | 待同条件复测确认回到 ~0.43 | — | — | **已执行** |

### 3.2 第 4 轮 → 第 5 轮 详细 Δ（同一温度计：free）

| 指标 | 第 4 轮后（`0526901a`） | 第 5 轮后（`a6de7860`） | Δ |
|------|-------------------------|-------------------------|---|
| nDCG@10 | 0.434 | 0.395 | **−0.039** |
| R@10 | ~0.45 量级（第 3 轮 0.454） | 0.437 | 略降 |
| R@100 | 第 3 轮 0.565；第 4 略降 | 0.504 | **明显降** |
| 用例 | 约 60 | 63（56 pass / 7 fail） | — |

第 5 轮分库快照（`a6de7860` / `result.json`）：

| 子集 | nDCG@10 | R@10 | R@100 |
|------|---------|------|-------|
| SciFact | ≈0.516 | ≈0.750 | ≈0.875 |
| NFCorpus | ≈0.307 | ≈0.070 | ≈0.144 |
| FiQA | ≈0.362 | ≈0.492 | ≈0.492（R@10≈R@100 → 深度不足） |

失败轨迹特征（7 fail，非完整归因）：多数 **已搜 1 次**，随后大量 `list_dir` / `grep` / `read_file`；另有 `no_search`、`query_drift` 各见。说明 free 分数仍耦合 **搜后行为**，不是纯 Index 读数。

### 3.3 第 5 刀设计意图（为何后来想动 Index）

当时叙事：

- 行为桶已干净 → 再拧 prompt/搜次 **收益递减**。
- free nDCG@10≈0.43，而 Index 冒烟（fusion、rerank 关闭）≈0.55；**R@10 已接近** → 猜「排序」而非「漏检」。
- 假设：lexical rerank 对长 claim 的 token-overlap 加分淹没 RRF（量级 ~0.01）。
- 改法：weak/strong bonus 按 `max(|score|)` 缩放 + `tanh`；`search_sources` 默认 limit 10→50；agent system 文案改为 prefer limit≥50。

**与团队最终立场的冲突**：该刀虽自称 Index/排序，但验收写的是「热部署后 **Ops free L1 20q**」。团队后来明确 **只认自由搜** → free 下行即否决，**不再用 forced 补测洗白**。

### 3.4 Context 旁证（非第 5 刀目标）

| 跑次 | F1 | EM | 备注 |
|------|----|----|------|
| m2 forced 冒烟 `ebc6abfd` | 0.315 | 0.05 | 旧尺 |
| free `48c4aee1`（与第 5 刀同日） | 0.331 | 0.25 | 60/60 pass；桶：ok 35 / verbose 15 / gave_up_early 10 |

**不要**用 context 微升为 soft-rerank 背书（改动面几乎纯 retrieval）。

### 3.5 Coding

本轮最新 coding official run **failed**；历史 patch_rate 在无 repo/无 harness 下 **无效果含义**。后续思考 **忽略 coding**，直至尺修干净。

---

## 4. 当前问题清单（给下一模型）

### P1 — 宏 IR 停在平台期（free）

- 行为刀已把 drift/cap 压下去，但 free nDCG@10 仍在 **~0.42–0.43** 平台，且曾因排序刀掉到 **0.395**。
- **尚未**有「同协议 free、改动可归因、IR 显著正 Δ」的入库候选。

### P2 — 分库极不均衡

- **NFCorpus** 长期拖宏平均（R@10 极低是官方多 qrels 特性 + 深度/排序问题缠在一起）。
- **FiQA** 出现 R@10≈R@100 → 合并 hit 列表有效深度不够（模型 `limit`、停搜过早、或合并策略）。

### P3 — free 分数 ≠ 纯 Index

- 即使用户拒绝跑 forced，也必须承认：free nDCG 含 **是否搜、query 忠实、搜几次、读哪些、hit 合并序**。
- 第 5 刀把「排序」和「default limit」绑在同一 commit，free 复测失败后 **无法 internally 拆因**（已整包回滚）。

### P4 — 冒烟噪声

- 20q/集方差大；单次 −4pp 足够 **否决该刀**，不足以精细比较 0.01 级 fusion 差异（C-3 八个点打平已提示）。

### P5 — 弱命中桶信号不足

- 行为过关后，应用 `weak_hits` 驱动 Index/embed 票；当前公开复盘里 **weak_hits 计数偏少/未成为主叙事**，下一轮应强制输出分桶直方图 + 低 nDCG case 列表。

### P6 — 搜后行为回潮风险

- 第 5 轮 fail 里再现「搜完去逛目录」；第 2 刀曾禁搜前 `list_dir`，**搜后**纪律可能仍松。
- 回滚后应用第 4 轮同条件 free 复测，确认行为桶仍在 ~ok 90% / cap~2% / drift 低。

### P7 — Embed / INDEX 升级未做

- 生产仍 MiniLM-L6-v2 @384；升级需 Turn 外重建 + `INDEX_VERSION` bump + free 配对；**未开工**。
- Fusion 默认保持；无证据切 `vector_heavy`。

---

## 5. 回滚后代码状态（预期）

恢复为第 5 刀之前：

- `services/runtime/app/retrieval/rerank.py`：原 lexical 加分（`score + overlap*0.15 + …`），无 `amp_weak` / `tanh` 缩放。
- `search_sources` / tool schema：**default `limit=10`**。
- agent `system.md`：prefer limit ≥20（非 50）类表述。
- 覆盖 soft-rerank 边界的大段单测移除（随 revert）。

**仍保留**：verbatim 首搜契约、≤2 搜次 / 有 hit 停搜、C-1 读预算、C-3「保持 default」结论、m3 free runner 与分桶探针。

---

## 6. 建议的下一轮思考框架（不规定具体补丁）

请后续模型在 **只认 free** 的约束下推演，优先回答：

1. **回滚确认**：同条件 free 20q 是否回到 nDCG@10≈0.43 且行为桶不塌？
2. **IR 若要动**：改动如何在 free 轨迹上可观测（例如 `weak_hits` 案例的 hit 序 vs qrels）？避免再把「纯排序假设」与「limit/行为」绑死同一 commit。
3. **NFCorpus / FiQA**：分治还是统一杠杆？深度问题（limit/合并）与相关性问题（embed）如何用 free 证据拆开？
4. **是否开 embed 升级票**：前置测量、回滚条件、与 R1–R5（热路径无同步重嵌）如何写死？
5. **入库门禁**：何种 free 跑量 + 重复次数才允许碰 SCORECARD？

禁止项提醒：

- 不要把 forced/Index 涨分写成主栏成功。
- 不要在 free 掉分时用诊断臂「上限涨了」否决回滚。
- 不要在 20q 单次噪声上 `update-baseline`。

---

## 7. 关键原始读数附录

### 7.1 `TEST.log`（第 5 刀 free 复测导出，约 2026-08-03）

```text
official.retrieval.ndcg_at_10 = 0.3950
official.retrieval.recall_at_10 = 0.4371
official.retrieval.recall_at_100 = 0.5037
official.retrieval.ndcg_at_1 = 0.3556
official.retrieval.map_at_10 = 0.2627
official.retrieval.n_queries = 20
official.retrieval.agent.* = 与上列同值
official.context.agent_f1 = 0.3305
official.context.agent_em = 0.2500
```

对应 run：retrieval `a6de7860-b126-4b2a-957c-99e308bb8a49`（title 含 `arm=free`）；context `48c4aee1-7149-4be2-8ea3-5e95cef3f661`。

### 7.2 第 4 轮行为验收数字（保留刀的高峰）

```text
search_cap: 18% → 2%
ok:         77% → 92%
nDCG@10:    0.427 → 0.434（持平级，不入库）
```

### 7.3 C-3 fusion 冒烟

```text
8 个 fusion 配置 macro nDCG@10 全为 0.54552（rerank 关闭）
结论：不改生产 RETRIEVAL_PROFILE=default
```

---

## 8. 一页决策树（给后续模型）

```text
改动候选
  ├─ 只改善行为桶、IR 持平     → 可合入产品；不入库；记录「行为正向」
  ├─ free IR 显著↑（同协议）   → 才考虑 compare + update-baseline
  ├─ free IR ↓ 或反向噪声大    → 回滚或拆 commit 重测；禁止 forced 洗白
  └─ 仅 Index/L0/forced ↑      → 对本团队 = 未验收；最多当假说，不进主栏
```

**当前节点**：第 5 刀走了「free IR ↓」分支 → **已回滚**；停留在第 4 轮「行为正向 + IR 平台期」；等待回滚后的 free 确认复测与下一杠杆设计。
