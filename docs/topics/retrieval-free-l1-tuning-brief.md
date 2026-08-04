# Free-L1 Tuning Brief（检索 + 上下文 · 交给后续模型）

> **受众**：高级模型 / 下一轮调优负责人  
> **日期戳记**：2026-08-03（§9 批次 1–3 代码已部署 · **仅记有效 free 跑**）  
> **唯一验收温度计**：L1 产品 Turn · `arm=free`（检索看 nDCG；上下文看 agent_f1/EM）  
> **不作为验收**：forced/oracle 诊断臂、纯 L0 旁路、coding（本轮不可信）；schema 事故跑（见 §7.7 说明，**不入对照**）  
> **本文自含**：不依赖阅读其他专题文档即可理解流程、历史与问题  
> **调优进度**：§9 批次 1–3 刀已落地（打包部署，**未严格单刀单 commit 拆因**）；有效冒烟：检索 nDCG@10 **0.455** · 上下文 F1 **0.413**（各 N=1，**不入库**）  
> **执行状态总览**：§9 见 **§9.6**；§10 批次 5 见 **§10.6**（REP/ABL 已跑 · CTX-2 **保留** · RET-6 已部署 · **未入库**）  
> **第二轮提案（基于 §9 有效跑归因 · 观测先于改动）**：见 **§10**（批次 5–7：复跑凑 N≥2 → 归因/消融 → 单刀契约 → 结构刀）  
> **第三轮补充思考（外部对标 · 2026-08-04）**：见 **§11**（EVAL 配对判别 / RET-10~13 / CTX-8~9 / 「合理、完备」终态定义）  
> **批次 6 前置 + 首刀**：见 **§11.7**（EVAL-1/2/3 · RET-10 · CTX-9 · EVAL-infra · RET-12 **均已落地并有 free 观测**；**未入库**）

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
| 回滚后冒烟锚（改刀前对照） | `689cfe71` nDCG@10 **0.409**；平台曾记 **~0.41**（勿再默认 0.434） |
| **§9 批次 1–3 代码** | **已部署运行时**：RET-1/2/2b/3 + CTX-1/2a/2b/3（打包上线，**未按单刀单 commit 拆因**；归因能力弱于方案纪律） |
| **有效检索 free** | `99d729de`：nDCG@10 **0.455** · R@10 **0.448** · R@100 **0.509**；桶 ok29 / weak_hits26 / cap3 / drift1 / no_search1；RET-3 观测已出（median≈0.434 · weak 快照 30 · promote=55） |
| **有效上下文 free** | `083eca09`：agent_f1 **0.413** · EM **0.283**；桶 ok37 / verbose8 / gave_up15（相对 CTX-0：verbose 16→8，gave_up 13→15，ok 30→37） |
| 相对改刀前锚的读法 | 检索宏分与宏 R 相对 ~0.41 **单次正 Δ**；上下文 F1 相对 ~0.33 **进入 0.40+ 预期带**。**均为 N=1** → 可记「方向正向」，**不得入库 / 不得单刀归因** |
| FiQA 深度 | 本次仍 **R@10=R@100=0.542** → RET-1「深度脱钩」假设**尚未兑现**；RET-5 解挂条件仍观察中 |
| SCORECARD / baseline | **未更新、不入库**（需 N≥2 + 叙事可归因） |
| 行为侧前几刀（verbatim / ≤2 搜） | **保留** |
| 下一轮硬约束 | 只认 free；重要刀 **N≥2**；优先补第二次同配置冒烟；再决定 RET-1/CTX-2 去留与是否开 RET-4；检索/上下文分开归因 |
| **执行进度表** | **§9.6** |
| **第二轮提案** | **§10**（REP 复跑 / RET-6~9 / CTX-4~7 / RET-4 执行细化；观测先于改动） |

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

## 5. 当前代码与运行时状态（§9 部署后）

相对第五刀回滚态，运行时现为：

- `search_sources`：**default `limit=30`**（RET-1）
- `search_sources_excerpt_chars`：**400**（RET-2b；`.env` 已对齐）
- writing `system.md`：有 hit 后禁 list_dir/grep「再确认」；prefer limit≥30（RET-2）
- agent `system.md`：Answer format（CTX-1）；长文续读 + grep→定向 read（CTX-2b/CTX-3）
- `read_file` 截断 hint：「已读 X / 共 Y … 续读 offset=N」（CTX-2a）
- RET-3：result 含 `bucket_counts` / `suite_ndcg_median` / `weak_hits_cases` / promote 计数；schema 允许 `excerpt_promote_reorder`
- soft lexical 缩放：**仍无**（第五刀保持回滚）
- **仍保留**：verbatim 首搜、≤2 搜次、C-1 读预算、C-3 default fusion、m3 free

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
- **检索**：§9 打包已部署；**有效**单次 nDCG@10 **0.455**（vs 改刀前锚 ~0.41）；FiQA 深度仍卡；**待 N≥2**；RET-4 可立项（weak 清单已有）。  
- **上下文**：专项刀已部署；**有效** F1 **0.413**（verbose↓，gave_up 未降）；**待 N≥2**。  
执行进度见 **§9.6**；**第二轮提案与批次 5–7 见 §10**（先复跑/归因/消融，再单刀开工）。

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
| `scenarios/agent/system.md` | 8774 | **2193** | 基线（0%） | CTX-1/2b/3 已在栈 |
| `scenarios/writing/system.md` | 12534 | **3133** | 基线（0%） | verbatim / ≤2 搜 / RET-2 |
| 工具描述 `search_sources` schema | （实现默认） | — | — | RET-1 limit=30；excerpt 属 settings 非 system |

**阈值**：任一文件相对本表建账点 **+15% ≈tokens** → 触发合并精简评审（精简本身按单刀 N≥2）。  
**批次 6 拟增刀预留记账**（落地时回填实测 Δ）：

| 拟增刀 | 目标文件 | 预估增量（字） | 记入条件 |
|--------|----------|----------------|----------|
| RET-9 第二搜互补 | writing/system.md | ~200–400 | 单刀合入后 |
| RET-12 分层呈现 | 工具格式化（非 system） | 0 system | 不进本台账分子（已落地） |
| CTX-7 答题示例 | agent/system.md | ~150–250 | 单刀合入后 |
| CTX-8 证据先行 | agent/system.md | ~200–400 | 单刀合入后 |

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

**状态**：**已部署**；观测跑 `3c34de88` nDCG 持平（`no_stable_delta` vs `0744546e`）符合「不写 nDCG」预期；**行为 N≥2 仍差一轮**；不入库。

#### 下一步（严格按 §11.5）

1. 检索再跑一轮 free 20q → RET-12 行为 N≥2（配对 `3c34de88`）。  
2. 上下文再跑一轮 free 60（通道稳时）→ 与 `1707135c` 凑 N≥2。  
3. 其后批次 6：**RET-7 → RET-9 → CTX-7 → CTX-8**（CTX-5 仍不开；主看 wrong_answer）。  
4. 批次 7：**RET-4** embed（weak_hits / `lanes_fed_relevance` 已证成）。  
5. 仍 **不** `update-baseline`。
