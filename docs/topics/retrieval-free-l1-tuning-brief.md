# Free-L1 Tuning Brief（检索 + 上下文 · 交给后续模型）

> **受众**：高级模型 / 下一轮调优负责人  
> **日期戳记**：2026-08-04（§13 部署窗口 A 收束 · **仅记有效 free 跑** · **未入库**）  
> **唯一验收温度计**：L1 产品 Turn · `arm=free`（检索看 nDCG；上下文看 agent_f1/EM）  
> **不作为验收**：forced/oracle 诊断臂、纯 L0 旁路、coding（本轮不可信）；schema 事故跑（见 §7.7 说明，**不入对照**）  
> **本文自含**：不依赖阅读其他专题文档即可理解流程、历史与问题  
> **当前平台锚（冒烟）**：检索 promote-off 均值 nDCG@10 **≈0.447**（`bcdbbb85`/`f92bc610`）；RET-9 两轮均值 **0.453**（丢刀后栈已回滚互补文案，平台仍按 promote-off 锚读）· 上下文 excl-infra F1 **≈0.40–0.42**  
> **调优进度**：§9 批次 1–3 已部署；批次 5–6 契约/呈现/消融多刀已收；**RET-9 N≥2 丢刀已回滚**（§13.8）；主缺口仍在 weak_hits / FiQA absent → **RET-4**；上下文主缺口 wrong_answer → **CTX-8**（先 CTX-12）  
> **执行状态总览**：§9 → **§9.6**；§10 批次 5 → **§10.6**；§11 前置 → **§11.7**；§12 → **§12.6–12.9**；§13 → **§13.8**  
> **第二轮提案（基于 §9 有效跑归因 · 观测先于改动）**：见 **§10**（批次 5–7：复跑凑 N≥2 → 归因/消融 → 单刀契约 → 结构刀）  
> **第三轮补充思考（外部对标 · 2026-08-04）**：见 **§11**（EVAL 配对判别 / RET-10~13 / CTX-8~9 / 「合理、完备」终态定义）  
> **批次 6 前置 + 首刀**：见 **§11.7**（EVAL-1/2/3 · RET-10 · CTX-9 · EVAL-infra · RET-12 **均已落地并有 free 观测**；**未入库**）  
> **第四轮补充思考（观测盲区与条件契约刀 · 2026-08-04）**：见 **§12**  
> **§12 执行进度（2026-08-04）**：见 **§12.6** / **§12.9**（RET-7 **默认关**；CTX-7 **保留不记 EM 胜**；**RET-9 已丢刀回滚**；**未入库**）  
> **RET-12 行为 N≥2（2026-08-04）**：检索 free `dfe97d37` nDCG@10 **0.422** · 配对 `3c34de88` → **no_stable_delta**（见 **§12.7**）；同批上下文 `c76e07a9` **infra 失败不作对照**  
> **RET-15-2 free（2026-08-04）**：`6c87e401` nDCG@10 **0.442** · 配对 `dfe97d37` → **no_stable_delta**（见 **§12.8**）· **不写 IR 胜**  
> **RET-7 消融 N≥2（2026-08-04）**：OFF `bcdbbb85`/`f92bc610` 均值 nDCG@10 **0.447** · vs ON `6c87e401` → 两轮皆 **no_stable_delta** → **默认关 promote**（§12.9）  
> **CTX-7 N≥2（2026-08-04）**：`13647cb0`/`61624e34` · verbose **11→4** 稳定；EM **↓** → **不记 EM 胜**（§12.9）  
> **第五轮补充思考（收束准备与停机线 · 2026-08-04）**：见 **§13**（EVAL-6 · RET-17/18 · CTX-12 · INFRA-1/2 · REP-3 · D-1）  
> **§13 部署窗口 A（2026-08-04）**：见 **§13.8**（INFRA-1/2 已部署 · **RET-9 N≥2 丢刀已回滚** · RET-18 开关默认 on · 停机计数 **+1/2** · **下一刀 CTX-8**（先 CTX-12）· **未入库**）  
> **第六轮补充思考（平台期直答 + 真正提升主线 · 2026-08-04）**：见 **§14**（为什么多轮无明显提升的三笔账 · 外部对标第二辑 · **RET-4 执行细化 v2（384 维免改 ANN）** · RET-19 离线 rerank 余量 · PROD-1 产品镜像套件 · EVAL-7 效应量门）  
> **§14 批次 A 进度（2026-08-05）**：见 **§14.6**（CTX-12/RET-17 离线 ✓ · RET-19 mean Δ **+0.51pp** → `close_rerank_topic` · RET-4 L0 选型推荐 **`thenlper/gte-small`** macro nDCG@10 **0.569** / vs MiniLM **+9.1pp** · CTX-8 文案已部署待 free N≥2 · PROD-1 草稿 24 题 · **L0 不入主栏 · 未入库**）  
> **流程图**：检索 [retrieval-tuning-flowchart.png](retrieval-tuning-flowchart.png) · 上下文 [context-tuning-flowchart.png](context-tuning-flowchart.png)（`python3 scripts/gen_l1_tuning_lanes_zh.py`）

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
| 第五刀（soft lexical rerank + limit 10→50） | **已回滚**（历史）；丢刀主因无稳定 IR 正 Δ |
| 改刀前冒烟锚 | `689cfe71` nDCG@10 **0.409**（勿再默认 0.434） |
| **当前检索冒烟平台** | promote-off 两轮均值 **≈0.447**（`bcdbbb85`/`f92bc610`）；RET-9 两轮均值 0.453 后**文案已回滚**，配对仍按 promote-off 锚 |
| **§9 批次 1–3 代码** | **仍在运行时**（limit30 · excerpt400 · CTX-1/2/3 · RET-2/2b/3）；另含 RET-12 分层呈现 · RET-15-2 相对分 · promote **默认关** · INFRA-1/2 |
| **批次 6 契约/呈现裁决** | RET-12 / RET-15-2 / RET-7 消融 / CTX-7：宏分多 `no_stable_delta`；子桶/栈有正向（verbose↓、promote 移除、hint 修复）；**RET-9 丢刀已回滚** |
| FiQA 深度 | 仍常见 **R@10≈R@100**；主因 gold **absent_from_ranked** / lane 饥饿 → **RET-4**（非再拧契约） |
| SCORECARD / baseline | **未更新、不入库** |
| 行为侧前几刀（verbatim / ≤2 搜） | **保留** |
| **停机线（EVAL-6）** | 第二观察批停机计数 **1/2**（RET-9）；CTX-8 为该批最后一把加法契约刀 |
| **下一刀** | **CTX-12 离线** → **CTX-8**；其后 RET-18 消融 → REP-3 全量锚 → 批次 7（RET-4） |
| **执行进度表** | **§13.8**（最新）；§12.6–12.9 · §11.7 · §10.6 · §9.6 |
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
| 5c | `689cfe71` 回滚后 | 容器确认 soft=False · limit=10；free 20q | ok 54；search_cap 3；drift 3；59/4 | **0.409** | **0.412** | **0.468** | **未回到 0.434**；与 soft#2 同带；**改刀前锚** |
| §9 包 | `99d729de` **有效** | 批次 1–3 打包部署后 free 20q（limit30 · excerpt400 · RET-3 观测 · writing/CTX 文案） | ok29 · weak_hits26 · cap3 · drift1 · no_search1；55/5 | **0.455** | **0.448** | **0.509** | **N=1 正向**；不入库；**不可单刀归因**；FiQA 仍 R10=R100 |

### 3.2 同温度计多跑对照（free · 20q · 修订结论）

### 3.2 同温度计多跑对照（free · 20q · 修订结论）

| 标签 | run_id | nDCG@10 | R@10 | R@100 | vs 第 4 轮 0.434 |
|------|--------|---------|------|-------|------------------|
| 第 4 轮高峰 | `0526901a` | 0.434 | ~0.45 | ~0.56 | — |
| soft#1 | `a6de7860` | 0.395 | 0.437 | 0.504 | −0.039 |
| soft#2 | `f7fc1b1a` | 0.411 | 0.466 | 0.517 | −0.023 |
| soft 两次均值 | — | **0.403** | — | — | **−0.031** |
| **回滚后确认** | `689cfe71` | **0.409** | **0.412** | **0.468** | −0.026 |
| **§9 包 · 有效** | `99d729de` | **0.455** | **0.448** | **0.509** | +0.021 vs 0.434；**+0.046 vs 回滚锚** |

**修订读法（重要）：**

1. soft#1 的 0.395 **偏悲观**；同配置 soft#2 拉回 0.411 → 单次 20q 抖动约 **1.5–4pp** 量级。
2. 回滚后 **0.409 ≈ soft#2**，**没有**「一回滚就回到 0.434」。回滚证明的是「第五刀无稳定增益、可丢」，不是「第五刀造成了可逆的稳定回归」。
3. 第 4 轮 **0.434 不宜再当硬锚**；改刀前诚实冒烟平台按 **~0.41**（`689cfe71`）记。
4. §9 打包后有效跑 **0.455** 高于改刀前锚，但 **N=1 + 多刀同栈** → 只作方向信号，补 N≥2 前不谈入库、不拆「哪一刀抬了分」。
5. 回滚后 R@10/R@100 曾弱于 soft#2；§9 有效跑宏 R@100 **0.509** 已回升，但 FiQA 子集仍 R10=R100（见下）。

### 3.2b 分库快照（三次邻近 free 跑）

| 子集 / 跑次 | soft#1 nDCG@10 | soft#2 | 回滚后 | **§9 有效 `99d729de`** |
|-------------|----------------|--------|--------|-------------------------|
| SciFact | 0.516 | 0.544 | 0.536 | **0.597**（R10=0.725 · R100=0.850） |
| NFCorpus | 0.307 | 0.276 | 0.336 | **0.357**（R10=0.078 · R100=0.136） |
| FiQA | 0.362（R10=R100≈0.49） | 0.412（R10=R100≈0.54） | 0.353（R10=R100≈0.49） | **0.411**（**R10=R100=0.542**） |

NFCorpus / FiQA 仍是宏平均拖累；FiQA 在 limit=30 打包跑上 **仍 R@10≈R@100** → 深度假设未在该子集拆开（RET-1 验收未过）。

### 3.2c §9 有效跑行为/观测（`99d729de`）

| 项 | 值 |
|----|-----|
| pass/fail（query） | 55 / 5 |
| terminal completed/failed | 56 / 4 |
| bucket_counts | ok **29** · weak_hits **26** · search_cap **3** · query_drift **1** · no_search **1** |
| suite_ndcg_median | ≈ **0.434** |
| weak_hits_cases（低分快照） | **30**（RET-3 已可开 RET-4 证据清单） |
| excerpt_promote_reorder_total | **55**（P10 审计有计数；schema 已含该字段） |

### 3.3 第 5 刀设计意图（为何后来想动 Index）

当时叙事：

- 行为桶已干净 → 再拧 prompt/搜次 **收益递减**。
- free nDCG@10≈0.43，而 Index 冒烟（fusion、rerank 关闭）≈0.55；**R@10 已接近** → 猜「排序」而非「漏检」。
- 假设：lexical rerank 对长 claim 的 token-overlap 加分淹没 RRF（量级 ~0.01）。
- 改法：weak/strong bonus 按 `max(|score|)` 缩放 + `tanh`；`search_sources` 默认 limit 10→50；agent system 文案改为 prefer limit≥50。

**与团队最终立场的冲突**：该刀虽自称 Index/排序，但验收写的是「热部署后 **Ops free L1 20q**」。团队后来明确 **只认自由搜** → 不以 forced 洗白；多跑之后进一步改为：**无稳定正 Δ 即丢刀**，同时承认冒烟噪声，不以单次 0.395 叙事「深度回归」。

### 3.4 上下文（LongBench · free L1）— 基线 + §9 有效跑

> **状态**：改刀前平台 F1≈0.33（CTX-0）；§9 CTX 刀已部署后有效跑 F1 **0.413**（N=1）。  
> 流程仍见下；**不要**把无效 schema 事故跑写入对照。

#### 3.4.1 当前与历史读数

| 跑次 | 臂/尺 | agent_f1 | agent_em | 备注 |
|------|-------|----------|----------|------|
| `272fdb71` | 早期 L1 | 0.279 | 0.05 | 过渡 |
| `ebc6abfd` | m2 强制单读冒烟 | 0.315 | 0.05 | 旧尺；不可当 free 锚 |
| `48c4aee1` | free · CTX-0 | 0.331 | 0.25 | 60/60；桶 ok35 / verbose15 / gave_up10 |
| `c8cc1bc1` | free · CTX-0 | **0.3295** | **0.300** | 与上几乎重合 → **改刀前平台 F1≈0.33** |
| **`083eca09`（§9 有效）** | **free · m3** | **0.413** | **0.283** | 60/60；见下分桶；**N=1 不入库** |

**分 task（`083eca09`，每 task 20 条 · §9 有效）**

| task | mean F1 | EM 率 | 桶要点 |
|------|---------|-------|--------|
| multifieldqa_en | 0.512 | 0.20 | ok 13；verbose 4；gave_up 3 |
| hotpotqa | 0.478 | 0.55 | ok 14；gave_up 6 |
| narrativeqa | 0.250 | 0.10 | ok 10；gave_up 6；verbose 4 |

**分桶（`083eca09` vs CTX-0 `c8cc1bc1`）**

| bucket | CTX-0 n | §9 有效 n | 读法 |
|--------|---------|-----------|------|
| ok | 30 | **37** | 行为合格增多 |
| verbose_answer | 16 | **8** | CTX-1 方向：答短纪律见效（单次） |
| gave_up_early | 13 | **15** | CTX-2 续读刀**未**收窄；略增 |
| steps_exhausted | 1 | 0 | — |

**读法**：宏 F1 **0.33→0.413** 进入方案诚实预期带；主贡献更像 **verbose↓**，gave_up 仍在。EM **0.30→0.283** 单次未升（噪声/分 task 不均）。须 **N≥2** 再定 CTX 刀去留。

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

### 3.6 检索行为桶近况

| 跑次 | ok（约） | search_cap | query_drift | no_search | weak_hits | pass/fail |
|------|----------|------------|-------------|-----------|-----------|-----------|
| 第 4 轮 `0526901a` | **92%** | **2%** | 低 | 2 | — | — |
| soft#1 `a6de7860` | 高（58 ok 量级） | 低 | 1 | 1 | — | 56/7 |
| soft#2 `f7fc1b1a` | 54 | **3** | **2** | 1 | — | 57/6 |
| 回滚后 `689cfe71` | 54 | **3** | **3** | 0 | — | 59/4 |
| **§9 有效 `99d729de`** | **29** | **3** | **1** | **1** | **26** | **55/5** |

结论：启用 weak_hits 后「ok」口径变严（行为过关但低于 median → weak_hits）。cap 仍为 3；drift 1。

---

## 4. 当前问题清单（给下一模型）

### P1 — 宏 IR：改刀前 ~0.41；§9 有效单次 0.455（待 N≥2）

- 改刀前锚：`689cfe71` ≈ **0.409**。
- §9 有效：`99d729de` **0.455**（N=1 · 多刀打包）→ 方向正向，**非**可复现入库锚。
- 下一步：同配置再跑 ≥1 次；均值仍显著高于 ~0.41 才谈「平台上修」。

### P2 — 分库极不均衡（仍在）

- **NFCorpus** 仍拖宏平均（§9：nDCG@10 0.357 · R@10 0.078）。
- **FiQA** 在 limit=30 后仍 **R@10=R@100=0.542** → 深度假设未兑现；观察是否解挂 RET-5。

### P3 — free 分数 ≠ 纯 Index；§9 打包加重拆因难度

- 第 5 刀曾绑 rerank+limit；§9 又一次 **多刀同栈** → 本轮正 Δ **不能**拆到单刀。
- 后续若要否决/保留单刀，须回滚到单杠杆或做消融。

### P4 — 冒烟噪声

- 20q ±1.5–4pp 仍成立；§9 相对锚 +4.6pp 落在可讨论带，但仍要 **N≥2**。

### P5 — weak_hits 观测已落地

- RET-3 已强制直方图 + 低分 case 快照（本跑 weak 快照 30、median≈0.434）。
- 下一步用该列表立项 RET-4。

### P6 — 行为桶：cap 仍在；weak_hits 成主解剖桶

- search_cap×3 仍在；应盯 weak_hits 清单而非只看 ok%。

### P7 — Embed / INDEX 升级未做（检索）

- 生产仍 MiniLM-L6-v2 @384；**RET-4 未执行**；证据清单已有。

### P8 — 检索温度计场景 = writing，不是 agent

- 未变。L1 retrieval 默认 `writing`；`agent` 未注册 `search_sources`。

### P9 — 检索：计分窗 ≠ 模型窗

- 运行时 excerpt 已 **400**（RET-2b）；IR 仍只用 ranked。勿把 excerpt 刀写成 nDCG 原因。

### P10 — 静默重排可审计

- promote 字段已入 `retrieval.completed` schema；本有效跑 promote_total=55。

### P11 — 上下文：已专项调优（相对 CTX-0）

- CTX-0：F1≈0.33；§9 有效：F1 **0.413** · verbose **8** · gave_up **15**。
- 剩余主拖累偏 **gave_up_early**；verbose 已明显下降。须 N≥2。

### 问题 → 第二轮提案对照（§10 索引）

| 问题 | 对应 §10 刀 |
|------|-------------|
| P1 / P4（N=1、噪声） | REP-1 / REP-2 复跑 |
| P2（FiQA 深度、NFCorpus） | RET-6 审计三选一 → RET-4 / RET-5 裁决 |
| P3（打包不可拆因） | ABL-1 消融 + 批次 6 起单刀单 commit（门禁 6/7） |
| P5 / P7（weak_hits 清单、embed 未升） | RET-8 分类 → RET-4 执行细化 |
| P10（promote 静默重排） | RET-7 消融（做减法同权） |
| P11（gave_up 不降反升） | CTX-4 解剖 → CTX-5 / ABL-1；多跳预算 CTX-6；EM 残余 CTX-7 |

---

## 5. 当前代码与运行时状态（§13.8 部署窗口 A 收束后）

相对第五刀回滚态，运行时现为：

- `search_sources`：**default `limit=30`**（RET-1）；excerpt **400**（RET-2b）；**分层呈现** top-5 详摘 + 余下单行（RET-12）；**相对分** 0–100 + low_score 阈值 1.0 raw（RET-15-2）
- `search_sources_excerpt_promote`：**默认 False**（RET-7 消融后）
- `retrieval_two_level_enabled`：**默认 True**（RET-18 开关已透传；尚未消融）
- writing `system.md`：有 hit 后禁逛库；prefer limit≥30；verbatim / ≤2 搜；**无** RET-9 互补词面句（已回滚）
- agent `system.md`：Answer format（CTX-1）+ good/bad 示例（CTX-7）；长文续读 + grep→定向 read（CTX-2b/CTX-3）；**无** CTX-8
- `read_file` 截断 hint（CTX-2a）；INFRA-1 summary 截断；评测 INFRA-2 case 级隔离
- RET-3/6/10/14 观测字段与 EVAL-1/2/4/5/infra 基建在栈
- soft lexical 缩放：**仍无**；C-3 default fusion；m3 free
- **仍保留**：verbatim 首搜、≤2 搜次、C-1 读预算

---

## 6. 建议的下一轮思考框架（不规定具体补丁）

> 本节是「怎么想」的框架；**具体提案已在 §9 按此框架操作化**（每刀带 §1.4 最小卡片）；**§9 有效跑之后的第二轮提案在 §10**（同框架，追加「观测先于改动」「消融对称性」两条门禁）。

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

### 7.6 上下文 CTX-0 · `c8cc1bc1`（改刀前锚 · 2026-08-03）

```text
official.context.agent_f1 = 0.3295
official.context.agent_em = 0.3000
```

- title：`LongBench small · L1 agent-path · arm=free` · model=`deepseek-v4-flash` · protocol m3  
- 60 题：桶 ok 30 · verbose_answer 16 · gave_up_early 13 · steps_exhausted 1  
- 对照 `48c4aee1`：F1 0.331 / EM 0.25 → **CTX-0 平台 ≈0.33**

### 7.7 §9 有效检索 · `99d729de`（打包部署后 · 唯一有效验收读数）

```text
official.retrieval.ndcg_at_10 = 0.4550
official.retrieval.recall_at_10 = 0.4484
official.retrieval.recall_at_100 = 0.5091
official.retrieval.ndcg_at_1 = 0.3889
official.retrieval.map_at_10 = 0.3172
official.retrieval.n_queries = 20
```

- arm=free · protocol m3 · pass/fail 55/5  
- 桶：ok 29 · weak_hits 26 · search_cap 3 · query_drift 1 · no_search 1  
- suite_ndcg_median ≈ 0.434 · weak_hits_cases 30 · excerpt_promote_reorder_total 55  
- 分库 nDCG@10：SciFact 0.597 · NFCorpus 0.357 · FiQA 0.411（R10=R100=0.542）

### 7.8 §9 有效上下文 · `083eca09`

```text
official.context.agent_f1 = 0.4134
official.context.agent_em = 0.2833
```

- 60 题 pass 60；桶：ok 37 · verbose_answer 8 · gave_up_early 15  
- 分 task F1：multifieldqa_en 0.512 · hotpotqa 0.478 · narrativeqa 0.250  

> **不记录**：schema 事故跑（`retrieval.completed` 拒收 `excerpt_promote_reorder` → 大量空召回 / nDCG≈0.09）——非工程温度计，已修 schema，**不作对照**。

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
- **检索**：promote-off 平台 ≈**0.447**；RET-9 丢刀已回滚；主缺口 weak_hits / FiQA absent → **RET-4**（先 RET-17 sizing · REP-3 全量锚）。  
- **上下文**：excl-infra F1 ≈0.40–0.42；verbose 已控；主缺口 **wrong_answer** → **CTX-12 → CTX-8**。  
- **停机线**：第二观察批 **1/2**（RET-9）；契约批宏分多 `no_stable_delta` 符合诚实预期（见 §13.8「为何无大提升」）。  
执行进度见 **§13.8**。

---

## 9. 下一轮优化提案与执行方案

> **性质**：§9.1–9.5 为原提案正文；**§9.6 为执行进度与有效验收（2026-08-03）**。  
> **纪律提醒**：方案要求单刀单 commit；本轮实施为**打包部署**，有效正 Δ **不可单刀归因**——后续消融/回滚单刀时须自觉。

### 9.0 总体判断：分数弹性在哪里（先算账，再动刀）

成熟做法是先用已有分桶数据估「哪层工程的缺口最大」，再决定加热顺序，而不是凭直觉挑刀：

**上下文（F1≈0.33，60 题）——弹性最大、成本最低、从未动过**

| 桶 | n | 桶内 F1 | 若修复到 ok 水平（0.533）的宏 F1 弹性 |
|----|---|---------|----------------------------------------|
| gave_up_early | 13 | 0.000 | 理论 +0.115（13×0.533/60）；打五折仍 **+0.06** |
| verbose_answer | 16 | 0.235 | 理论 +0.079（16×0.298/60）；打五折仍 **+0.04** |
| ok | 30 | 0.533 | —（证明「读对且答短」时能力已在） |

→ 两桶都是**行为/契约层**问题（读得少、答得长），不是模型能力墙；静态文案与工具提示即可加热，全部 R 友好。**上下文是本轮性价比最高的主战场**：诚实预期平台 F1 0.33 → **0.40–0.45** 区间可及。

**检索（nDCG@10≈0.41）——弹性有限、需先补深度与证据**

| 证据 | 指向的工程层 | 短期弹性 |
|------|--------------|----------|
| FiQA 反复 R@10≈R@100（三跑均 ~0.49/0.54/0.49） | 合并 hit 有效深度（limit / 停搜 / union） | R@100 可先动；nDCG@10 或不动（先补 recall 是正常时序） |
| NFCorpus 长期 0.28–0.34 | Index/embed 相关性（叠加官方多 qrels 结构因素） | 需 embed 升级票，重活离线，本轮先立证据 |
| 回滚后 cap×3 / drift×3（vs 第 4 轮 2% cap） | 契约行为回潮或噪声 | 先归因再动文案 |
| soft#1 fail 特征：搜 1 次后大量 list_dir/grep | 模型对 hit 是否有用**不确信** → 逛库再确认 | excerpt 200 字可能过窄（行为层，不进 IR 公式） |

→ 检索侧诚实预期：nDCG@10 短期 0.41 → **0.43±噪声**；真正该看的是 **FiQA R@100 是否脱离 R@10、weak_hits 桶是否收窄**。宏分大涨要等 embed 升级（批次 4）。

### 9.1 第零步：重钉基线（一切对照的前提）

| 项 | 内容 |
|----|------|
| RET-0 | 与 `689cfe71` 完全同配置再跑 **2 次** free 20q，取三跑均值为「当前平台锚」（预期落 0.40–0.42 带）。此后所有刀的 Δ 都对这个均值，不再对 0.434 |
| CTX-0 | `c8cc1bc1` 与 `48c4aee1` 已双跑重合（0.330/0.331）→ **基线视为已钉**（F1≈0.33 / EM≈0.25–0.30），无需加跑；直接进刀 |
| 产出 | 把均值与各跑 run_id 记入本文件 §3.2 附表，作为 §9 全部提案的统一对照 |

### 9.2 检索提案（RET-1 … RET-5）

#### RET-1 · `search_sources` 默认 `limit` 10→30（单杠杆重开）

```text
加热层: 工具契约（深度）+ 合并深度
改动点: search_sources schema/实现默认 limit（单独 commit，不带任何 rerank/文案改动）
预期用户路径变化: 写作 RAG 单次搜索返回更深候选，长尾文档可进合并榜
R1–R5 / while / 强制搜: 通过——纯默认值；over-fetch 池 limit*2~4 → CPU 轻增在 R3 内；不改 loop、不强制搜
分桶预期: weak_hits ↓（尤其 FiQA）；ok 不变；行为几乎不动（模型可见面仍受 4k 截断，见下）
free 验收: N≥2 vs RET-0 锚；主看 FiQA R@100 与宏 R@100 是否脱离 R@10；nDCG@10 不劣化即可
非目标: 不指望 nDCG@10 立涨；不靠 forced 叙事
```

依据与设计取舍：

- FiQA 三跑 R@10≈R@100 是**深度不足**的直接证据（P2）；ranked cap 100，limit 30 × ≤2 搜 ≤60 条 union，不顶协议。
- **为什么 30 不是 50**：第五刀的 50 与 rerank 绑死整包回滚，limit 本身从未被单独证伪；30 已能测「深度假设」，且 tool_result JSON 的 4k 截断意味着模型可见面基本不变——**ranked（IR 计分）不受截断影响**（§1.4-D），正好把「深度对 IR 的贡献」与「行为副作用」解耦。
- **回滚条件**：N≥2 后 R@100 无正 Δ 或 nDCG@10 稳定下滑 → 还原 10。

#### RET-2 · 行为回潮归因 + 契约文案巩固

```text
加热层: 工具契约 / 静态 system 文案
改动点: writing system.md 静态文案（不动 hard 闸、不动 loop）
预期用户路径变化: 有 hit 后停止 list_dir/grep 逛库，直接 read 命中文件；重申原文首搜与 ≤2 搜次
R1–R5: 通过——纯静态字符串
分桶预期: search_cap 3→≤1、query_drift 3→≤1，回到第 4 轮量级；搜后 list_dir 步数下降
free 验收: 分桶为主、IR 为辅；N≥2
非目标: 不为压桶写死「必须搜 / 禁止 list_dir」这类强制剧本
```

前置动作（先归因再动刀）：读回滚后 + soft#2 两跑的 fail/cap/drift 轨迹（`process.jsonl`），确认回潮是**文案约束衰减**还是 20q 抽样噪声。若轨迹显示 cap/drift 案例的 query 与首搜纪律并无恶化 → 判噪声，**本刀撤销**，避免无病乱医。

#### RET-2b · excerpt 200→400 字（与 RET-1 互斥排期，独立 commit）

```text
加热层: 工具契约（模型可见证据窗，不进 IR 公式）
改动点: 搜索结果 excerpt 截断长度 200→400
预期用户路径变化: 模型能从 excerpt 直接判断 hit 是否可用 → 减少搜后 list_dir/grep 的「再确认」行为，更快转入 read
R1–R5: 通过——静态截断参数；无新计算
分桶预期: ok 内的「搜后逛库」步数下降；weak_hits 不动（IR 公式与 excerpt 无关）
free 验收: N≥2；主看行为轨迹（搜后工具序列）与 pass/fail，IR 预期持平
非目标: 不宣称本刀抬 nDCG（§P9：计分窗 ≠ 模型窗）
```

**与 RET-1 的交互（重要）**：limit 30 × excerpt 400 ≈ 12k JSON，会被 4k 预算截得只剩前几条——两刀同开会互相污染观测。**排期上先 RET-1（IR 深度）后 RET-2b（行为窗）**，各自 N≥2，绝不同 commit。

#### RET-3 · weak_hits 观测强制化 + 静默重排审计（尺子刀）

```text
加热层: 可归因性（评测产物，不动运行时行为）
改动点: official runner 报告强制输出——分桶直方图、每 case nDCG、低分 case 的 query+top hits 快照；
        另对 _prefer_excerpt_covering_hits 加日志：本次返回是否发生 promote 改序（P10 审计）
预期用户路径变化: 无（Turn 内零改动）
R1–R5: 通过——报告侧；promote 日志为轻量计数
分桶预期: 不改变分桶，只让 weak_hits 可解剖
free 验收: 不需要（观测刀）；产物质量以「能否直接开出 embed 票」衡量
非目标: 不把观测数据当分数叙事
```

这是 RET-4 的**立项前置**：embed 升级贵，必须先有「哪些 case 是纯相关性失败（行为已 ok、hit 仍弱）」的 case 列表，才符合原则一的可归因要求（P5）。

#### RET-4 · Embed 升级票（MiniLM-L6-v2@384 → 现代 small 级模型）

```text
加热层: Index plane（Turn 外，质量主战场）
改动点: embed 模型（候选 bge-small / gte-small 级，384→768 需处理 ANN 维数）+ INDEX_VERSION 8→9 + 离线全量重嵌
预期用户路径变化: 向量车道相关性天花板抬升，NFCorpus 类长尾语料召回改善
R1–R5: R4 合规——重嵌全部离线/影子索引；查询路径零新增同步活；切换=改配置指向新 INDEX_VERSION
分桶预期: weak_hits 显著收窄（以 RET-3 的 case 列表做前后对照）
free 验收: N≥2 分库看 NFCorpus/FiQA nDCG@10 与宏 R@100；正 Δ 后才谈全量锚 + compare
非目标: 不在 20q 单次上宣布成功；不因 forced/Index 网格涨分入库
回滚: 保留旧 INDEX_VERSION 向量不删，配置切回即回滚
```

排在批次 4：成本最高（全量重建 + 双份存储），且必须等 RET-3 证据立项。这是检索侧唯一有望突破 0.43 平台的**结构性**杠杆。

#### RET-5 ·（明确挂起）多搜合并协议 first-seen union → score-aware

first-seen union 使第二次搜**永远不能重排**已见 doc（§1.4-D）。成熟 RAG 会按分数/RRF 跨搜合并，但**改合并 = 计分协议 bump（m3→m4）**，历史对照全部作废。裁决：**挂起**——仅当 RET-1 落地后 FiQA 深度仍卡死（R@10 仍 ≈ R@100），才立 m4 协议票，并在换尺当天重钉全部基线。

### 9.3 上下文提案（CTX-1 … CTX-3 · 第一批专项刀）

> 场景提醒（§3.4.2）：本温度计 = **agent scenario + passage.md + read/grep + 短答**。改 `agent/system.md` 读纪律**会**影响本温度计（与检索 P8 相反），同时也影响产品 agent 用户——因此每条文案必须是「对产品用户本来就正确」的通用纪律，而非评测特化。

#### CTX-1 · 答题形态契约（打 verbose_answer，16 例 · F1 0.235）

```text
加热层: 工具契约 / 静态 system 文案（答题形态）
改动点: agent system.md 增加通用纪律——「用户指定了回答格式（如短短语/一个词）时，最终回答严格按格式给出，
        不附加解释、复述或引文；解释性内容仅在用户未限定格式时提供」
预期用户路径变化: 所有要求定格式输出的产品场景（不止评测）回答更守约
R1–R5 / while / 强制搜: 通过——纯静态文案；不加任何 runtime 答案后处理
分桶预期: verbose_answer 16 → 显著下降并转入 ok；EM 直接受益（verbose 的 F1>0 说明答案常已在长文里）
free 验收: 三 task×20 · N≥2；主看 verbose 桶量与桶内 F1、EM；宏 F1 预期 +0.03~0.06
非目标: 禁止在 runner/runtime 对答案做截断后处理（那是伺候分数，不是工程）
```

#### CTX-2 · 续读纪律（打 gave_up_early，13 例 · F1=0.000 —— 全场最大单桶）

两个子刀，**分开 commit**：

```text
CTX-2a（工具侧静态提示，类比检索 low_score hint 的成熟做法）
加热层: 工具契约
改动点: read_file 返回被截断且存在 next_offset 时，结果尾部附一行明确提示：
        「已读 X / 共 Y 字节，内容未完；续读请传 offset=N」
预期用户路径变化: 模型清楚知道「还没读完」这一事实，续读与否仍由它自由决定
R1–R5: 通过——静态字符串拼接
分桶预期: gave_up_early（判据=读入比例过低且 F1=0）直接受击
free 验收: N≥2；主看 gave_up 桶量；宏 F1 间接
非目标: 不强制「必须读完」（那是 oracle 剧本，毁 free 同构）

CTX-2b（system 静态文案）
改动点: agent system.md 增加——「回答依赖长文材料时，未找到答案前优先续读（offset 续读）而非放弃或凭前文猜测」
其余同上；与 CTX-2a 分 commit 以便拆因
```

监控点：续读会加大 token 消耗与步数——观察 steps_exhausted（当前仅 1 例）与单题时延。这是模型自主多轮，不触 R1–R5，但若 steps_exhausted 明显上升需回看 max_steps 边界。

#### CTX-3 · 长文读法引导：grep 定位 → 定向 read（排在 CTX-1/2 之后）

```text
加热层: Context 行为
改动点: agent system.md 增加读长文策略——「超长材料先用 grep 定位关键词命中行，再带 offset 定向 read 附近区间，
        避免从头顺序盲读」
预期用户路径变化: 长文 QA 少走「读 4k 就放弃」或「顺序读到步数耗尽」两个极端
R1–R5: 通过——静态文案
分桶预期: 主看 hotpotqa（multi-hop，F1 0.320）与 narrativeqa（长文，F1 0.255）分 task 提升；gave_up 进一步收窄
free 验收: N≥2 分 task 对照；宏 F1 间接
非目标: 不写死工具调用顺序（模型可自由选择直接 read）
```

**上下文侧不做清单**：不改 loop / max_steps 换分；不把 oracle 臂写进主栏；不动 LongBench 题面（题面属温度计本体）；不做答案后处理；不用检索侧任何 Δ 给 context 背书（P11）。

### 9.4 执行批次与验收门

| 批次 | 内容 | 前置 | 验收动作 | **进度** |
|------|------|------|----------|----------|
| 1（低成本先行） | RET-0 基线重钉 ×2 跑；RET-3 观测刀；CTX-1 答题形态 | 无 | RET-0 均值入 §3.2；CTX-1 跑 N≥2 看 verbose 桶 | **部分**：RET-3+CTX-1 已做；RET-0 跳过 |
| 2 | RET-1 limit 30；CTX-2a/2b 续读（分 commit） | 批次 1 锚已钉 | 各自 N≥2；RET-1 看 FiQA R@100，CTX-2 看 gave_up 桶 | **代码已做**；FiQA/gave_up 验收未过；未分 commit |
| 3 | RET-2 行为巩固；RET-2b excerpt 400；CTX-3 读法引导 | 批次 2 已收尾 | 分桶为主；N≥2 | **代码已做**（与批次 2 同栈） |
| 4 | RET-4 embed 升级票 | RET-3 产出 weak_hits case 列表足以立项 | 影子索引→free N≥2… | **未做**（清单已有） |
| 挂起 | RET-5 等 | — | 触发条件写明才解挂 | **仍挂起** |

**每刀统一门禁（重申，逐条自检后才跑温度计）**：

1. 单刀单 commit，卡片（§1.4）填全并附在 commit message / PR 描述。
2. R1–R5 + 不改 while + 不强制搜/读 + 无评测专用分支。
3. free N≥2 对 RET-0/CTX-0 锚看 Δ；20q/20×3 冒烟**只用于去留判断**，不 update-baseline。
4. 入库（SCORECARD/baseline）仅限：同协议全量锚 + 稳定正 Δ + 叙事写成「工程变好的间接证明」。
5. 任一刀 N≥2 无稳定正 Δ → 丢刀/回滚，禁止用 forced/oracle/Index 网格洗白。

### 9.5 预期结果的诚实版本（供验收时对照，防事后叙事漂移）

| 温度计 | 改刀前平台 | 批次 1–3 诚实预期 | **§9 有效单次** | 主要看什么 |
|--------|------------|-------------------|-----------------|------------|
| 上下文 agent_f1 | ≈0.33 | **0.40–0.45** | **0.413** ✓ 进带 | verbose/gave_up；须 N≥2 |
| 上下文 agent_em | 0.25–0.30 | 0.35–0.45 | **0.283**（未进带） | verbose→ok；单次未升 |
| 检索 nDCG@10 | ≈0.41 | **0.42–0.44** | **0.455**（单次超预期上沿） | 须 N≥2 均值 |
| 检索 FiQA R@100 | ≈0.49 且 ≈R@10 | 脱离 R@10、向 0.55+ | **0.542 仍 =R@10** ✗ | RET-1 未兑现 |
| 检索 weak_hits 桶 | 无强制产出 | 有 case 级列表 | **已有**（30 条快照）✓ | RET-4 立项依据 |

若 N≥2 后上下文 F1 掉回 <0.38、或检索跌回 ~0.41 噪声带、或 FiQA 深度仍卡死 → 回 §6 重新归因 / 考虑单刀回滚，而不是加大剂量。

### 9.6 执行进度与有效验收（2026-08-03）

| ID | 内容 | 状态 | 备注 |
|----|------|------|------|
| RET-0 | 改刀前再跑 2 次取均值锚 | **未严格执行** | 沿用 `689cfe71`≈0.409 作改刀前锚；未另跑双次均值 |
| CTX-0 | 上下文基线 | **已钉** | `c8cc1bc1` / `48c4aee1` ≈0.33 |
| RET-3 | weak_hits 报告 + promote 审计 | **已执行** | 有效跑已出桶/快照/promote；曾缺 schema 字段已补 |
| CTX-1 | 答题形态契约 | **已执行** | 有效跑 verbose 16→8 |
| RET-1 | limit 10→30 | **已执行** | 代码已上；FiQA R10 仍=R100 → **验收未过** |
| CTX-2a | read_file 续读 hint | **已执行** | 有效跑 gave_up 13→15 → **未见收益** |
| CTX-2b | system 续读纪律 | **已执行** | 同上（与 2a 打包，未拆因） |
| RET-2 | writing 有 hit 禁逛库 | **已执行** | 打包部署；未单独 N≥2 |
| RET-2b | excerpt 200→400 | **已执行** | `.env`+settings；与 RET-1 同栈（原方案互斥排期被打破） |
| CTX-3 | grep→定向 read | **已执行** | 打包；narrativeqa F1 仍低 |
| RET-4 | embed 升级 | **未执行** | 证据清单已有，待立项 |
| RET-5 | 合并协议 m4 | **挂起** | FiQA 深度仍卡，解挂条件仍观察 |

**批次表进度**

| 批次 | 计划 | 实际 |
|------|------|------|
| 1 | RET-0×2 + RET-3 + CTX-1 | RET-3+CTX-1 已做；RET-0 跳过 |
| 2 | RET-1 + CTX-2a/2b | **已做**（打包） |
| 3 | RET-2 + RET-2b + CTX-3 | **已做**（与 2 同栈，未分排期） |
| 4 | RET-4 | **未做** |
| 挂起 | RET-5 等 | **仍挂起** |

**有效跑（仅此记入对照）**

| 温度计 | run_id | 主指标 | vs 改刀前 |
|--------|--------|--------|-----------|
| 检索 free 20q | `99d729de` | nDCG@10 **0.455** · R@10 0.448 · R@100 0.509 | vs `689cfe71` 0.409 |
| 上下文 free 60 | `083eca09` | F1 **0.413** · EM 0.283 | vs CTX-0 ≈0.33 / 0.25–0.30 |

**下一步（门禁）**：同配置再各跑 **≥1 次**（凑 N≥2）→ 再裁决单刀去留 / 是否开 RET-4；**禁止**在 N=1 上 `update-baseline`。  
**第二轮提案（基于 §9 有效跑归因）见 §10。**

---

## 10. 第二轮优化提案与执行方案（基于 §9 有效跑 · 2026-08-03 起草）

> **性质**：本节是 §9 的后继提案，全部基于 `99d729de` / `083eca09` 两次有效跑的**已观测事实**推导；每刀带 §1.4 最小卡片，先过原则一/二再谈分数。  
> **核心纪律修正**：§9 打包部署导致正 Δ 不可拆因——本轮**恢复单刀单 commit + 部署即测**，且把「归因/观测刀」排在「改动刀」之前（成熟 agent 调优的标准时序：先量准，再动刀）。

### 10.0 本轮判断：§9 有效跑告诉我们什么（先算账）

**检索（0.455 · N=1）——最大桶已从行为迁移到相关性/排序**

| 已观测事实 | 归因方向 | 对应刀 |
|------------|----------|--------|
| weak_hits **26 例**成第一大失血桶（行为已过关、hit 仍弱）；RET-3 快照 30 条已在手 | Index/embed 相关性 或 排序搅动 | RET-8 分类 → RET-4 立项 |
| FiQA 在 limit=30 后**仍 R@10=R@100=0.542** | 三种互斥解释未拆开：① 合并榜有效长度其实 ≤10（模型显式传小 limit / 单搜就停）② 深度够但 10 名以外全不相关（相关性问题）③ qrels 结构 | **RET-6 先审计，禁止直接开 RET-5** |
| excerpt_promote_reorder_total = **55**（几乎每搜必改序） | `_prefer_excerpt_covering_hits` 在系统性覆盖 RRF 序，但**从未被单独证明有正贡献** | RET-7 消融 |
| cap 3 · drift 1 · no_search 1 | 行为侧已接近天花板 | 不再开行为刀 |

**上下文（F1 0.413 · N=1）——verbose 刀见效，gave_up 刀失效且可能有副作用**

| 已观测事实 | 归因方向 | 对应刀 |
|------------|----------|--------|
| verbose 16→**8**（CTX-1 方向成立）；但 EM 0.30→0.283 未升 | 残余 8 例 verbose 仍压 EM；或 F1>0 但措辞不精确 | CTX-7 |
| gave_up 13→**15**（CTX-2a/2b 未收窄反而略增） | 疑点：CTX-3 的「grep 先行」文案可能与 narrativeqa 释义性语言**互相拮抗**——grep 字面不命中 → 模型误判「材料里没有」→ 放弃。这是打包部署最典型的刀间干扰 | **CTX-4 先解剖轨迹**，再定 CTX-5 / 是否消融 CTX-2 |
| narrativeqa F1 **0.250**（最弱 task）；hotpotqa EM 0.55 但 F1 0.478 | 长文释义 + 多跳证据保持是两类不同失败 | CTX-5 / CTX-6 |
| ContextEngine：仅**最近一次** read 享 32k，此前 read 回落 4k | 多跳题第一跳证据在第二次 read 后被截 → 模型凭残片作答 | CTX-6（本轮唯一 runtime 候选刀） |

→ **加热顺序**：观测/归因（零风险）→ 静态契约单刀（低风险）→ 结构刀（RET-4 / CTX-6，重活离线或需预算评审）。

### 10.1 第零步（硬门）：复跑凑 N≥2 + 打包消融

| ID | 内容 | 说明 |
|----|------|------|
| REP-1 | 检索：与 `99d729de` **完全同配置**再跑 ≥1 次 free 20q | 均值 vs `689cfe71`≈0.409；均值仍 ≥0.44 才承认「§9 包整体正向」；掉回 ~0.41 带则回 §6 重新归因 |
| REP-2 | 上下文：与 `083eca09` 同配置再跑 ≥1 次 60 题 | 均值 F1 ≥0.40 才承认 CTX 包正向；同时看 gave_up 15 是否复现（复现→非噪声，CTX-4 必开） |
| ABL-1 | CTX-2a/2b 打包消融：**临时关闭**续读 hint + 续读文案，跑一次 60 题 | 若 gave_up 反而下降 → 证实刀间拮抗（续读文案诱导无效续读耗步数）→ 回滚 CTX-2；若不变 → 判 CTX-2 无效但无害，保留观察 |
| REP-3 | （批次收尾时）同协议**全量锚**各一次 | 入库唯一合法证据（§9.4 门禁 4）；冒烟均值再高也不直接 `update-baseline` |

> REP/ABL 全是跑测试与配置开关，零运行时新代码；ABL-1 的「关闭」指还原文案 commit，不是评测专用分支。

### 10.2 检索第二轮（RET-6 … RET-9 + RET-4 执行细化）

#### RET-6 · 合并榜深度审计（观测刀 · FiQA 归因前置）

```text
加热层: 可归因性（评测产物 + 轻量轨迹字段，Turn 内零行为改动）
改动点: official runner 报告新增——每 query：模型实际传入的 limit、n_search、
        各次 ranked 长度、first-seen 合并后总榜长；按数据集聚合分布
预期用户路径变化: 无
R1–R5 / while / 强制搜: 通过——报告侧统计，运行时最多加一个已存在事件字段的透传
分桶预期: 不改分桶；产出「FiQA 合并榜长度直方图」
free 验收: 不需要（观测刀）；产物质量以能否三选一裁决 FiQA 归因（榜短 / 深而不相关 / qrels 结构）衡量
非目标: 不把审计数据当分数叙事
```

裁决表（拿到数据后按此走，避免拍脑袋）：

| RET-6 观测结果 | 结论 | 后续 |
|----------------|------|------|
| FiQA 合并榜普遍 ≤10（模型显式传小 limit 或单搜即停） | 深度是**契约执行**问题，不是协议问题 | 微调 writing 文案重申 limit≥30（静态，单刀）；RET-5 继续挂起 |
| 合并榜 ≥30 但 10 名以外命中率≈0 | 深度已给足，是**相关性**问题 | 归 RET-4（embed）；RET-5 永久挂起的证据 |
| 合并榜长但相关文档被 first-seen 压在低位 | 合并协议问题**首次被证实** | 才解挂 RET-5（m4 协议票 + 重钉全部基线） |

#### RET-7 · excerpt-promote 改序消融（排序栈简化候选）

```text
加热层: 融合排序（热路径，做减法）
改动点: _prefer_excerpt_covering_hits 加配置开关，默认保持现状；消融跑=关闭后 free 20q N≥2
预期用户路径变化: 关闭时返回序回归纯 hybrid+RRF(+two-level/lexical)，少一层未经证明的静默重排
R1–R5: 通过——关闭是减计算；开关本身零成本
分桶预期: 若 promote 一直在帮忙 → 关闭后 weak_hits ↑ / nDCG ↓（则保留并记录正贡献）；
          若无差异或更好 → 默认关闭（简化排序栈 = 成熟取舍，见「lexical 默认开、CE 默认关」同款逻辑）
free 验收: N≥2 vs REP-1 均值；主看 nDCG@10 与 weak_hits 桶
非目标: 不因「代码写了就该留着」保留无证据的重排层
```

依据：promote_total=55 说明该层几乎每搜都在覆盖 RRF 序（P10），却从未有过单独的 free 对照。**排序栈里每一层都应该有自己的存在证据**——这是比加新刀更成熟的第一步。

#### RET-8 · weak_hits 30 条快照分类（RET-4 立项书）

```text
加热层: 可归因性（离线分析，不动运行时）
改动点: 对 RET-3 产出的 30 条低分 case 快照做失败分类（脚本 + 人工抽验）：
        ① 词面不匹配（query 与 gold 文档几乎无共享词 → 向量车道纯语义失败）
        ② 命中同主题但非 gold（排序细粒度问题）
        ③ qrels 多相关结构（NFCorpus 型，R@10 结构性低，见 §1.4-E）
预期用户路径变化: 无
R1–R5: 通过
free 验收: 不需要；产出物 = RET-4 立项书（各类占比 + 典型 case）
非目标: 不把 ③ 类结构性 case 当 embed 失败去修
```

若 ①+② 合计占比 ≥ 半数 → RET-4 立项充分；若 ③ 占大头 → embed 升级预期收益要打折，先在 §10.5 下修诚实预期再动。

#### RET-9 · 第二搜互补性文案（打 weak_hits 的行为侧余量）

```text
加热层: 工具契约 / 静态 system 文案
改动点: writing system.md 增加通用纪律——「首搜结果分数弱（low_score hint 触发）时，
        第二搜换用互补词面/同义关键概念，而非重复或微调原句」；仍在 ≤2 搜纪律内
预期用户路径变化: 弱命中后的第二搜真正扩大召回面，而不是浪费在同义重跑
R1–R5 / while / 强制搜: 通过——纯静态文案；不强制第二搜，搜与不搜仍由模型决定
分桶预期: weak_hits 边际收窄（对 ① 类词面失配 case 有效）；drift 需盯防（互补词面 ≠ 乱改写，
          文案须写明「保持原始信息需求，替换表述」）
free 验收: N≥2 vs REP-1 均值；主看 weak_hits 桶量与 drift 是否回潮
非目标: 不引入查询改写的额外 LLM 调用（R2）；不强制多搜
```

#### RET-4（执行细化 · 承接 §9.2 原票）

原卡片不变（§9.2），补充执行方案：

1. **候选与验证**：`bge-small-en-v1.5` / `gte-small` 级；先用 RET-8 分类出的 ①② 类 case（离线、不占 Turn）做嵌入相似度前后对照——gold 文档排名提升的 case 数即立项证据。
2. **影子索引**：新 `INDEX_VERSION=9` 全量离线重嵌（R4）；384→768 需新 ANN 索引，旧向量不删。
3. **切换与验收**：配置指向 v9 → free 20q N≥2，分库看 NFCorpus/FiQA nDCG@10 + weak_hits 桶（用 RET-8 同一 case 列表做前后对照）；正 Δ → REP-3 全量锚 → 才谈 compare/入库。
4. **回滚**：配置切回 v8 即回滚，零重建成本。
5. **排期**：RET-8 完成且 ①② 占比达标后立即开工；这是检索侧唯一可能突破 0.46 平台的结构杠杆，其余刀都是边际修整。

### 10.3 上下文第二轮（CTX-4 … CTX-7）

#### CTX-4 · gave_up 15 例轨迹解剖（归因刀 · 一切上下文刀的前置）

```text
加热层: 可归因性（离线读 process.jsonl，不动运行时）
改动点: 对 `083eca09` 的 15 例 gave_up 逐条分类：
        (a) grep 无命中后直接作答/放弃（CTX-3 拮抗假设）
        (b) 读一段即停、未续读（CTX-2 未生效）
        (c) 续读了但步数/耐心耗尽在错误区域（读法策略问题）
        (d) 判据误伤（实际读得够但 F1=0 → 是答错不是放弃）
预期用户路径变化: 无
R1–R5: 通过
free 验收: 不需要；产出 = 分类占比表，直接决定 CTX-5 开不开、CTX-2 消不消融（与 ABL-1 联动）
非目标: 不在归因前叠加更多续读文案（避免§9 打包错误重演）
```

#### CTX-5 · grep 失配回退纪律（打 narrativeqa · 条件开刀）

```text
加热层: Context 行为 / 静态 system 文案
改动点: agent system.md 对 CTX-3 的 grep 策略补一条回退——「grep 用于精确词面定位；
        若关键词无命中或材料为叙事/释义性文本，回退为分段顺序 read（offset 递进），
        不得据 grep 无命中断定材料无答案」
预期用户路径变化: 所有长文场景（不止评测）grep 失配后不再误判「没有答案」；对产品 agent 用户本来就正确
R1–R5 / while / 强制读: 通过——静态文案；读法仍由模型自选
分桶预期: gave_up 中 (a) 类直接受击；narrativeqa F1 0.250 是主观测位
free 验收: N≥2 分 task 对照；开刀前置 = CTX-4 证实 (a) 类占比可观（≥1/3）
非目标: 不写死「必须先 grep / 必须顺序读」的固定剧本
```

#### CTX-6 · 多跳读预算：「最近 1 次 read 32k」→「最近 K 次分级预算」（本轮唯一 runtime 候选刀）

```text
加热层: Context 行为（ContextEngine 组装预算策略；不改 while 序，只改预算分配）
改动点: 组装时对最近 K=2 次 read_file 结果给高预算（如 16k+16k 或 24k+8k），
        更早的 read 仍回落 4k；总预算不变或有界
预期用户路径变化: 多跳/对照类任务里，倒数第二份材料不再瞬间缩水到 4k——
        对产品用户的多文件阅读工作流同样是通用改善，非评测特化
R1–R5 / while: 通过需评审——纯预算再分配，无新模型调用、无新同步计算（R1–R3 安全）；
        需确认总 token 预算与折叠链（fold→budget→…）交互无回归（R5：加单测）
分桶预期: hotpotqa（两跳）F1/EM 受益；gave_up 中 (c) 类边际改善
free 验收: 单刀单 commit；N≥2 分 task 对照（主看 hotpotqa）；宏 F1 间接
非目标: 不无限抬预算（预算=速率资产）；不为评测把 K 调到题集形状上（K=2 是多跳的最小通用值）
回滚: 配置回 K=1 即还原 C-1 现状
```

这是 C-1（32k 最新 read）的自然延伸：C-1 解决「读得下」，CTX-6 解决「读完上一份不忘掉」。属于成熟长上下文 agent 的标准做法（保留最近工作集，而非只保留最后一步）。

#### CTX-7 · 答题形态残余：最小 good/bad 示例（打剩余 verbose 8 + EM）

```text
加热层: 工具契约 / 静态 system 文案
改动点: agent system.md 在 CTX-1 纪律后附一组最小对比示例——
        good:「Paris」 bad:「The answer is Paris, because the passage states…」
        （通用格式纪律示例，不含任何题集内容）
预期用户路径变化: 定格式输出场景的守约率进一步提高；EM 直接受益
R1–R5: 通过——静态文案
分桶预期: verbose 8 → ≤4；EM 0.28 → 0.32+（诚实预期，见 §10.5）
free 验收: N≥2；主看 verbose 桶与 EM
非目标: 不做 runner/runtime 答案截断后处理（同 CTX-1 禁令）
```

**上下文侧不做清单（承接 §9.3 并追加）**：不因 gave_up 上升就加大续读文案剂量（先 CTX-4 归因）；不把 oracle 臂读完率当 CTX-6 验收；CTX-6 以外不开任何 runtime 刀。

### 10.4 执行批次与验收门（批次 5–7）

| 批次 | 内容 | 性质 | 前置 | 验收动作 |
|------|------|------|------|----------|
| **5（观测/复跑 · 零风险先行）** | REP-1 / REP-2 复跑；RET-6 深度审计；RET-8 weak_hits 分类；CTX-4 gave_up 解剖；ABL-1 CTX-2 消融 | 跑测试 + 报告字段 + 离线分析 | 无 | 产出：N≥2 均值、FiQA 三选一裁决、RET-4 立项书、gave_up 分类表、CTX-2 去留 |
| **6（静态契约单刀）** | RET-9 第二搜互补；CTX-5 grep 回退（若 CTX-4 支持）；CTX-7 答题示例；RET-7 promote 消融 | 静态文案 / 配置开关 | 批次 5 归因产出 | **每刀单 commit、部署即测、N≥2**；分桶为主、IR/F1 为辅 |
| **7（结构刀）** | RET-4 embed 影子索引；CTX-6 读预算 K=2 | 离线重活 / runtime 预算 | RET-8 ①②占比达标；CTX-6 过 R5 单测评审 | 各自 N≥2 → REP-3 全量锚 → 才谈 compare / update-baseline |

**门禁重申（在 §9.4 五条之上追加两条）**：

6. **观测先于改动**：批次 6/7 任何刀在其对应归因产出（RET-6/8、CTX-4）落地前不得开工——§9 打包教训的直接制度化。
7. **消融对称性**：已在栈上但无单独证据的层（promote、CTX-2）与新刀同权对待——「留着」同样需要 free N≥2 证据，做减法与做加法同等合法。

### 10.5 预期结果的诚实版本（第二轮）

| 温度计 | 当前（§9 有效 N=1） | 批次 5–6 诚实预期 | 批次 7 诚实预期 | 主要看什么 |
|--------|---------------------|-------------------|------------------|------------|
| 检索 nDCG@10 | 0.455（待 N≥2 确认） | **0.44–0.47 带确认平台**（契约刀多为边际） | RET-4 若立项成立：**0.46–0.50** | REP-1 均值；weak_hits 桶 |
| 检索 FiQA | R@10=R@100=0.542 | RET-6 给出归因裁决（不承诺分数） | 按裁决路径走 | 三选一表（§10.2） |
| 检索 NFCorpus | 0.357 | 基本不动（结构性） | RET-4 主战场：0.38–0.42 | 分库 + RET-8 同 case 对照 |
| 上下文 agent_f1 | 0.413（待 N≥2） | gave_up 15→≤10 时 **0.43–0.47** | CTX-6 后 hotpotqa 抬升：**0.45–0.50** | gave_up 分类表；分 task |
| 上下文 agent_em | 0.283 | CTX-7 后 **0.32–0.38** | 随 F1 同向 | verbose 桶 → EM |
| narrativeqa F1 | 0.250 | CTX-5 后 **0.28–0.33**（长文释义是硬骨头，勿高估） | — | 分 task 对照 |

**失败预案**（防事后叙事漂移，与 §9.5 同款纪律）：

- REP-1 均值掉回 ~0.41 带 → §9 包正 Δ 判噪声，逐刀消融而非加新刀。
- ABL-1 显示 CTX-2 有害 → 回滚 CTX-2a/2b，gave_up 基线按消融后读数重记。
- RET-8 显示 ③ 类（qrels 结构）占大头 → RET-4 预期下修，检索侧承认「20q 冒烟平台 ≈0.45 即当前工程上限」，转投上下文与全量锚。
- 任一静态文案刀 N≥2 无稳定正 Δ → 丢刀；**文案不是免费的**——每多一条纪律都在消耗 system prompt 的注意力预算，无效即删。

### 10.6 批次 5 执行进度（2026-08-03 · REP/ABL 已收）

> **纪律**：批次 5 观测/复跑已完成；**未开**批次 6/7 改动刀（门禁 6）。**禁止**本节点 `update-baseline`。  
> **运行时栈（终态）**：§9 包（limit=30 · excerpt=400 · **CTX-1/2/3 全保留** · RET-2 文案）+ **RET-6 报告字段**。

| ID | 内容 | 状态 | 备注 |
|----|------|------|------|
| RET-6 | 合并榜深度审计（result.`depth_audit`） | **已部署** | 线上跑已出 `fiqa_adjudication` |
| RET-8 | weak_hits 30 条分类 | **已完成** | 脚本 `scripts/official_bench/batch5_offline_analysis.py`（产物在 `eval/reports/…/batch5/`，gitignore） |
| CTX-4 | gave_up 15 例解剖 | **已完成** | 同上；`(a)` 27% → **不开 CTX-5** |
| REP-1 | 检索 free 20q | **已完成** | `307ea1d0` · nDCG@10 **0.4425** |
| REP-2 | 上下文 free 60（**CTX-2 开**） | **已完成** | `9998d9eb` · F1 **0.3677** · EM **0.250** |
| ABL-1 | 关 CTX-2a/2b 后再跑 60 | **已完成** | `b84f26c0` · F1 **0.3661** · gave_up 15 → **保留 CTX-2** |

#### Ops 合并跑（提交主读数 · CTX-2 开启）

- 窗口：**2026-08-03 23:28:42 → 23:48:10**（UTC 15:28:42→15:48:10）· 用时 ~19m · pass **2/2**（retrieval+context）  
- 模型：`deepseek-v4-flash` · arm=**free** · protocol m3  

| 温度计 | run_id | 主指标 | 分桶要点 |
|--------|--------|--------|----------|
| 检索 free 20q | `307ea1d0` | nDCG@10 **0.4425** · R@10 **0.462** · R@100 **0.525** | ok28 · weak_hits27 · cap3 · drift1 · no_search1；`depth_audit`=**pool_starvation_despite_limit**；FiQA R10=R100=0.492 |
| 上下文 free 60 | `9998d9eb` | F1 **0.3677** · EM **0.250** | ok36 · verbose12 · gave_up12 |

**N=2（对照 §9 有效）**

| | §9 有效 | REP | 均值 | 相对改刀前锚 |
|--|---------|-----|------|--------------|
| 检索 nDCG@10 | 0.455 (`99d729de`) | 0.443 | **0.449** | vs `689cfe71`≈0.409 → **§9 包检索正向可认** |
| 上下文 F1 | 0.413 (`083eca09`) | 0.368 | **0.391** | vs CTX-0≈0.33 → 仍高；略低于「≥0.40 认包」线 |

#### ABL-1（CTX-2 去留）

| | CTX-2 | F1 | EM | gave_up | verbose |
|--|-------|-----|-----|---------|---------|
| REP-2 `9998d9eb` | 开 | 0.368 | 0.250 | 12 | 12 |
| ABL-1 `b84f26c0` | 关 | 0.366 | 0.250 | **15** | 9 |

- F1 几乎不动；关掉后 gave_up 略升 → **非有害**；宏 F1 主贡献仍偏 CTX-1。  
- **裁决：恢复并保留 CTX-2**（无效于宏分叙事、对 gave_up 至少无害/略有帮助）。  
- 旁注：关 CTX-2 后误跑的检索 `2753d1b7`（nDCG 0.379）因 **model transport 失败 → no_search×8**，**不作对照、不否决检索改动**。

#### 离线裁决（仍成立）

| 产出 | 结论 |
|------|------|
| RET-6 FiQA | **`pool_starvation_despite_limit`** → RET-5 挂起；结构杠杆 → RET-4 |
| RET-8 | lexical_miss 为主 → **RET-4 立项充分** |
| CTX-4 | `(a)` <1/3 → **不开 CTX-5** |

**下一步**：批次 6 起单刀（RET-7/9、CTX-7；CTX-5 不开）；RET-4 进批次 7。仍 **不** `update-baseline`。

---

## 11. 第三轮补充思考：外部对标与追加提案（2026-08-04）

> **性质**：在 §10 批次 5 产出之后、批次 6/7 开工之前的补充思考。全部遵守文首两道门 + §9.4 五条 + §10.4 追加两条门禁：观测刀在前、静态契约刀居中、Index/结构刀在后；不改 while、不强制搜/读、只认 free、重要刀 N≥2、单刀单 commit。  
> **编号承接**：EVAL-1~3（评测基建）/ RET-10~13 / CTX-8~9；与既有批次的排期嵌入见 §11.5，终态定义见 §11.6；**执行进度见 §11.7**。  
> **本节不推翻 §10 任何裁决**（RET-4 立项、CTX-5 不开、RET-5 挂起均维持）。  
> **实施状态**：§11.5「6 前置」+ RET-12 + EVAL-infra **已落地**（§11.7）；其余契约/结构刀（RET-7/9、CTX-7/8、批次 7）未开。

### 11.0 外部对标：成熟 agent 在这两条流程上怎么做（映射到本栈）

| # | 成熟做法 | 代表 | 本栈现状 | 缺口 → 对应刀 |
|---|----------|------|----------|----------------|
| 1 | 模型驱动检索：不强制搜、纪律写在工具描述与 system 静态文案里 | Claude Code / Cursor 的 agentic search | 已对齐（free 主臂 + verbatim/≤2 搜 + RET-2/9 系文案） | 行为侧已近天花板（§10.0），无需新刀 |
| 2 | 搜索结果**紧凑分层呈现**：保证模型看到候选全宽度（title/path 一行 × 全部 + 摘要 × 头部），而不是让截断决定可见面 | 各类成熟 agent 的 search 工具渲染 | limit30 × excerpt400 ≈ 12k JSON，曾被 4k 预算截到只剩前几条；**RET-12 已落地**（top-5 详摘 + 余下单行） | **RET-12**（已部署；free 行为验收 N≥2 进行中） |
| 3 | **离线语料增强**：入索引前用离线 LLM 给 chunk 补定位上下文 / 生成伪查询，embed 与 BM25 同吃（Anthropic 报 top-20 检索失败率降约 49%，与 embed 升级正交可叠加） | Anthropic Contextual Retrieval（2024-09）/ doc2query 系 | embed 文本仅 path 线索 + body；BM25 车道对 lexical_miss（RET-8 主类）无能为力 | **RET-11**（R4 合规离线重活，与 RET-4 正交） |
| 4 | 一次调用多 query、服务端融合（multi-query / RAG-fusion） | LlamaIndex / LangChain 标准件 | first-seen union 使第二搜不能重排已见 doc；RET-5 挂起 | **RET-13**（挂起级候选，见卡片内解挂条件） |
| 5 | **逐题配对显著性检验**：同一批 query 前后配对比 Δ + bootstrap/符号检验，而非裸比宏均值 | IR 社区（TREC）几十年惯例 | 用「N≥2 取均值 vs 锚」抗 ±1.5–4pp 噪声，判别力低、跑一次 ~20m | **EVAL-1/2**（零成本大幅提高判别力，所有后续刀受益） |
| 6 | 长上下文**证据先行**（quote-then-answer / structured note-taking）：作答前先摘支撑引文，提炼物天然留在对话里抗截断 | Anthropic context engineering / 各长文 agent 的 citations 实践 | 只有读法引导（CTX-2/3），无证据保持纪律；hotpotqa 第一跳证据被 4k 回落截掉（§10.0） | **CTX-8**（与 CTX-6 互补：CTX-6 保原文，CTX-8 保提炼） |
| 7 | **注意力预算管理**：system prompt 每条纪律有成本，定期合并精简 | 成熟 prompt 工程共识 | §10.5 已有「文案不是免费的」共识，但无量化台账；CTX-3×narrativeqa 拮抗已是实例 | **EVAL-3** |

### 11.1 评测与归因基建（EVAL-1~3 · 排最前 · 零运行时改动）

#### EVAL-1 · 逐题配对对照 + 置信区间（判别力刀 · 所有后续刀的乘数）

```text
加热层: 可归因性（compare 报告侧，Turn 内零改动）
改动点: official-bench-compare 增加——同题包两跑的每 query 配对 Δ（nDCG@10 / F1）、
        win/loss/tie 计数、中位配对 Δ、bootstrap 95% CI（或符号检验 p 值）
预期用户路径变化: 无
R1–R5 / while / 强制搜: 通过——纯报告计算
分桶预期: 不改分桶；改「刀的去留怎么判」
free 验收: 不需要（观测基建）；产物质量以「能否把 ±1.5–4pp 噪声带内的刀判出生死」衡量
非目标: 不用 CI 替代全量锚入库门禁（入库规则不变）
```

依据：20q 冒烟的噪声主要来自**查询间方差**（题与题难度差远大于刀的效应量）；同题配对能消掉这部分方差，判别力等价于把 N 放大数倍，而每次跑仍是 ~20m。现状「均值 0.449 vs 锚 0.409」的读法里，一半信息（每题方向一致性）被扔掉了。runner 已有每 case 分数（`result.json` cases），只差 compare 侧一段统计。**这是本节所有提案里性价比最高的一件事**：批次 6 每刀 N≥2 的裁决质量直接取决于它。

#### EVAL-2 · 冒烟题包固定与轮换（配对前提）

```text
加热层: 可归因性（抽样协议）
改动点: 断言并在 manifest 记录冒烟 20q/20×3 的抽样确定性（固定 seed 或固定切片）；
        若当前非确定性 → 固定之；同时规定每 M 轮（建议 M=4~6 批次）轮换一次题包防过拟合
预期用户路径变化: 无
R1–R5: 通过
free 验收: 不需要；与 EVAL-1 绑定生效
非目标: 固定题包只服务配对去留判断；入库仍以全量锚为唯一合法证据（门禁不变）
```

#### EVAL-3 · 契约文案 token 台账（防纪律通胀）

```text
加热层: 可归因性 / 注意力预算
改动点: 每条契约刀在卡片里记录 system.md / 工具描述的增量 token 数；维护累计台账；
        累计增幅超阈值（建议相对 CTX-0 时点 +15%）触发一次合并精简评审（精简本身按单刀走 N≥2）
预期用户路径变化: 长期防止纪律条目互相稀释/拮抗（CTX-3 与 narrativeqa 的拮抗即前车之鉴）
R1–R5: 通过——台账是文档工作
free 验收: 不需要
非目标: 不以台账为由拒绝有证据的新文案刀；台账只触发「评审」，不自动删条目
```

### 11.2 检索追加刀（RET-10~13）

#### RET-10 · 车道级候选深度审计（观测刀 · pool_starvation 的第二解释排除）

```text
加热层: 可归因性（depth_audit 增字段，Turn 内最多透传已有中间量）
改动点: depth_audit 每 query 增加——vector 车道候选数、BM25 车道候选数、去重并集大小、
        two-level 补充数、over-fetch 实际倍数；按数据集聚合
预期用户路径变化: 无
R1–R5: 通过——轻量计数
分桶预期: 不改分桶；产出「FiQA 池子在哪一级被饿死」
free 验收: 不需要（观测刀）；产物质量以能否二选一裁决衡量（见下）
非目标: 不在审计前就调车道 k
```

依据：`pool_starvation_despite_limit` 当前被整体归因到「结构杠杆 → RET-4」，但该裁决词本身有两种成因未拆开：**(i) 每车道 top-k / over-fetch 倍数先把池子饿死**（融合排序层，热路径轻量旋钮即可修，R3 可预算）；**(ii) 车道给足了但候选确实不相关**（才真正归 RET-4/11）。若审计显示是 (i)，单刀提高车道 k 的成本比影子索引低一个数量级——**在开批次 7 重活之前值得花这一跑排除**。若是 (ii)，RET-4 立项书反而更扎实。

#### RET-12 · 搜索结果分层呈现（修「模型只见前几条」的已知自伤）

```text
加热层: 工具契约（结果呈现；不进 IR 公式）
改动点: search_sources tool_result 渲染改为两层——top-5 带 400 字 excerpt；
        第 6~30 名仅 path + title + score 单行；总 JSON 控制在 4k 预算内不被截断
预期用户路径变化: 模型第一次真正「看见」30 条候选的全宽度，可以主动 read 第 17 名，
        而不是被 4k 截断只见前几条；RET-1 买来的深度从「只进 ranked」变成「行为可用」
R1–R5 / while / 强制搜: 通过——纯格式化，无新计算
分桶预期: weak_hits 中「gold 在榜上但模型没看见/读错文档」的部分 ↓；搜后 list_dir 再降；
        ranked 与 IR 完全不动（P9 纪律：勿把本刀写成 nDCG 原因，但行为改善可间接带动读对文档后的终答）
free 验收: N≥2（配 EVAL-1 配对）；主看行为轨迹（搜后 read 目标名次分布）与 weak_hits 桶
非目标: 不动 4k tool_result 预算本身；不宣称本刀直接抬 nDCG
```

依据：§9.2 在 RET-2b 卡片里明确写了 limit30×excerpt400 ≈ 12k 会被 4k 截得只剩前几条、两刀须互斥排期——§9.6 承认排期被打破、两刀同栈至今。**当前运行时栈上这是一处已知、已文档化、未处理的自我矛盾**；成熟 agent 的 search 工具几乎都做分层渲染（全部候选一行摘要 + 头部详情），正是为了让「深度」对模型可见。此刀应排在批次 6 最前。

#### RET-11 · 离线语料/嵌入文本增强（Index plane · 正面攻击 lexical_miss）

```text
加热层: Index plane（Turn 外离线重活，R4 合规）
改动点: 物化/索引前离线为文档生成补充文本，两个成熟变体择一先试（分开拆因）：
        (a) contextual chunk header——离线 LLM 用全文为每 chunk 写 1~2 句定位语，
            拼在 chunk 前，embed 与 BM25 字段同吃（Anthropic Contextual Retrieval 做法；
            其基准报告 contextual embedding+BM25 合计降低 top-20 检索失败率约 49%）
        (b) doc2query 式伪查询——为每 doc 离线生成 3~5 个可能的查询词面，仅拼入 BM25 字段
        任一变体：INDEX_VERSION bump + 影子索引；查询路径零改动
预期用户路径变化: 词面桥从语料侧搭起——query 与 gold 无共享词的 case（RET-8 主类 lexical_miss）
        BM25 车道从「无能为力」变「能救」；对产品树状语料同样通用
R1–R5 / while: 通过——全部离线；R4 影子索引，配置切回即回滚
分桶预期: weak_hits 中 lexical_miss 类收窄（用 RET-8 同一 case 清单前后对照）
free 验收: N≥2 分库看 FiQA/NFCorpus nDCG@10 + weak_hits；诚实预期分库 +0.02~0.05（BEIR 文档短，
        (a) 的定位语增益或有限，(b) 更对症本题集；勿照搬 Anthropic 长文语料的降幅预期）
非目标: 不在查询路径做 HyDE/查询改写 LLM 调用（违 R2）；
        **严禁**用 qrels/官方 query 文本参与生成（那是注入答案，违反因果表「错」列）
回滚: 配置切回旧 INDEX_VERSION，零重建成本
```

与 RET-4 的关系：**正交可叠加**——RET-4 换向量车道的脑子，RET-11 改两条车道的食材。排期上同属批次 7 级重活；若 RET-4 因 384→768 维数/ANN 成本受阻，RET-11(b) 是不动 embed 模型的替代路线（纯 BM25 字段扩展，连 ANN 都不用重建）。两票若都做，**必须分影子索引分别 N≥2**，不得重演 §9 打包错误。

#### RET-13 ·（挂起级）单次调用多 query 服务端融合

```text
加热层: 工具契约 + 融合排序（涉行为分布，谨慎）
改动点: search_sources 接受 queries[]（2~3 条），服务端各自检索后 RRF 融合出单一 ranked——
        单事件单榜，绕开 first-seen union 的跨搜不可重排，不 bump m4 协议
预期用户路径变化: 模型一次表达多个互补词面（它本来就在做的事，只是省掉第二轮），
        融合榜质量优于两次独立搜的 first-seen 并集
R1–R5: 通过——无新 LLM 调用（query 由主模型在工具参数里给出）；服务端多一次并行检索在 R3 预算内
分桶预期: weak_hits ↓；drift 需盯防（多 query ≠ 乱改写，schema 描述须重申保持原始信息需求）
free 验收: N≥2 + EVAL-1 配对
非目标: 不强制传多 query（单 query 仍合法）；不因此放松 ≤2 搜纪律
解挂条件（写死）: RET-9 N≥2 证实「互补词面第二搜」有正 Δ，且 RET-10/11/4 之后 FiQA 深度仍卡
        —— 三者同时成立才立项；否则永久挂起
```

理由放在挂起位：改 schema = 行为分布变化 + 一次协议边缘试探,在 RET-9 尚未证明「多词面有增益」之前开它属于跳步。

### 11.3 上下文追加刀（CTX-8~9）

#### CTX-9 · gave_up 判据细化 + 读覆盖率探针（观测刀 · 排在一切上下文刀前）

```text
加热层: 可归因性（L2 探针与分桶判据，不动运行时）
改动点: ① gave_up_early 拆为两个子桶——truly_abandoned（读入比例低且未续读即答/放弃）
        与 wrong_answer_after_read（读入充分但 F1=0——是答错，不是放弃）；
        ② trace 增加 read_coverage =（累计已读字节 / passage 大小）、续读次数、末次 read 位置
预期用户路径变化: 无
R1–R5: 通过
分桶预期: 现 gave_up 12~15 例将分流；CTX-2/5/8 的验收从此各看各的子桶
free 验收: 不需要（判据刀）；生效当轮起 gave_up 系读数按新口径重记（旧数不可直接比，需注记）
非目标: 不为让某刀「显得有效」调判据阈值（判据改动一次性、先于刀、写明动机）
```

依据：CTX-4 已发现 (d) 类「实际读得够但 F1=0 → 是答错不是放弃」的误伤——**判据混桶时，续读类刀（CTX-2）与证据类刀（CTX-6/8）的验收在读同一口混数**。§10 已把「观测先于改动」定为门禁 6，判据本身的清晰度是同一条纪律的延伸。成本极低（分桶脚本 + 一个比值字段）。

#### CTX-8 · 证据先行纪律（quote-then-answer · 打「读了但答错」与多跳证据丢失）

```text
加热层: Context 行为 / 静态 system 文案
改动点: agent system.md 增加通用长文纪律——「回答依赖长材料时，最终作答前先摘录 1~3 条
        支撑原文短引文（注明大致位置）；再仅基于摘录作答；若摘不出支撑句，继续定位而非凭印象作答」
预期用户路径变化: 所有长文场景（不止评测）先取证后作答；摘录留在对话历史里，
        天然是抗 4k 截断的「工作集」——第一跳证据以提炼形态存活到第二跳之后
R1–R5 / while / 强制读: 通过——纯静态文案；读法与是否摘录仍由模型自主
分桶预期: CTX-9 新口径下 wrong_answer_after_read ↓；hotpotqa（多跳证据保持）与
        narrativeqa（释义长文，防凭印象臆答）分 task F1 为主观测位；
        verbose 需盯防——文案必须写明两阶段（摘录是过程，最终答案仍守 CTX-1 短答格式）
free 验收: N≥2 分 task + EVAL-1 配对；同时观测步数/时延（摘录多一步自然消耗，watch steps_exhausted）
非目标: 不强制固定 scratchpad 格式、不加任何 runtime 解析/后处理；不把摘录写成必须步骤（自由臂）
```

与 CTX-6 的关系（互补且可能替代）：CTX-6 用预算保住**原文**（最近 K=2 次 read 各 16k），CTX-8 用提炼保住**结论**。成熟长上下文 agent 两者都做，但 CTX-8 是静态文案（便宜、零风险），CTX-6 是 runtime 预算刀（需 R5 单测评审）——**排期上 CTX-8 先行**；若 CTX-8 落地后 hotpotqa 的证据丢失已被摘录解决，CTX-6 的必要性应重估（在 CTX-6 验收卡片里加一条：对照「已有 CTX-8」的基线，而非对照裸 §9 栈）。这与 §10.4 批次结构（静态先于结构）一致。

### 11.4 本节不做清单（承接 §9.3 / §10.3 并追加）

- 不在 EVAL-1/2 落地前开批次 6 任何契约刀的第二轮裁决（先把尺子换成配对读法）。
- 不把 RET-12 的行为改善写成 nDCG 叙事（P9 纪律）；不把 RET-11 的离线 LLM 生成物混入任何含 qrels 信息的路径。
- 不因外部对标数字（如 contextual retrieval 的 49%）直接抬高本栈诚实预期——语料形态不同，预期以 §11.2 卡片内保守带为准。
- 不同时上 RET-4 与 RET-11 于同一影子索引；不同时上 CTX-6 与 CTX-8 于同一 commit。
- 不新增任何需要查询路径同步 LLM 调用的刀（HyDE、查询改写、LLM rerank 一律不做，R2/R3）。

### 11.5 排期建议（嵌入既有批次，不打乱 §10.4）

| 批次 | §10 原计划 | 本节追加 | 性质 |
|------|------------|----------|------|
| **6 前置**（可即刻并行） | — | EVAL-1/2（compare 配对报告 + 抽样断言）；RET-10 车道审计；CTX-9 判据细化；EVAL-3 台账建账 | 观测/基建 · 零运行时改动 |
| **6**（静态契约单刀） | RET-7 promote 消融；RET-9 第二搜互补；CTX-7 答题示例 | **RET-12 分层呈现**（建议排最前，修已知自伤）；**CTX-8 证据先行**（排 CTX-7 之后，防两条答题文案同批互扰） | 每刀单 commit · 部署即测 · N≥2 配对 |
| **7**（结构刀） | RET-4 embed 影子索引；CTX-6 读预算 K=2 | **RET-11**（与 RET-4 分影子索引拆因；受阻时 (b) 变体为替代路线）；CTX-6 验收基线改为「含 CTX-8 的栈」 | 离线重活 / runtime 评审 |
| **挂起** | RET-5 | **RET-13**（解挂三条件见卡片） | 协议敏感 |

### 11.6 什么样的终态才算「合理、完备」（建议作为入库叙事与停机线）

终态**不是某个分数**，而是四个「可回答」——全部能回答时，这轮调优就是完备的：

1. **每一层有存在证据**：排序栈每层（hybrid / RRF / two-level / lexical / promote / 呈现层）都有一次 N≥2 的正贡献证据，或已被消融移除。不存在「代码写了就留着」的层。RET-7 是第一块，终态是全栈过完一遍。
2. **每一个残余失败可归因**：weak_hits 与 gave_up（新口径）的残余 case 100% 可分类到 {qrels 结构 / embed 语义天花板 / 模型能力墙} 三者之一，且各类有 case 清单——即「剩下的分数缺口，我们知道为什么剩、并决定不修」。
3. **温度计本身可信**：固定题包配对对照已常态化（EVAL-1/2）；同协议全量锚已入库至少一次（REP-3）；P8 场景同构有明确决策记录（接受 writing-RAG 为目标，或补 agent 工具面后换温度计）——不再是悬案。
4. **有停机线**：连续两个批次的契约刀配对 CI 均含 0 → 停开新契约刀；边际投入转向全量锚、产品树状语料上的同构验证、与 P8 决策。**温度计的使命是校准工程，不是无限刷冒烟。**

在四条满足的前提下，数字的诚实带（对照参考，不作 KPI）：

| 温度计 | 当前平台（N=2） | 完备终态诚实带 | 备注 |
|--------|-----------------|----------------|------|
| 检索 nDCG@10（冒烟） | ≈0.449 | **0.46–0.50** | RET-4/11 至少一票落地后；再往上要换题集尺度谈 |
| 检索 FiQA | R@10=R@100 | R@100 稳定脱离 R@10 | 深度问题按 RET-10 裁决路径关闭 |
| 检索 NFCorpus | 0.357 | 0.38–0.42 或**书面承认结构下限** | ③ 类占大头时选后者，写进归因记录 |
| 上下文 agent_f1 | ≈0.391 | **0.45–0.50** | CTX-6/8 落地后；narrativeqa 0.30± 即接近该模型能力墙 |
| 上下文 agent_em | 0.25–0.283 | **0.32–0.38** | 主要由 verbose→ok 转化兑现 |
| 行为桶（检索） | cap3 · drift1 · no_search1 | 维持 ≤5% 总量即视为清洁 | 不再投入行为刀 |
| gave_up（新口径） | 12–15（混桶） | truly_abandoned ≤5；其余归入 wrong_answer 类并有归因 | CTX-9 生效后重记 |

**一句话版**：当「每层有证据、每败有归因、尺子可信、知道何时停」四条同时成立，且冒烟平台进入上表诚实带，本轮检索与上下文工程即可宣布完备——之后的分数问题属于换 embed 时代/换模型时代的新一轮，而不是本 brief 的延长线。

---

## 11.7 批次 6 前置执行进度（2026-08-04 · 观测/基建 + RET-12 + EVAL-infra）

> **纪律**：§11.5「6 前置」已落地并观测；**RET-12 / EVAL-infra / CTX-9 探针**已部署且有 free 读数。其余批次 6 刀（RET-7/9、CTX-7/8）与批次 7 未开。**禁止**本节点 `update-baseline`。  
> **门禁**：EVAL-1/2 已就绪；RET-10 裁决 `lanes_fed_relevance`（`0744546e`）；CTX-9 新桶可用；主宏分已剔 `infra_channel`。

| ID | 内容 | 状态 | 备注 |
|----|------|------|------|
| EVAL-1 | 逐题配对 Δ + win/loss/tie + bootstrap 95% CI + sign_p | **已完成** | `baseline.paired_case_delta_report`；`make official-bench-compare`；`--compare-runs A,B` |
| EVAL-2 | 冒烟题包确定性断言 + manifest.`sample_policy` | **已完成** | `method=head_slice` · `ids_fingerprint=7a12e885fa75b4e3`（ret/ctx smoke） |
| EVAL-3 | 契约文案 token 台账 | **已完成** | 见下表；阈值 = 相对建账点 +15% |
| RET-10 | 车道级 depth（vector/bm25/union/top_k/over_fetch/two_level） | **已完成** | `0744546e` → `fiqa_lane_adjudication=lanes_fed_relevance` → **不先抬 lane-k；RET-4 仍立项** |
| CTX-9 | `truly_abandoned` / `wrong_answer_after_read` + read_coverage | **已完成** | 探针修复后 `1707135c` 重记桶（见下） |
| RET-12 | search_sources top-5 详摘 + 余下单行 | **已完成（代码+观测）** | `3c34de88` vs `0744546e` → `no_stable_delta`（预期，不写 nDCG）；待再跑凑 N≥2 行为读 |
| EVAL-infra | 通道不稳剔出主宏分 | **已完成** | 桶 `infra_channel`；主分不含；`*_incl_infra` 旁注 |

#### 通道不稳剔除规则（EVAL-infra · 2026-08-04）

- **识别**：`turn.failed` / 异常文案含 `model_error`、`503`/`too busy`、`transport error`、`first byte timeout`、`openai http timeout`、`retries exhausted` 等 → `failure_class=infra_channel`。  
- **分桶**：优先 `infra_channel`，**禁止**并入 `truly_abandoned` / `no_search` / `steps_exhausted`。  
- **主宏分**：上下文 `agent_f1`/`agent_em`、检索 IR 宏均只对非 infra case；审计保留 `agent_f1_incl_infra` / `ndcg_at_10_incl_infra` 与 `infra_rate`。  
- **仍计入**：完成 Turn 的放弃/答错/verbose、非通道的 failed（如步数耗尽）。  
- **裁决**：`infra_rate` 过高时整跑仍可标「通道不稳、谨慎对照」；剔除不等于洗白。  
- **Ops 读数**：单次批看选中 Ops 行的 `official.context.agent_f1`（最新 context 批应为剔后主分）；勿与历史批 0.299 混淆；`*_incl_infra` 为旁注。

#### Free 观测跑（2026-08-04 · 有效读数）

| 套件 | run_id | 主指标 | 分桶 / 备注 |
|------|--------|--------|-------------|
| 检索 free 20q（RET-10 观测） | `0744546e` | nDCG@10 **0.426** | `lanes_fed_relevance`；FiQA R10=0.392 R100=0.625 |
| 检索 free 20q（RET-12 后） | `3c34de88` | nDCG@10 **0.426** | 配对 vs `0744546e` → **no_stable_delta**（预期）；weak_hits 27；read-after-search 58/60 |
| 上下文（探针坏，作废） | `327953e2` | — | coverage 全 0；**不作对照** |
| 上下文（503 潮，作废） | `0d299f6b` | F1 0.165（污染） | failed 31/60 · 几乎全 503；**不作对照** |
| 上下文（transport，半废） | `01e17a80` | F1 0.299（未剔） | failed 17 · 污染 abandoned；**不作效果锚** |
| 上下文 free 60（**有效**） | `1707135c` | F1 **0.424** · EM **0.331** | 见下；Ops 批 `a2acdbd1` |

**`1707135c` 分桶（CTX-9 + EVAL-infra）** · n=60 · scored=53 · infra_excluded=7 · infra_rate=11.7%

| 桶 | n | 说明 |
|----|---|------|
| ok | 36 | 主峰 |
| wrong_answer_after_read | 9 | 全 completed → 真「读了答错」 |
| infra_channel | 7 | 全 failed → 已剔出主分 |
| verbose_answer | 6 | |
| truly_abandoned | 2 | 全 completed → 真放弃 |

分 task（剔 infra 后）：multifield **0.55**（20）· hotpot **0.43**（18）· narrative **0.29**（15）。  
含 infra 旁注：F1 0.385 · EM 0.300。  
**裁决**：CTX-5 仍不开（abandoned 仅 2）；主缺口 **wrong_answer** → 下刀偏 CTX-8/7；本跑 **N=1**，不入库。

#### EVAL-3 · 契约文案 token 台账（建账点 = 2026-08-04 · §9 包终态）

近似 token = `chars // 4`（非 tokenizer；只用于纪律通胀相对量）。

| 文件 | chars | ≈tokens | 相对建账点 | 来源刀（累计） |
|------|------:|--------:|-----------|----------------|
| `scenarios/agent/system.md` | **9753** | **2438** | **+11.2%**（相对 2193） | CTX-1/2b/3/7 + **CTX-8** |
| `scenarios/writing/system.md` | **12665** | **3166** | **+1.1%**（相对 3133） | verbatim / ≤2 搜 / RET-2；**RET-9 已回滚**（−互补词面句） |
| 工具描述 `search_sources` schema | （实现默认） | — | — | RET-1 limit=30；excerpt 属 settings 非 system |

**阈值**：任一文件相对本表建账点 **+15% ≈tokens** → 触发合并精简评审（精简本身按单刀 N≥2）。  
**批次 6 拟增刀预留记账**（落地时回填实测 Δ）：

| 拟增刀 | 目标文件 | 预估增量（字） | 记入条件 |
|--------|----------|----------------|----------|
| RET-9 第二搜互补 | writing/system.md | ~200–400 | **已合入后 N≥2 丢刀 → 已回滚**（§13.8） |
| RET-12 分层呈现 | 工具格式化（非 system） | 0 system | 不进本台账分子（已落地） |
| CTX-7 答题示例 | agent/system.md | ~150–250 | **已合入**（+256 字 / ≈+64 tok；N≥2 已收） |
| CTX-8 证据先行 | agent/system.md | ~200–400 | **已合入**（agent ≈+723 字 / ≈+181 tok；待 free N≥2） |

#### 单测

- `scripts/tests/test_official_bench_baseline.py`：配对 bootstrap / CI 含 0  
- `scripts/tests/test_official_bench_agent_path_extract.py`：RET-10 lane；CTX-9 新桶；infra_channel 识别/分桶  
- `services/runtime/tests/test_retrieval_audit.py`：lane_depth 进 audit  
- `services/runtime/tests/test_tools_extended.py`：RET-12 / read_file 覆盖字段  

#### CTX-9 读覆盖探针修复（2026-08-04）

> **根因**：`tool.completed` 事件从不携带 `result.content`（仅 summary），提取器读 content → `read_bytes` 恒 0 → 凡 F1=0 皆进 `truly_abandoned`。  
> **修复**：runtime 在 `read_file` 的 `tool.completed` 上写入轻量字段 `chars_read` / `file_chars` / `next_offset` / …；提取器优先用这些字段。  
> **验收**：`1707135c` coverage 非零 36/60；wrong_answer 与 abandoned 分流成立。

#### 批次 6 · RET-12 执行（2026-08-04 · 单刀）

```text
加热层: 工具契约（结果呈现；不进 IR）
改动: search_sources 返回 hits —— top search_sources_detail_hits(=5) 保留 excerpt(400)；
      其余仅 path + title + score(+chunk_id)；附 hint 说明可 read 后排名
排期: 观测生效后首刀；与 CTX-9 修复同部署窗口，但逻辑独立
验收: free 检索 N≥2 + EVAL-1 配对；主看搜后 read 名次分布 / weak_hits；禁止用 nDCG 叙事
R 门禁: 纯格式化；ranked/IR 仍用 path+score 全列表
```

**状态**：**已部署**；观测跑 `3c34de88` nDCG 持平（`no_stable_delta` vs `0744546e`）符合「不写 nDCG」预期；**行为 N≥2 已由 `dfe97d37` 凑齐**（见 §12.7）；不入库。

#### 下一步（严格按 §11.5 · 终态指针 → §13.8）

1. ~~检索再跑 / RET-15-2 / RET-7 / CTX-7 / RET-9~~ → **均已收**；**RET-9 丢刀已回滚**（§13.8）。  
2. **当前**：CTX-12 离线 → CTX-8；并行 RET-17；其后 RET-18 → REP-3 → RET-4。  
3. RET-16 / CTX-11 / CTX-5 **不开**。  
4. 仍 **不** `update-baseline`。完整进度与「为何无大提升」见 **§13.8**。

---

## 12. 第四轮补充思考：观测盲区与条件契约刀（2026-08-04）

> **性质**：在 §11.7 落地之后、批次 6 剩余刀（RET-7 消融跑 / RET-9、CTX-7/8）开工之前的补充提案与执行。全部遵守文首两道门 + §9.4 五条 + §10.4 门禁 6/7（观测先于改动、消融对称性）+ §11.4 不做清单；**不推翻任何既有裁决**（RET-4 立项、CTX-5 不开、RET-5/13 挂起均维持），不改 §11.5 已排批次的相对顺序。  
> **编号承接**：EVAL-4/5 · RET-14~16 · CTX-10~11；REP-3 为既有 ID 的排期前移，非新刀。  
> **一句话定位**：前三轮把「怎么搜 / 怎么读」的行为面与排序栈逐层观测基本建齐；本轮补的是四处**仍看不见的地方**——它们都有成熟 agent 体系的标准做法,且全部能以零运行时改动的观测刀先行。  
> **执行进度**：见 **§12.6**（观测/基建 + RET-7 开关已落地；条件契约刀按观测裁决开/关）。

### 12.0 先算账：当前栈还有哪些「看不见的地方」

| # | 盲区 | 现状证据 | 不补的后果 | 成熟做法（对标） | 对应刀 |
|---|------|----------|------------|------------------|--------|
| 1 | 检索温度计只量 ranked，**不量「模型最终读没读到 gold」** | read-after-search 58/60 只记「搜后读了」，不记「读对了」 | RET-12/16 这类呈现刀的真实收益不可判；weak_hits 里「榜上有 gold 但模型读错文档」（呈现/行为失败）与「榜上无 gold」（真 Index 失败）混桶 | RAG 评测三元组把 context relevance 与 groundedness 分开量（RAGAS / TruLens 系）；本栈只有前者 | **RET-14** |
| 2 | `low_score` hint 阈值 **0.15** 从未被审计是否与 RRF 分数量级匹配 | RRF 每车道贡献 ≈1/(60+rank)≈0.016，融合+doc_boost 后仍 ~0.03–0.05 量级；0.15 疑似按别的分数体系设定 → **可能恒触发或永不触发** | 排序栈里存在一层无存在证据的行为开关（违 §11.6 条 1 精神）；模型可见 score 是不可解释小浮点，无法用于「读 vs 再搜」决策 | 成熟 agent 给模型看**归一化/相对**分而非原始融合分 | **RET-15** |
| 3 | `wrong_answer_after_read` **9 例**（上下文第一大失血桶）未解剖，CTX-8 已按假设立项 | `1707135c`：wrong_answer 9 / abandoned 仅 2 | 若主因是判分器口径（alias/格式）或定位失败而非「凭印象臆答」，CTX-8 文案剂量打空——重演 CTX-5 险些犯的错（CTX-4 解剖救回） | error-analysis-first：先逐例看数据再开刀（评测工程共识） | **CTX-10** |
| 4 | EVAL-1 只有统计量（CI/win-loss），**无自动轨迹级归因材料**；噪声带 ±1.5–4pp 仍是口口相传 | 逐例归因仍靠人工翻 `process.jsonl`；同配置方差从未系统累计 | 批次 6 每刀 N≥2 的定性裁决成本高、容易被省略成「只看 CI」 | 配对评测标配 top 回归/提升 case 并排错误分析；方差档案化 | **EVAL-4 / EVAL-5** |
| 5 | REP-3 全量锚**反复被推迟**，批次 7 结构刀却已在排期 | §10.1 立项至今未跑；入库门禁（§9.4 条 4）要求全量锚却无排期约束 | RET-4/11 落地后其 Δ 又只能在 20q 冒烟上讲——重活没有像样的前锚 | 大改动前冻结基线（工程常识） | **REP-3 排期前移**（§12.3） |

### 12.1 观测/基建刀（零运行时行为改动 · 可并入「6 前置」尾部，与两轮待跑复测并行）

#### RET-14 · gold-read 探针（检索温度计的 outcome 层）

```text
加热层: 可归因性（L2 探针 + 离线计算，Turn 内零改动）
改动点: 检索 L2 探针增加——本 Turn read 系工具目标与该 query qrels gold 的交集统计：
        gold_read_rate（读到 ≥1 gold 文档的 query 占比）、read_target_ranks（read 目标在合并榜的名次分布）、
        gold_on_ranked_but_unread 计数；按数据集聚合进 result
预期用户路径变化: 无
R1–R5 / while / 强制搜: 通过——离线对 process.jsonl + qrels 计算，运行时零改动
分桶预期: 不改分桶；把 weak_hits 一切为二——「榜上无 gold」（真 Index/embed 失败 → RET-4/11 战场）
        vs「榜上有 gold 但模型没读它」（呈现/行为失败 → RET-12/16 战场）
free 验收: 不需要（观测刀）；产物质量以「RET-12 行为 N≥2 的裁决能否直接落到 gold_read_rate 配对 Δ」衡量
非目标: gold/qrels 信息仅在评测侧离线使用，严禁以任何形式进入 runtime 提示或题面（那是注入答案，
        违反因果表「错」列）
```

依据：ranked nDCG 是中间量；写作 RAG 的产品之果是「模型拿对证据并用上」。现有轨迹已记 read-after-search 与 read 目标名次（`3c34de88` 已有 58/60 读数），只差与 qrels 的离线交集一步——**成本一个脚本，回报是 weak_hits 的第二次二分**（第一次是 RET-8 的词面分类）。这也让 §11.6 条 2「每一个残余失败可归因」在检索侧真正闭环。

#### RET-15 · score 语义审计 + 归一化呈现（两段式：先审计，条件开第二段）

```text
加热层: 可归因性（第一段）→ 工具契约/结果呈现（第二段；不进 IR）
改动点: 第一段（纯审计）：离线统计融合后 score 分布（分车道/分数据集）与 low_score hint(0.15)
        的实际触发率（每跑触发几次、触发时命中质量如何）；
        第二段（仅当审计证实阈值与量级失配或分数不可解释才开）：tool_result 中 score 渲染为
        归一化相对分（如 top1=100 的百分比），low_score hint 阈值改为分位定义；
        ranked 事件仍写原始分，IR 计分完全不动
预期用户路径变化: 模型第一次能用 score 做「读 vs 再搜」的可解释决策；low_score hint 恢复设计意图
R1–R5 / while / 强制搜: 通过——审计离线；归一化为 O(limit) 除法，毫秒级（R3 内）
分桶预期: 若 hint 此前恒触发（0.15 >> RRF 量级时人人皆「弱」）→ 修复后「强命中仍再搜」类噪声行为 ↓；
        若永不触发 → 弱命中改读的设计从未生效，修复后 weak_hits 内行为余量可见
free 验收: 第二段单刀 N≥2 + EVAL-1 配对；主看行为轨迹（hint 触发后的工具选择）与 weak_hits；
        不写 nDCG 叙事（P9 同款纪律）
非目标: 审计结果为「正常匹配」则第二段不开（观测先于改动）；不顺手改融合公式
        （公式层的去留走 RET-7 一族消融，单刀纪律）
```

依据：这是 §11.6 条 1「每层有存在证据」的字面应用——promote 层有 RET-7 排期，lexical 层有历史消融，**low_score hint 层是排序—行为链上唯一从未被审计过的开关**。且嫌疑具体（量级失配），一次离线统计即可定案。

#### CTX-10 · wrong_answer_after_read 解剖（CTX-8 开刀前置 · 与 CTX-4 同款纪律）

```text
加热层: 可归因性（离线读 process.jsonl + 判分复核，不动运行时）
改动点: 对 `1707135c` 的 9 例 wrong_answer_after_read 逐条分类：
        (i) 证据已读但理解/推理错 —— 真能力墙或 CTX-8「凭印象臆答」战场
        (ii) 读的区域不含答案 —— 定位失败，归 CTX-3 读法族 / CTX-11 候选证据
        (iii) 语义等价但判分口径不容（alias/单复数/格式）—— 记为尺子局限，不开刀
        (iv) 多跳装配失败（第一跳证据被 4k 回落截掉）—— CTX-6/8 战场
        同时复核 F1/EM 归一化规则（大小写/冠词/标点）与 LongBench 官方口径一致性
预期用户路径变化: 无
R1–R5: 通过
free 验收: 不需要；产出 = 分类占比表，直接决定 CTX-8 的诚实预期上下限、CTX-11 开不开、
        以及 (iii) 类是否写进 §11.6 终态归因记录（「知道为什么剩、并决定不修」）
非目标: 不为抬分改判分归一化——判分口径属温度计本体；若确认 bug 单独走尺子修复票并注记
        新旧读数不可比（与 CTX-9 判据刀同款纪律）
```

依据：CTX-4 的解剖曾直接否掉 CTX-5，省下一条无效文案；wrong_answer 现在是新口径下的第一大桶（9/53），而 CTX-8 的立项叙事（「防凭印象臆答」「多跳证据保持」）只对 (i)(iv) 两类有效——**若 (ii)(iii) 占大头，CTX-8 的预期须先下修再开刀**。这是门禁 6 的字面要求。

#### EVAL-4 · 配对回归/提升 case 轨迹并排摘要（归因加速器）

```text
加热层: 可归因性（compare 报告侧，Turn 内零改动）
改动点: EVAL-1 配对报告追加——按配对 Δ 绝对值取 top-K（建议 K=5）回归与提升 case，
        自动抽取两跑轨迹关键步（queries、工具序列、read 目标与名次、终答摘要、桶）并排渲染进 report
预期用户路径变化: 无
R1–R5: 通过——纯报告生成
free 验收: 不需要；产物质量以「批次 6 每刀的定性归因不再需要手工翻 process.jsonl」衡量
非目标: 不用轨迹摘要替代统计裁决（CI 仍是生死线；摘要只供归因与防误判）
```

#### EVAL-5 · 噪声带实测档案（把 ±1.5–4pp 从口传变成数据）

```text
加热层: 可归因性
改动点: 利用既有与未来的同配置重复跑（REP 系、每刀 N≥2 的两跑），持续累计「同配置逐题配对方差」
        分套件档案；写入 compare 报告脚注（当前实测噪声带 ± 多少、基于几对跑）
预期用户路径变化: 无
R1–R5: 通过——离线统计，复用 EVAL-1 已有的每 case 分数
free 验收: 不需要；生效标志 = §11.6 条 4 停机线（「配对 CI 均含 0」）的判读有实测方差背书
非目标: 不为凑档案加跑额外冒烟（只回收本来就要跑的重复跑数据）
```

### 12.2 条件契约刀（对应观测证成后才开 · 嵌入批次 6 尾部 · 单刀 N≥2 配对）

#### RET-16 · 详摘槽 doc 多样性（RET-12 的补丁 · 条件开刀）

```text
加热层: 工具契约（结果呈现；不进 IR）
前置观测: 统计 RET-12 现网 top-5 详摘槽的 distinct-doc 数分布（RET-14 数据可顺带产出）；
        仅当「详摘槽被 ≤2 个 doc 占据」的查询占比可观（建议 ≥1/3）才开刀
改动点: 详摘槽选择改为「按合并榜序取前 5 个互不相同 doc 的首个块」；被跳过的同 doc 块仍留在单行层；
        ranked 事件与 IR 完全不动
预期用户路径变化: two-level doc 加成造成的同 doc 块刷屏不再吃掉全部详摘预算，
        模型可见证据宽度覆盖更多候选文档（搜索引擎结果页多样性的同款取舍）
R1–R5 / while / 强制搜: 通过——选择逻辑 O(limit)，毫秒级；无新计算、无重排
分桶预期: weak_hits 中「榜上有 gold 但未读」类 ↓（以 RET-14 的 gold_read_rate 为主验收位）
free 验收: N≥2 + EVAL-1 配对；主看 gold_read_rate 与搜后 read 名次分布；不写 nDCG 叙事
非目标: 不做 MMR/语义去重等超预算计算；不动单行层内容与 ranked 序
```

#### CTX-11 · read_file 呈现加行号/位置标记（条件开刀 · CTX-8 的配套地基）

```text
加热层: 工具契约（读结果呈现）
前置观测: CTX-10 显示 (ii) 定位失败或 (iv) 多跳装配占比可观，且确认当前 read_file 输出无行号/偏移标记
改动点: read_file 返回内容按行（或固定字节段）加轻量位置前缀；截断 hint 与 next_offset 用同一坐标系；
        grep 命中行号与 read 坐标对齐（grep→定向 read 换乘不再靠目测估 offset）
预期用户路径变化: 所有读大文件场景（不止评测）定位更准；CTX-8 摘录纪律的「注明大致位置」有了
        天然锚点——Cursor / Claude Code 读文件带行号是同款成熟做法
R1–R5 / while / 强制读: 通过——静态格式化；行号前缀带来约 3–5% 可见面 token 膨胀，
        记入 EVAL-3 台账单独列行（这是工具可见面成本，非 system 文案成本）
分桶预期: wrong_answer 中 (ii) 类、及新口径 gave_up 中「续读位置乱跳」类 ↓；
        主观测位 narrativeqa / hotpotqa 分 task
free 验收: N≥2 分 task + EVAL-1 配对；同时看 read 轨迹的 offset 跳转合理性
非目标: 不改 read_file 预算与语义；不强制 grep 先行（读法仍模型自选）
```

排期注记：CTX-11 若开，须排在 **CTX-8 之前或与其隔批**——若 CTX-8 先落地、CTX-11 后落地，CTX-8 的 N≥2 对照会被坐标系变化污染（与 §11.3「CTX-6 验收基线改为含 CTX-8 的栈」同款依赖管理）。

### 12.3 流程建议：REP-3 全量锚先行（批次 7 的硬前置）

建议把 REP-3（同协议全量锚，约 1.3k Turn 量级）**明确排为批次 7 的硬前置**，即在 RET-4/11 影子索引与 CTX-6 之前，用当前栈（§9 包 + RET-12 + EVAL 基建）各跑一次检索/上下文全量锚：

1. **时机成熟**：检索 §9 包已 N=2 认包（均值 0.449 vs 锚 0.409），当前栈是第一个值得钉全量锚的稳定平台；再等下去锚会一直追着刀跑。
2. **批次 7 需要它**：结构刀（embed / 语料增强 / 读预算）是本轮最贵的改动，若无全量前锚，其 Δ 又只能在 20q 冒烟上讲——「重活没有像样对照」的风险已在 §9 打包上付过一次学费。
3. **构成前后对照**：结构刀落地后再跑一次全量锚，两次全量即批次 7 的入库级对照；这是 §9.4 门禁 4 与 §11.6 条 3（「同协议全量锚已入库至少一次」）的唯一合法兑现路径。
4. **纪律不变**：全量锚入库 ≠ 给冒烟均值背书；入库叙事仍按门禁写成「检索/上下文工程变好的间接证明」；上下文侧若 REP 复测均值仍 <0.40，则上下文全量锚推迟、只钉检索侧。

### 12.4 本节不做清单（承接 §11.4 并追加）

- **不开 BEIR 切块尺寸刀**：BEIR 三集文档普遍远短于 4000 字符，一 doc ≈ 一 chunk，切块杠杆在本温度计上基本不存在；产品树状语料的切块优化另立票，勿借本温度计立项（§1.4-E 同款「别误判杠杆」）。
- **不做查询侧静态同义词/词典扩展**：lexical_miss 的正解在语料侧（RET-11 词面桥），查询侧扩展徒增 drift 风险且与 verbatim 首搜纪律相抵。
- **不加答案自评/二次 LLM 验证调用**：违 R2/R3 精神；CTX-8 的摘录纪律已是零成本版自验（先取证后作答），无需再叠一轮模型调用。
- **不因 RET-15 审计发现失配就顺手改融合公式或阈值以外的东西**：单刀纪律；公式层去留走 RET-7 一族消融。
- **不把 gold/qrels 信息以任何形式带进 runtime、题面或工具提示**（RET-14 仅评测侧离线用）；不为让 (iii) 类 case 得分而改判分归一化。
- **不在 RET-12 行为 N≥2 与 REP 上下文复测完成前开本节任何条件契约刀**（§11.7 下一步 1/2 优先级不变）。

### 12.5 排期嵌入与诚实预期（不打乱 §11.5）

| 批次 | §11.5 既定 | 本节追加 | 性质 |
|------|------------|----------|------|
| **6 前置（续）** | （已完成部分不变） | EVAL-4/5；RET-14；RET-15 第一段（审计）；CTX-10 | 观测/基建 · 零运行时 · 可与待跑的两轮 N≥2 复测并行 |
| **6（静态契约单刀）** | RET-7 → RET-9 → CTX-7 → CTX-8 | RET-15 第二段（条件）与 RET-16（条件）排 RET-7/9 之后；CTX-11（条件）排 CTX-8 **之前或隔批**（见 §12.2 注记） | 每刀单 commit · N≥2 · EVAL-1 配对 |
| **7 前（硬前置）** | — | **REP-3 全量锚**（当前栈 · 检索必跑；上下文视 REP 复测均值） | 入库唯一合法时点 |
| **7（结构刀）** | RET-4 / RET-11 / CTX-6 | 不变；验收对照改用全量前锚 + 冒烟配对双轨 | 离线重活 / runtime 评审 |

**诚实预期（防事后叙事漂移）**：

- 本节观测刀**不承诺任何分数**；其产出以「能否改变某个既定裁决或预期」衡量（RET-14 可能改写 weak_hits 归因占比、CTX-10 可能下修 CTX-8 预期、RET-15 审计可能发现一层死开关）。
- 条件契约刀（RET-15 二段 / RET-16 / CTX-11）的宏分 Δ 大概率落在噪声带内，**只在行为轨迹与子桶上可见**——验收全部走 EVAL-1 配对 + 子桶（gold_read_rate / wrong_answer 分类），禁止用宏 nDCG/F1 叙事。
- 主分弹性仍押在既定结构刀：检索 RET-4/11（终态带 0.46–0.50），上下文 CTX-8/6（终态带 0.45–0.50）。
- 若 CTX-10 显示 (iii) 判分口径类占比高 → 上下文终态带相应下修，该部分写入归因记录为「尺子局限、决定不修」——这不是失败，是 §11.6 条 2 的完成态。

**与终态四问的关系（§11.6）**：本节全部提案只服务于条 1（每层有存在证据：RET-15 补 low_score hint 层的缺证）与条 2（每败可归因：RET-14 / CTX-10 补两个最大失血桶的最后一次二分），另以 §12.3 直接兑现条 3（全量锚入库）。**不新增终态目标、不抬高任何诚实带**——若四问在批次 7 后全部可答，本 brief 按 §11.6 停机线收束。

---

## 12.6 批次 6 前置（续）执行进度（2026-08-04 · 观测落地 + RET-7 开关）

> **纪律**：§12.1 观测/基建已落地并跑通既有 free 产物；**RET-7 配置开关已合入（默认 on）**，消融 free 跑尚未开。条件刀按下方裁决开/关。**禁止**本节点 `update-baseline`。  
> **产物**：`scripts/official_bench/batch6_offline_analysis.py` → `eval/reports/official/batch6/`（gitignore）；EVAL-5 档案 → `eval/reports/official/noise_band/archive.json`。

| ID | 内容 | 状态 | 裁决 / 备注 |
|----|------|------|-------------|
| EVAL-4 | 配对 top-K 回归/提升 + 轨迹并排摘要 | **已完成** | `paired_case_delta_report` → `improvements`/`regressions` + `trajectory_highlights`；`compare_two_manifests` 自动 enrich |
| EVAL-5 | 同配置噪声带档案 | **已完成** | `record_noise_band_pair`；`0744546e`↔`3c34de88` 已写入；首对 suggested_noise_pp≈**0.44**（样本少，后续 N≥2 对会抬升） |
| RET-14 | gold-read 探针（L2 + 离线） | **已完成** | runner 写 `gold_read`；离线对 `3c34de88`：rate **0.783**；slice gold_read42 / absent15 / unread3 |
| RET-15-1 | low_score@0.15 审计 | **已完成** | **`never_triggers`**（top1 min≈0.78 ≫ 0.15）→ **开 stage-2**（归一化呈现） |
| CTX-10 | wrong_answer 9 例解剖 | **已完成** | (i)+(iv)=**5/9** → CTX-8 预期 **full**；(ii)=1 → **不开 CTX-11**；(iii)=3 → 尺子局限记入归因 |
| RET-7 开关 | `search_sources_excerpt_promote`（**默认 False**） | **N≥2 已收 → 默认关** | OFF `bcdbbb85`/`f92bc610` vs ON `6c87e401` 皆 `no_stable_delta`；无正贡献 → 简化栈（§12.9） |
| RET-16 | 详摘槽多样性 | **不开** | detail 槽 ≤2 doc 占比 **0.018** ≪ 1/3 |
| CTX-11 | read 行号 | **不开** | (ii) 仅 1/9 |
| RET-15-2 | 归一化 score 呈现 | **已收（no_stable_delta）** | free `6c87e401` vs `dfe97d37`；**不写 IR 胜**；默认保留呈现（§12.8） |
| CTX-7 | 答题 good/bad 示例 | **N≥2 已收** | verbose↓ 成立；EM↑ **未过**；保留文案不记宏分胜（§12.9） |
| RET-9 | 第二搜互补文案 | **N≥2 丢刀已回滚** | `03304987`/`03569f22`；weak 未收窄；见 §13.8 |
| REP-3 | 全量锚 | **未跑** | 仍为批次 7 硬前置 |

#### RET-14 离线读数（`3c34de88` · top_hits∩qrels∩DB read_paths）

| 数据集 | n | gold_read_rate | absent_from_ranked | on_ranked_but_unread |
|--------|---|----------------|--------------------|----------------------|
| SciFact | 20 | 0.95 | 3 | 1 |
| NFCorpus | 20 | 0.90 | 2 | 1 |
| FiQA | 20 | **0.50** | **10** | 1 |
| **合计** | 60 | **0.783** | **15** | **3** |

**读法**：weak_hits 的主因是 **gold 根本不在 ranked**（Index/embed，归 RET-4/11），不是「榜上有 gold 模型没看见」（呈现/RET-12 战场仅 3 例）。FiQA 一半 query 读不到任何 gold → 与 `lanes_fed_relevance` / RET-4 立项一致。

#### RET-15 审计读数（同跑）

- top1 score：min **0.78** · p50 **1.64** · max **3.11**（n=56 有 hit）  
- `low_score` hint@**0.15** 触发率 **0%** → 设计意图从未生效 → stage-2（相对分 / 分位阈值）立项充分。  
- 注：brief §12.0 曾按「裸 RRF ~0.03」猜量级；生产融合分已是另一量级，审计以实测为准。

#### CTX-10 分类（`1707135c` · 9 例）

| 类 | n | 含义 | 后续 |
|----|---|------|------|
| (iv) multihop_assembly | 4 | 多跳证据丢失 | CTX-8 / CTX-6 |
| (iii) scorer_alias | 3 | 近义/口径（含 em=1∧f1=0  quirk） | **不修判分刷分**；终态归因「尺子局限」 |
| (i) read_but_reason_wrong | 1 | 读了理解错 | CTX-8 |
| (ii) localization_miss | 1 | 定位失败 | CTX-11 门槛未过 |

#### RET-7 开关用法（消融时）

```bash
# 默认已关（settings + compose default false）。若需临时重开对照：
SEARCH_SOURCES_EXCERPT_PROMOTE=true
# recreate runtime 后 free；配对时注明 promote 状态
```

**裁决后默认 false**；开关保留供回滚对照。不改 while / 不强制搜。

#### 单测

- `scripts/tests/test_official_bench_baseline.py`：EVAL-4 highlights / EVAL-5 archive / RET-14 stats / RET-15 / CTX-10  
- `services/runtime/tests/test_tools_extended.py`：RET-7 settings default + disable

#### 下一步（承接 §11.7，按观测裁决修订 · 2026-08-04 终稿）

1. ~~检索再跑一轮 / RET-15-2 / RET-7 消融 / CTX-7 / RET-9~~ → **均已收**（§12.7–12.9 · §13.8）；**RET-9 丢刀已回滚**。  
2. **当前**：跑 **CTX-12** 离线（`batch6b_offline_analysis.py`）→ 定 CTX-8 文案终稿与 EM 盯防位 → **CTX-8** free N≥2。  
3. 并行/随后：**RET-17** 离线 sizing；**RET-18** two-level 消融（锚 = RET-9 回滚后栈 = 当前 promote-off · two-level on）。  
4. 批次 7 前 **REP-3** 全量锚 → **RET-4**（+ 可选 RET-11）。  
5. 仍 **不** `update-baseline`。

---

## 12.7 Free 观测批（2026-08-04 · Ops retrieval+context · pass 1/2）

> **窗口**：2026-08-04 14:51:38 → 15:14:25（UTC+8）· ~23m · **pass 1/2**  
> **栈**：§9 包 + RET-12 + §12.6 观测基建（重建后 runtime/api）· arm=**free** · protocol m3 · `deepseek-v4-flash`  
> **纪律**：检索有效记入；上下文整跑失败 = **infra**，**不作效果对照、不否决检索**；**不** `update-baseline`。

### 检索 free 20q · `dfe97d37`（**有效**）

| 项 | 值 |
|----|-----|
| run_id | `dfe97d37-05ac-4ea9-8d98-8f5ff0fca312` |
| nDCG@10 | **0.4224** |
| R@10 | 0.4258 |
| R@100 | 0.5341 |
| nDCG@1 | 0.3722 |
| MAP@10 | 0.2911 |
| infra_rate | **0**（n_infra_excluded=0） |
| 桶 | ok **30** · weak_hits **28** · search_cap **2** |
| promote_total | 58 |
| FiQA depth / lane | `depth_ok_relevance_or_qrels` · **`lanes_fed_relevance`** |
| RET-14 gold_read_rate | **0.85**（n=60：gold_read 47 · absent 10 · unread 3） |
| 分库 gold_read | SciFact/NF **1.0** · FiQA **0.55**（absent 7 · unread 3） |

**配对（EVAL-1/4）vs RET-12 前锚 `3c34de88`**

| | 值 |
|--|-----|
| n_paired | 55 |
| W/L/T | 3 / 4 / 48 |
| meanΔ | −0.011 |
| bootstrap 95% CI | 含 0 |
| verdict | **`no_stable_delta`** |
| EVAL-5 noise_band | 档案 n=2 · suggested ≈±1.1pp |

**裁决（RET-12）**：IR 持平符合「分层呈现不写 nDCG」预期；行为 N≥2 **已凑齐**；主缺口仍在 weak_hits / FiQA absent-from-ranked → 结构杠杆仍归 **RET-4**。不入库。

原始键（`debug.log` / TEST 导出）：

```text
official.retrieval.ndcg_at_10 = 0.4224
official.retrieval.recall_at_10 = 0.4258
official.retrieval.recall_at_100 = 0.5341
official.retrieval.ndcg_at_1 = 0.3722
official.retrieval.map_at_10 = 0.2911
official.retrieval.n_queries = 20
official.retrieval.infra_rate = 0
```

### 上下文 free · `c76e07a9`（**作废 · infra**）

| 项 | 值 |
|----|-----|
| run_id | `c76e07a9-8cae-46c1-bc39-09d47502f326` |
| status | **failed** |
| 落盘 cases | 仅 **30/60**（multifieldqa_en 20 + hotpotqa 前 10）；无宏 F1/EM |
| 根因 | `httpx.ReadError` ← `httpcore.ReadError`（api 并行 `asyncio.gather` 等 Turn 时 **读 runtime HTTP 连接断开**） |
| 归类 | **infra / transport**（EVAL-infra 口径）；**非** agent 读法/答题失败 |
| 对照 | **禁止**与 `1707135c` 配对；须通道稳时重跑 context-only |

过程现象：`run_finished — failed` 之后 process 仍见后续 case 日志（并行 worker 未立刻停），但会话已失败、主分未写出——典型 gather 一票否决。

**旁注（同窗口、非本次挂因）**：检索阶段 runtime 多次 `turn.completed: summary is too long`（schema `maxLength=4096`），长终答写事件失败；检索仍出完整宏分。可另立截断刀，**不**解释本次 context 整挂。

### RET-15-2 落地（2026-08-04 · 单刀）

```text
加热层: 工具契约（结果呈现；不进 IR 公式）
改动:
  · search_sources 命中：保留 score_raw=融合原分；模型可见 score=相对 top1 的 0–100
  · retrieval.completed.ranked 优先写 score_raw（agent_engine）
  · low_score hint 阈值默认 0.15 → 1.0（对 raw；≈冒烟 top1 p10）
  · 开关 search_sources_score_rel（默认 true）
验收: free 检索 N≥2 + EVAL-1 配对 vs dfe97d37；主看 low_score 触发后的工具选择 / weak_hits；禁止 nDCG 叙事
R 门禁: O(limit) 除法；不改 while / 不强制搜
```

**状态**：代码已重建；free 见 **§12.8** → **`no_stable_delta`**；默认保留呈现；不入库。

### CTX-7 落地（2026-08-04 · 单刀）

```text
加热层: 工具契约 / 静态 system 文案
改动: agent/system.md 在 Answer format 后附最小 good/bad 示例（Paris / yes — 无题集内容）
验收: free 上下文 60 · N≥2 配对 vs b3bb17d9；主看 verbose 桶与 EM；禁止答案后处理
R 门禁: 纯静态文案
```

**状态**：已进镜像并 free N≥2 → 见 **§12.9**（verbose↓ 成立；EM↑ 未过；保留文案）。

---

## 12.8 RET-15-2 free + RET-7 消融武装（2026-08-04）

> **纪律**：只记 free；配对同栈；**禁止**用 nDCG 给呈现刀（RET-15-2）叙事胜利；RET-7 是**减法存在证据**刀。不入库。

### RET-15-2 free · `6c87e401`（**有效 · 收刀**）

| 项 | 值 |
|----|-----|
| run_id | `6c87e401-eab4-4f68-98e5-95a9fe6c98d5` |
| nDCG@10 | **0.4419** |
| R@10 / R@100 | 0.4303 / 0.5307 |
| infra_rate | **0** |
| 桶 | ok **29** · weak_hits **27** · search_cap **3** · query_drift **1** |
| promote_total | **60**（promote 仍开） |
| gold_read_rate | **0.80**（unread 7；较 `dfe97d37` 的 0.85 略降） |
| FiQA | nDCG@10 **0.324**；R@10 **0.392** vs R@100 **0.558**（gap≈0.17，深度通道可见） |

**配对 vs `dfe97d37`（RET-15-1 锚）**：n=56 · W4/L3/T49 · meanΔ **+0.017** · CI 含 0 → **`no_stable_delta`**。

**裁决**：符合「呈现层不写 nDCG」预期；默认 **保留** RET-15-2；主缺口仍在 weak_hits / FiQA absent → RET-4。不入库。

### RET-7 消融 · 武装记录（已被 §12.9 收束）

武装窗口：`.env=false` + compose 透传 + recreate；配对锚当时为 promote-on `6c87e401`。结果与默认变更见 **§12.9**。

---

## 12.9 RET-7 / CTX-7 free N≥2 + RET-9 落地（2026-08-04）

> **纪律**：只记 free；两轨分开归因；**不** `update-baseline`。

### RET-7 消融 · N=2（**收刀 · 默认关**）

| | pass1 `bcdbbb85` | pass2 `f92bc610` | 锚 ON `6c87e401` |
|--|------------------|------------------|------------------|
| nDCG@10 | 0.4359 | **0.4573** | 0.4419 |
| R@10 / R@100 | 0.421 / 0.538 | 0.446 / 0.532 | 0.430 / 0.531 |
| promote_total | **0** | **0** | 60 |
| weak_hits | 28 | 26 | 27 |
| infra | 0 | 0 | 0 |
| vs ON | `no_stable_delta` | `no_stable_delta` | — |

两轮 OFF 均值 nDCG@10 **0.4466**（略高于 ON）。关 promote **无稳定伤 IR** → **无存在证据** → **默认关闭**（`settings.search_sources_excerpt_promote=False`；compose default false）。开关保留供回滚。不入库。

### CTX-7 · N=2（**收刀 · 不记 EM/宏分胜**）

| | 锚 `b3bb17d9` | pass1 `13647cb0` | pass2 `61624e34` |
|--|--------------|------------------|------------------|
| F1 | 0.362 | 0.411 | **0.424** |
| EM | **0.267** | 0.217 | **0.183** |
| verbose | 11 | **4** | **4** |
| ok / wrong / abandoned | 33 / 13 / 3 | 40 / 13 / 3 | **44 / 8 / 4** |
| vs 锚 F1 | — | `no_stable_delta` | `no_stable_delta` |

**裁决**：verbose↓ **稳定成立**；EM↑ **连续未过**（反降）。保留 good/bad 示例作文案边际；**禁止**以 F1/EM 叙事胜利。不入库。主缺口仍偏 wrong_answer → **CTX-8**。

### RET-9 落地 → N≥2 丢刀（2026-08-04 · 详见 §13.8）

```text
加热层: 工具契约 / 静态 writing system.md
改动: 弱命中（low_score hint）时第二搜换互补词面，保持原信息需求；仍 ≤2 搜；禁乱漂
验收: free 检索 20q N≥2；配对锚 promote-off；主看 weak_hits ↓、盯 drift
R 门禁: 纯静态文案；不强制第二搜；无额外 LLM 改写（R2）
```

**状态**：**N≥2 已收 → 丢刀 → 文案已回滚**（pass1 `03304987` / pass2 `03569f22`；weak 27→28 未收窄；FiQA 两轮单搜未触发互补搜）。完整对照表与停机计数见 **§13.8**。

**下一步**：§13.8「下一步」——CTX-12 → CTX-8；不开 RET-16 / CTX-11 / CTX-5。

---

## 13. 第五轮补充思考：收束准备、停机线与评测吞吐（2026-08-04）

> **性质**：在 §12.9 收刀（RET-7 默认关 · CTX-7 保留不记胜）之后、RET-9 free N≥2 与 CTX-8 开工之前的补充提案。全部遵守文首两道门 + §9.4 五条 + §10.4 门禁 6/7（观测先于改动、消融对称性）+ §11.4/§12.4 不做清单；**不推翻任何既有裁决**（RET-4 立项、RET-16/CTX-5/CTX-11 不开、RET-5/13 挂起均维持），不打乱 §11.5/§12.5 既定相对顺序。  
> **编号承接**：EVAL-6 · RET-17/18 · CTX-12 · INFRA-1/2 · D-1（决策记录）；REP-3 为既有 ID 的执行规格化，非新刀。  
> **一句话定位**：批次 6 加法契约刀宏分四连 `no_stable_delta`（RET-12 / RET-15-2 / RET-7 消融 / CTX-7）说明契约层边际已薄——本轮的任务不是再找新刀，而是**把停机线判读口径写死、把最后的归因盲区（EM 残余 · gold 名次分布 · two-level 存在证据）补完、把评测吞吐修好，然后按 §12.3 冻结栈钉全量锚，转入批次 7 结构刀并收束 §11.6 终态四问**。

### 13.0 先算账：§12.7–12.9 收刀之后还剩什么

| # | 已观测事实（均在本文有记录） | 含义 | 对应动作 |
|---|------------------------------|------|----------|
| 1 | 批次 6 已收 4 刀，宏分配对全部 `no_stable_delta`；唯一稳定改变在子桶与栈简化（verbose 11→4、promote 层移除、low_score hint 修复） | 契约层边际已薄，§11.6 条 4 停机线临近；但「主观测位达成 vs 宏分 CI 含 0」的判读口径未写死，停机线无法机械执行 | **EVAL-6**（规则刀）；RET-9 / CTX-8 定位为**最后两把加法契约刀** |
| 2 | 上下文 EM 跨栈下滑：`b3bb17d9` 0.267 → `13647cb0` 0.217 → `61624e34` 0.183；但 EM 粒度 1/60≈1.7pp，同配置两轮差 3.4pp（≈2 例） | 「答短纪律过冲（丢限定词）」「scorer alias（CTX-10 (iii) 族）」「噪声」三种解释未拆开；CTX-8 开刀前若不解剖，其 EM 验收位没有可信基线 | **CTX-12**（CTX-8 前置解剖） |
| 3 | FiQA R@10 0.392 vs R@100 0.558（`6c87e401`，gap≈0.17，深度通道已可见）；absent-from-ranked 7–10/20；gold_read_rate 0.50–0.55 | 残余缺口须二分为「absent（召回缺口 → RET-4/11 可修上限）」与「gold 在 11–100（排序余量）」，两者占比未量化 → RET-4 诚实预期无法校准 | **RET-17**（RET-14 的最后一次二分 · 离线） |
| 4 | 排序栈内 **two-level doc 加成**（开 · 超时 0.3s · doc_limit 8）从未有单独 free 证据；§11.6 条 1 点名的层里它是最后一块无证据的 | 「代码写了就留着」违反终态条 1；promote 的 RET-7 已示范同款消融 | **RET-18**（消融开关 · 减法证据） |
| 5 | 上下文/检索评测通道事故已废/半废 4 跑（`0d299f6b`/`01e17a80`/`c76e07a9`/`2753d1b7`），另 1 跑探针缺陷（`327953e2`）；根因含 api 并行 gather 一票否决、`turn.completed` summary 超 4096 写事件失败（§12.7 旁注） | 评测吞吐是当前最大执行瓶颈：每次通道事故 ≈20m 全废 + 归因污染风险；这不是运行时质量问题，是评测编排健壮性问题 | **INFRA-1/2**（评测/事件卫生侧加固） |
| 6 | promote 默认关后，全部历史锚（`99d729de`…`6c87e401`）均为 promote-on 栈 | 后续配对若不注明 promote 状态会静默混栈 | **§13.1 记账**：平台锚改记 OFF 两轮均值 **0.4466** |
| 7 | EVAL-5 档案仅 n=2（±1.1pp）；RET-7 OFF 两轮、CTX-7 两轮均为同配置对 | 白拿的方差样本未回收 | **§13.1 记账**：回收 +2 对 |
| 8 | P8（检索温度计 = writing 场景）自 §4 起持续悬置；§11.6 条 3 要求「明确决策记录」 | 不决策则终态条 3 永远不可答 | **D-1**（书面决策，§13.4） |

### 13.1 记账更新（零改动 · 随本节生效）

| 项 | 旧 | 新 | 依据 |
|----|----|----|------|
| 检索冒烟平台锚 | `689cfe71`≈0.409（改刀前）/ §9 包 N=2 均值 0.449（promote-on） | **promote-off 两轮均值 0.4466**（`bcdbbb85` 0.4359 / `f92bc610` 0.4573）；此后一切配对锚**必须注明 promote / two-level 开关状态** | §12.9 收刀后默认栈已变；混栈配对 = 静默协议漂移 |
| 上下文冒烟平台 | REP 均值 0.391（旧口径 · 未剔 infra） | **excl-infra 口径 ≈0.41–0.42**（`13647cb0` 0.411 / `61624e34` 0.424，含 CTX-7 栈）；旧口径读数不直接比（注记） | CTX-9 + EVAL-infra 生效后口径变更（§11.7 已声明新旧不可比） |
| EVAL-5 噪声档案 | n=2 · suggested ≈±1.1pp | **回收 +2 对**：RET-7 OFF 对（`bcdbbb85`↔`f92bc610`，nDCG Δ≈2.1pp）与 CTX-7 对（`13647cb0`↔`61624e34`，F1 Δ1.3pp · **EM Δ3.4pp**）→ n=4；EM 噪声单列条目（EM 粒度粗，判 EM 类刀需更宽带） | EVAL-5 非目标条款：只回收本来就要跑的重复跑 |
| §12.3 上下文全量锚推迟条件 | 按 REP 复测均值 0.391 <0.40 → 曾倾向推迟 | 以**现行栈 + excl-infra 口径**重判：两轮均值 0.4175 **已过 ≥0.40 线** → 上下文全量锚随检索一起跑（§13.4） | 判定线不变，读数口径统一并注记——不是「改线凑数」 |

### 13.2 规则与观测刀（零运行时改动）

#### EVAL-6 · 停机线判读口径（规则刀 · 即刻生效）

```text
加热层: 可归因性 / 调优流程规则（纯文档 + compare 报告读法；零运行时代码）
改动点: 把 §11.6 条 4 停机线操作化为三条可机械执行的规则：
        ① 每把加法契约刀开工前必须在卡片里声明唯一「主观测位」（某子桶量 / 行为量 / 宏分，三选一）；
        ② 该刀记一次「停机计数」当且仅当 N≥2 后主观测位与宏分配对均无稳定 Δ；
        ③ 消融刀（RET-7/18 族）、观测/基建/吞吐刀（EVAL 系 / RET-14~17 / CTX-9~12 / INFRA 系）
          不计入停机线——门禁 7 本来就要求把栈过完；停机线只停「加法」
        连续两个批次的加法契约刀全部记停机计数 → 停开新契约刀，边际投入转全量锚与结构刀
预期用户路径变化: 无
R1–R5 / while / 强制搜: 通过——规则条目
free 验收: 不需要
非目标: 不追溯改写已收刀的裁决；不以「主观测位达成」给宏分入库背书（入库门禁不变）
```

**当前计数（按新口径 · 2026-08-04 更新）**：批次 6 已收刀中，CTX-7 主观测位（verbose↓）**达成** → 该批不记满额停机；RET-12 等宏分 `no_stable_delta` 但行为测位正当。  
**第二观察批**：**RET-9 已记停机计数 +1**（weak_hits 未收窄 + 宏分无稳定正 Δ）；剩余 **CTX-8**（主观测位 = wrong_answer 子桶）——若亦双无 Δ → **停机线触发**，停开新加法契约刀，边际投入转 RET-18 / REP-3 / RET-4。

#### RET-17 · gold 名次分布（RET-14 的最后一次二分 · 离线）

```text
加热层: 可归因性（离线脚本，复用既有 run 产物 + qrels，Turn 内零改动）
改动点: 对既有 free 跑（dfe97d37 / 6c87e401 / bcdbbb85 / f92bc610）统计每 query 的 gold 文档
        在 first-seen 合并榜上的名次分布：{top10 / 11–30 / 31–100 / absent}，分数据集聚合
预期用户路径变化: 无
R1–R5: 通过——评测侧离线；qrels 不进 runtime（RET-14 同款红线）
分桶预期: 不改分桶；产出 RET-4 预期校准表——absent 占比 = 召回缺口（embed/语料主战场，
        RET-4/11 可修上限）；11–100 占比 = 排序余量（只记归因，本轮不为它开新排序加法刀）
free 验收: 不需要（观测刀）；产物质量以「能否给 RET-4 的分库诚实预期带一个上限依据」衡量
非目标: 不因 11–30 占比高就立 rerank 新刀（CE 默认关纪律；排序余量优先由 RET-4 语义提升自然兑现）
```

#### CTX-12 · EM 残余解剖（CTX-8 开刀前置 · 与 CTX-4/CTX-10 同款纪律）

```text
加热层: 可归因性（离线读 process.jsonl + 判分复核，不动运行时）
改动点: 对 `61624e34`（EM 0.183）与 `13647cb0`（0.217）的 EM=0∧F1>0 case 逐条分类：
        (α) 答短过冲——答案是 gold 的子串 / 丢限定词（CTX-1/7 纪律副作用嫌疑）
        (β) alias/归一化口径——承接 CTX-10 (iii) 族，记尺子局限，不开刀
        (γ) 同义改写——语义对但未用原文词面（CTX-8 quote-then-answer 的正面战场）
        (δ) 噪声核销——同配置两轮 EM Δ3.4pp（≈2 例），先扣除再定性「三连降」
预期用户路径变化: 无
R1–R5: 通过
free 验收: 不需要；产出 = 分类占比表，直接决定：
        · CTX-8 文案是否附「最终短答尽量沿用原文词面」一句（(γ) 占大头时这是 CTX-8 的自然组成，非新刀）
        · (α) 占大头 → CTX-7 示例措辞微调（单刀）
        · 给 CTX-8 的 EM 验收位一个可信基线
非目标: 不为抬 EM 改判分归一化（CTX-10 (iii) 同款禁令）；不因 EM 下滑回滚 CTX-1/7
        （verbose→ok 转化仍是 F1 主贡献，先归因后动作）
```

### 13.3 评测吞吐刀（INFRA-1/2 · 与 RET-9 重建同窗部署 · 分 commit）

#### INFRA-1 · `turn.completed` summary 超长写事件失败修复（事件卫生刀）

```text
加热层: 运行时事件卫生（不进任何计分/呈现/质量路径）
改动点: 事件发出前对 summary 按 schema maxLength=4096 截断（尾部省略号标记），
        长终答不再导致 turn.completed 写失败（§12.7 旁注现象）
预期用户路径变化: 无（事件负载截断；对话内容与终答本体不受影响）
R1–R5 / while: 通过——字符串切片，毫秒内
free 验收: 不需要专跑；下一次 free 观察 `summary is too long` 日志清零即为验收
非目标: 不改 summary 生成逻辑与语义；不借机动事件 schema
```

#### INFRA-2 · 上下文评测通道加固（case 级隔离 · runner/api 编排侧）

```text
加热层: 评测编排健壮性（api/runner 编排；Turn 内零改动）
改动点: 评测编排对单 case 的 transport/HTTP 异常做 case 级捕获——该 case 记 `infra_channel`
        （EVAL-infra 既有口径）并继续余下 case；整跑仅在系统性故障（如连续多 case 全挂）才 fail；
        已完成 case 的分数照常落盘（scored/n 与 infra_rate 如实报告）
预期用户路径变化: 无
R1–R5: 通过——评测侧容错；不触运行时质量路径，不构成「评测专用质量分支」
        （不改任何质量逻辑，只改评测自身的失败传播方式）
free 验收: 不需要专跑；验收 = 单测注入故障 + 下一次通道抖动时整跑不再作废
非目标: 不做 case 级自动重试掩盖通道问题（infra_rate 必须如实暴露，剔除 ≠ 洗白，§11.7 规则不变）；
        部分成绩跑做配对时只对齐共同 scored case（EVAL-1 已按 n_paired 处理）
```

依据：上下文近期 6 跑仅 2 跑有效（§11.7/§12.7 记录在案），全量锚（1.3k Turn 量级）更经不起 gather 一票否决——INFRA-2 是 REP-3 的事实前置。

### 13.4 REP-3 执行规格（栈冻结）与 D-1 场景同构决策

**REP-3 规格（既有 ID 的操作化，承接 §12.3）**

| 项 | 规定 |
|----|------|
| 时点 | RET-9 收刀 + CTX-8 收刀 + RET-18 消融裁决之后、批次 7 任何结构刀之前（硬前置不变） |
| 栈冻结 | 全量锚所跑栈 = 上述三刀收刀后的终态栈；**锚跑窗口内禁止任何部署**；manifest 记录配置指纹 + promote / two-level 开关终态 |
| 范围 | 检索：全量 qrels（约 1.3k Turn 量级）× arm=free × protocol m3；上下文：全量 LongBench 切片（excl-infra 口径已过 ≥0.40 线随跑；若 INFRA-2 未落地则等其落地） |
| 用途 | 批次 7 结构刀的入库级前锚；结构刀落地后再跑一次全量即前后对照——§9.4 门禁 4 / §11.6 条 3 的唯一合法兑现路径 |
| 纪律 | 全量锚入库 ≠ 给冒烟均值背书；叙事仍写「工程变好的间接证明」；锚数值不回填冒烟对照表（两档不混） |

**D-1 · P8 场景同构书面决策（建议裁决 · 即 §11.6 条 3 要求的决策记录）**

| 项 | 内容 |
|----|------|
| 决策 | **接受 writing-RAG 为本轮检索温度计的目标场景**，P8 悬案关闭 |
| 依据 | 本轮全部检索刀（契约 / 呈现 / Index）落点均在 writing 工具面与 Index plane，与产品写作 RAG 用户路径同构（§1.4 场景表）；温度计合法性不受影响 |
| 边界 | agent 场景注册 `search_sources` 属产品功能票，超出本 brief 范围；若未来立项，须新开温度计并重钉全部基线（是新一轮，不是本轮延长线） |
| 记录位置 | 本表即决策记录；终态归因记录（§13.6）引用之 |

### 13.5 排期嵌入与执行清单（不打乱 §11.5/§12.5）

| 批次 | 既定 | 本节追加 | 性质 |
|------|------|----------|------|
| **6 收尾** | RET-9 free N≥2 → CTX-8 | **RET-9 已丢刀回滚**（§13.8）；INFRA-1/2 已部署；EVAL-6 停机 **1/2**；待 CTX-12 → CTX-8 | 规则/观测/吞吐已收；剩最后一把加法契约刀 |
| **6.5（消融收束）** | — | RET-18 two-level 消融（锚 = RET-9 回滚后当前栈）→ 回填排序栈证据台账（§13.6） | 减法证据 · 不计停机线 |
| **7 前（硬前置）** | REP-3 全量锚 | 按 §13.4 规格执行（栈冻结 + 上下文随跑） | 入库唯一合法时点 |
| **7（结构刀）** | RET-4 /（可选 RET-11）/ CTX-6 | RET-4 诚实预期以 RET-17 sizing 校准后回填（**只许下修或维持**）；CTX-6 对照含 CTX-8 栈 | 离线重活 / runtime 评审 |
| **收束** | — | §13.6 终态四问逐条书面回答 + D-1 归档 → 按停机线收刀 | 文档/裁决 |

**RET-18 · two-level doc 加成消融（6.5 批次 · 唯一新开关）**

```text
加热层: 融合排序（热路径，做减法；RET-7 同款模式）
改动点: two-level doc 加成加配置开关，默认保持现状（on）；消融跑 = 关闭后 free 20q N≥2
预期用户路径变化: 关闭时返回序回归 hybrid+RRF+lexical（+呈现层），少一层无单独证据的加成与 0.3s 超时预算
R1–R5: 通过——关闭是减计算；开关零成本
分桶预期: 若 two-level 一直在帮忙 → 关闭后 weak_hits ↑ / nDCG ↓（保留并记录正贡献，成为全栈
        第一个有正存在证据的加成层）；若无差异 → 默认关闭（简化栈，同 RET-7 逻辑）
free 验收: N≥2 + EVAL-1 配对，锚 = RET-9 收刀后栈（注明 promote=off / two-level 状态）
非目标: 不与 RET-9/CTX-8 同批观测（分批防污染）；不计入停机线（减法证据刀）
```

**执行清单（操作顺序 · 给执行者 · 2026-08-04 进度）**

```text
1. [文档] §13.1 记账 + EVAL-6 + D-1 —— ✓ 已生效
2. [离线] RET-17 / CTX-12 —— 脚本已备（batch6b）；**待跑**
3. [部署窗口 A] INFRA-1/2 + RET-18 开关 + RET-9 —— ✓ 已部署；RET-9 N≥2 丢刀已回滚
4. ~~[free] RET-9 N≥2~~ —— ✓ `03304987` / `03569f22` → 丢刀
5. [free] 上下文 60 ×2 —— CTX-8（先 CTX-12）；配对锚可用 `714e38be` / `61624e34`
6. [free] 检索 20q ×2 —— RET-18 OFF；配对锚 = 当前栈
7. [判定] EVAL-6 停机线（已 1/2；看 CTX-8）
8. [全量] REP-3 → 批次 7（RET-4 → 可选 RET-11 → CTX-6）→ 全量后锚
9. 全程仍不 update-baseline（直至第 8 步全量前后对照成立）
```

### 13.6 终态四问收束表（§11.6 的当前可答状态）

| §11.6 四问 | 当前状态 | 剩余缺口 → 动作 |
|------------|----------|-----------------|
| 1 每层有存在证据 | promote 已消融移除（RET-7）✓；low_score hint 已审计修复（RET-15）✓；呈现层已收（RET-12/15-2）✓；lexical 有历史消融 ✓ | **two-level 无单独证据 → RET-18**；hybrid/RRF 记「保留 · 决定不再消融」——台账写全即条 1 关闭 |
| 2 每败可归因 | 检索：RET-8 → RET-14 两次二分；上下文：wrong_answer 已 CTX-10 | 检索差 **RET-17**；上下文差 **CTX-12**（可用 `714e38be` wrong_answer×12 扩样） |
| 3 尺子可信 | EVAL-1/2/4/5 · EVAL-infra · D-1 ✓ | **全量锚未入库 → REP-3** |
| 4 有停机线 | EVAL-6 已操作化；**第二观察批 1/2**（RET-9 已计） | **CTX-8** 为该批最后一票；双计满则停开加法契约刀 |

**排序栈证据台账（条 1 的落地形态 · RET-18 收刀后回填第 4 行）**

| 层 | 存在证据 | 裁决 |
|----|----------|------|
| hybrid 双车道 | C-3 网格打平（L0 弱证据）+ 生产常识 | 保留 · 决定不再消融（理由记录在案） |
| RRF k=60 | C-3 打平 | 保留默认（无证据改动即不动） |
| lexical rerank（经典版） | 历史消融（soft 缩放第五刀回滚史） | 保留 |
| two-level doc 加成 | **无** | **RET-18 消融定去留** |
| excerpt-promote | RET-7 N≥2 无正贡献 | **已默认关**（开关留回滚） |
| low_score hint | RET-15-1 审计（never_triggers）→ 15-2 修复 | 已修 · 阈值 1.0（raw） |
| 呈现层（分层详摘 + 相对分） | RET-12/15-2 N≥2 IR 持平、行为正当 | 保留（呈现不写 IR 叙事） |

### 13.7 诚实预期与不做清单

**诚实预期（防事后叙事漂移）**

- 本节观测/规则/吞吐刀**不承诺任何分数**：EVAL-6 承诺停机线可机械执行；RET-17/CTX-12 承诺归因闭环（可能下修 RET-4/CTX-8 预期，绝不上抬）；INFRA-1/2 承诺评测有效跑率（上下文近期 6 跑仅 2 有效 → 目标：非系统性故障不再整跑作废），不承诺分数。
- RET-9 / CTX-8 宏分大概率仍落噪声带内（EVAL-5 实测 ±1.1pp 起，档案扩到 n=4 后更新）；验收全押主观测位（weak_hits / wrong_answer 子桶 + EVAL-1 配对），并与停机线判定直接挂钩。
- RET-18 两种结果都是收束：`no_stable_delta` → 默认关（简化栈 + 释放 0.3s 超时预算）；OFF 稳定掉分 → two-level 成为全栈第一个有正存在证据的加成层，保留并记录——不存在「白跑」。
- 终态数字带**维持 §11.6 不变**；RET-17 只许下修或维持 RET-4 预期带。主分弹性仍押在既定结构刀（RET-4/11 · CTX-8/6）。

**不做清单（承接 §11.4/§12.4 并追加）**

- 不因 EM 下滑回滚或加改 CTX-1/7（先 CTX-12；EM 粒度 1.7pp/例，「三连降」幅度与同配置噪声同量级）。
- 不为 11–100 排序余量开任何新排序加法刀（CE 默认关纪律；余量归 RET-4 兑现，RET-17 只做归因）。
- 不给 INFRA-2 加 case 级自动重试（掩盖通道问题；infra_rate 必须如实暴露）。
- 不借 INFRA-1 改 summary 生成语义（只截断，不改内容）。
- REP-3 锚跑窗口内不部署任何东西（栈冻结）；锚数值不回填冒烟对照表。
- 不把 RET-18 与 RET-9/CTX-8 同批观测（分批防污染，§9 打包教训不重演）。
- 全量前后对照成立前，仍**不** `update-baseline`。

**与终态四问的关系**：本节四类动作分别关闭条 4（EVAL-6）、推进条 1（RET-18 + 台账）与条 2（RET-17/CTX-12）、兑现条 3（REP-3 规格 + D-1）——**不新增终态目标、不抬高任何诚实带**。若第二观察批触发停机线且 RET-18/REP-3/批次 7 按序完成，本 brief 按 §11.6 停机线收束。
---

## 13.8 部署窗口 A 执行进度（2026-08-04 · 已收束 · RET-9 丢刀）

> **纪律**：§13.5 部署窗口 A **已落地并收束**。INFRA-1/2 · RET-18 开关（默认 on）已部署；**RET-9 N≥2 丢刀，互补词面文案已回滚**（runtime 已重建）。**CTX-8 未合入**（等 CTX-12）。**禁止**本节点 `update-baseline`。  
> **当前运行时栈**：§9 包（limit=30 · excerpt=400 · CTX-1/2/3 · RET-2）+ RET-12 分层呈现 + RET-15-2 相对分 + promote **关** + two-level **开** + INFRA-1/2；**无** RET-9 互补词面句。

| ID | 内容 | 状态 | 备注 |
|----|------|------|------|
| RET-9 | writing 第二搜互补文案 | **N≥2 丢刀 · 已回滚** | 见下方对照表；停机计数 **+1** |
| INFRA-1 | `turn.completed` summary ≤4096 截断 | **已落地** | `turn_controller._truncate_turn_summary` |
| INFRA-2 | case 级隔离 + httpx/httpcore markers | **已落地 · 已验证** | pass1 上下文 `0884c141` infra_excluded=1 整跑完成；pass2 `714e38be` infra_rate=0 |
| RET-18 开关 | `RETRIEVAL_TWO_LEVEL_ENABLED` compose 透传 | **已落地（默认 true）** | 消融排 6.5；**本窗口未关** |
| EVAL-6 / D-1 / §13.1 | 规则与记账 | **已生效** | 停机计数 1/2（RET-9） |
| RET-17 / CTX-12 | 离线脚本 | **脚本已备 · 待跑** | `scripts/official_bench/batch6b_offline_analysis.py` |
| CTX-8 | 证据先行文案 | **未开** | 先 CTX-12 |

#### RET-9 pass1（`03304987`）

| 项 | 值 |
|----|-----|
| run_id | `03304987-cee9-4b21-957a-34724003d9c4` |
| nDCG@10 | **0.4596** |
| R@10 / R@100 | 0.466 / 0.510 |
| 桶 | ok **30** · weak_hits **27** · no_search **2** · search_cap **1** · query_drift **0** |
| promote_total | **0** |
| gold_read_rate | **0.80**（FiQA 0.60 · absent 8） |
| FiQA | nDCG@10 0.377 · **R10=R100=0.492**；n_search **全 1** |
| 同批上下文 | `0884c141` F1 **0.423** · EM 0.237 · infra_excluded **1**（INFRA-2 生效） |

#### RET-9 pass2（`03569f22`）

| 项 | 值 |
|----|-----|
| run_id | `03569f22-7b37-42f6-b63e-741a5e8ee82a` |
| nDCG@10 | **0.4466** |
| R@10 / R@100 | 0.446 / 0.492 |
| 桶 | ok **30** · weak_hits **28** · no_search **1** · search_cap **1** · query_drift **0** |
| promote_total | **0** |
| gold_read_rate | **0.817**（FiQA 0.60 · absent 8） |
| 分库 nDCG@10 | SciFact **0.620** · NFCorpus **0.343** · FiQA **0.377**（**R10=R100=0.492**） |
| FiQA n_search | **全 1**（互补搜仍未触发） |
| 同批上下文 | `714e38be` F1 **0.404** · EM **0.183** · infra_rate **0** · ok38 / wrong_answer**12** / verbose6 / abandoned4 |

#### RET-9 N≥2 裁决（**丢刀**）

| | pass1 | pass2 | promote-off 锚 |
|--|-------|-------|----------------|
| nDCG@10 | 0.460 | **0.447** | 均值 0.447 / `f92bc610` 0.457 |
| weak_hits | 27 | **28** | 26–28 |
| query_drift 桶 | 0 | **0** | ≤1 |

- 两轮均值 nDCG@10 **0.453**（锚噪声带内）；weak_hits 均值 **27.5** **未收窄**。  
- 触发面空：FiQA 两轮均为单搜 → 「互补词面第二搜」未进轨迹。  
- **裁决（EVAL-6）**：主观测位 + 宏分双无稳定 Δ → **丢刀**；已回滚 `writing/system.md` 互补词面句（保留 ≤2 / low_score→改读）；writing 台账回落至 ≈3166 tok（§11.7）。不入库。  
- **停机线**：第二观察批 **+1/2**；下刀 **CTX-8**（先 CTX-12）——若亦双无 Δ → 触发停机线。

#### 为何契约批看不到「很大提升」（读法备忘 · 防叙事漂移）

1. **主缺口在 Index/相关性，不在「怎么搜」**：weak_hits≈27、FiQA gold absent_from_ranked、lane 饥饿——契约/呈现刀改不了 ranked 里没有 gold。宏分大涨押在 **RET-4/11**（尚未开）。  
2. **行为侧早已近天花板**：verbatim/≤2 之后再加纪律（RET-9）常进不了轨迹（FiQA 全单搜）。  
3. **冒烟噪声 ±1.5–4pp** 盖过契约刀效应量 → 多刀 `no_stable_delta` 是预期，不是「完全无效」。  
4. **诚实预期本就写在 0.44–0.47 平台带**：当前 ≈0.45 落在「平台已钉、结构刀未开」；终态 0.46–0.50 须等 embed。  
5. **上下文同理**：verbose 已降；残余 **wrong_answer** 要 CTX-8/6 或承认能力墙，不是再堆答题文案。

#### 下一步（窗口 A 收束后）

1. **CTX-12** 离线解剖（复用 `61624e34` / `13647cb0` / 可选 `714e38be`）→ 定 CTX-8 文案与 EM 盯防。  
2. **RET-17** 离线 gold 名次带（复用 `03304987`/`03569f22` 等）→ 校准 RET-4 预期（只许下修）。  
3. **CTX-8** 单刀合入 → free 上下文 60 ×2；主观测位 wrong_answer；计入停机线第二票。  
4. **RET-18** two-level 消融 N≥2（锚 = 当前栈：promote=off · RET-9 已回滚 · two-level on）。  
5. **REP-3** 全量锚 → 批次 7 **RET-4**。全程仍 **不** `update-baseline`。

#### RET-18 消融用法（6.5 批 · 当前勿关）

```bash
RETRIEVAL_TWO_LEVEL_ENABLED=false
# recreate runtime 后 free N≥2；配对锚 = 当前栈（promote=off · RET-9 已回滚 · 注明 two-level 状态）
```

---

## 14. 第六轮补充思考：为什么多轮无明显提升 + 真正提升的执行主线（2026-08-04）

> **性质**：直答一个复盘级问题——「优化了很多轮，为什么没有一个相对明显的提升？」并给出后续唯一执行主线。全部遵守文首两道门 + 既有全部门禁与不做清单；**不推翻任何既有裁决**（RET-4 立项、RET-16/CTX-5/CTX-11 不开、RET-5/13 挂起、停机计数 1/2 均维持）。  
> **编号承接**：EVAL-7（流程规则）· RET-19（观测刀）· PROD-1（新温度计票）；RET-4 给出**执行细化 v2**（改执行方式，不改立项结论）。  
> **一句话定位**：前五轮的问题不是「刀无效」也不是「流程不严」，而是**排期把杠杆倒挂了**——便宜、安全、可观测的契约刀轮轮优先，贵但决定性的结构刀（证据链三次独立指向它）五轮零执行。本节把结构刀从「批次 7 的远期项」改写为**日历上的主线**，其余一切让路。

### 14.0 直答：为什么多轮看不到明显提升（三笔账）

先承认已兑现的真实提升（防止把「近三轮平」误读成「全程无效」）：

| 温度计 | 起点 | 当前 | 兑现来源 | 性质 |
|--------|------|------|----------|------|
| 上下文 F1 | ≈0.33（CTX-0） | ≈0.41–0.42（excl-infra） | CTX-1 答短纪律 为主 | 真实工程改善（verbose 16→4） |
| 检索 nDCG@10 | ≈0.409（`689cfe71`） | ≈0.447（promote-off 均值） | §9 包（limit30 等） | 真实工程改善（+9%） |
| 行为桶 | drift 83% | drift ≤1 · cap ≤3 | 前四轮契约刀 | 已近天花板 |
| 排序栈 | 两层无证据层 | promote 已消融移除 · hint 已修 | RET-7/15 | 栈更干净（分数不动是预期） |

真正「平」的是 §11–13 三轮（契约/呈现批），而这是**三笔账共同注定的**：

**账本一：刀型配比倒挂（执行了什么 vs 证据指向什么）**

| 刀型 | 五轮内已执行（进过运行时/评测） | 数量级 |
|------|--------------------------------|--------|
| 契约/呈现/文案刀 | RET-1/2/2b/9(回滚)/12/15-2 · CTX-1/2a/2b/3/7 | **11 把** |
| 观测/基建/规则/消融 | RET-3/6/7/8/10/14/15-1/17(备) · CTX-4/9/10/12(备) · EVAL-1~6/infra · INFRA-1/2 · REP-1/2 · ABL-1 · D-1 | **20+ 项** |
| **结构刀（Index / 预算）** | RET-4 · RET-11 · CTX-6 | **0 / 3 执行** |

与此同时，归因证据**三次独立**指向同一层：RET-8（weak_hits 主类 = lexical_miss）→ RET-6/10（`pool_starvation` → `lanes_fed_relevance`：车道喂饱了、候选就是不相关）→ RET-14（FiQA **一半 query 的 gold 根本不在 ranked**，absent 7–10/20）。三条证据全说「向量车道语义召回不行」，而向量车道的脑子（MiniLM-L6-v2，2021 年模型）五轮未动。**不是不知道缺口在哪，是一直没去。**

**账本二：天花板账（在天花板下方拧契约，宏分只能 no_stable_delta）**

- FiQA 每 20 题有 7–10 题 gold 完全不在合并榜上——这些题的 nDCG 被**召回硬顶死为 ~0**，任何呈现/文案/停搜纪律都改不了「榜上没有」。
- 当前冒烟平台 0.447 已落在旧 embed 在这三个子集上的能力带内；§11.6 终态带写 0.46–0.50 的前提本来就是「RET-4/11 至少一票落地」。
- 结论：**契约刀不是失败了，是它们的战场（行为面）早在第 4 轮就打扫干净了**；剩余缺口的钥匙不在它们手里。四连 `no_stable_delta` 是对「主缺口不在契约层」的第四次确认，属于花钱买的确定性——但没必要再买第五次。

**账本三：MDE 账（刀比尺子的刻度细）**

- 尺子的最小可检测效应：20q 冒烟噪声 ±1.5–4pp；EVAL-5 实测同配置配对带 ±1.1pp 起（n=4，样本少偏乐观）。
- 契约/呈现刀的真实效应量：观测到的全部 ≤1–2pp（RET-12/15-2/7/9/CTX-7 皆然）。
- **效应量 < 尺子刻度 → 单刀 N≥2 冒烟从统计上就不可能判出胜负**，`no_stable_delta` 在开跑前就已注定。每把这样的刀消耗 2×20m 跑量 + 归因人力，却只能产出「无法证明」。这是流程要修的地方（→ EVAL-7），不是刀要更多。

**三笔账合起来的直答**：分数没有明显再涨，因为（1）便宜的提升已被前四轮吃完；（2）剩余缺口是结构性的，而结构刀零执行；（3）继续开的契约刀在统计上不可能证明自己。**接下来唯一合理的动作是把日历让给结构刀。**

### 14.1 外部对标（第二辑 · 聚焦「平台期怎么破」——成熟团队在这个节点做什么）

| # | 案例 / 实践 | 关键数字（执行时须复核，勿直接照搬预期） | 映射本栈 |
|---|-------------|------------------------------------------|----------|
| 1 | **Embedding 代差**：MTEB Retrieval（BEIR 系）公榜上 `all-MiniLM-L6-v2` ≈42 nDCG@10 均分；`bge-small-en-v1.5` ≈51.7、`gte-small` ≈49.5、`e5-small-v2` ≈49——同为 **384 维**、参数量 22M→33M 级 | 代差 **≈+7~10pp**，是本栈所有已试杠杆效应量的 5–10 倍 | **RET-4**——且 384 维候选让原票「384→768 改 ANN」整段作废（§14.2.1） |
| 2 | **Anthropic Contextual Retrieval**（2024-09）：离线 LLM 为 chunk 补定位语，contextual embed+BM25 → top-20 检索失败率 **−49%**，再叠 rerank → **−67%** | 与 embed 升级**正交可叠加**（§11.2 已立项） | **RET-11**——执行而非再论证；(b) doc2query 变体连 ANN 都不用重建 |
| 3 | **两段式检索是生产 RAG 标配**：召回宽 + 精排窄（Cohere Rerank / bge-reranker 级），BEIR 类任务常见 +3~8pp nDCG@10 | 本栈 R3 禁默认 CE 上热路径——**正确**；但成熟做法是先**离线回放**量化余量再决定是否写预算票，而不是永远不看 | **RET-19**（零风险离线余量刀，§14.2.4）；RET-17 的「11–100 排序余量」正好给它当输入 |
| 4 | **Claude Code 式 agentic search**：不建索引，靠模型多轮 grep/read 迭代逼近——其前提是**模型愿意也能够多轮迭代** | 本栈反例：FiQA 两轮全部单搜、RET-9 文案进不了轨迹——**行为文案已到顶，别再劝**；召回要么靠 index 自己行（RET-4/11），要么服务端代劳（RET-13，解挂条件不变） | 教训固化：契约层对「搜得更好」的边际 ≈0，停机线精神提前适用 |
| 5 | **用真实使用构建 golden set**：成熟团队的评测演进方向都是「公开 bench 校准工程 → 产品分布验收效果」（从产品日志/真实任务提炼题集与 gold） | 本 brief 温度计是**扁平 BEIR**，§1.4-A 已自知「温度计≠产品语料分布」；§11.6 条 4 点名「产品树状语料上的同构验证」但无落地票 | **PROD-1**（§14.2.5）——这是用户问的「不只评测分数的真正效果提升」的直接度量 |
| 6 | **长上下文证据先行**（quote-then-answer / citations）：Anthropic 等长文 agent 标准做法 | **CTX-8 已立项、已排期、前置（CTX-12）脚本已备**——缺的是执行，不是新知 | 上下文主线不加新刀：CTX-12 → CTX-8 → CTX-6，按序走完 |

**对标的元结论**：成熟团队在平台期做的不是「更多更细的 prompt 刀」，而是三件事——**换代结构组件（#1/#2/#3）、把评测锚到真实分布（#5）、承认行为层已收敛并停手（#4）**。本栈的观测/纪律基建已是成熟水平（配对检验、消融对称、停机线、infra 剔除都齐了），缺的只是把结构刀真正打出去。

### 14.2 真正提升的执行主线（主菜单 · 按预期效应量排序）

#### 14.2.1 RET-4 执行细化 v2（主菜 · 效应量最大 · 票比原计划小）

对 §9.2/§10.2 原票的三点修订（只改执行方式，立项结论与门禁不变）：

```text
修订 1（票的体积砍半）：候选优先取 384 维现代模型——bge-small-en-v1.5 / gte-small / e5-small-v2。
        原票「384→768 需处理 ANN 维数」整段作废：同维替换 = 影子 INDEX_VERSION=9 + 全量离线重嵌，
        pgvector/ANN 结构零改动。768 维 base 级仅当 384 候选 N≥2 后仍不达预期才另立票。
修订 2（离线预验证，一天内出结论）：影子重嵌之前，先在评测侧离线做候选选型——
        对三个 BEIR 子集语料 + 官方 query 直接算各候选的 nDCG@10（纯 L0 假说尺，不进主栏、不洗白 free，
        与 forced 同一纪律地位）。选型标准：对 MiniLM 的 Δ、对 RET-8 ①② 类 case 清单的 gold 排名提升数。
        e5 系注意 query/passage 前缀协议须按模型卡实现，选型与生产实现保持一致。
修订 3（污染诚实条款）：现代 embed 模型的训练数据普遍与 BEIR 域重叠（MS MARCO 等），
        BEIR 温度计上的 Δ 可能高估产品迁移增益——这正是 PROD-1 存在的理由；
        入库叙事里必须写明该保留意见。
执行序（不变量：REP-3 全量前锚先行）：
        离线选型（评测侧脚本）→ 影子索引 v9 重嵌（Turn 外，R4）→ 配置切 v9 → free 20q N≥2 + EVAL-1 配对
        → 分库看 NFCorpus/FiQA nDCG + RET-14 gold_read/absent 同 case 对照 → 正 Δ → 全量后锚 → 入库裁决
回滚：配置切回 v8，零重建成本（原票不变）
诚实预期：冒烟宏 nDCG@10 0.447 → 0.47–0.51（依据代差账 + RET-17 sizing 校准，只许下修）；
        FiQA absent 7–10/20 → 显著下降是主验收位（比宏分更硬）
```

#### 14.2.2 RET-11(b) 先行变体（配菜 · 与 RET-4 分影子索引拆因）

维持 §11.2 原票，执行顺序建议明确为 **(b) doc2query 伪查询先行**：只扩 BM25 字段、不动 embed、不动 ANN，是两个变体里更便宜且更对症 lexical_miss 的一个；(a) contextual header 待 RET-4 落地后按剩余 absent 占比决定开不开。**两票与 RET-4 绝不同影子索引**（§11.4 纪律不变）。

#### 14.2.3 上下文主线（不加新刀 · 按既定序执行）

CTX-12 离线（脚本已备）→ **CTX-8** 单刀 N≥2（主观测位 wrong_answer 子桶；停机线第二票）→ 视 CTX-8 对 hotpotqa 证据丢失的兑现度决定 **CTX-6** 开不开（§11.3 依赖管理不变）。EM 残余里 (iii) scorer_alias 类按 CTX-10 裁决记「尺子局限、决定不修」；narrativeqa 0.25–0.29 按 §11.6 承认接近该 bench 模型能力墙——**这两块不再投入任何刀**。

#### 14.2.4 RET-19 · 离线 rerank 余量回放（观测刀 · 零运行时改动）

```text
加热层: 可归因性（评测侧离线回放，Turn 内零改动）
改动点: 取既有 free 跑（dfe97d37 / 6c87e401 / bcdbbb85 / f92bc610）落盘的每 query 合并榜前 50，
        离线用 small 级 cross-encoder（如 bge-reranker-base）重排后重算 nDCG@10，与原榜配对对照；
        分数据集聚合，与 RET-17 的「gold 在 11–100」占比互相印证
预期用户路径变化: 无
R1–R5 / while / 强制搜: 通过——纯离线回放；qrels 仅评测侧使用（RET-14 同款红线）
分桶预期: 不改分桶；产出「排序余量上限」一个数
free 验收: 不需要（观测刀）；产物质量以能否二选一裁决衡量——
        余量 ≥3pp → 值得写一张有 R3 预算测试的 rerank 票（top-20 池 · 轻量模型 · 严格超时，另行评审）；
        余量 <2pp → 书面关闭 rerank 议题（记入 §13.6 台账「决定不做」行），CE 默认关纪律从此有实测背书
非目标: 不因回放数字直接上热路径（预算票另立另审）；不用回放 Δ 做任何入库叙事
```

依据：这是 §11.6 条 1「每层有存在证据」的镜像——**「决定不做的层」同样应该有证据**。当前「CE 默认关」只是文档纪律，一次零成本回放就能把它变成实测裁决，且顺手给 RET-4 的预期校准提供第二视角（若 rerank 余量大，说明召回其实够、排序是主犯，RET-4 预期应下修）。

#### 14.2.5 PROD-1 · 产品镜像小套件（新温度计票 · 回答「不只评测分数的真正效果」）

```text
加热层: 温度计本体（新增第二套件，不动既有 BEIR 温度计与其历史可比性）
改动点: 构建 20–30 题「产品形状」检索题集——树状 seed 语料（真实目录/path/tags 分布）+
        writing 场景真实信息需求题面 + 人工标注 gold 文档（qrels-lite，允许多 gold）；
        以与 BEIR L1 完全相同的 free 协议跑（Session/Turn/search_sources/first-seen 合并）；
        题面与 gold 一次冻结、版本化，严禁用其调参（只做验收，防过拟合）
预期用户路径变化: 无（评测资产）；但它度量的正是用户路径——path 线索、树状层级、真实查询词面
R1–R5: 通过——评测侧资产构建
free 验收: 本身是尺子；生效标志 = RET-4/11 落地后在本套件上复验 BEIR Δ 的迁移率
        （BEIR 涨而 PROD-1 不涨 → 污染/分布不匹配警报，入库叙事必须如实记录）
非目标: 不替代 BEIR 温度计（历史对照链不断）；不用 LLM 生成题面充数（题面须来自真实使用形态）；
        规模控制在 20–30 题（人工 gold 的可负担上限，宁小而真）
```

依据：本 brief 反复自知「扁平 BEIR ≠ 产品语料分布」（§1.4-A/E、§14.2.1 污染条款），但五轮里「工程变好」的最终证明始终只有 BEIR 间接分。PROD-1 把「用户路径真的变好」从叙事变成读数——**这是本节唯一直接回应「流程和效果上的优化，而不只是评测分数」的票**，也是 §11.6 条 3 终态的最后一块拼图。排期在 RET-4 影子索引重嵌的等待窗口内并行构建（人工标注与离线重活互不抢资源）。

### 14.3 流程修正：EVAL-7 效应量门（防止契约刀继续消耗日历）

```text
加热层: 调优流程规则（纯文档规则，零运行时代码；EVAL-6 的前置补丁）
改动点: 任何拟开新刀在卡片阶段必须声明「预期效应量」并与 EVAL-5 实测噪声带比对：
        ① 预期宏分效应 ≥ 2× 当前噪声带（现 ≈±1.1pp → 门槛 ≈2.2pp）→ 才有资格申请单刀 N≥2 冒烟跑量；
        ② 达不到门槛但有明确子桶/行为主观测位 → 只允许以子桶证据验收（不占宏分叙事、不单独跑分，
           可搭其他必跑批次的顺风观测）；
        ③ 两者都没有 → 不开刀（写入不做清单，附一句理由）
预期用户路径变化: 无
R1–R5: 通过——规则条目
free 验收: 不需要；生效标志 = 此后不再出现「开跑前就注定 no_stable_delta」的单刀冒烟
非目标: 不追溯否定已收刀（它们买到了确定性）；不妨碍消融/观测刀（本就不占宏分叙事）；
        结构刀天然过门槛①，本规则实质效果 = 把冒烟跑量预算让给结构刀
```

配套排期纪律（写死）：**自本节起，每个含改动刀的批次必须至少有一把结构刀（RET-4/11/CTX-6/PROD-1 之一）在推进中**（离线选型、重嵌、标注都算推进）；不满足则该批次只许跑观测/消融/全量锚。这是对账本一「杠杆倒挂」的制度化纠正——与停机线（EVAL-6）互为表里：停机线负责「停开无效加法」，本条负责「主线不再让位」。

### 14.4 收束排期表（唯一主线 · 覆盖至本 brief 终态）

| 批次 | 内容 | 性质 | 完成判据 |
|------|------|------|----------|
| **A（即刻 · 全离线可并行）** | CTX-12 + RET-17（脚本已备）；**RET-19 回放**；EVAL-7 生效；PROD-1 题集构建启动；RET-4 离线选型（修订 2） | 观测/规则/资产 · 零运行时 | 四份归因产物 + 候选 embed 选型结论 |
| **B（最后的契约位 + 消融收束）** | CTX-8 单刀 N≥2（停机线第二票）；RET-18 two-level 消融 N≥2 | 既定排期不变 | 停机线判定出结果；排序栈证据台账（§13.6）回填完毕 |
| **C（硬前置）** | REP-3 全量锚（检索必跑；上下文按 §13.1 已过线随跑；栈冻结） | 入库唯一合法时点 | 两套件全量前锚落库 |
| **D（主菜）** | RET-4：影子索引 v9 → free N≥2 配对 → 全量后锚 → 入库裁决 | 结构刀 | FiQA absent 显著下降 + 宏分正 Δ +全量对照成立 |
| **E（视 D 余量）** | RET-11(b)（分影子索引）；CTX-6（对照含 CTX-8 栈）；RET-19 若余量 ≥3pp 则评审 rerank 预算票 | 结构刀 / 条件票 | 各自 N≥2 + 同 case 前后对照 |
| **F（收束）** | PROD-1 首跑验证迁移率 → §11.6 终态四问逐条书面作答 → 按停机线收刀归档 | 验收/文档 | 四问全部可答；本 brief 宣布完备 |

### 14.5 诚实预期与不做清单（第六轮）

**诚实预期（防事后叙事漂移）**

- 本节两把观测/资产刀（RET-19 / PROD-1）与规则刀（EVAL-7）**不承诺分数**；承诺的是：rerank 议题一次定案、BEIR→产品迁移率首次可测、冒烟跑量不再花在注定无果的刀上。
- 主分弹性全押 RET-4：冒烟带 0.47–0.51（RET-17/19 校准后只许下修）；FiQA absent 收窄是比宏分更硬的验收位。若 RET-4 落地后宏分仍平 → 按 §11.6 条 2 把残余缺口书面归因到 {qrels 结构 / 能力墙}，本 brief 照样按停机线收束——**「证明了修不动」与「修好了」都是完备终态**，唯一不可接受的是第六轮还在天花板下面拧契约。
- PROD-1 迁移率如果显著低于 BEIR Δ → 如实写入入库叙事（污染/分布保留意见），并把它当成下一轮（产品语料专项）的开题证据，而不是本轮的失败。

**不做清单（承接 §11.4/§12.4/§13.7 并追加）**

- 停机线判定前后，**不再立项任何新的加法契约/文案刀**（CTX-8 是最后一把；EVAL-7 门槛从制度上封死回头路）。
- 不把 RET-4 离线选型的 L0 数字写进任何主栏（与 forced 同一纪律地位）。
- 不用 PROD-1 题集做任何调参循环（它是验收资产，不是训练信号；一旦用于调参立即作废重建）。
- 不在 RET-19 回放余量出来之前写 rerank 预算票（观测先于改动，门禁 6 同款）。
- 不因「第六轮了还没大涨」而放宽任何入库门禁或改判分口径——分数是果，不是目的（文首因果表不变）。

**一句话版**：前五轮把「怎么搜、怎么读」的行为工程做到了天花板并证明了它——这是真提升；剩下的分数缺口三次归因都指向 2021 年的 embed 模型和语料词面桥，**下一个明显提升只会来自把 RET-4/11 真正打出去、用全量锚和产品镜像套件验收**；契约刀的时代到 CTX-8 为止。

### 14.6 批次 A 执行进度（2026-08-05 · 离线产物 · **未入库**）

> **纪律**：下表 L0 / 离线数字 **禁止**写入 SCORECARD / free 主栏；仅作影子索引选型与排期依据。

| 票 | 状态 | 结论（一句话） |
|----|------|----------------|
| CTX-12 | ✓ 离线 | `gamma_paraphrase` 主导 → 支持 CTX-8「prefer passage wording」 |
| RET-17 | ✓ 离线 | gold absent ~18–20%；FiQA 冒烟切片 absent 仍可见 → 支撑 RET-4 主杠杆叙事 |
| RET-19 | ✓ 离线 | mean Δ **+0.51pp** → **`close_rerank_topic`**（不上热路径 CE） |
| RET-4 L0 选型 | ✓ 离线（GPU / 5080） | 推荐 **`thenlper/gte-small`**（384-d）；宏观 vs MiniLM **+9.05pp** |
| CTX-8 | 文案已部署 · free **待 N≥2** | `system.md`：Evidence-before-answer + prefer passage wording |
| PROD-1 | 草稿 | `eval/official/prod1/` 24 题 · `frozen=false` · 禁调参 |
| EVAL-7 | 规则已述 | 效应量门写在 §14.3；冒烟契约刀继续受其约束 |

**RET-4 L0 冒烟表**（smoke run `03569f22` · 每库 ≤20q · artifact `eval/reports/official/batch14/ret4_selection.json`）

| 模型 | SciFact nDCG@10 / abs@100 | NFCorpus | FiQA | macro |
|------|---------------------------|----------|------|-------|
| MiniLM-L6-v2（基线） | 0.645 / 1 | 0.386 / 0 | 0.404 / 3 | **0.478** |
| bge-small-en-v1.5 | 0.759 / 0 | 0.412 / 0 | **0.465** / 3 | 0.545 |
| **gte-small（选）** | **0.793** / 0 | **0.482** / 0 | 0.432 / 3 | **0.569** |

- **选型**：`thenlper/gte-small` → 计划影子 `INDEX_VERSION=9` 全库重嵌；**仍需** free N≥2 + 全量锚才谈入库。  
- **诚实注**：本冒烟切片上三模型 FiQA **absent@100 均为 3**——L0 宏分大涨主要来自 SciFact/NF；FiQA absent 收窄仍要以影子索引后的 free/全量对照为准，不得用本表宣称「absent 已灭」。  
- **bge vs gte**：bge 在 FiQA nDCG 略高；gte 宏分与 SciFact/NF 领先 → 按修订 2 的宏分+同分选型规则取 gte；若影子后 FiQA 回归异常可回看 bge。

**下一批（§14.4 B）**：CTX-8 free N≥2（停机线第二票）→ RET-18 two-level 消融 N≥2 → 再进 REP-3 / 影子重嵌。
