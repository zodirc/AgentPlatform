# Free-L1 Tuning Brief（检索 + 上下文 · 交给后续模型）

> **受众**：高级模型 / 下一轮调优负责人  
> **日期戳记**：2026-08-03（检索 soft 二次/回滚确认 + **上下文最新 free 读数**）  
> **唯一验收温度计**：L1 产品 Turn · `arm=free`（检索看 nDCG；上下文看 agent_f1/EM）  
> **不作为验收**：forced/oracle 诊断臂、纯 L0 旁路、coding（本轮不可信）  
> **本文自含**：不依赖阅读其他专题文档即可理解流程、历史与问题  
> **调优进度**：检索已多轮行为/排序刀；**上下文尚未做专项调优**（仅有产品向 C-1 读预算等旁路影响），下文记录基线与真实流程供思考

---

## 目的与第一性原则（先于一切改动）

### 我们到底在优化什么

```text
目标（因）     = 把生产工程做成熟：
                 · 检索：Index / hybrid 排序 / 工具契约 / 如何用 hit
                 · 上下文：长文 read 预算、续读、答题形态 —— 主 agent 真实能力
手段（温度计） = 官方小量题集走与用户相同的 Session→Turn→loop→工具
                 · 检索 → BEIR → nDCG / Recall（search_sources）
                 · 上下文 → LongBench → agent_f1 / EM（read_file 等）
结果（果）     = bench 分数若上升，只是工程变好的「间接证明」
```

**因果不可反转：**

| 对 | 错 |
|----|----|
| 改生产检索/读预算/契约 → 用户路径变好 → free L1 分数**间接**上升 → 才可谈入库 | 为抬 bench 分改评测臂、注入答案、forced/oracle 剧本、评测专用质量分支 |
| 跑测试集是为了**量准、归因、否决坏刀** | 跑测试集是为了「把数字刷上去」 |
| 分桶告诉你失败落在哪层工程 | 分桶分数本身当 KPI 去优化文案糊弄过去 |

因此：审查时先问——**「加热的是检索/上下文工程，还是在伺候分数？」**  
下文检索与上下文两套温度计**分开归因**；不要用一边的分给另一边背书。

### 原则一：相对成熟、合理的思路

调优与评测方式应对齐成熟 coding / RAG agent 的常识，而不是「够用就行」的旁路：

1. **同构**：题面进真实会话与工具面；主臂自由搜（不写交互剧本）。
2. **可归因**：轨迹探针 + 确定性分桶；失败能落到 Index / 契约 / 行为 / 预算某一层。
3. **可复现**：同协议、同档、配置指纹；冒烟噪声下 **N≥2** 再定生死；全量锚才入库。
4. **杠杆分层**：先行为（怎么搜），再 Index/排序/embed（hits 弱），不混绑在同一 commit 里无法拆因。
5. **否决坏杠杆**：无稳定正 Δ、伤速率、毁同构、或只能靠诊断臂涨分的刀 → 丢弃 / 回滚。

「成熟」不是堆复杂度：lexical 默认开、cross-encoder 默认关、fusion 无证据不改默认——都是成熟取舍。

### 原则二：不能破坏主 agent 的交互速率与交互逻辑

主 agent = 用户日常 Turn 路径上的 `AgentEngine` while-loop + 工具 + 流式体验。任何「优化检索」的补丁必须过下列硬门（速率红线 R1–R5，此处写全以免外查）：

| 红线 | 含义 | 检索调优里常见违规 |
|------|------|--------------------|
| **R1** | 不挡 `turn.accepted` / 不拖 TTFB | 在 Turn 启动前塞同步检索或重初始化 |
| **R2** | 首 token 前不加同步模型调用 | 为「改写 query / 是否该搜」再问一轮 LLM |
| **R3** | 热路径同步 CPU 仅毫秒级 | 默认打开 cross-encoder、重 tokenizer、大模型 rerank |
| **R4** | 重活异步 / 离线 / 用户触发 | 查询路径同步重建索引、全库重嵌 |
| **R5** | 可测才合并 | 无单测/无延迟对照的「感觉更快」 |

**交互逻辑**不可破坏的底线：

- **不改** `AgentEngine` 的冻结 while（assemble → model → tools → checkpoint）。
- **不**强制每轮检索；搜与不搜仍由模型在工具面决定（自由主臂）。
- **不**为评测在 runtime 留「official 专用质量分支」或隐藏强制搜。
- 质量优先进 **Index plane（Turn 外）** 与 **静态**工具/schema/system 文案；热路径只做轻量排序加分等可预算工作。

**一票否决**：bench 分涨了，但伤了 R1–R5 或改了 loop / 强制搜剧本 → **不算成功，不得入库，应回滚。**

### 原则如何约束本文后续章节

| 章节用途 | 受原则约束的读法 |
|----------|------------------|
| §0 当前裁决 | 只记录事实与刀的去留；**不**把分数当目的 |
| §1–2 立场与流程 | 温度计怎么造；必须同构、只认 free |
| §3 历史刀 | 每刀问：加热的是哪层检索工程？有无伤速率/逻辑？ |
| §4 问题清单 | 工程缺口，不是「差几分」 |
| §6–8 下一轮 | 提案必须同时满足：成熟合理 + 不伤速率/逻辑 + 分数仅间接验收 |

---

## 0. 当前裁决（本轮事实）

| 项 | 结论 |
|----|------|
| 第五刀（soft lexical rerank + `search_sources` default limit 10→50） | **已回滚**；运行时已重建为回滚代码（容器内 `amp_weak` 不存在 · `limit=10`） |
| 回滚提交 | `cf87911` 还原覆盖测；`4189325` 还原功能改动（对应原 `f8f583b` / `07b4e3e`） |
| 初判回滚理由 | soft#1 free nDCG@10 **0.434 → 0.395** |
| **修订后证据** | soft#2 再跑得 **0.411**；回滚后确认跑 **0.409**。soft 两次均值 ≈ **0.403**，与回滚后几乎同带 → **20q 噪声大**；第 4 轮 **0.434 可能是偏高单次**，不能当「回滚后必回」的锚 |
| 回滚是否仍成立 | **是**——没有稳定正 Δ，无入库理由；但 **不要期待回滚本身抬 IR** |
| 相对原则的解读 | 第五刀试图加热 Index/排序；free 上无稳定间接增益 → 丢刀。**未**发现该刀已伤 R1–R5 的实测，丢刀主因是「检索未变好的间接证明不足」，不是速率事故 |
| 当前工作平台（冒烟） | free nDCG@10 **~0.41**（非 ~0.43）；下一刀以此为对照，勿再默认 0.434 |
| SCORECARD / baseline | **未更新、不入库** |
| 行为侧前几刀（verbatim 首搜、≤2 搜次） | **保留**；但近几次复测 cap/drift 有回潮（见 §3.6） |
| **上下文（LongBench free）** | **几乎未专项调优**；最新 `TEST.log`：agent_f1 **0.3295** · EM **0.300**（`c8cc1bc1`，三 task×20）；平台约 **F1≈0.33**。流程与影响面见 **§3.4** |
| 下一轮硬约束 | 继续只认 free；勿用 forced/oracle 洗白；20q/每 task 冒烟单次不作效果入库；重要刀至少 **N≥2**；**每刀过原则一+原则二门禁**；检索/上下文分开归因 |

---

## 1. 系统与评测立场（必须对齐）

### 1.1 产品形态

- 平台是 **一个 AgentEngine while-loop × 多个 ScenarioProfile**。
- 用户路径：创建 Session → Turn → Runtime loop → 工具（含 `search_sources`）→ 流式事件 → 终态**。
- 检索质量进入 **Index plane**（切块 / embed / hybrid+RRF / 可选 lexical rerank）与 **静态工具契约 / system 文案**；**禁止**为刷分改 loop、强制每轮检索、或评测专用质量分支。

### 1.2 本轮评测立场（团队已确认）

下列各条都是文首「目的与第一性原则」的操作化，不是另起炉灶：

1. **优化对象 = 检索工程**（Index / 排序 / 契约 / 如何用 hit）；**不是**优化 bench 报表。
2. **测试集的目的** = 同构量测 + 归因 + 否决；分数上涨 = 检索变好的**间接**信号。
3. **主臂 = 自由 agent**：题面只说明「答案在本地资料库，请给出依据」；**不**规定工具名、次数、`limit`、query 原文。
4. **只跑 / 只信 free**。forced（强制单搜隔离 Index 上限）与纯 Index 网格可以存在于代码，但**不是本团队的验收尺**（可作假说，不可洗白 free）。
5. **禁止**为刷分伪造路径、注入答案、或把诊断臂分数写进主栏。
6. **行为改善 ≠ 入库**：分桶（怎么搜）可以判「正向」；宏 IR（nDCG/R）无稳定正 Δ 则不 `update-baseline` / 不写 SCORECARD 主栏。
7. **速率与逻辑一票否决**：任何刀合入前自检 R1–R5 + 未改 while + 未强制每轮检索。

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

### 1.4 RAG 因果栈与可调影响面（高级模型必读）

温度计与用户写作 RAG 共享下列栈。改任何一层前：先标「加热的是哪一层」，再过原则一/二，再用 free N≥2 看间接分数。

#### 因果栈（自由 L1 检索）

```text
BEIR 语料物化 → sources/beir/<dataset>/<doc_id>.txt（title+text 拼接）
  → Turn 外：切块 / embed（生产 MiniLM-L6-v2@384）/ INDEX_VERSION / pgvector
  → StartTurn：scenario 默认 writing（见下「场景陷阱」）+ 自由题面
  → 模型调用 search_sources(query≈?, limit 常默认 10)
  → hybrid：向量 ∥ BM25 → RRF →（可选）two-level doc 加成 → lexical rerank
  → 工具侧：excerpt 覆盖词提升序 → 格式化 excerpt(200字) → tool_result
  → 同时写 retrieval.completed.ranked（path+score，最多约 100）← IR 计分只用这个
  → ContextEngine 组装时普通 tool_result 常被 4k 预算截断 ← 只影响下一步行为，不影响已发出的 ranked
  → 多搜合并：first-seen union → nDCG@k / R@k
```

#### 场景陷阱（同构缝隙）

| 表面 | 默认 scenario | 是否有 `search_sources` | 含义 |
|------|---------------|-------------------------|------|
| **Free L1 检索温度计** | **`writing`**（`run_retrieval_l1` 默认） | 有 | 测的是**写作 RAG 工具面 + writing system 文案** |
| 用户写作 Work | `writing` | 有 | 与温度计最同构 |
| 用户 intel Work | `intel` | 有（常带 `path_prefix`） | 另有前缀作用域 |
| 用户 agent Work | `agent` | **无**（仅有 `search_codebase`≈grep） | **不是**本温度计；`agent/system.md` 里写 search_sources 纪律 ≠ 工具已注册 |

推演时勿把「优化 agent 模式代码检索」与「抬 BEIR free L1」混为一谈，除非先改协议/场景。

#### 影响面表（按层 · 当前默认 · 动它会怎样）

**A. Index plane（Turn 外 · 质量主战场 · 重活必须离线）**

| 触点 | 当前默认（生产取向） | 影响什么 | 改动风险 |
|------|----------------------|----------|----------|
| 切块大小/重叠 | 4000 / 400 字符 | 命中粒度、边界漏检 | 须 bump `INDEX_VERSION` + 全量重建（R4） |
| 宽表拆出 | 行/字阈值触发 | 表体可能不进 embed，靠 `read_file` | 排序与可读证据分叉 |
| embed 文本 | path 线索 + 可选 tags + body | 路径弱的扁平 BEIR 比树状 seed 吃亏 | 重建索引 |
| Embed 模型/维 | compose：`all-MiniLM-L6-v2` @384（代码默认 hash 仅开发） | 向量车道天花板；升级票未开 | R4；维数变更会弄坏 ANN |
| `INDEX_VERSION` | 代码 **8** | 遗忘 bump → 新旧向量混用 | 逻辑正确性 |
| 后端 | pgvector；schema 可隔离 | ANN + SQL BM25 | 切 json 只适合冒烟 |
| 同步/watch | 启动延迟/轮询/防抖；**查询路径禁止 sync** | 索引滞后 → 空召回/keyword-fallback | 热路径 sync = 违 R4/A9 |
| L1 物化形状 | 扁平 `sources/beir/<ds>/<id>.txt`，非 seed 树 | path/tag 增益难迁移到产品树状语料 | 温度计≠产品语料分布 |
| `visibility_seed` | L1 常关 seed | 避免 seed 污染 BEIR | 误开则分数不可比 |

**B. 查询融合与排序（热路径 · 只许轻量）**

| 触点 | 当前默认 | 影响什么 | 改动风险 |
|------|----------|----------|----------|
| `retrieval_mode` | hybrid | 单车道会改召回族 | 逻辑 |
| RRF `k` | 60 | 融合陡度；C-3 冒烟八点打平 | 20q 上难见 Δ |
| profile | **default** 1:1 + doc_boost 0.35（`vector_heavy` 1.6/0.4/0.45 已备未切） | 车道嗓门 | 无 free 证据勿切默认 |
| two-level | 开；超时 0.3s；doc_limit 8 | 同 doc 块加成 | 超时↑吃 R3 |
| lexical rerank | **开**；经典 overlap/title/phrase 加分（soft 缩放已回滚） | 可搅动小 RRF 分 | 轻量 R3；须 free N≥2 |
| cross-encoder | **关**；池≤20；超时 50ms | 文档禁止默认上热路径 | 打开≈打 R3 |
| over-fetch | 约 `limit*2~4` 再截断 | 截断前池深 | CPU |
| excerpt 覆盖提升序 | `_prefer_excerpt_covering_hits` | **会改写返回序 → 进 IR ranked** | 逻辑；可与纯 RRF 对抗 |
| ANN 无覆盖词 → keyword-fallback | 有 | 救弱向量；排序族切换 | 行为/IR |

**C. 工具契约与模型行为（常被低估 · 直接进 free 分）**

| 触点 | 当前默认 | 影响什么 | 改动风险 |
|------|----------|----------|----------|
| `search_sources` limit | schema+实现默认 **10**（曾试 50，随第五刀回滚） | 深度；FiQA 常见 R@10≈R@100 | 行为+IR；单独开刀、N≥2 |
| excerpt 长度 | **200** 字符 | 模型可见证据窗；**不进 IR 公式** | 行为（再搜 vs 读） |
| soft 搜次文案 | ≤2；有 hit 停搜改读 | drift/cap 桶 | 纯文案，R 友好 |
| hard 闸 | `search_sources_max_per_turn=3` | 与 soft≤2 不一致；cap 桶在 ≥3 且换词 | 逻辑 |
| low_score hint | 0.15 | 弱命中提示改读 | 行为 |
| writing `system.md` | 近乎原文首搜、库地图、path_prefix 习惯 | **L1 正在用**；扁平 BEIR 上易诱发 list_dir/逛库 | 行为；勿为刷分写死强制搜 |
| late-stage 可丢工具 | 含 `search_sources` | 末段可能 no_search | 行为 |
| 自由题面 | 无工具剧本 | 温度计合法性 | 写回 forced 即毁主臂 |

**D. 计分合并 vs 模型上下文（两套窗）**

| 触点 | 当前默认 | 影响什么 | 改动风险 |
|------|----------|----------|----------|
| IR 用 `ranked` | 最多约 100 条 path+score | nDCG/R/MAP | 改 cap = 协议级 |
| 多搜合并 | **first-seen union**（先出现的 doc 保留位次） | 第二次搜不能重排已见 doc；深度≈各次 limit 并集 | 改合并=协议 bump |
| 未搜 | 空榜 → 0 分 | no_search 诚实 | 勿改成跳过不计 |
| tool_result 预算 | 普通结果 **4k**；最近一次 read **32k** | 搜结果 JSON 易被截 → 模型丢后排 hit | **只改行为，不改已发 ranked** |
| assemble 压力链 | fold→budget→microcompact→collapse→snip | 多步 Turn 里早先 search JSON 更易丢 | 行为 |

**E. 题集结构坑（归因时别误判杠杆）**

| 现象 | 含义 | 错误对策 |
|------|------|----------|
| NFCorpus R@10 极低 | 每查询相关文极多；R@10 结构上难大 | 只盯 R@10 猛调 embed |
| FiQA R@10≈R@100 | 合并 hit 深度不够（limit/停搜/合并） | 只怪 MiniLM |
| 20q ±1.5–4pp | 冒烟噪声 | 单次定生死 / 单次入库 |
| C-3 fusion 打平 | 本档拧 rrf/profile 无 macro Δ | 无证据切 `vector_heavy` |
| writing 文案 × 扁平 BEIR | 行为像「逛目录」 | 当成纯 Index 坏了 |

#### 高杠杆优先序（在原则门禁内）

1. **行为/契约可观测缺口**：drift、cap、搜后 list_dir、limit 常落 10（深度）——改动能在分桶直接看见。  
2. **深度与合并**：default limit、搜次数、first-seen union ——对 FiQA 类 R@10=R@100。  
3. **Index/embed**：MiniLM 天花板、切块、INDEX bump ——R4 离线；要用 weak_hits 案例说话。  
4. **轻量排序**：lexical / excerpt-promote / two-level ——须 free N≥2；勿默认开 CE。  
5. **Context 4k 截 search JSON** ——优先改善「搜完不会用 hit」，IR 数字可能不动。  
6. **场景同构**：若产品目标含 agent 模式 RAG，须先注册工具或改 L1 scenario，否则优化 agent/system.md 对温度计无效。

#### 提案时建议填写的最小卡片（给后续模型）

```text
加热层: Index | 融合排序 | 工具契约 | 合并/深度 | Context 行为 | 场景同构
改动点: <文件/Settings 键>
预期用户路径变化: <一句话>
R1–R5 / while / 强制搜: 通过 / 否决原因
分桶预期: drift/cap/weak_hits/ok 怎样变
free 验收: N≥2 · 对照 run · 主看 nDCG@10（兼看分库）
非目标: 不靠 forced 涨分叙事
```

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

### 3.4 上下文（LongBench · free L1）— 基线记录 · 调优很少

> **状态**：尺已切到 m3 free（可续读）；产品侧有 C-1「最近一次 read 更高预算」等，但**没有**像检索那样多轮「刀 + 复测 + 回滚」的上下文专项调优。  
> **本文作用**：把真实流程与当前分数写清，供后续模型设计**第一刀**；勿把检索 Δ 安到 context 上。

#### 3.4.1 当前与历史读数

| 跑次 | 臂/尺 | agent_f1 | agent_em | 备注 |
|------|-------|----------|----------|------|
| `272fdb71` | 早期 L1 | 0.279 | 0.05 | 过渡 |
| `ebc6abfd` | m2 强制单读冒烟 | 0.315 | 0.05 | 旧尺；不可当 free 锚 |
| `48c4aee1` | free · 与检索 soft 同日 | 0.331 | 0.25 | 60/60；桶 ok35 / verbose15 / gave_up10 |
| **`c8cc1bc1`（最新 · `TEST.log`）** | **free · m3** | **0.3295** | **0.300** | 59/1；见下分桶与分 task |

最新 `TEST.log`（仅上下文段）：

```text
official.context.agent_f1 = 0.3295
official.context.agent_em = 0.3000
```

**分 task（`c8cc1bc1`，每 task 20 条）**

| task | mean F1 | EM 率 | 桶要点 |
|------|---------|-------|--------|
| multifieldqa_en | 0.413 | 0.20 | verbose 与 ok 各 8；gave_up 4 |
| hotpotqa | 0.320 | 0.55 | ok 12；gave_up 7 |
| narrativeqa | 0.255 | 0.15 | ok 10；verbose 7；steps_exhausted 1 |

**分桶质量（同跑）**

| bucket | n | mean F1 | 含义 |
|--------|---|---------|------|
| ok | 30 | **0.533** | 行为合格且有可对齐答案时，质量其实不差 |
| verbose_answer | 16 | 0.235 | 有 F1 但答太长 → EM 常 0 |
| gave_up_early | 13 | **0.000** | 读入相对 passage 过少且 F1=0 |
| steps_exhausted | 1 | 0.000 | 步数耗尽 |

**读法**：宏 F1≈0.33 被 **gave_up_early + verbose** 拖住；ok 子集已 ~0.53。与检索类似——先分桶，再决定加热「读预算 / 续读纪律 / 答题形态」，不要只盯宏分。两次 free（0.331 / 0.330）几乎重合 → 当前冒烟平台 **F1≈0.33 · EM≈0.25–0.30**。

#### 3.4.2 实际场景流程（对照检索温度计）

与检索 **同构原则相同**（真 Session/Turn/loop），但 **场景、工具、物化、计分完全不同**：

| | 检索 free L1 | **上下文 free L1** |
|--|--------------|-------------------|
| 题集 | BEIR SciFact/NFCorpus/FiQA | LongBench：multifieldqa_en / hotpotqa / narrativeqa |
| 默认 scenario | **`writing`**（有 `search_sources`） | **`agent`**（读/搜代码工具面；passage 靠 `read_file`/`grep`） |
| 主臂 | free（forced=诊断） | free（**oracle**=诊断：显式要求读完） |
| 物化 | 多文档 `sources/beir/<ds>/<id>.txt` + 索引 sync | **单文件** `sources/passage.md` = 整段 context（每题独立 Work，防 read 缓存串题） |
| 题面 | 「Information need: …」去搜库 | 「材料在 passage.md，可用分段 read/grep，**只答短短语**」 |
| 模型常用工具 | `search_sources` → 可选 read | **`read_file`（含 offset 续读）**、grep 等；一般**不**走 BEIR 索引 |
| 计分 | `retrieval.completed.ranked` → nDCG/R | 终答文本 vs gold → **token F1 / EM**（官方式短答约定） |
| 冒烟档 | 每集 20q | **每 task 上限**（本次 20×3=60），不是全局只切第一 task |

**单题因果栈（上下文）**

```text
Pull LongBench small_slice → 按 task 截断 limit
  → 每题新建隔离 Work
  → 写入 sources/passage.md（全文 context，可很长）
  → StartTurn(scenario=agent, arm=free)
  → 自由题面：读 passage.md，短短语作答（不限制读法）
  → 模型：read_file / grep / …（可续读 next_offset）
  → ContextEngine 组装：普通 tool_result ~4k 截断；
        最近一次 read_file 可用更高预算（C-1，约 32k）——这是少数已落地、会影响本温度计的产品改动
  → 终答抽取 → 与 gold 算 F1/EM
  → L2 分桶：verbose_answer / gave_up_early / truncation 相关 / ok …
```

**oracle 臂（不进主栏）**：题面改为「必须读完再答，可多次续读」；用于估 retention，**不是**本团队当前验收尺（与检索不做 forced 同理：可诊断，不洗白 free）。

#### 3.4.3 上下文影响面（调优很少 · 供第一刀思考）

| 层 | 触点 | 现状 | 与分数关系 |
|----|------|------|------------|
| 读预算 | 普通 tool_result **4k**；最新 read **~32k**（C-1） | 已落地产品票 | 长 passage 仍可能只见局部 → gave_up / 错答 |
| 续读 | `offset` / `next_offset`；free 题面允许 | 模型常不续读 | 行为桶；勿强制剧本伤同构 |
| 答题形态 | 题面要求 short phrase；judge 偏短答 | verbose 多 → EM 低 | 契约/system 薄说明（勿改 loop） |
| 步数 | max_steps 等 | 见 1× steps_exhausted | 速率/逻辑边界 |
| scenario | **agent** 默认 | 与检索 writing 不同 | 改 agent 读纪律会影响本温度计；改 writing RAG **不会** |
| 物化 | 整篇 passage.md，无 BEIR 索引 | 不测 hybrid | 不要用检索 fusion 刀期望抬 F1 |

**原则提醒**：上下文优化同样是「加热读/预算/契约工程 → F1 间接升」；禁止为刷分改成强制单读旧尺或把 oracle 当主栏。

### 3.5 Coding

本轮最新 coding official run **failed**；历史 patch_rate 在无 repo/无 harness 下 **无效果含义**。后续思考 **忽略 coding**，直至尺修干净。

### 3.6 检索行为桶近况（相对第 4 轮高峰有回潮）

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

### P7 — Embed / INDEX 升级未做（检索）

- 生产仍 MiniLM-L6-v2 @384；升级需 Turn 外重建 + `INDEX_VERSION` bump + free 配对；**未开工**。
- Fusion 默认保持；无证据切 `vector_heavy`。

### P8 — 检索温度计场景 = writing，不是 agent

- L1 retrieval 默认 `scenario_id=writing`；`agent` 配置**未注册** `search_sources`。
- 优化 `agent/system.md` 或代码检索 **不会**自动抬 BEIR free L1。
- 若产品要「agent 模式也能 hybrid RAG」，须先补工具注册/协议，再谈同构温度计。

### P9 — 检索：计分窗 ≠ 模型窗

- IR：`retrieval.completed.ranked` + first-seen union。
- 模型：200 字 excerpt + 组装期 4k 截断。
- 只改 Context/excerpt 可能「体感更好」而 nDCG 不动——仍可算产品正向，但**不要**写成 IR 入库理由。

### P10 — 查询路径上的「静默重排」

- `_prefer_excerpt_covering_hits` 等会在工具返回前改序，从而改 IR。
- 调 fusion/rerank 时若忽略这层，归因会漂。

### P11 — 上下文几乎未专项调优（基线 F1≈0.33）

- 最新 free：F1 **0.3295** · EM **0.30**；与 `48c4aee1` 几乎持平 → 平台稳定在 ~0.33。
- 主拖累：**gave_up_early**（少读）与 **verbose_answer**（答太长）；ok 子集 F1≈0.53 说明「读对且答短」时并不差。
- 温度计是 **agent + passage.md + 短答**，不是 writing RAG；第一刀应落在读预算/续读/答题形态，并过 R1–R5。
- **禁止**用检索 soft/回滚叙事解释 context 分数。

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

任何提案先过文首两道门，再谈分数：

1. **成熟合理吗？**（同构 free、可归因、可复现、杠杆可拆、非旁路刷分）
2. **伤主 agent 速率/逻辑吗？**（R1–R5、不改 while、不强制搜、无评测专用质量分支）

通过后再在 **只认 free** 下回答：

1. **基线重钉**：以回滚后 `689cfe71`（≈0.409）为冒烟对照，是否再跑 1–2 次取均值当「当前平台」？
2. **检索工程改哪一层**（见 §1.4）：Index / 融合排序 / 契约行为 / 合并深度 / Context 行为 / 场景同构——如何在 free 轨迹上可观测？**禁止**多杠杆绑同一 commit；重要刀 **N≥2**。
3. **NFCorpus / FiQA**：分治还是统一？深度（limit/合并）vs 相关性（embed）怎么用 free 证据拆开？
4. **行为回潮**：cap/drift、搜后 list_dir——契约刀还是噪声？（不得伤速率）
5. **writing 温度计 vs agent 产品**：是否接受「只优化 writing RAG」？若要 agent hybrid，先补工具面再改温度计。
6. **embed 升级票**：Turn 外重建、回滚条件、R3/R4 写死。
7. **入库门禁**：何种 free 跑量 + 重复次数？入库叙事 = 检索工程变好的间接证明。

禁止项提醒：

- 不要把「抬 bench 分」写成目的；目的永远是检索工程。
- 不要把 forced/Index 涨分写成主栏成功。
- 不要在 free 掉分时用诊断臂「上限涨了」洗白。
- 不要在 20q **单次**噪声上 `update-baseline`。
- 不要假设「回滚后 IR 应回到 0.434」。
- 不要用同步 CE / 启动时重嵌 / 改 while / 强制每轮搜 换分数。
- 不要只改 `agent/system.md` 却宣称 BEIR L1 会动。

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

### 7.6 上下文最新 · `c8cc1bc1`（`TEST.log` 仅 context 段 · 2026-08-03）

```text
official.context.agent_f1 = 0.3295
official.context.agent_em = 0.3000
```

- title：`LongBench small · L1 agent-path · arm=free` · model=`deepseek-v4-flash` · protocol m3  
- 60 题（三 task×20）：pass 59 / fail 1  
- 桶：ok 30 · verbose_answer 16 · gave_up_early 13 · steps_exhausted 1  
- 分 task F1：multifieldqa_en 0.413 · hotpotqa 0.320 · narrativeqa 0.255  

对照同协议 free 前序 `48c4aee1`：F1 0.331 / EM 0.25 → **宏 F1 平台 ≈0.33，几乎未因检索刀而动**（符合「上下文未专项调优」）。

---

## 8. 一页决策树（给后续模型）

```text
改动候选
  │
  ├─ 伤 R1–R5 / 改 while / 强制搜 / 评测专用分支 → 一票否决（无论分数）
  │
  ├─ 目的不是加热检索工程（只为刷分） → 否决
  │
  ├─ 成熟合理？同构 free · 可归因 · 可拆因 · N≥2 可复现
  │     └─ 否 → 先补尺子/拆 commit，再谈合入
  │
  └─ 通过门禁后看温度计（分数 = 间接结果）
        ├─ 只改善行为桶、IR 持平     → 可合入产品；不入库；记「行为正向」
        ├─ free IR 显著↑（同协议·N≥2）→ 才考虑 compare + update-baseline
        ├─ free IR ↓ 但 N=1 噪声带内 → 同配置再跑；勿单次定生死
        ├─ free IR 无稳定正 Δ（N≥2） → 丢刀 / 回滚；禁止 forced 洗白
        └─ 仅 Index/L0/forced ↑      → 未验收；最多当假说，不进主栏
```

**当前节点**：  
- **检索**：第五刀已回滚；平台 **nDCG@10≈0.41**；行为桶有回潮。  
- **上下文**：几乎未专项调优；平台 **F1≈0.33 / EM≈0.30**；拖累在 gave_up_early + verbose；流程见 §3.4（agent + passage.md，异于检索 writing）。  
下一轮设计杠杆时两套温度计分开；全程守住成熟合理与主 agent 速率/逻辑。
