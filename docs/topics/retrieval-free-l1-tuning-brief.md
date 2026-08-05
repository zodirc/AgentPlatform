# Free-L1 Tuning Brief（检索 + 上下文 · 收敛版）

> **受众**：下一轮调优负责人 / 高级模型  
> **日期戳记**：2026-08-05（**收敛重写** · CTX-8 N≥2 已收 · 停机线 **2/2** · RET-4 重嵌进行中 · **CTX-13 已收 · 组装层暴露面=0 → CTX-14/15/6 不开** · **EVAL-8 已执行**（双锚离线复算 · 口径 v2 已切码 · CTX-16/定位面门槛未过→关题）· **未入库**）  
> **历史全文备份**：同目录 `retrieval-free-l1-tuning-brief.md.bak-20260805`（原 2563 行叙事稿，裁决以本文为准）  
> **唯一验收温度计**：L1 产品 Turn · `arm=free`（检索 nDCG；上下文 agent_f1/EM）  
> **不作为验收**：forced/oracle、纯 L0、coding；schema/inflight 事故跑 **不入对照**  
> **当前平台锚（冒烟）**：检索 promote-off 均值 nDCG@10 **≈0.447**（`bcdbbb85`/`f92bc610`）；上下文 excl-infra F1 **v1≈0.41**（`fdd03298` 0.428 / `b5d24c9e` 0.411）；**v2 复算锚 ≈0.53**（`b5d24c9e` 0.516 / `1707135c` 0.544 · `eval/reports/official/batch16` · **口径修正，非工程涨分**）  
> **停机线（EVAL-6）**：**2/2 已触发**（RET-9 + CTX-8）→ **停开新加法契约刀**  
> **下一刀序**：检索——嵌库就绪后 **RET-18 → REP-3 → RET-4 重嵌验收**；上下文——**产品侧工程停手**（组装层已否决；CTX-16/定位面门槛未过→关题）；**测量面 EVAL-8 已收**（此后新跑须注明 `agent_f1@v2`；旧锚 ≈0.41 = v1，禁止裸比）  
> **SCORECARD / baseline**：**未更新、不入库**  
> **流程图**：[retrieval-tuning-flowchart.png](retrieval-tuning-flowchart.png) · [context-tuning-flowchart.png](context-tuning-flowchart.png)

---

## 1. 目的与第一性原则

### 1.1 在优化什么

```text
目标（因）     = 生产工程成熟（Index / 排序 / 契约 / 读预算）
手段（温度计） = 官方小量题集走与用户相同的 Session→Turn→loop→工具 · arm=free
结果（果）     = free 分数上升只是工程变好的「间接证明」
```

| 对 | 错 |
|----|----|
| 改生产工程 → free 分间接升 → 才谈入库 | 为抬分改评测臂、注入答案、forced/oracle、评测专用质量分支 |
| 测试集 = 量准、归因、否决坏刀 | 测试集 = 把数字刷上去 |

检索与上下文两套温度计**分开归因**；一边的分不给另一边背书。

### 1.2 原则一：成熟合理

1. **同构**：题面进真实会话与工具面；主臂自由搜（不写交互剧本）。  
2. **可归因**：轨迹探针 + 确定性分桶；失败落到 Index / 契约 / 行为 / 预算某一层。  
3. **可复现**：同协议、同档、配置指纹；冒烟噪声下 **N≥2**；全量锚才入库。  
4. **杠杆分层**：先行为，再 Index/排序/embed；禁止多杠杆绑同一 commit。  
5. **否决坏杠杆**：无稳定正 Δ、伤速率、毁同构、只靠诊断臂涨分 → 丢弃 / 回滚。

### 1.3 原则二：不伤主 agent 速率与交互逻辑（R1–R5）

| 红线 | 含义 | 常见违规 |
|------|------|----------|
| **R1** | 不挡 `turn.accepted` / 不拖 TTFB | Turn 启动前同步检索或重初始化 |
| **R2** | 首 token 前不加同步模型调用 | 改写 query / 是否该搜再问一轮 LLM |
| **R3** | 热路径同步 CPU 仅毫秒级 | 默认 CE、重 tokenizer、大模型 rerank |
| **R4** | 重活异步 / 离线 / 用户触发 | 查询路径同步重建索引、全库重嵌 |
| **R5** | 可测才合并 | 无单测/无延迟对照的「感觉更快」 |

**交互逻辑底线**：不改 `AgentEngine` while；不强制每轮检索；不为评测留 official 专用质量分支。质量优先进 Index plane（Turn 外）与静态契约/文案。

**一票否决**：bench 分涨但伤 R1–R5 / 改 while / 强制搜 → **不算成功，不得入库，应回滚。**

### 1.4 两轨判定

```text
分桶优先序：no_search → query_drift → search_cap → weak_hits → ok
```

| 轨 | 看什么 | 能否入库 |
|----|--------|----------|
| 行为桶 | no_search / query_drift / search_cap / weak_hits / ok | 否（归因用） |
| 宏 IR / F1 | nDCG@k · Recall · agent_f1/EM | **仅同协议 free；全量锚或明确锚点档才谈入库** |

---

## 2. 统一门禁与停机规则（必须遵守）

### 2.1 门禁 1–7

1. **单刀单 commit**；卡片填全（加热层 / 改动点 / R1–R5 / 分桶预期 / free 验收 / 非目标）。  
2. **过 R1–R5** + 不改 while + 不强制搜/读 + 无评测专用质量分支。  
3. **free N≥2**；冒烟**只用于去留**，不 `update-baseline`。  
4. **入库仅限**：同协议全量锚 + 稳定正 Δ + 叙事=「工程变好的间接证明」。  
5. N≥2 **无稳定正 Δ → 丢刀/回滚**；禁止 forced/oracle/Index 网格洗白。  
6. **观测先于改动**。  
7. **消融对称性**：「留着」与「新加」同权，做减法同等合法。

### 2.2 EVAL-6 · 停机线（已触发 2/2）

```text
① 每把加法契约刀开工前声明唯一「主观测位」（子桶 / 行为 / 宏分，三选一）
② 记停机计数当且仅当 N≥2 后主观测位与宏分配对均无稳定 Δ
③ 消融 / 观测 / 基建 / 吞吐刀不计入停机线
连续两个批次的加法契约刀全部记停机计数 → 停开新契约刀，边际投入转全量锚与结构刀
```

| 票 | 主观测位 | 结果 | 停机计数 |
|----|----------|------|----------|
| RET-9 互补词面 | weak_hits 收窄 | 未收窄 + 宏分无正 Δ；**已回滚** | +1 |
| CTX-8 证据先行 | wrong_answer 收窄 | 10→11，无正 Δ；文案**保留**、不记宏分胜 | +1 → **2/2** |

**现行效力**：禁止再立项任何新的加法契约/文案刀。

### 2.3 EVAL-7 · 效应量门（持续生效）

```text
① 预期宏分效应 ≥ 2× EVAL-5 噪声带（现 ≈±1.1pp → 门槛 ≈2.2pp）→ 才有资格单刀 N≥2 冒烟
② 达不到但有明确子桶/行为测位 → 只允许子桶证据验收（不占宏分叙事、不单独跑分）
③ 两者都没有 → 不开刀
配套：每个含改动刀的批次必须至少有一把结构刀（RET-4/11/PROD-1；上下文组装层刀已由 CTX-13 否决）在推进中
       （离线选型、重嵌、标注都算推进）；否则该批只许观测/消融/全量锚
```

### 2.4 终态四问（§11.6 · 收束标准）

| # | 问 | 当前状态 | 剩余动作 |
|---|----|----------|----------|
| 1 | 每层有存在证据（或已消融移除） | promote 已默认关；hint 已修；呈现层已收 | **two-level → RET-18** |
| 2 | 每败可归因 | 检索主归因已闭环；上下文 **CTX-13 + 残余细拆已书面**（尺子近对 / 定位 / 真错；组装层决定不修；**不归咎单模型**） | RET-4 后检索残余书面归因 |
| 3 | 温度计可信 | EVAL 配对 ✓；D-1 接受 writing-RAG；**EVAL-8 尺子 v2 已切码 + 双锚复算**（§7.9） | **REP-3 全量锚未入库**（须用 v2 尺子） |
| 4 | 有停机线 | **2/2 已触发** | 遵守：停开加法契约 |

诚实带（对照非 KPI）：检索冒烟终态 **0.46–0.50**（须 RET-4/11）；上下文 F1 **v1 诚实带 ≈0.41**；**v2 复算读数 ≈0.52–0.54**（双锚实测；**口径修正，禁止叙述为涨分**）。narrativeqa v2 仍低（≈0.32）：**承认题型局限，不为刷分开刀、不换模背锅**。CTX-16 / 定位面：**门槛未过 → 关题**（§7.9）。

### 2.5 不做清单（并集 · 完整保留）

**通用**

- 不以抬 bench 分为目的；不把 forced/L0 涨分写进主栏。  
- 不在 20q **单次**噪声上 `update-baseline`；全量前后对照成立前禁止入库。  
- 不假设回滚后 IR 应回到历史峰 0.434。  
- 不同时上 RET-4 与 RET-11 于同一影子索引；CTX-6/14/15 已降级不开（无需同 commit 约束）。  
- 无查询路径同步 LLM（HyDE / 改写 / LLM rerank）。  
- 停机线后**不再立项新加法契约/文案刀**。  
- 不把 RET-4 L0 选型数字写入 SCORECARD / free 主栏。  
- 不因「多轮了还没大涨」放宽入库门禁或改判分口径。（EVAL-8 非此列：立项依据是代码审计发现尺子偏离官方参考实现，且对标同时收紧 EM；判据见 §7.9 相容性表。）

**检索**

- 不开 BEIR 切块刀；不做查询侧同义词扩展；不改融合公式「顺手修」。  
- qrels / 官方 query **不进** runtime，也不参与 RET-11 生成。  
- 不为 gold 名次 11–100 开新排序加法；CE 默认关（RET-19 已关闭热路径议题）。  
- 未重嵌只改查询模型；跳过 REP-3 把 L0 +9pp 写入 SCORECARD —— **禁止**。  
- RET-5 / RET-13 **挂起**（RET-13 解挂条件含 RET-9 正 Δ，实质已死）。

**上下文**

- 不改 loop / max_steps 换分；不把 oracle 读完率当验收；不动 LongBench 题面。  
- 不做答案后处理 / 二次 LLM 自验；不改判分刷分。（「刷分」= 按失败样例定制规则；对标官方参考实现的 EVAL-8 属尺子校准，双向对齐、口径版本化，见 §7.9。）  
- CTX-5 / CTX-11 / RET-16 **不开**；**CTX-6 / CTX-14 / CTX-15 不开**（CTX-13 裁决：组装暴露面 < 1/3 wrong_answer）；契约/文案刀维持停机禁令。  
- 不为抬 EM 改判分归一化；不因 EM 下滑回滚 CTX-1/7。  
- 组装层结构刀不采纳：LLM 摘要压缩 / 子 agent 隔离 / todo 复诵契约 / embedding 语义选窗（§7.7 写死）。  
- **不因检索侧阻塞（重嵌等待）强开低置信度上下文刀**；不立项「判分卫生 / 首读选窗 / 破停机线拧文案」为本轮**抬分刀**（§7.7 已评估不立项；其中判分类问题已升级定性为尺子偏差 → 以基建刀 EVAL-8 立项，Δ 不进抬分叙事；首读选窗仅按 §7.9 条件回访）。  
- 不以 free F1≈0.41 单凭断定模型不行；残余含尺子近对，禁止「换模背锅」叙事进主栏。

**PROD-1**

- 禁调参；一旦用于调参立即作废重建；不替代 BEIR 历史链。

---

## 3. 当前运行时栈（事实）

**检索**

- `search_sources` default **limit=30**；excerpt **400**  
- RET-12：top-5 详摘 + 余下单行  
- RET-15-2：相对分 0–100；low_score 阈值 **1.0 raw**  
- **promote 默认 False**（开关保留）  
- **two-level 默认 True**（消融未跑）  
- writing `system.md`：有 hit 禁逛库；prefer limit≥30；verbatim / ≤2 搜；**无** RET-9 互补句  
- soft lexical 缩放：**无**；lexical 经典版开；CE **默认关**；C-3 fusion；protocol **m3**  
- Embed：`make resolve-embedding` → GPU≥8GiB `gte-large@1024`/index **10**，否则 `gte-small@384`/index **9**；MiniLM **非默认**；**查询空间以重嵌完成为准**

**上下文**

- agent `system.md`：CTX-1 Answer format + CTX-7 good/bad + CTX-2b 续读 + CTX-3 grep→read + **CTX-8 证据先行（保留）**  
- `read_file` 截断 hint（CTX-2a）；C-1 读预算（最近 1 次 read 高预算）保留  

**评测 / 基建**

- RET-3/6/10/14 观测；EVAL-1/2/4/5/infra；INFRA-1 summary≤4096；INFRA-2 case 隔离  
- EVAL-6 / EVAL-7 / D-1 规则生效  

**记账锚（配对时必须注明 promote / two-level）**

| 温度计 | 锚 | 备注 |
|--------|-----|------|
| 检索 | promote-off 均值 **≈0.447** | 配对锚；RET-9 回滚后不以 0.453 为锚 |
| 上下文 | excl-infra F1 **v1≈0.41** · **v2≈0.53**（复算） | CTX-9/EVAL-infra 后口径；**EVAL-8 后须注明 scorer 版本**；勿与旧口径裸比 |

---

## 4. 系统立场与操作路径（精简）

### 4.1 产品形态与温度计场景

- 平台 = **一个 AgentEngine while-loop × 多个 ScenarioProfile**。  
- 用户路径：Session → Turn → Runtime loop → 工具 → 流式事件 → 终态。  
- **Free L1 检索温度计默认 scenario = `writing`**（有 `search_sources`）。agent 场景默认**无** `search_sources`——优化 `agent/system.md` **不会**抬 BEIR L1。  
- **D-1（已裁决）**：接受 writing-RAG 为本轮检索温度计目标；agent 注册 search_sources = 另开产品票 + 新温度计。

### 4.2 因果栈（自由 L1 检索 · 当前默认）

```text
语料物化 → 切块 / embed（GTE small|large）/ INDEX_VERSION(9|10) / pgvector
  → writing 自由题面 → search_sources(limit 常 30)
  → hybrid：向量 ∥ BM25 → RRF →（可选）two-level → lexical
  → 分层呈现 + 相对分 → tool_result（行为窗）
  → ranked(path+score) → IR 计分（与 tool_result 截断脱钩）
  → 多搜 first-seen union → nDCG / R@k
```

**高杠杆优先序（平台期内）**：结构 Index/embed（RET-4）> 离线语料增强（RET-11）> 消融无证据层（RET-18）> ~~上下文组装层结构刀~~（CTX-13 已否决）> **禁止**再拧加法契约。

### 4.3 推荐操作路径

```text
# 仓库根；已 make up；已 source .env；BENCH_MODEL_* 可用
make official-bench-run SUITE=retrieval ARM=free LIMIT=20   # 或 Ops 等价
# 配对：official-bench-compare + EVAL-1
# 认可后才：make official-bench-update-baseline   # 本轮明确禁止，直至 REP-3 前后对照
```

---

## 5. 已验收台账（效果标明 · 叙事已收敛）

> 下列票**已执行/已裁决**。只保留状态与效果；完整提案散文见备份稿。  
> 标记：**保留** = 仍在栈；**回滚/默认关** = 已撤出质量路径；**不开** = 从未合入；**离线收** = 无运行时改动。

### 5.1 平台期兑现（相对改刀前）

| 温度计 | 起点 | 当前 | 主要来源 | 性质 |
|--------|------|------|----------|------|
| 检索 nDCG@10 | ≈0.409（`689cfe71`） | ≈**0.447** promote-off | §9 包 limit30 等 | 真实工程改善；**未入库** |
| 上下文 F1 | ≈0.33（CTX-0） | ≈**0.41** excl-infra | 主贡献 CTX-1；CTX-7 verbose↓ | 真实工程改善；**未入库** |
| 行为桶 | drift≈83% | drift≤1 · cap≤3 | 前四轮契约 | 行为近天花板 |
| 排序栈 | 两层无证据加成 | promote **默认关**；hint 已修 | RET-7 / RET-15 | 栈更干净（分数不动是预期） |

### 5.2 检索 · 已收

| ID | 状态 | 效果（一句话） | 关键 run / 产物 |
|----|------|----------------|-----------------|
| Soft lexical 第五刀 | **回滚** | 无稳定 IR 正 Δ | `a6de7860` / `f7fc1b1a`；确认 `689cfe71` |
| Verbatim / ≤2 搜 | **保留** | drift 大降；行为验收过 | 历史峰 `0526901a`≈0.434（非当前硬锚） |
| RET-1 limit→30 | **保留** | §9 包贡献平台；FiQA 仍常 R10≈R100 | 包均值 nDCG **0.449**（`99d729de`/`307ea1d0`） |
| RET-2 / 2b | **保留** | 禁逛库 + excerpt400；与分层呈现同栈 | 打包 |
| RET-3 weak_hits 观测 | **保留** | 立项依据字段 | `99d729de` |
| RET-6 depth_audit | **保留** | `pool_starvation_despite_limit` → 结构杠杆 | `307ea1d0` |
| RET-8 分类 | **离线收** | lexical_miss 为主 → **RET-4 立项充分** | batch5 |
| RET-10 lanes | **保留** | `lanes_fed_relevance` → 不抬 lane-k | `0744546e` |
| RET-12 分层呈现 | **保留 · 不写 IR 胜** | IR `no_stable_delta`；行为正当 | `3c34de88`/`dfe97d37` |
| RET-14 gold_read | **观测收** | FiQA gold absent 主因硬召回 | `3c34de88`/`dfe97d37` |
| RET-15-1/2 | **保留 · 不写 IR 胜** | never_triggers→相对分修复；IR 持平 | `6c87e401` vs `dfe97d37` |
| RET-7 promote | **默认关** | OFF 均值 0.447 vs ON；无正贡献 | OFF `bcdbbb85`/`f92bc610` |
| RET-9 互补词面 | **丢刀回滚** | weak 未收窄；FiQA 全单搜未触发；**停机+1** | `03304987`/`03569f22` |
| RET-17 gold 名次 | **离线收** | absent ~18–20% → 支撑 RET-4 | batch6b / batch14 |
| RET-19 CE 回放 | **离线收 · 关闭议题** | mean Δ **+0.51pp** → **不上热路径 CE** | §14 产物 |
| RET-4 L0+接线 | **选型锁定 · 重嵌未验收** | L0 gte-small macro 0.569 vs MiniLM 0.478（**不进主栏**） | `ret4_selection.json` |
| RET-5 / RET-13 | **挂起** | 解挂条件未满足 / 已死 | — |

### 5.3 上下文 · 已收

| ID | 状态 | 效果（一句话） | 关键 run / 产物 |
|----|------|----------------|-----------------|
| CTX-0 | 基线 | F1≈0.33 | `c8cc1bc1` |
| CTX-1 答短 | **保留** | verbose 16→8 主贡献；F1 抬升主因 | `083eca09` 等 |
| CTX-2a/2b 续读 | **保留**（ABL 后） | 宏分无害；关后 gave_up↑ | ABL `b84f26c0` vs `9998d9eb` |
| CTX-3 grep→read | **保留** | narrativeqa 仍低（能力墙） | 打包 |
| CTX-4 解剖 | **离线收** | (a)<1/3 → **不开 CTX-5** | batch5 |
| CTX-5 | **不开** | — | — |
| CTX-7 good/bad | **保留 · 不记 EM/F1 胜** | verbose 11→**4** 稳定；EM↓ | `13647cb0`/`61624e34` |
| CTX-9 + 探针 | **保留** | abandoned vs wrong_answer 分流 | `1707135c` |
| CTX-10 解剖 | **离线收** | (i)+(iv)=5/9 → CTX-8 预期 full；(ii)=1 → **不开 CTX-11** | on `1707135c` |
| CTX-11 / RET-16 | **不开** | 门槛未过 | — |
| CTX-12 EM 解剖 | **离线收** | gamma_paraphrase → 支持 CTX-8 wording | batch6b |
| CTX-8 证据先行 | **保留 · 停机第2票 · 不记宏分胜** | wrong_answer 无正 Δ；F1≈0.41 噪声带 | 见下表 |
| CTX-13 折叠丢证审计 | **离线收 · 暴露面=0** | trunc=0 · fold=0 · pointer=0 → **CTX-14/15/6 不开** | `batch15/ctx13_*` · 主跑 `b5d24c9e`（`fdd03298` 本机缺产物） |
| CTX-13 残余细拆 | **离线收 · 停手** | 尺子近对 / 定位 / 真错三分；候选抬分刀均非高置信 → **不立项** | §7.7「残余细拆与停手裁决」 |
| CTX-6 / CTX-14 / CTX-15 | **不开** | CTX-13 门槛未过 | §7.7 |

**CTX-8 free N≥2（干净）**

| 轮 | run_id | F1 | EM | ok | wrong_answer | infra |
|----|--------|-----|-----|-----|--------------|-------|
| 1 | `fdd03298` / Ops `13a28e28` | 0.428 | 0.200 | 40 | 10 | 0 |
| 2 | `b5d24c9e-…` | 0.411 | 0.183 | 38 | 11 | 0 |

作废：`39dcede1`（inflight）**不入对照**。裁决：双无 Δ → 停机 2/2；文案保留；禁止 `update-baseline`。

### 5.4 评测基建 · 已收

| ID | 状态 | 效果 |
|----|------|------|
| EVAL-1/2/3 | **生效** | 配对 CI / sample_policy / token 台账 |
| EVAL-4/5 | **生效** | highlights；噪声带 ≈±1.1pp 起 |
| EVAL-infra | **生效** | infra_channel 剔主宏分 |
| EVAL-6/7 | **生效** | 停机线 2/2；效应量门 |
| **EVAL-8** | **已执行 · 口径 v2 切码** | 双锚复算 `batch16`；F1 +10.4/+12.0pp（校准）；CTX-16 关题；INFRA-3 落盘字段已接 |
| INFRA-1/2 | **部署** | summary 截断；case 隔离（整跑不再一票否决） |
| **INFRA-3** | **已接**（随 EVAL-8） | process/l2 增记 pred/golds/norm；manifest `agent_f1_scorer` |
| REP-1/2 | **完成** | §9 包认包（检索）；上下文旧口径均值 0.391 |
| ABL-1 | **完成** | 保留 CTX-2 |
| D-1 | **裁决生效** | writing-RAG = 本轮检索温度计目标 |

### 5.5 排序栈证据台账（条 1 · RET-18 后回填第 4 行）

| 层 | 存在证据 | 裁决 |
|----|----------|------|
| hybrid 双车道 | C-3 弱证据 + 生产常识 | 保留 · 决定不再消融 |
| RRF k=60 | C-3 打平 | 保留默认 |
| lexical rerank（经典） | soft 第五刀回滚史 | 保留 |
| **two-level doc 加成** | **无单独证据** | **→ RET-18** |
| excerpt-promote | RET-7 N≥2 无正贡献 | **已默认关** |
| low_score hint | RET-15 审计+修复 | 已修 |
| 呈现层 | RET-12/15-2 IR 持平、行为正当 | 保留（不写 IR 叙事） |
| 热路径 CE | RET-19 +0.51pp | **关闭议题** |

---

## 6. 残余缺口（工程，不是「差几分」）

| 缺口 | 证据 | 下一步 |
|------|------|--------|
| FiQA / 多库 gold **absent_from_ranked** | RET-6/8/10/14/17 | **RET-4**（主杠杆） |
| weak_hits · lexical_miss | RET-8 | RET-4 → 视余量 **RET-11(b)** |
| two-level 无存在证据 | 台账空行 | **RET-18** |
| 全量锚未入库 | 门禁 4 / 终态条 3 | **REP-3** |
| wrong_answer 残余 | CTX-8 无正 Δ；CTX-13 组装暴露面=0；EVAL-8 后尺子近对部分消解（b5 近对 6 题；CTX-13 WA 中 2 题 v2 F1>0.5） | 产品侧停手；残余仍以定位 + 真错为主；**不开新契约** |
| **上下文尺子偏离官方口径** | EVAL-8 双锚：v1→v2 F1 +10.4/+12.0pp；EM 双向（+8.3 / −6.5pp） | **已闭合**（v2 切码 + batch16 产物）；旧锚标 v1 |
| 组装层丢证暴露面 | CTX-13：三分桶合计 **0** / WA（`b5d24c9e` + 佐证 `1707135c`） | **已闭合**；CTX-14/15/6 降级不开 |
| BEIR≠产品分布 | 自知 + RET-4 污染条款 | **PROD-1** 迁移率 |

---

## 7. 未执行 / 未验证票（全文保留）

> 严格按序。检索嵌库/模型加载完成前 **暂缓 RET-18**。  
> 上下文：**CTX-13 已收**；组装层结构刀候选包按裁决**全部降级不开**；**EVAL-8 已收**（v2 切码）；CTX-16/定位面门槛未过→**关题**；产品侧继续停手。

### 7.1 执行序

| 序 | 批次 | 内容 | 完成判据 | 状态 |
|----|------|------|----------|------|
| 1 | B | CTX-8 free 干净 N≥2 | 停机线判定 | **✓ 已收 · 2/2** |
| 2 | B′ | **CTX-13** 折叠丢证审计（离线观测） | 三分桶暴露面回填 §7.7 裁决行 | **✓ 已收 · 暴露面=0** |
| 3 | B′ | 依 CTX-13 裁决开组装层结构刀（CTX-14 / CTX-15 / CTX-6） | — | **不开**（门槛未过） |
| 3.5 | B′ | **EVAL-8** 尺子官方对标（离线复算 → 口径 v2）+ INFRA-3 落盘 | 双锚复算对照 + §7.7 残余表按 v2 重写 + §3 锚更新 | **✓ 已收**（`batch16/eval8_rescore.*` · 代码已切 v2） |
| 3.6 | B′ | CTX-16 交付面 / 定位面回访 | EVAL-8 复算中的稀释质量 / never_retrieved 质量 ≥ 2.2pp | **关题**（稀释 potential 0.00/2.08pp < 2.2；定位面不立项） |
| 4 | B | **RET-18** two-level 消融 N≥2 | 回填 §5.5 台账第 4 行 | **暂缓**（嵌库就绪后） |
| 5 | C | **REP-3** 全量锚 | 栈冻结 + 两套件落库 | **未执行**（硬前置） |
| 6 | D | **RET-4** bake+全库重嵌 → free 20q N≥2 → 全量后锚 | FiQA absent 收窄 + 宏分正 Δ | **接线 ✓ · 重嵌进行中/待验收** |
| 7 | E | **RET-11(b)**（视 D 余量） | N≥2；分影子 | **视 D 余量**；rerank 已由 RET-19 关闭 |
| 8 | F | **PROD-1** 首跑 + 终态四问书面作答 | 完备收束 | **草稿 · 未首跑** |

### 7.2 RET-18 · two-level 消融（减法 · 不计停机线）

```text
加热层: 融合排序（做减法；RET-7 同款）
改动点: two-level 已有开关，默认 on；消融 = RETRIEVAL_TWO_LEVEL_ENABLED=false
        → recreate runtime → free 20q N≥2
预期用户路径变化: 关闭时返回序回归 hybrid+RRF+lexical（+呈现层），少一层无单独证据的加成与 0.3s 超时预算
R1–R5: 通过——关闭减计算；开关零成本
分桶预期: OFF 后 weak↑/nDCG↓ → 保留并记正贡献；无差异 → 默认关（简化栈）
free 验收: N≥2 + EVAL-1；锚 = promote=off · RET-9 已回滚 · 注明 two-level 状态
非目标: 不与契约刀同批；不计入停机线
诚实预期: 两种结果都是收束——无Δ默认关 / 掉分则保留有证据层
完成判据: 回填 §5.5 排序栈台账「two-level」行
```

### 7.3 REP-3 · 全量锚（入库唯一合法前锚）

| 项 | 规定 |
|----|------|
| 时点 | **RET-18 消融裁决之后**、结构刀验收对照之前（硬前置） |
| 栈冻结 | 锚跑窗口内**禁止任何部署**；manifest 记配置指纹 + promote / two-level 终态 |
| 范围 | 检索：全量 qrels（~1.3k Turn）× free × m3；上下文：全量 LongBench（excl-infra 已过 ≥0.40，随跑） |
| 用途 | 结构刀入库级前锚；刀后再全量 = 前后对照；门禁 4 / 终态条 3 的唯一合法路径 |
| 纪律 | 全量入库 ≠ 给冒烟背书；锚数值**不回填**冒烟对照表 |

### 7.4 RET-4 · Embed 换代（主菜 · 重嵌验收未完成）

**已完成**：L0 选型；`make resolve-embedding`；MiniLM 移出默认；index 9=small / 10=large；CUDA 探测。

**部署策略（锁定）**

- `EMBEDDING_PROFILE=auto`：VRAM≥8GiB → `thenlper/gte-large@1024` / INDEX **10**；否则 `thenlper/gte-small@384` / INDEX **9**  
- 强制：`EMBEDDING_PROFILE=small|large` 或 `EMBEDDING_FORCE_MODEL=…`  
- MiniLM **不再是生产默认**

**执行细化（v2 · 立项不变）**

```text
修订 1: 优先 384 维现代模型（同维替换 = INDEX bump + 离线重嵌；ANN 结构零改）。
        768 维仅当 384 候选 N≥2 后仍不达预期才另立票。本机策略已扩到 GPU→large。
修订 2: 影子重嵌前 L0 选型（✓ 已做；数字不进主栏）。
修订 3: BEIR Δ 可能高估产品迁移 → PROD-1 保留意见必须入入库叙事。
执行序: 离线选型(✓) → bake + 全库重嵌(R4) → 配置切新 INDEX
        → free 20q N≥2 + EVAL-1 → 分库 NFCorpus/FiQA + RET-14 gold_read/absent 同 case 对照
        → 正 Δ → 全量后锚 → 入库裁决
回滚: 配置切回旧 INDEX，零重建
诚实预期: 冒烟 0.447 → 0.47–0.51（只许下修）；FiQA absent 显著下降 = 主验收位（比宏分更硬）
禁止: 未重嵌只改查询模型；与 RET-11 同影子；L0 数字进 SCORECARD
```

**L0 证据（仅选型 · 不入主栏）** · run 切片 `03569f22` · `eval/reports/official/batch14/ret4_selection.json`

| 模型 | SciFact | NFCorpus | FiQA | macro |
|------|---------|----------|------|-------|
| MiniLM-L6-v2 | 0.645 | 0.386 | 0.404 | 0.478 |
| bge-small-en-v1.5 | 0.759 | 0.412 | 0.465 | 0.545 |
| **gte-small（锁定档）** | **0.793** | **0.482** | 0.432 | **0.569** |

三模型 FiQA **absent@100 均为 3** —— 不得用 L0 表宣称「absent 已灭」。

**CPU-only 换模验收清单**

```text
make resolve-embedding   # 无 GPU → gte-small@384
cat deploy/embedding.auto.env
make up / make up-runtime
验收: 容器 EMBEDDING_MODEL 匹配；.baked_embedding_model stamp 匹配；search_sources 非空；20q 冒烟记 run_id（不入库）
```

### 7.5 RET-11(b) · 离线伪查询扩 BM25（视 D 余量 · 分影子）

```text
加热层: Index plane（Turn 外离线重活，R4）
改动点: 优先变体 (b) doc2query——每 doc 离线生成 3~5 伪查询，仅拼入 BM25 字段；
        INDEX_VERSION bump + 影子索引；查询路径零改动
        变体 (a) contextual header：待 RET-4 后按剩余 absent 占比决定
预期用户路径变化: lexical_miss 类 query 的 BM25 车道可救；对产品树状语料通用
R1–R5 / while: 通过——全部离线；配置切回即回滚
分桶预期: weak_hits 中 lexical_miss 收窄（RET-8 同 case 前后对照）
free 验收: N≥2 分库 FiQA/NFCorpus + weak_hits；诚实 +0.02~0.05
非目标: 不在查询路径做 HyDE；严禁用 qrels/官方 query 参与生成
与 RET-4: 正交可叠加；必须分影子分别 N≥2
```

### 7.6 CTX-6 · 多跳读预算 K=2（**不开** · CTX-13 裁决 fold_budget_miss=0）

```text
加热层: ContextEngine 组装预算；不改 while 序
改动点: 最近 K=2 次 read 高预算（如 16k+16k 或 24k+8k）；更早仍 4k；总预算有界
开刀门槛: CTX-13 审计中 fold_budget_miss 占优 —— **未满足（=0）→ 不开**
状态: 降级不开；卡片保留备查
```

### 7.7 上下文组装层结构刀候选包（CTX-13 **已收** · CTX-14/15 **不开**）

**立项背景**：五轮契约/文案刀后 F1 停在 ≈0.41 噪声带，停机线 2/2 判定「指令工程」边际归零。曾假设剩余弹性在组装层信息保真度；**CTX-13 实测否决该假设**（暴露面=0）。后续残余细拆进一步表明：失败主因不是 fold/trunc 丢证，也不是「单模型不行」，而是**尺子近对 + 定位 + 少数真错**的混合物（见下节）。

**成熟 agent 惯例 → 本仓映射（采纳/禁止一次写死）**

| 成熟 agent 惯例 | 思想 | 本仓可采纳形态 | 被本仓红线禁止的形态 |
|----|----|----|----|
| 可恢复压缩（丢内容不丢指针） | 压缩掉的材料必须留精确回读入口 | **CTX-15**（门槛未过 · 不开） | LLM 摘要式 compaction（新增模型调用） |
| 任务相关保留（context curation） | 截断按「与任务的相关性」而非「文件头部」 | **CTX-14**（门槛未过 · 不开） | embedding 语义选窗 |
| 预算形状（近因材料保高预算） | 近因 × 相关性双维分配 | **CTX-6**（门槛未过 · 不开） | 无限抬预算 / 为题集调 K |
| 子 agent 上下文隔离 | 脏活隔离在干净窗口外 | ——不采纳 | 改 while / 多 loop |
| Recitation / todo 复诵 | 目标钉在近因注意力里 | ——不采纳 | 新加法契约（停机线 2/2） |
| 跨 session 记忆 | 长期偏好沉淀 | ——不采纳（与温度计无关） | — |

#### CTX-13 · 折叠丢证审计（观测 · **已收** · 不计停机线）

```text
加热层: 无（纯离线轨迹分析）
实现: scripts/official_bench/ctx13_fold_evidence_audit.py
       单测 scripts/tests/test_ctx13_fold_evidence_audit.py
产物: eval/reports/official/batch15/ctx13_summary.{json,md} · ctx13_cases.json
主跑: b5d24c9e（CTX-8 N≥2 第 2 轮；本机有 envelopes + workspace）
缺产物: fdd03298 / Ops 13a28e28 —— 本机无 run 目录 / 无 envelopes；未强行计入
佐证: 1707135c（CTX-9 锚，同协议 free；暴露面同样为 0）
口径: case_id 与 Ops runner 对齐（enumerate(limit_rows_per_task) 全局 idx）；
      passage 优先 small_slice context；可见窗=末步 model_request_envelopes
```

**裁决行（已回填）**：`trunc_window_miss = 0 · fold_budget_miss = 0 · pointer_lost = 0 → 首刀 = none_capability_wall`

| 跑 | n (WA+abandoned) | not_assembly_loss | never_retrieved | gold_not_localizable | 组装三分桶 |
|----|------------------:|------------------:|----------------:|---------------------:|-----------|
| `b5d24c9e` | 15 | 11 | 3 | 1 | **0** |
| `1707135c`（佐证） | 11 | 9 | 2 | 0 | **0** |
| 合计 | 26 | 20 | 5 | 1 | **0** |

- 组装暴露面 / wrong_answer = **0/20 < 1/3** → 三把结构刀全部降级「不开」。  
- 「量出来修不动」= 上下文组装层完备收束（终态条 2）。  
- **注意**：`not_assembly_loss` **≠**「模型太弱」——见下节细拆。

#### 残余细拆与停手裁决（2026-08-05）

对主跑 `b5d24c9e` 的 WA+abandoned 轨迹再读 pred / gold / 可见窗后，把 CTX-13 的粗桶拆成三分（**不改代码、不重跑冒烟**）：

| 残余类 | 含义 | 例（`b5d24c9e`） | 工程含义 |
|--------|------|------------------|----------|
| **尺子近对** | 行为上接近正确，F1/EM 因标点/长短/别名未认 | `watt`↔`Watt, one joule per second.`；`flexibility`↔`Flexibility.`；`Yes`↔长 Yes 句；`Pierre Grassou.`↔`Grassou`；`American`↔`She is an American.` | **不为抬分改判分**（既有禁令）；禁止用 free≈0.41 断定模型不行 |
| **定位 / never_retrieved** | 证据段从未进读窗或读偏 | hotpot 类 Betty Cohen / Bob Dylan 等；低 coverage 读窗 | 非 fold/trunc；停机线后**不开新契约**补救 |
| **真推理/多跳错** | 材料在窗仍答错（表误读、实体张冠李戴等） | 如首场比分误读战绩行；Sun↔Jupiter 类 | 少数才是模型/题型难度；**不换模背锅进主栏** |

**候选抬分方向已评估 → 均不立项（非高置信）**

| 候选 | 预期 | 为何不立项 |
|------|------|------------|
| A 判分卫生（去标点等） | 或救数题近对 | 效应常落噪声带（≈±1.1pp）；与「不为抬分改判分」冲突 |
| B 首读选窗（工具层词面） | 最多打 never_retrieved 少数题 | 宏分未必过 EVAL-7；不保证多跳/叙事 |
| C 再观测 | 0 分 | 归因已够用 |
| D 破停机线拧 `system.md` | 已证无稳定 Δ | 停机线 2/2 |

**停手裁决**：现行门禁下上下文**无明确会抬分的下一刀**；工程停手。下一工程火力只在检索嵌库就绪后的 **RET-18 → REP-3 → RET-4**。若日后要换更强模型或改尺子，须**另开产品/温度计票**，不进本轮 free 主栏优化叙事。

#### CTX-14 · 相关性选窗截断（**不开**）

```text
开刀门槛: CTX-13 trunc_window_miss 占优 —— 未满足（=0）→ 不开
状态: 降级不开；卡片保留备查（原提案见备份稿 / 本文件历史）
```

#### CTX-15 · 可恢复折叠残根（**不开**）

```text
开刀门槛: CTX-13 pointer_lost 占优 —— 未满足（=0）→ 不开
状态: 降级不开；卡片保留备查
```

**候选包纪律（事后）**

- CTX-13 为观测刀，不占停机线、不承诺分数；裁决已执行。  
- 禁止借「成熟 agent 惯例」在暴露面=0 时强开 CTX-14/15/6。  
- **明确不采纳（写死）**：LLM 摘要压缩；子 agent / 多 loop；todo/recitation 契约；跨 session 记忆；embedding 语义选窗。

### 7.8 PROD-1 · 产品镜像小套件（草稿 · 未首跑）

```text
加热层: 温度计本体（第二套件；不动 BEIR 历史可比性）
改动点: 20–30 题产品形状检索题（树状 seed + writing 真实需求 + 人工 gold）；
        与 BEIR L1 同 free 协议；题面与 gold 一次冻结、版本化
路径: eval/official/prod1/ · 现 24 题 · frozen=false · 禁调参
生效标志: RET-4/11 后复验 BEIR→PROD 迁移率
        （BEIR 涨而 PROD 不涨 → 污染警报必须入入库叙事）
非目标: 不替代 BEIR；不用 LLM 生成题面；宁小而真
排期: F 批；可与重嵌并行构建
```

### 7.9 上下文第二审视：测量面与交付面（2026-08-05 增补 · 新证据）

> **动机**：五轮上下文刀（CTX-1/2/3/7/8）全部作用于**行为面**（prompt 契约），而行为桶早已近天花板（drift≤1 · verbose=4）——这就是「多轮优化效果不明显」的结构性原因：剩余 F1 损失根本不在契约刀能触及的平面上。本节基于**代码审计 + 离线复算**（非分数焦虑）提出测量面/交付面立项；检索嵌库阻塞期内**唯一可立即执行**。

**成熟 agent / 评测组织惯例 → 本仓缺口映射（与 §7.7 表正交，不重复）**

| 惯例 | 本仓现状 | 缺口（已实测） | 对应票 |
|------|----------|----------|--------|
| **尺子先于刀**：自实现指标必须与官方参考实现 parity | `_normalize` 仅小写+空白折叠（`context_run.py` L21–22） | 缺官方 LongBench `qa_f1_score` 的去标点、去冠词；EM 含非官方「gold⊆pred 记 1」宽容条款 | **EVAL-8** |
| 交付物 = 机器可读字段，不是散文 | pred = 整条终态消息（`official_agent_path.py` L1528 `final_assistant_text`） | 答案被句式稀释时精确率被动摊薄 | **CTX-16**（门槛制） |
| 每题 pred/gold 落盘可审计 | `process.jsonl` 只有 `answer_len` | 尺子审计需 envelope 考古 | **INFRA-3** |
| 工具工效：命中自带上下文 | grep→read 两跳定位 | never_retrieved 3–5/26 | 定位面**条件回访**（P3） |

**新证据：现行尺子偏离官方口径（2026-08-05 离线复算）**

对 §7.7「尺子近对」桶已记录的 5 例，用仓库现行 `score_prediction` 与官方 LongBench `qa_f1_score` 归一化（lower + 去标点 + 去冠词 + 空白折叠）并排复算：

| pred（§7.7 表记） | gold（`ctx13_cases.json`） | 现行 F1 | 官方口径 F1 |
|------|------|--------:|------------:|
| `watt` | `Watt, one joule per second.` | **0.000** | 0.333 |
| `flexibility` | `Flexibility.` | **0.000** | **1.000** |
| `Pierre Grassou.` | `Grassou` | **0.000** | 0.667 |
| `American` | `She is an American.` | **0.000** | 0.500 |
| `Yes` | `Yes, individual molecules of…` | **0.000** | 0.133 |

- 现行 tokenization 下 `grassou.`≠`grassou`，一个尾标点即 F1=0——「尺子近对」实为**尺子 bug**，非产品失败，也非模型失败。  
- 仅此 5 例 = b5d24c9e 宏分 **+4.4pp 下界**（2.633/60），**超 EVAL-7 门（2.2pp）两倍**；ok 桶长答案的去冠词/去标点部分分未计入。  
- **归因被污染**：CTX-13 `not_assembly_loss`=11 中至少 5 例应移出「产品残余」；§7.7 残余三分表须按新口径重写后才可信。  
- 对称事实：现行 EM 的子串条款**比官方宽**——对标是双向的，EM 预期**下降**；这是「校准而非刷分」的自证。

#### EVAL-8 · 尺子官方对标（评测基建刀 · **已执行 2026-08-05** · 不计停机线）

```text
类别: EVAL 系基建刀——非契约/文案刀（EVAL-6 ③ 明确不计停机线）；非「为抬分改判分」
立项判据: 与官方参考实现逐条 diff（F1 对标 LongBench qa_f1_score 的 normalize_answer；
          EM 本为自加指标，对标 SQuAD EM 定义即 normalize 后全等，并版本化）
改动点: score_prediction 归一化对齐官方（lower + 去标点 + 去冠词 + 空白折叠）；
        EM 收紧删除子串宽容条款——宽严同时采纳，双向对齐
        INFRA-3: l2/process 落盘 pred/golds/pred_norm/gold_norms；result.agent_f1_scorer=v2
纪律: ① 只采纳官方参考实现中存在的变换；禁止自创规则、禁止按失败样例挑规则
      ② 先离线复算后切口径：manifest pred + LongBench gold（fdd03298 本机缺产物，已标注跳过）
      ③ 口径版本化 agent_f1@v2；新旧数字并记；旧口径锚 ≈0.41 不与新口径裸比
      ④ Δ 是口径修正，不进「工程变好」叙事、不记宏分胜、不给任何刀背书
      ⑤ EM 双向变化照常采纳（去标点可抬 EM；删子串可降 EM）
产物: eval/reports/official/batch16/eval8_rescore.{json,md} · eval8_near_miss_fixture.json
      + scripts/tests/test_eval8_scorer.py
完成判据: ✓ v2 切码；✓ 双锚复算；✓ CTX-16/定位面门槛裁决；此后对照注明口径版本
非目标: 不为特定失败样例定制规则；不动 nDCG/检索尺；不 update-baseline
```

**双锚复算结果（已收）**

| run | v1 F1 | v2 F1 | ΔF1 | v1 EM | v2 EM | ΔEM | near_miss |
|-----|------:|------:|----:|------:|------:|----:|----------:|
| `b5d24c9e` | 0.411 | **0.516** | **+10.43pp** | 0.183 | 0.267 | +8.33pp | 6 |
| `1707135c` | 0.424 | **0.544** | **+12.01pp** | 0.331 | 0.267 | −6.48pp | 6 |

- v1 宏分与 recorded 逐锚一致（复算可信）。  
- 均值 ΔF1 **+11.2pp** ≫ EVAL-7 门；属**校准**，禁止写入工程胜 / SCORECARD。  
- CTX-13 WA 重看：15 题中仅 2 题因尺子升至 v2 F1>0.5 可移出硬残余；其余仍为定位/真错。  
- **CTX-16**：稀释 potential 0.00 / 2.08pp < 2.2 → **关题**。  
- **定位面**：never_retrieved 仍在硬残余但宏分效应未达立项门 → **不立项**。

#### INFRA-3 · 逐题 pred/gold 落盘（**已接** · 随 EVAL-8）

`l2` / `process.jsonl` 增记 `pred` · `golds` · `pred_norm` · `gold_norms` · `scorer`；manifest case 同步；`result.agent_f1_scorer=v2`。无运行时热路径改动。

#### CTX-16 · 终态交付面（**关题** · 门槛未过）

```text
门槛复算: b5 diluted_n=0 (0.00pp)；1707 diluted_n=2 (≈2.08pp) → 均 < 2.2pp
裁决: 不开 · 不回访（除非未来锚上稀释质量稳定 ≥2.2pp 另立卡）
```

#### 定位面 · 条件回访（**关题** · 维持不立项）

EVAL-8 后 never_retrieved 仍为部分 WA 主因，但无可过 EVAL-7 的宏分/子桶立项证据。维持停手；若日后另开工具面工效票须单独卡片 + 子桶验收。

#### 与既有裁决的相容性（一次写死，防止误读为破戒）

| 既有禁令 | 为何不冲突 |
|----------|-----------|
| 停机线 2/2「停开加法契约刀」 | EVAL-8/INFRA-3 = 基建刀，EVAL-6 ③ 明确不计；CTX-16/定位面 = 结构刀且门槛制 |
| 「不为抬分改判分」（§2.5） | 该禁令防的是**按失败样例定制规则**；EVAL-8 只采纳官方参考实现、双向对齐（EM 反而收紧）、口径版本化、Δ 不进工程叙事——是终态条 3「温度计可信」的欠账 |
| §7.7 候选 A「判分卫生」不立项 | 候选 A 当时按「或救数题、效应常落噪声带」评估；现已实测下界 +4.4pp > 2×门槛，且定性从「卫生」升级为「偏离官方参考实现」——立项判据变了，不是复议旧案 |
| 「不因多轮没大涨放宽口径」（§2.5） | 触发源是代码审计发现偏差，非分数焦虑；且对标同时**收紧** EM |
| 「上下文工程停手」 | 维持——EVAL-8 修的是温度计不是产品；产品侧停手裁决不变，除非 CTX-16/定位面过门槛 |

**诚实预期（本节 · 已兑现）**：双锚 v2 F1 ≈0.52–0.54，为**同一工程的更准读数**，不是工程改善，禁止叙述为「涨分」。CTX-16/定位面已按门槛关题。归因上尺子近对部分消解，硬残余仍以定位 + 真错为主——产品侧停手裁决维持。

### 7.10 诚实预期（结构刀阶段）

- 检索主分弹性全押 **RET-4**：冒烟带 0.47–0.51（只许下修）；FiQA absent 收窄硬于宏分。  
- 上下文：**CTX-13 已收 · 暴露面=0**；**EVAL-8 已收** → 产品侧不承诺工程抬分；v1 锚 ≈0.41 / **v2 读数 ≈0.53**（校准）；CTX-16/定位面**关题**。  
- RET-4 后宏分仍平 → 按终态条 2 把检索残余书面归因到 {qrels 结构 / 能力墙}，brief 仍可完备收束——**「证明了修不动」与「修好了」都是完备终态**。  
- PROD-1 迁移率显著低于 BEIR Δ → 如实写入入库叙事，作为下一轮产品语料专项开题，不是本轮失败。  
- RET-18 / REP-3 / 观测刀（含已收 CTX-13 / EVAL-8）**不承诺分数**；EVAL-8 Δ 尤其禁止记宏分胜。

---

## 8. 一页决策树

```text
拟议改动
  ├─ 伤 R1–R5 / while / 强制搜 / 评测专用分支？ → 否决
  ├─ 加法契约/文案？ → 停机线 2/2 已触发 → 否决
  ├─ 上下文新抬分刀（组装层 / 判分卫生 / 首读选窗 / …）？ → §7.7 已否决或不立项 → 否决
  │    （例外：EVAL-8 尺子官方对标 = 基建刀非抬分刀，走 §7.9 判据与纪律）
  ├─ 过 EVAL-7 效应量门？ → 否 → 不开或仅子桶顺风观测
  ├─ 门禁 6/7（观测先于改动 · 消融对称）？ → 否 → 先补观测/消融
  └─ 通过 → free N≥2 + EVAL-1
        ├─ 结构刀 + 全量前后对照成立 → 才谈 compare / update-baseline
        ├─ 无稳定正 Δ → 丢刀 / 回滚
        └─ 仅 L0 / forced ↑ → 未验收；最多当假说，不进主栏
```

**当前唯一正确日历**：
检索——嵌库就绪 → **RET-18** → **REP-3**（须 `agent_f1@v2`）→ **RET-4 验收** → 视余量 RET-11(b)；
上下文——**产品侧工程停手**；**EVAL-8 已收**（v2 切码 · CTX-16/定位面关题）；
收束——PROD-1 首跑 + 终态四问书面作答（终态条 3：EVAL-8 ✓ · REP-3 待补）。
