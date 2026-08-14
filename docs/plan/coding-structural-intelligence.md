# 方案：Coding 结构智能（LSP / AST）

> **状态（2026-08-15）**：Wave 1–4 代码已落地 · 工作区 AST（A6）已接线 · P15 确认坐标 Bug 已修  
> **姊妹**：[工作区异步 AST](agent-workspace-ast-index.md)（冷启 / 快照 / wait-ready / grammar bake）  
> **正文**：[工具与上下文](../core/tools-and-context.md) 图 3  
> **非范围**：writing/intel RAG；不以资料检索充当 Agent Locate  

本文只保留现行权威：流程 · 已做优化 · 观测定位 · 解决方案。历史跑次细表已收敛；AST 拓扑细节见姊妹文。

---

## 1. 整体流程

### 1.1 一句话

**LSP 是写入链权威结构车道；工作区 AST 只做 Locate 粗筛；能力焊进模型已会点的工具，不改 AgentEngine while，不新增工具名。**

```text
能力
  Locate ：search_codebase / 裸符号 grep →（可选 AST 候选）→ LSP definition 确认
  Impact ：edit_file.impact.references
  Verify ：edit_file.checks + read_lints + W9 回执 +（可选）test_summary / related_tests
隔离
  agent：有结构工具 / 无 search_sources
  writing·intel：有 search_sources / 无结构工具
红线
  R1 不挡 StartTurn 等全库索引（wait-ready 仅可选）
  失败显式 failed；词面不得冒充 Locate 成功
  AST 候选未经 LSP 确认不得进 definitions[]（veto 3）
```

### 1.2 Ops L1 / SWE 一题路径

```text
pull Lite → plan → mirror prewarm → checkout(commit)
  →（可选）AST enqueue + wait-ready
  → StartTurn(agent)
       Orient → Locate → Read → Edit(+impact+checks[+related_tests])
              → Verify（lints / tests / W9）→ 终态
  → git_diff / apply-check →（可选）官方 harness → 报告
```

并行：`l1_max_parallel`（常 2）；indexer 与 runtime **分进程**。

### 1.3 Locate 漏斗（现行）

```text
符号查询
  ├─ AST lookup → (path,line,col) → goto@标识符列 → definitions[] | definition_null
  ├─ miss/cold → D2 有界文件名即时 parse → 同上
  ├─ 无候选 → LSP workspace/symbol 两跳 + 词面
  └─ 基建挂 → lsp_failed | lsp_timeout
非定义名（模块 stem / 形参）→ no_workspace_symbol_match + 词面（defs-only 边界）
```

### 1.4 场景隔离（硬）

| Profile | 结构 / RAG |
|---------|------------|
| `agent` | Locate/Impact/Verify；**无** `search_sources` |
| `writing` / `intel` | `search_sources`；**无** coding 结构工具、不起 LSP |

---

## 2. 已优化

| 波次 / 项 | 内容 | 状态 |
|-----------|------|------|
| Wave 1 | `read_lints`=LSP∪CLI；Locate/Impact 揉进 grep/`edit_file`；pyright openFilesOnly | 已落地 |
| Wave 2 | `edit_file.checks`；span 失配候选；Reproduce/交卷 prompt | 主项已落地；**pager→read_file 硬重定向未落地** |
| Wave 3 | D1 证据指标；D2 即时符号；`read_file` outline；`related_tests` | 已落地 |
| Wave 4 | W9 终局回执；W10 `test_summary`；W11 命令化 related_tests | 代码已落地；冒烟中 `test_summary` 附带常为 0 |
| AST A6 | 旁路 indexer + ephemeral 快照；可选 wait-ready；grammar bake / 未缓存→regex | 已接线 |
| P15 | parse 写 **name 标识符列**；locate 确认前 snap 到标识符（兼容旧 snapshot） | **已修** |
| 交卷链 | 强制 checkout、clean-HEAD apply、`max_steps` 150、禁网进 runtime | 已解 |

成熟参照（揉合手法）：能力进高频动词结果契约，而非催用新工具名（Cursor/SWE-agent/OpenHands 同类结论）。

---

## 3. 观测结果与定位到的问题

### 3.1 核验跑次

| 跑次 | 角色 | 关键读数 |
|------|------|----------|
| `b3357dd6` / `66077649` / `5a4e9ba9` | 真 harness 可测 | 官方 resolve **稳态 3/5 同题**；`file_hit≈1`；Locate≠resolve |
| **`7f235e7c`**（ops `2a5b3d97`，2026-08-14） | **现行定位主样本** | 见下；**本跑 resolve_rate=0 无效**（见 §3.2 harness 题集加载） |

### 3.2 现象（`7f235e7c`，已复核）

**套件**

| 指标 | 值 | 含义 |
|------|-----|------|
| `patch_rate` / apply / `file_hit_rate` | 1.0 / 满 / **1.0** | 交卷与「找对文件」过关 |
| `locate_fuse_ok_rate` | **≈0.077**（n=13） | Locate 融合几乎全 incomplete |
| `n_locate_fuse_no_ws_symbol` / `definition_null` | 13 / 5 | 分桶见 §3.3 |
| `n_testish_tool` / `test_summary_attach_rate` | **67** / **0** | 跑了很多测，结构化失败摘要未进事件 |
| `resolve_rate` | **0.0** | 见下方「题集双轨」——**非**「本地完全没缓存」 |

**题集双轨（易混 · 本跑已核实）**

| 轨道 | 路径 / 行为 | 本跑状态 |
|------|-------------|----------|
| **平台 Pull / L1 infer** | `BENCH_DATA_DIR` → `/data/ops-official/data/swebench_lite/instances.jsonl`（已存在，~3.6MB） | **有本地缓存**；checkout / 出 patch 不依赖本次 Hub |
| **官方 `swebench.harness.run_evaluation`** | CLI 现传本地 `…/instances.jsonl`（H0）；旧跑曾传 `princeton-nlp/SWE-bench_Lite` → Hub | **已接线**；旧行为：禁网 + `HF_HOME` 无 HF dataset 缓存 → `LocalEntryNotFoundError` |
| `cache_level: instance` | 只管 **sweb.eval Docker 镜像**是否保留 | **不是**题集 jsonl 缓存开关 |

结论：本地 **instances.jsonl 已有**；旧 evaluate 仍传 Hub id → 禁网挂。**H0 接线已修**：`run_swe_eval` 改吃 `instances.jsonl`，子进程强制 `HF_HUB_OFFLINE` / `HF_DATASETS_OFFLINE`（`7f235e7c` 类失败应消）。


**分题墙钟与工具账（`tool.completed`，复核）**

| 题 | 墙钟 | 工具数 | `run_command` | `update_plan` | `read_file` | 命令粗分（摘要/命令文本） |
|----|------|--------|---------------|---------------|-------------|---------------------------|
| 12907 | 29.7m | 134 | **47%** | 25% | 6% | pager≈20 · testish≈13 · other≈29 |
| 14182 | **38.9m** | 188 | 30% | 22% | **18%** | pager≈23 · testish≈19；continue_reads=24 |
| 14365 | 28.5m | 171 | **47%** | 15% | 6% | pager≈35 · testish≈31 |
| 14995 | 28.6m | 91 | **53%** | 26% | 13% | other≈31 · pager≈13 |
| 6938 | **4.2m** | 45 | 33% | 18% | 16% | **对照短题** |

注：CSI `n_pager_run_command` 本跑多为 0，与 turn 内 sed/head/tail **计数口径不一致**——定位以 turn 命令文本为准。

### 3.3 问题定位（可证伪）

#### Q1 — 步骤多 / 时间长

| 结论 | 证据 |
|------|------|
| **主因：`run_command` 执行环**（pager 读源 + 反复试测 + 杂命令） | 占比 30–53%；6938 同栈仅 4min → 非索引宿命 |
| **辅因：`update_plan` 过密** | 15–26% 工具事件 |
| **旁因（仅部分题）：截断续读** | 14182：34 reads / 24 continue；另两长题读很少仍 ~30min |
| **非因** | cold_start（秒级）；Locate 调用占比 &lt;3%；「模型不会点 search_codebase 名」 |

#### Q2 — 编码质量（官方通过）

| 结论 | 证据 |
|------|------|
| **本跑不可用 resolve 评判质量** | 当时 harness 未消费本地 `instances.jsonl`（H0 前）；HF `load_dataset` 禁网失败 |
| **历史真 harness：主因是补丁未过 F2P（修复正确性）** | 3/5 同题稳态；失败题 `file_hit=1` |
| **辅因：验证信号弱** | 测了很多（`n_testish` 高）但 `test_summary_attach_rate=0` |
| **非因** | 交卷链坏；「找不到文件」；单靠 AST 不完善解释 resolve |

#### Q3 — Locate / 索引（结构车道，次于 Q1/Q2）

| ID | 性质 | 状态 | 说明 |
|----|------|------|------|
| P15 `definition_null` | **Bug** | **已修** | col 指空白/`def`；parse name 列 + locate snap |
| P16 `no_ws` 查模块名/参数 | **结构边界** | 已知 | defs-only；`ready`≠任意词可 Locate |
| P17 StartTurn 早于 ready | **设计权衡** | 可选门默认关 | 例：14365 首 Locate 早 ~1s |
| P18 grammar 冷拉挂死 | **Bug** | **已缓解** | bake / 未缓存→regex；regex 曾放大 P15 |

**分流钉死**：慢 ≠ AST 没建好；质量 ≠ Locate 主崩；索引预备只消竞态与稳住粗筛，不解决 Q1/Q2 主桶。

---

## 5. 解决方案与思路

### 5.1 总策略（成熟口径）

对标已验证做法：**把约束焊进控制环高频动词**，并保证 **评测度量可信**。三条并行轨道，禁止混成「再加一个索引」：

```text
轨道 M — 度量可信（harness）     没有可信 resolve，一切质量优化不可证伪
轨道 T — 时长 / 步数（执行环）   打 run_command / update_plan / 续读
轨道 Q — 官方通过（修复+验证）   打 F2P 与失败测回灌；不承诺 AST 抬 resolve
轨道 L — Locate 收尾             P15 已修；wait-ready / 查询类型认知
```

### 5.2 综合 harness 优化方案（推荐落地顺序）

目标：n5/n25 **可重复、可归因、墙钟可控、resolve 可信**。分四层，由外到内。

#### H0 — 度量层（必须先绿）

| 项 | 做法 | 出口 |
|----|------|------|
| 官方评价题集接线 | harness **改吃**已有 `swebench_lite/instances.jsonl`；evaluate 子进程强制 `HF_HUB_OFFLINE=1`；失败标 `harness_infra`，**不得**记成模型 0 分 | **已修**（`swe_run._harness_dataset_arg`）；历史 `7f235e7c` 为接线前样本 |
| 实例镜像 | 维持 `sweb.eval` 预拉 + `require_local_images`（已有 N0） | evaluate 不挂死 |
| 分桶校正 | `resolve_rate` 仅在 harness exit 0 时写入；否则 `resolve_rate=null` + `harness_error` | 看板不再把基建失败读成「模型 0 分」 |
| 探针口径 | `n_pager_run_command` 与 turn 命令分类对齐（sed/head/tail/nl） | 时长归因与 CSI 一致 |

#### H1 — 执行环层（打 Q1 时长）

| 项 | 做法 | 参照 |
|----|------|------|
| **W2 pager 重定向** | 纯 pager 整条 `run_command` → 内部 `read_file`，带 `redirected_from`；含管道/写副作用则原样 | 同 grep→Locate 揉合 |
| **计划刷新预算** | `update_plan` 每 N step 或内容变更才落事件；或合并为静默 checkpoint | 本跑 15–26% 事件 |
| **测试命令预算** | 优先 `related_tests[].command`；限制盲目全仓 pytest；W10 必须接到摘要（含 `\| tail` 场景） | `n_testish=67` 且 summary=0 |
| **读预算** | 截断默认 outline+定点；弱化无目标 continue-read 链 | 14182 类 |

#### H2 — 质量层（打 Q2，依赖 H0）

| 项 | 做法 | 参照 |
|----|------|------|
| 失败测回灌 | W10 解析进上下文；回执引用同一失败首条 | OpenHands / Anthropic 配方 |
| 题级对照 | 对不过题保留 patch↔gold 文件差 + harness 失败日志（D1 已有 file_hit） | 区分逻辑错 vs 测错 |
| 测量升级 | n5=冒烟；n25+harness 立锚；lite-50 双轨定论（structural / AST on-off） | 避免 3/5 同分饱和误读 |

#### H3 — Locate 收尾（轨道 L，不挡 H0–H2）

| 项 | 做法 |
|----|------|
| 评测默认 `workspace_index_wait_ready=true` | 消 P17 首步竞态 |
| 重建镜像含 grammar bake | 避免再走全 regex |
| 文档/探针区分 P16 | 模块名 `no_ws` 不计「索引故障」 |

### 5.3 明确不做什么

- 不靠全仓 LSP indexing 换 fuse（已否决，伤 R3）。  
- 不以「再完整的 CST」承诺抬 resolve 或砍半墙钟。  
- 不新增模型必须学会的导航工具名。  
- 不在 harness 基建红时用 resolve 做波次效果结论。

### 5.4 验收出口（短清单）

| 轨道 | 出口信号 |
|------|----------|
| M | harness 连续 n5 exit 0；基建失败进独立桶 |
| T | 同题墙钟↓；`run_command` 占比↓；pager 重定向命中↑；`update_plan` 占比↓ |
| Q | 真 harness 下 resolve 对照入档；失败题有失败测摘要回灌 |
| L | `definition_null` 主桶↓；wait-ready 下无「首步早于 ready」 |

### 5.5 代码与文档锚点

| 锚点 | 路径 |
|------|------|
| Locate / Impact / parse | `services/runtime/app/structural/` · `workspace_index/` |
| 工具揉合 | `tools/core/codebase_search.py` · `tools/core/tools.py` |
| 评测 / harness | `eval/swebench/` · `scripts/official_bench/` · `eval/official/suites.small.yaml` |
| AST 旁路 | [agent-workspace-ast-index.md](agent-workspace-ast-index.md) |
| agent 纪律 | `scenarios/agent/system.md` |

---

## 修订记录（收敛后）

| 日期 | 修订 |
|------|------|
| 2026-08-10→14 | Wave 1–4 落地；AST A6；多轮 n5 入档（详见 git 历史） |
| 2026-08-15 | P15 坐标修复；`7f235e7c` 工具账定位时长主因 |
| 2026-08-15 | **文档收敛重写**：删历史大表/波次长文；保留 §1 流程 · §2 已优化 · §3 观测定位 · §5 harness 综合方案 |

旧版长纪要（§6.7 逐跑、Wave 细则全文）以 git 历史为准，不再在本文展开。
