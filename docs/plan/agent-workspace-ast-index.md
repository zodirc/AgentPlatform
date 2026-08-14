# 方案：Agent 工作区异步 AST 索引（Cursor 式 codebase index）

> **状态**：A6 **已接线**（2026-08-13）· A0–A5/E1 骨架已落地 · 旁路进程 + SKIP LOCKED 队列已运行（runtime 默认不同环全仓冷启动）· **验收缺口**：A6 拓扑下双轨 n5 数字尚未入库  
> **与主方案关系**：从 [Coding 结构智能](coding-structural-intelligence.md) 拆出；正文摘要见 [架构](../core/architecture.md) 旁路与 [工具与上下文](../core/tools-and-context.md)  
> **非目标**：不替代 LSP；不携带 RAG / embedding；不服务 writing/intel 的 `search_sources`  

> **落地摘要（2026-08-13 A6）**：compose 服务 `ast-indexer`（同 runtime 镜像、独立 PID、mem≈768m、parse concurrency=1）· DDL `phase1n_work_ast_index_jobs` · runtime `enqueue`→队列 / indexer `worker` claim · 评测 ephemeral 经 `.agent/ast_index_snapshot.json` 跨进程 · harness `max_workers` 默认 1（受限主机）。此前摘要：DDL/`0018` · `structural/workspace_index/` · 焊入 `search_codebase` · dirty/watch · status/rebuild/purge API · GUI `AstIndexStatusBar` · CSI `locate_fuse_fail_reason` · `suites.coding.workspace_index`。

本文回答：

1. 为什么要在 LSP + 词面之外，再给 Agent 一条 **工作区 AST 旁路**；它是否可行、成熟（§0.1 评审结论）。  
2. AST 与 LSP 的 **结合面矩阵**（§2）：索引买什么、LSP 保留什么、二者如何在同一条 Locate 漏斗里协作。  
3. **为何不能让冷启动占满 runtime**、Cursor/SCIP 式进程边界、以及目标部署拓扑（§0.4 / §3.0）。  
4. 生命周期 / **变更捕获三通道** / content-hash 失效（§3–§4）。  
5. **本地存储**（Postgres schema 草案 + 内存投影）、GUI、多账号 / 多 Work、GC（§5–§7）。  
6. 如何 **零感知** 于 agent 交互速率与交互逻辑（§8 红线映射）。  
7. **评测效果差（`d459ca51` 官方 resolve 0/5）时，本索引能救什么、不能救什么**（§0.3 归因），以及如何在评测里可控启用并证明差值（§7 评测瞬态索引 + 双轨）。

---

## 0. 一句话

**按 `work_id` 异步维护一份无向量的符号/边界表（冷启动 + 增量），焊进既有 Locate 漏斗做候选粗筛；查询只读内存投影，DB 仅作恢复快照；精确定义 / Impact / 诊断仍归 LSP。禁止绑进资料 RAG 流水线，禁止新增模型需要学会点的工具名。**

### 0.1 可行性评审结论（v2 修订依据）

**总判断：方向可行、与既有架构兼容、基建复用率高；v1 草案有三处不成熟，本版逐一修正。**

可行性依据（均已核实为本仓现状）：

| 依据 | 现状锚点 |
|------|----------|
| tree-sitter 依赖与解析代码已在仓 | `retrieval/chunking.py`（RAG 切块，AST 优先正则回落）· `structural/syntax.py`（写前语法门）· `pyproject.toml` 已含 `tree-sitter` + `tree-sitter-language-pack` |
| LSP 会话池已存在，可直接对接确认步 | `structural/pool.py`（Work 级池、idle 600s 回收、prewarm）· `adapters.py` |
| Postgres + meta 表 + 轮询进度均有先例 | `retrieval/pgvector_store.py`（`source_index_meta`）· `sync_progress.py` + `sources_index_status` 轮询（**非 SSE**） |
| 单飞 sync / mtime 轮询 debounce 有先例 | `retrieval/index_scheduler.py` · `retrieval/sources_watch.py`（明确 poll mtime+size，Docker/WSL 不用 inotify） |
| 重活 off-loop 有既定模式 | `asyncio.to_thread`（grep / lexical scan / sync 均如此） |

v1 草案的三处不成熟与修正：

| # | v1 缺口 | 后果 | v2 修正 |
|---|---------|------|---------|
| 1 | **消费面未闭环**：A3「Locate 候选只读接入」标为可选，索引建成后没有必然的消费者 | 重蹈主方案 §6.7 实测教训——「能力在菜单里，不在控制环里」；索引沦为纯成本 | 消费面**焊进既有 `search_codebase` / 裸符号 `grep` 重定向的同一条 Locate 漏斗**（§2.2）：符号查询先打内存符号表拿候选，再交 LSP definition 确认；不新增工具名，无索引时行为与今日逐字节一致 |
| 2 | **时效仅靠 mtime，变更捕获机制未指定** | mtime 可被 `git checkout` / 复制工具保留或抖动；「文件事件从哪来」悬空 | **content-hash 为权威失效判据，mtime+size 仅作快速路径**（§4.1）；变更捕获三通道：runtime 工具钩子为主（agent 工作区绝大多数变更由 runtime 自己制造）+ `run_command` 后轻量 rescan + 低频轮询兜底（§3.2） |
| 3 | **存储粒度未定型**（「symbols 行存或分片 blob」两可） | 中型仓 20 万+ 符号行存 = 写放大 + 迁移负担；热路径若查 DB 违反 R3 | 定型为 **per-file JSONB blob**（每文件一行）+ meta 表（§5.1）；**内存投影是唯一查询面**，DB 只做重启恢复快照，热路径零 DB 查询 |

### 0.2 成熟参照系（借鉴什么、不借鉴什么）

只选取有长期产品或研究验证、且与本仓约束（无预注入、无向量、LSP 权威）相容的做法：

| 系统 | 被验证的做法 | 借鉴 | 不借鉴 |
|------|--------------|------|--------|
| **Cursor** codebase index | 客户端/旁路后台建索引；对话路径消费；Merkle 式 content-hash 增量对账；不全量在答话进程重建 | content-hash 失效；对账语义（§4.2）；**索引器与交互面进程分离**（§0.4） | 服务端 embedding 检索（本文无向量红线） |
| **ctags / gtags** | 纯 definitions 符号表，几十年 IDE/编辑器验证；refs 交给更精确的工具 | 索引最小面 = **definitions only**（name/kind/位置）；references/类型一律归 LSP（§2.1） | 全局单库（我们按 `work_id` 分域） |
| **Zed / Helix** | tree-sitter 单文件即时 parse（毫秒级）做 outline/符号，无持久层也可用 | stale 时的回落路径 = **单文件即时 parse**，不必等索引追平（§4.1） | 无持久化（我们要「重启点回 Agent 还能用」，故 DB 快照） |
| **Sourcegraph SCIP / LSIF** | 快照式符号索引 + 由 commit/内容驱动失效；索引器与查询端解耦 | `generation` 世代语义；索引是**可丢弃的加速快照**，权威在源码与 LSP（§4） | 跨仓全局图（超出 Work 边界） |
| **Aider** repo map | tree-sitter tags 抽符号骨架，按引用密度排序 | 本索引即未来 Wave 3 `repo_map` 按需工具的**现成数据源**（§2.3），一份投入两处消费 | 预注入形态（主方案否决 8） |

共同规律与主方案 §7.2 一致：**收益来自把结构信息焊进模型无法绕开的路径，而不是加新入口催用**。本文消费面设计（§2.2）是同一决策的延伸。

### 0.3 评测归因与本文的位置（v3 新增，基于 `d459ca51` 完整 harness n5）

首次真跑官方 harness（主方案 §6.7.8）：`patch_rate=1.0` · `apply_ok=5/5` · **`resolve_rate=0/5`**。逐指标归因，明确哪些是本文的作用面：

| 指标（`d459ca51`） | 值 | 归因 | 是否本文作用面 |
|---|---|---|---|
| `patch_rate` / `apply_ok` / `impact_cov` / `checks_cov` / `syntax_rej` | 1.0 / 5/5 / 1.0 / 1.0 / 0 | **交卷链与编辑护栏健康**；失败不在「能不能改」 | 否（已由主方案 Wave 1/2 覆盖） |
| `locate_fuse_ok_rate` | **0.364**（n=11） | 符号 Locate 融合三次两空。机制：pyright **openFilesOnly** 下 `workspace/symbol` 对未打开文件召回差，两跳常落空（主方案 §7.1.1 已知禁全仓 indexing 的代价）——**全仓符号面缺位**正是 §1.1 定义的缺口 | ✅ **主责** |
| `n_grep_locate_incomplete` | **7** | 同上：LSP 无候选可确认 → `locate_incomplete`，模型只拿到词面兜底 | ✅ **主责** |
| 3/5 题 `grep_ok=0`；6938 `reads=36`、12907 `steps=105`、14995 `steps=99` | — | Locate 落空后模型退回**词面漫游**：靠连环 read/grep 猜文件，步数烧在找位置上 | ✅ 间接（候选回显压缩漫游，§2.2.1） |
| 14182 turn 超时（`no_verify` 桶） | 1/5 | Turn 级预算/收尾问题 | 否 → 主方案 P4 / W5 |
| 4/5 `patch_not_resolved`（找到了也改了，官方仍未过） | — | **修复正确性**：缺「复现→修→复跑」相位与增量验证深度 | 否 → 主方案 Wave 2 W1/W4 |

三条核心判断：

1. **自我排除与短板重合**：本文 v2 §7 口径是「SWE 临时 Work 默认不建」——即评测测的产品恰好没有本索引；而 `d459ca51` 显示评测**最大的可测短板（Locate 段）正是本索引的唯一主责能力**。继续默认不建，等于放着已设计好的解药不进对照组。  
2. **索引不是评测银弹**：resolve 的另一半（改对逻辑、复现验证）在主方案 Wave 2（W1/W3/W4/W5），优先级不因本文变化；本文只认领 Locate 段指标（fuse 率、incomplete 数、找位置的步数），**不承诺 resolve 直接翻正**——瓶颈可能在 fuse 修复后转移，这本身就是双轨要回答的问题。  
3. **修订方向**：v3 把 §7 从「默认不建」改写为「**评测瞬态索引 + 双轨可测**」（构建在 StartTurn 之前、纯内存、失败回落现行为），并给 §2.2 补 **incomplete 候选回显契约**（§2.2.1）。全部改动不加工具名、不改交互逻辑、不动 Turn 路径速率（§8 红线映射不变）。

**验收前置（归因探针，先于一切开关）**：现有指标只知道 fuse 失败了、不知道**为什么**失败。须先给 Locate 融合失败加原因分桶（进主方案 §7.6 探针清单）：

```text
locate_fuse_fail_reason ∈
  no_workspace_symbol_match   # LSP 两跳无候选（预期主桶；索引直接可救）
  definition_null             # 有候选但 definition 确认为空（索引只能部分救）
  lsp_failed | lsp_timeout    # 基建故障（索引救不了，另修）
```

该探针纯观测、不改行为；没有它，索引 on/off 的差值无法归因，双轨结论不可信。

### 0.4 进程边界与成熟架构（v4 · 2026-08-12 实战复盘）

> **总判断：同进程冷启动可以作为骨架验证消费面，但不是成熟产品形态。成熟目标 = 独立 indexer 生产、runtime 只消费——与 Cursor / SCIP / ctags 的共性一致。**

#### 0.4.1 现有问题（已观测，非推测）

E1 落地后 n5（`workspace_index=true`，`parallel=2`）暴露的不是「tree-sitter 算法太慢」，而是 **部署拓扑错误**：

| 观测 | 含义 |
|------|------|
| 空闲单文件 parse ≈ 毫秒级；负载下 60s 预算常 `done≈4/900` | **假慢**：CPU/线程被 Turn、模型流、Jedi、写库挤占，不是语法解析本身要数秒/文件 |
| 双题同时 `first byte timeout` → DB `TimeoutError` / `QueryCanceledError` → 成片 `turn.failed` | 索引与 agent 主环 **同进程互抢**，连带拖垮 Postgres 连接与事件写路径 |
| `LSP start failed (jedi)` 与 `search_codebase` 后失败叠加 | Locate 确认步与冷启动叠在同一条性命攸关的执行带上 |
| 单题 `start_turn` `ReadTimeout`（隔离后不再拖垮整场） | HTTP 受理面也被同机负载拖住 |
| 看板曾误报「已编入」而 API 镜像陈旧 | 发布判据问题（已修）；与索引拓扑正交，但说明评测环境对「是否真在测目标代码」敏感 |

结论：**把全仓 walk+parse 放进 `agent-runtime` 与 `_run_turn` 同居，违反「索引面 / 交互面分离」的成熟规律**（主方案 §7.2 / 本文 §8 R4 的精神）。`asyncio.to_thread` + 独立线程池只能减缓事件循环饿死，**不能**提供进程级隔离与独立扩缩。

#### 0.4.2 思路（对标什么）

| 参照 | 成熟规律 | 落到本仓 |
|------|----------|----------|
| **Cursor** codebase index | 旁路/客户端后台建索引；对话路径 **消费** 已有符号面；Merkle/content-hash **增量对账**，不全量互殴；「很快」= 先可用 + 后台变全，不是答话进程里同步建仓 | 索引 **不** 与 StartTurn / 模型流 / Jedi 抢同一进程；增量语义已在 §4，缺的是 **进程边界** |
| **SCIP / LSIF** | **索引器与查询端解耦**：indexer 产出可丢弃快照，IDE/服务只读 | `work_ast_*` + 内存投影 = 快照；**生产端应是独立 worker** |
| **ctags** | 外部工具生成 defs 表，编辑器只查 | 同构：defs-only 表；runtime = 编辑器侧 |
| **Zed** | 热路径毫秒级单文件 parse | 保留为 stale 回落（§4.1），**不是**全仓冷启动的宿主 |

一句话：**生产（parse/walk/hash/upsert）与消费（lookup / Locate 粗筛）必须是两条生命线。** Runtime 是 Agent 的交互面与 LSP 宿主；它只该：投递任务、加载投影、回答查询。

不采用的「够用」捷径（可作过渡，**不得**写成终态）：

- 仅把评测改为 `parallel=1` 假装问题解决；  
- 仅加长 60s 预算、幻想同进程下能「建完再稳」；  
- StartTurn await 全仓 ready（否决 13 / R1）；  
- 在 runtime 内再叠更多线程「看起来像异步」。

#### 0.4.3 目标解决方案（成熟拓扑）

```text
                    ┌─────────────────────────────────────┐
  checkout / 工具钩子 │  agent-api / agent-runtime（交互面） │
  dirty path ───────►│  · enqueue(work_id, root, gen)      │
                     │  · 内存投影 lookup（热路径）         │
                     │  · Locate 漏斗消费（§2.2）           │
                     │  · 永不在本进程做全仓 parse          │
                     └──────────────┬──────────────────────┘
                                    │ 队列（PG SKIP LOCKED /
                                    │  Redis / NATS；实现选型见下）
                                    ▼
                     ┌─────────────────────────────────────┐
                     │  agent-ast-indexer（索引面 · 旁路）   │
                     │  · walk code_only + hash + parse    │
                     │  · 批量写 work_ast_* 或 eval 投影 IPC │
                     │  · 独立 CPU/内存配额；可水平扩副本   │
                     │  · 进度写 meta（GUI/轮询仍读 runtime）│
                     └─────────────────────────────────────┘
```

**契约（写死）：**

| 项 | 约定 |
|----|------|
| Runtime 职责 | `enqueue` / `status` / `purge` 编排；**唯一查询面仍是进程内投影**（R3）；投影来源 = DB 快照加载 **或** indexer 推送的 generation 包 |
| Indexer 职责 | 冷启动 + 增量 parse；写 DB（产品态）或写共享投影介质（评测 memory-only 可用 mmap/临时快照文件 + runtime 加载） |
| 隔离 | compose 独立服务（推荐）或至少 **独立进程**（同机不同 PID）；禁止再把 `run_cold_start` 绑进 uvicorn worker 与 Turn 同环 |
| 优先级 | Indexer nice/cgroup 可低于 runtime；**丢进度可以，拖死 Turn 不行** |
| 分阶段可查 | 先索引 `.py`/已打开路径 → 标 `stale` 可查 → 再补全；对齐 Cursor「先可用」 |
| 动态预算 | `budget_s = clamp(f(n_code_files), min, max)` 由 **indexer** 执行；封顶防墙钟爆炸；**不能**替代进程隔离 |
| 评测态 | 仍禁止 StartTurn await ready（否决 13）；但 indexer 旁路后，Turn 与建索引可真并行而不互杀——这才是测「有索引的 coding 质量」的前提 |
| 队列选型 | 首期可用 Postgres `FOR UPDATE SKIP LOCKED` 任务表（与本仓 meta 同库、运维简单）；流量起来再迁专用队列——**接口稳定，传输可换** |

**落地步（记 A6，不挡 E1 消费面验证）：** 见 §9。E1 在 A6 落地前可继续用同进程 job 做 **消费面/探针** 冒烟，但 **双轨定论跑与 parallel>1 的正式臂，以 A6 为目标拓扑**；文档与看板不得把同进程挤兑下的失败归因成「索引无价值」。

---

## 1. 动机与边界

### 1.1 要解决什么

| 现状 | 缺口 |
|------|------|
| Agent 已揉合 **LSP** Locate/Impact/`read_lints`（pyright openFilesOnly + didOpen 定向） | openFilesOnly 下无全仓符号面：模糊符号 → 候选文件这一步靠词面全树扫；pyright 全仓 indexing 在 django 量级是分钟级（主方案 §7.1.1 已禁） |
| 词面扫盘（grep / lexical，`to_thread` off-loop） | 无语法边界；大仓每次 Locate 都重付全树 IO；符号重名时假阳性多 |
| RAG `sources/` tree-sitter 切块 | **Agent 无 `search_sources`**，该旁路不服务编码 Locate |

一句话：**LSP 精而窄（openFilesOnly），词面全而糙（每次全树扫）——中间缺一张「常驻、廉价、按语法边界组织」的全仓符号表。** 这正是 Cursor / ctags 类索引在 IDE 栈里的位置。

产品期望接近 Cursor：工作区就绪后后台建索引；文件增删改异步更新；面板能看见进度。

### 1.2 明确不做

- 不把 AST 索引当 Locate「成功」的充分条件（索引命中 ≠ definition 完成；确认步永远是 LSP 或显式 `locate_incomplete`）。  
- 不存 embedding、不写 `source_chunks`、不跑 `index_scheduler` 资料语义。  
- 不因 GUI 点「写作→Agent」同步全仓 rebuild。  
- 不新增模型需要主动学会点的工具名（`search_codebase` / `grep` 契约不变，仅内部粗筛升级）。  
- 不做 references 图 / 调用图（归 LSP；ctags 教训：糙 refs 比没有更伤信任）。  
- SWE/ops-l1 临时 Work 不走产品态全量生命周期（不落 DB、无 GUI、无 GC）——**v3 起改为「评测瞬态索引」按 §7 双轨可控启用**；修复正确性主链仍见主方案 Wave 2。

### 1.3 与主方案文档的分工

| 文档 | 内容 |
|------|------|
| [coding-structural-intelligence.md](coding-structural-intelligence.md) | LSP 揉合、Wave 1/2、Ops L1 / SWE-bench、writing/intel 场景隔离总表 |
| **本文** | Agent 工作区异步 AST：结合面、生命周期、失效、存储、GUI、Work/账号、GC |

---

## 2. 结合面：AST 索引 × LSP × 词面

### 2.1 能力分工矩阵（谁买什么）

| 能力 | AST 索引（本文） | LSP | 词面 grep |
|------|------------------|-----|-----------|
| 模糊符号 → 候选文件/行（全仓） | ✅ **主责**：内存符号表 O(1)~O(log n) | openFilesOnly 下弱；全仓 indexing 太贵 | 现状兜底（全树扫，糙） |
| 精确 definition | ❌ 只出候选 | ✅ **权威**（didOpen 定向后 definition） | ❌ |
| references / Impact | ❌ **不做** | ✅ 权威（`edit_file.impact` 已焊） | ❌ 禁止伪装 |
| 诊断 / 类型 | ❌ | ✅（`read_lints` = LSP∪ruff） | — |
| outline / 文件符号骨架 | ✅（现成副产品） | 可（documentSymbol，需 didOpen） | ❌ |
| 报错串 / regex / 字面量搜索 | ❌ | ❌ | ✅ 主责 |
| 未来 `repo_map`（Wave 3 候选） | ✅ 数据源 | — | — |

分工原则一句话：**索引负责「从名字到候选位置」这一步的速度与召回；LSP 负责一切需要语义正确性的判定；词面负责非符号查询。** 三者失效链单向：索引 miss/stale → 现行为（词面 + LSP），永不反向依赖。

### 2.2 消费面契约：焊进既有 Locate 漏斗（核心，非可选）

不改 `search_codebase` / `grep` 的工具签名、事件名与结果 schema；只升级符号路径的**内部粗筛**：

```text
模型调用 search_codebase(query)（或裸符号 grep 重定向，现契约不变）
  ├─ is_symbol_query? 否 → 词面（现状，不变）
  └─ 是 →
      ① 索引可用（ready/stale）且命中：
           内存符号表 → 候选 [(path,line,kind), …]（按 kind/精确度排序，截断 top-k）
           → 对 top 候选 LSP didOpen 定向 → definition 确认
           → definitions[]（与今日 schema 相同；meta 附 index_gen / candidates_from=ast_index）
           命中文件 hash 与投影不符 → 该条目降级：单文件即时 parse 校正或跳过（§4.1）
      ② 索引 cold/error/miss：
           现行为逐字节不变（LSP workspace/symbol 两跳 + 词面兜底）
      ③ LSP 基建失败：
           status=failed（不变；索引候选不得冒充 definitions —— 见否决 3）
```

这样设计的原因（对应 §0.1 缺口 1）：

1. **adoption 零风险**：模型不需要学任何新东西——它已经在点 `search_codebase`/`grep`，索引只让同一次调用更快更准。主方案 `01599d49` 实测证明新工具名 adoption ≈ 0，本文不再赌第二次。  
2. **收益可测**：同一 golden 对照「索引 on/off」的 Locate 墙钟与 definitions 命中率即可验收（§9 A3）。  
3. **失败面不扩大**：任何索引故障 = 回到今日行为，交互逻辑零变化。

#### 2.2.1 v3 增补：incomplete 候选回显 + 排序与查询归一化契约

`d459ca51` 的失血形态是「Locate 落空 → 词面漫游烧步数」（§0.3 行 3）。因此当索引有候选但 **LSP definition 确认失败/超时/为空** 时，不许把候选整个扔掉：

| 项 | 契约 |
|---|---|
| 候选回显 | 结果仍 `locate_incomplete=true`（否决 3 不变，**绝不**标成 `definitions[]`），但附 `candidates[]`：`path:line kind \| 单行源码`（行协议同主方案 §9.4），标 `source=ast_index`、`confirmed=false`；top-k 截断（建议 5） |
| 价值 | 模型下一步直接 `read_file` 最可能的文件，替代 30+ 次 read/grep 漫游；与主方案 W3（span 失配回显候选）**同一手法**——失败结果必须可行动 |
| 排序 | ① 精确名匹配 > 限定名尾段链匹配 > 大小写不敏感 > 前缀；② 同级按 kind：`class`/顶层 `def` > method > 顶层赋值；③ 再按路径深度浅优先（`src/` 优于 `tests/`、`examples/` 的启发式仅作 tie-break，禁止按仓库定制） |
| 查询归一化 | issue 文本里的符号常是限定形态：`astropy.io.fits.Card` 用**尾段**（`Card`）查倒排、用限定链过滤/加权；`Card.fromstring` 用容器字段匹配（method 挂在哪个 class 下） |
| 投影结构影响 | postings 条目须带 `container`（所属 class/module 链）——对应 §5.1 symbols blob 增 `ct` 字段 |
| 反过拟合 | 排序规则全局一致；**禁止**用 gold patch 调排序、禁止题级/仓级特判（承主方案 §8.4） |

### 2.3 其余消费面（只读、按需、后置）

| 消费者 | 形态 | 排期 |
|--------|------|------|
| GUI outline / 符号面板 | 读该 work 内存投影的 per-file 符号 | A5 后可选 |
| `edit_file` span 失配候选（主方案 W3） | 用符号表把候选搜索限定到相关文件，降噪 | 可选增强，W3 不依赖 |
| Wave 3 `repo_map` 按需工具 | 以本索引为数据源，避免首查现算冷启动 | 等主方案 Wave 2 数据后复议 |

---

## 3. 生命周期

### 3.0 部署拓扑：Indexer 生产 · Runtime 消费（v4）

§0.4 的落点。生命周期状态机（§3.3）与消费契约（§2）不变；**变的是谁执行 walk/parse**：

| 阶段 | Runtime | Indexer |
|------|---------|---------|
| 启用 / rebuild | 写任务行（或 RPC enqueue），立即返回 | 领取任务，advisory/单飞按 `work_id` |
| building | 只读 meta 进度供 GUI/轮询 | walk → hash → parse → 批量 upsert / 投影包 |
| ready / stale | **加载或热替换内存投影**；Locate 只读投影 | 空闲或处理脏队列 |
| 工具改文件 | 通道 ① **只投递 path**（不 parse） | debounce 后重 parse 该文件 |
| purge / Work 结束 | 编排 purge；丢本地投影 | 取消 inflight；删快照 |

过渡期（A6 前）：代码路径仍可在 runtime 内跑 `run_cold_start`（E1 已如此），但架构评审与排期必须以本节为准，禁止把过渡实现写成终态。

### 3.1 冷启动

```text
Work 启用 Agent 索引（首次进入 agent-workbench 或显式开启）
  → runtime enqueue 到 indexer（advisory-lock / 任务单飞；不挡 StartTurn / 首 token）
  → indexer 走 work_root（ignore 与 grep 同源；默认 code_only：仅 language_for_code_path 可映射后缀）
  → 每文件一趟：读取 → content-hash → tree-sitter 抽 definitions
       · 解析在 indexer 进程内线程池限并发（建议 2–4）；单文件失败跳过不崩 job
       · 不支持语言 / 超大文件 → lang=skipped，只存 hash
       · 分阶段：先 Python（及已打开路径）→ 投影可查（stale/ready）→ 再补其它语言
  → 每 N 文件批量 upsert work_ast_files + meta；runtime 按 generation 加载/热替换投影
  → status: cold → building (files_done/files_total) → ready | error
```

### 3.2 增量：变更捕获三通道（v2 新增）

Agent 工作区与 `sources/` 的关键差异：**变更的主要制造者就是 runtime 自己**。因此不需要重型 watcher，用「钩子为主、扫描兜底」：

| 通道 | 触发 | 精度 | 成本 |
|------|------|------|------|
| **① 工具钩子（主）** | `edit_file` / `write_file` / 删除类工具**成功后**，runtime 将 path **入队**（不在本进程 parse） | 精确到文件，零延迟 | ~0（一次 enqueue） |
| **② `run_command` 后轻扫** | `run_command` 成功返回后，对 work_root 做一次 mtime+size 快速比对（只比投影，不读内容）；变更者入脏队列；超时间预算（如 200ms）则中断并标 `scan_pending`，留给通道 ③ | 文件级 | 有上限，off-loop |
| **③ 低频轮询兜底** | 周期（如 30–60s，仅该 Work 有活跃 agent Session 时）mtime+size 全扫；复用 `sources_watch.py` 的 poll+debounce 模式（明确不依赖 inotify，Docker/WSL 一致） | 兜住外部改动（宿主编辑器、git 操作、容器外脚本） | 与 sources watch 同量级 |

脏队列纪律（承 v1，细化）：

| 事件 | 行为 |
|------|------|
| create / update | path 入队去重合并；debounce（~500ms）后重 parse 该文件（先 hash，hash 未变则丢弃）；替换该文件 blob；bump `generation` |
| delete | drop 该 path 行与投影条目（delete 优先于同 path 的 update） |
| rename | 视为 delete 旧 + create 新（通道 ②/③ 天然如此呈现） |
| 队列过长（背压） | 限并发不限队列；超阈值（如 >500 待处理）→ status 转 `stale` + 只优先处理「本 Turn 内被工具触碰过的 path」，其余后台慢慢追 |

即使 GUI 当前停在 **写作** 模式：若该 Work 已启用 Agent AST，仓库文件变更仍应 **异步脏更新**（写作面板不展示进度）。

### 3.3 状态机

`cold` → `building` → `ready` ↔ `stale` →（追平后）`ready`；任意步可 → `error`。

- `stale` 不是失败态：查询仍可用（逐条目 hash 校验兜底，§4.1）。  
- 工具与 GUI 必须能读到状态；**禁止假装 ready**。

---

## 4. 时效与失效契约

### 4.1 失效判据：content-hash 权威，mtime 快速路径（v2 修订）

| 层 | 判据 | 用途 |
|----|------|------|
| 快速路径 | `(mtime_ns, size)` 与投影一致 | 通道 ②/③ 扫描时跳过未变文件，不读内容 |
| 权威判据 | `content_hash`（blake2b 截断或 sha1，冷启动/重 parse 时与读文件同趟计算） | mtime 可疑（checkout / 复制 / 时钟抖动）时的最终裁决；查询命中条目的可选校验 |

**查询时校验**：Locate 漏斗（§2.2）取到候选后，对将交给 LSP 的 top 候选做一次轻校验（stat 快速路径；可疑再 hash）。不符 →

1. 该文件条目标 stale、入脏队列；  
2. 本次查询对该文件走 **单文件即时 parse**（Zed 式，毫秒级）取正确候选，或直接跳过交 LSP/词面；  
3. **绝不**把过期行号交给 LSP 后把错位结果当 definitions 返回。

### 4.2 世代与重启对账（借鉴 Cursor 对账语义）

| 机制 | 要求 |
|------|------|
| `generation` | Work 级单调递增；每批增量提交 bump 一次；查询结果 meta 可带 `index_gen` |
| runtime 重启 | **惰性恢复**：首次查询或进入 agent-workbench 时，从 DB 加载该 work 投影（不在进程启动时全量加载所有 Work）；随后一次通道 ③ 全扫对账 —— hash 一致的文件零工作，只重 parse 差异文件；**禁止无脑全量冷启动** |
| 多副本 | 写入方持 Postgres advisory lock（`work_id` 键）单飞；无锁副本只读 DB 快照建投影，查询照常 |
| GC | 删 Work：新表 FK `ON DELETE CASCADE` + 显式 purge job 双保险（**注意：本仓 `works` 现无级联删除产品路径**，`sessions.work_id` 也无 CASCADE——不能假设「删 works 行自然清干净」，purge job 必须显式存在）；idle TTL / 配额淘汰按 `work_id` 整域删；ops-l1 默认不持久 |

---

## 5. 本地存储：Postgres 快照 + 内存投影

### 5.1 表结构草案（实施时过 Alembic，独立迁移文件，与 RAG 迁移分离）

```sql
CREATE TABLE work_ast_index_meta (
    work_id        uuid PRIMARY KEY REFERENCES works(id) ON DELETE CASCADE,
    owner_user_id  text NOT NULL,
    status         text NOT NULL,          -- cold|building|ready|stale|error
    generation     bigint NOT NULL DEFAULT 0,
    files_total    integer NOT NULL DEFAULT 0,
    files_done     integer NOT NULL DEFAULT 0,
    error          text,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE work_ast_files (
    work_id       uuid NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    path          text NOT NULL,            -- 相对 work_root
    lang          text NOT NULL,            -- python|…|skipped
    content_hash  text NOT NULL,
    mtime_ns      bigint NOT NULL,
    size          bigint NOT NULL,
    symbols       jsonb NOT NULL,           -- [{"n":name,"k":kind,"l":line,"c":col,"el":end_line,"ct":container}, …]（ct=所属 class/module 链，供 §2.2.1 限定名/方法匹配）
    generation    bigint NOT NULL,
    PRIMARY KEY (work_id, path)
);
```

### 5.2 定型理由与纪律

| 议题 | 约定 | 理由 |
|------|------|------|
| 粒度 | **per-file JSONB blob**，不做符号级行存 | 10k 文件中型仓 ≈ 10k 行（而非 20 万+ 符号行）；增量 = 单行 upsert 单事务；符号级查询全部发生在内存投影，DB 不需要按符号索引 |
| 查询面 | **内存投影唯一**：`name → postings` 倒排 + `path → FileEntry`；DB 仅冷启动恢复 / 崩溃恢复读 | R3：热路径零 DB 往返；投影每 Work 估 10–50MB（10k 文件量级），LRU/idle 淘汰与 LSP 池同纪律（600s 参照） |
| 连接 | 复用 runtime 现有 asyncpg pool | 不新增连接面 |
| 隔离 | 独立表；**禁止**触碰 `source_chunks` / `source_index_meta` / `index_scheduler` 的任何行为语义 | RAG 两平面红线 |
| 一致性顺序 | 落盘文件 → 脏队列 → 重 parse → **DB upsert（事务）→ 内存投影替换 → bump generation → 进度可见** | 投影落后于 DB 至多一批；崩溃后 DB 为准重建 |
| 多账号 | 行带 `owner_user_id`；查询 API 强制按 principal 过滤；禁止跨用户读 | 与现有多租户纪律一致 |
| 容量估算 | 10k 文件 × 每文件 blob 数 KB ≈ 数十 MB/Work | Postgres 无压力；超大 monorepo 由 §3.2 背压 + 文件数上限（settings 可配）兜住 |

---

## 6. GUI · 模式切换 · 进度

### 6.1 模式点击的产品事实

Web 上 Agent / 写作 / 其他往往是 **同一 Work 下换 `scenario_id` / `web_layout`**，不是换租户，也未必换 `work_root`。

| 面 | 模式切换时应怎样 |
|----|------------------|
| RAG | 继续该 Work 的 embed/sync 状态；**不**因点击同步重建 |
| LSP | 进 Agent 可软预热；离开可 idle 回收 |
| 工作区 AST | **主权在 Work**，不在「当前模式」；进度显示的是该 `work_id` 的世代 |

推论：

1. 禁止「点到 Agent 才从零 parse、点到写作就丢掉」。  
2. 模式切换只改 **工具白名单与面板**；GUI **只订阅** 索引状态。  
3. RAG 进度与 AST 进度 **必须分开**（两套文案 / 两个 job / 两个 endpoint）。

### 6.2 进度传输：先对齐现有轮询先例（v2 修订）

本仓 sources 摄入进度的现役机制是 **meta 快照 + GET 轮询**（`sync_progress.json` + `sources_index_status`），刻意未用 SSE。AST 进度**先同构复用该模式**：

| 项 | 约定 |
|----|------|
| 快照源 | `work_ast_index_meta` 行（status / files_done / files_total / generation / error）即快照，无需另设进度文件 |
| 传输 | **独立** GET endpoint（如 `/workspace/{work_id}/ast-index/status`），Web 轮询（与 `IngestionProgressBar` 同构不同源）；SSE 列为后置可选优化，不进首批验收 |
| 展示 | Agent 工作台：`cold` / `building (n/N)` / `ready` / `stale` / `error`；可折叠，不挡输入 |
| 可见性 | 仅 `agent-workbench`（或该 Work 已启用 coding）；writing/intel **不挂** AST 进度 |
| building 时 | Locate 仍可用（走 §2.2 分支 ②，现行为）；仅提示索引未就绪 |

```text
GUI 点击「Agent」
  → 不重建索引
  → 轮询该 work_id 的 ast-index status
  → 若 cold：enqueue 冷启动（单飞）
  → 进度 ← meta 行

GUI 点击「写作」
  → 订阅 sources sync / embed 进度（若有）
  → 不展示、不取消 Agent AST job（除非 Work 销毁）
```

---

## 7. 与 SWE / Ops 评测（v3 重写：从「默认不建」到「瞬态索引 + 双轨可测」）

### 7.1 口径变更与公平性辨析

v2 口径「SWE 临时 Work 默认不建」的出发点是评测洁癖（harness 工作区无预建索引、避免评测特权）。`d459ca51` 归因（§0.3）暴露该口径的两个问题：

1. **测的不是产品**：真实用户的 Work 会有本索引（§3 生命周期），评测 Work 却没有——评测在测一个能力被阉割的产品，`locate_fuse=0.364` 部分是自我设限的结果。  
2. **短板与主责重合**：评测最大可测短板（Locate 段）恰是本索引唯一主责，继续排除等于放弃唯一直接杠杆。

公平性辨析（为什么这不算作弊）：

| 质疑 | 回答 |
|------|------|
| 是否评测特权？ | 索引是**产品固有能力**（Cursor 用户天然有 codebase index），对 300 题一视同仁，与题目内容无关 |
| 是否预注入？ | 否。索引只改 `search_codebase`/`grep` 的**工具内部粗筛**与失败候选字段，不向 prompt 注入任何字节（否决 8 / 主方案否决 8 均不触碰） |
| 是否 gold 泄漏？ | 否。构建输入只有 checkout 后的 worktree 本身；排序规则全局一致、禁止题级调优（§2.2.1 反过拟合行） |
| 与「无预建索引」口径矛盾？ | 该口径真正要防的是**题级预热的检索特权**（如预算好的 embedding / 预注入骨架）。本索引 = 从当前 worktree 现算的语法事实，任何选手用 ctags 都能得到，属工具链而非先验知识 |

### 7.2 评测瞬态索引 profile（eval-ephemeral）

与产品态（§3–§6 全量生命周期）不同，评测态是其**最小可信子集**：

| 项 | 约定 |
|----|------|
| 构建时机 | 套件层每题 **checkout 完成后、StartTurn 已受理之后** enqueue（Turn 先 202，索引在 Turn 期间异步补齐）；**不阻塞开题**——StartTurn 时索引尚未 ready 则走 §2.2 分支 ②，ready 后自然生效 |
| 存续 | **仅内存投影，不写 `work_ast_*` 表**（与主方案 §3.6「SWE 临时 Work 默认不写 AST DB」兼容——变更的是建不建，不是持久化口径）；Work 结束即弃，无 GC 负担 |
| 增量 | **仅通道 ①**（工具钩子）。SWE worktree 的全部变更来自 runtime 工具（`edit_file`/`write_file`/`run_command` 内脚本极少改源码），通道 ②③ 不进评测态 |
| GUI | 不挂进度（评测无面板诉求；§6 全部不适用） |
| 预算 | **动态** `clamp(f(n_code_files), min, max)`（由 indexer 执行；建议 min≈45s、max≈180–240s）；硬封顶防套件墙钟爆炸；超限 → partial/`stale`，已建部分可查。固定 60s 仅作 A6 前过渡默认，**不是**成熟口径 |
| 失败面 | job 失败/超时 = 该题走现行为（今日基线），**不得**把索引缺失记 case fail、不得重试阻塞套件 |
| 开关 | 只存在于**基准 runner 配置**（`suites.coding.workspace_index`）；**默认 `true`**（产品同构臂）；对照基线时改 `false`。不回流产品语义——与主方案「structural on/off 只存在于 runner」同一先例 |

### 7.3 双轨协议与决策规则（事先写死，防拍脑袋）

| 项 | 约定 |
|----|------|
| 协议 | 承主方案 §8.2 全部条款（同模型/同 prompt/同种子/禁网/复现存档）；`workspace_index` 是新的 structural 变量，**禁止跨配置比数字** |
| 样本 | n5 冒烟（与 `d459ca51` 同 5 题，可直接对基线）→ lite-50 定论 |
| 主判据（Locate 段，本文认领） | `locate_fuse_ok_rate`（基线 0.364）· `n_grep_locate_incomplete`（基线 7）· 融合失败原因分桶（§0.3 探针）· 首次命中 gold 涉及文件前的 steps/reads |
| 从判据 | 官方 `resolve_rate` 差值 · 步数 p50 · TTFB / assemble_ms 持平（R1/R3 旁证） |
| 决策规则 | ① fuse 显著升 **且** resolve 差值 ≥ 0 且速率不劣化 → 评测默认 on，进 lite-300；② fuse 显著升但 resolve 不动 → 定位瓶颈已解除、瓶颈转移至修复正确性——索引保持 on（它已买到步数与定位），**火力回主方案 Wave 2 W1/W4**；③ fuse 不升 → 查失败原因分桶：若主桶本就是 `definition_null`/`lsp_failed` 而非 `no_workspace_symbol_match`，说明缺口判断错了，索引回默认 off 并复盘 §0.3 归因 |
| 反过拟合 | 不用 gold patch 调排序/建索引参数；lite-50 子集冻结（主方案 §8.4） |

### 7.4 与主方案排期的关系

不阻塞、不抢主方案 Wave 2（N1 的 W1/W3/W4/W5 仍是 resolve 的最大杠杆）。建议挂点：**N2（n5 复跑）之后作为并行轨（记 N2.5）**，复用同一批跑次做 index on/off 双轨，避免另起炉灶烧配额。归因探针（§0.3）应随 N2 一并落，先于开关。

---

## 8. 速率红线映射（R1–R5）与交互零感知

| 红线 | 本文如何遵守 | 违规示例（禁止） |
|------|--------------|------------------|
| **R1** 不挡受理/TTFB | 冷启动/增量全部异步 job；StartTurn 不 await 索引任何状态 | `turn.accepted` 前 await building 完成 |
| **R2** 首 token 前无同步模型 | 索引纯语法层，无任何模型调用 | 用 LLM 抽符号 |
| **R3** 热路径 CPU 毫秒级 | 查询 = 内存 dict/倒排查找；候选校验 = 单次 stat；**热路径零 DB 查询、零同步 parse**（stale 单文件即时 parse 是毫秒级且有 timeout） | 查询现查 Postgres；查询触发重建 |
| **R4** 重活异步 | parse/hash/DB 写在 **indexer 进程**（§3.0）；runtime 热路径零全仓 parse；通道 ② 轻扫有硬预算 | `search_codebase` 内 rebuild；在 uvicorn/Turn 同环跑全仓冷启动 |
| **R5** 可测才合并 | 每步验收见 §9；A3 需 Locate 墙钟 + definitions 命中率 on/off 对照 | 「手感快了」无对照合入 |

交互逻辑零变化清单：

- 工具面：**零新工具名**、零签名变更、零 `system.md` 文案变更（prompt 前缀字节不变 → cache 不失效）。  
- Engine：零新节点、零 `if scenario`。  
- 失败面：索引任何故障 = 回到今日行为；LSP 失败语义不变（显式 `failed`）。  
- writing/intel：零感知（不起 job 于其面板、不展示进度、不注册查询 API）。

---

## 9. 落地序（A0–A6 主链已接线；双轨数字待复跑）

> **状态（2026-08-13）**：A0–A5/E1 骨架 + **A6 旁路 indexer** 已接线。下表保留原验收口径；「待」仅指评测数字/增强通道，不再表示骨架未写。

| 步 | 内容 | 状态 | 验收要点 |
|----|------|------|----------|
| A0 | 表结构 + 内存投影骨架 | **已落地** | upsert/恢复/ACL；与 RAG 迁移隔离 |
| A1 | 冷启动 job + 进度 API | **已落地** | building→ready；不挡 TTFB |
| A2 | 工具钩子 + 脏队列 + hash 失效 | **已落地** | 编辑后世代变；无幽灵条目 |
| A3 | Locate 粗筛 + incomplete 候选 | **已落地** | 焊进既有 Locate 漏斗；off 时行为一致 |
| E1 | 评测瞬态索引 profile | **骨架已落地** | 双轨 n5 数字待 A6 拓扑复跑入库 |
| A6 | 独立 ast-indexer 进程 + 队列 | **已接线** | runtime 默认不同环全仓冷启动 |
| A4 | run_command 轻扫 + 低频轮询 | 可增强 | 外部 checkout 追平 |
| A5 | 多 Work LRU + GC + ACL | 可增强 | 跨用户不可见；内存有上限 |

依赖：正式 parallel>1 / 定论双轨以 A6 拓扑为准。主方案 Wave 2 **不依赖**本文未完成增强步。

---

## 10. 风险与对策

| 风险 | 对策 |
|------|------|
| 大仓冷启动 parse 耗时/耗 CPU | **A6 进程隔离** + indexer 限并发（2–4）+ 单文件超时跳过 + 动态预算封顶 + 分阶段可查；building 期 Locate 走现行为或已建子集 |
| **同进程索引挤兑 Turn**（v4） | 禁止终态同环冷启动（§0.4）；A6 独立 indexer；正式 parallel>1 双轨不以同进程臂定论 |
| 投影内存膨胀（多 Work 常驻） | 惰性加载 + LRU/idle 淘汰（与 LSP 池 600s 同纪律）；每 Work 投影字节数进观测 |
| hash 计算成本 | 冷启动与重 parse 时和读文件同趟算（读都读了）；扫描快速路径只 stat 不读内容 |
| 索引候选与 LSP 结果不一致 | LSP 永远权威；候选仅决定「先看哪个文件」；错位候选被确认步自然过滤 |
| Postgres 写放大 | per-file blob + 批量事务（冷启动每 200 文件一批；增量单文件单事务，天然低频） |
| 多副本重复建索引 | advisory lock / 任务单飞（indexer 侧）；无锁副本只读 |
| tree-sitter 语言覆盖不全 | `lang=skipped` 显式记录，只存 hash；该文件 Locate 走现行为；语言矩阵 Python-first（与主方案 §9.1 一致），grammar 构建期打入镜像，禁运行时下载 |
| `run_command` 轻扫误判/超时 | 只比 stat 不读内容；硬预算 + `scan_pending` 显式转兜底轮询；误判由 hash 权威层兜住 |
| 与用户/agent 并发编辑竞态 | 投影替换为原子操作（整 FileEntry 换）；查询时校验（§4.1）是最后一道闸 |
| **评测冷启动挤占套件墙钟**（v3） | A6 后与 Turn 真并行；动态预算封顶；StartTurn 永不等待索引（§7.2） |
| **`candidates[]` 噪声误导模型**（v3） | top-k=5 截断 + kind/限定名排序 + 附单行源码供模型自判；双轨若 steps/reads 反而变差 → 收紧 k 或只在 `no_workspace_symbol_match` 桶回显 |
| **评测公平性质疑**（v3） | §7.1 辨析入档：产品固有能力、零预注入、零 gold 输入；on/off 双轨永久保留，差值透明可复现 |
| **双轨差值无法归因**（v3） | 失败原因分桶探针（§0.3）先于开关落地；无探针不跑双轨 |

---

## 11. 否决清单（本文）

1. 用 RAG embed 管道「顺便」当 Agent codebase index。  
2. GUI 模式点击触发同步全仓 parse。  
3. 索引命中即标记 Locate 成功 / 索引候选直接冒充 `definitions[]`（绕过 LSP 确认与失败显式化）。  
4. writing/intel 面板强行展示代码 AST 进度。  
5. 与 `source_chunks` 共表缠迁移。  
6. 查询热路径查 DB、或查询触发同步重建（R3/R4）。  
7. 为索引新增模型需主动学会点的工具名（重蹈 adoption 覆辙）。  
8. runtime 启动时全量加载所有 Work 投影（必须惰性 + 淘汰）。  
9. 仅凭 mtime 判「未变」而跳过 hash 权威裁决路径（checkout 场景必失效）。  
10. 在索引里存 references / 调用图并对外提供（糙 refs 伤信任；归 LSP）。  
11. **把评测瞬态索引做成预注入**（repo map / 符号骨架文本进 prompt）——评测态只许工具内部粗筛 + `candidates[]` 结果字段（§7.1 公平性辨析的前提）。  
12. **用 gold patch 调候选排序 / 建索引参数，或做题级、仓级排序特判**（§2.2.1 / 主方案 §8.4）。  
13. **StartTurn 等待评测索引 ready**，或把索引构建失败记为 case fail（评测态失败面 = 今日基线，§7.2）。  
14. **将全仓 AST 冷启动/增量 parse 留在 runtime 与 Turn 同进程作为产品终态**（§0.4）；同进程仅允许作 A6 前过渡，不得写入「已成熟」口径。  
15. **用 parallel=1 或加长预算掩盖同进程挤兑，并据此宣称索引无价值 / 双轨定论**（须在 A6 拓扑或明确标注过渡臂下复跑）。

---

## 12. 修订记录

| 日期 | 修订 |
|------|------|
| 2026-08-11 | 从 `coding-structural-intelligence.md` §3.3.2–3.3.5 等拆出独立草案：工作区异步 AST、GUI/Work/DB、与 RAG/LSP/评测隔离 |
| 2026-08-11 | **v2（深度评审修订）**：新增 §0.1 可行性结论（三处不成熟：消费面未闭环 / 失效仅 mtime / 存储粒度未定，逐一修正）与 §0.2 成熟参照系（Cursor 对账、ctags defs-only、Zed 即时 parse 回落、SCIP 世代、Aider repo map 数据源）；§2 重写为 AST×LSP×词面结合面矩阵 + Locate 漏斗消费契约（焊进 `search_codebase`/`grep`，零新工具名）；§3.2 变更捕获三通道（工具钩子主 / run_command 轻扫 / 低频轮询兜底，对齐 sources_watch poll 先例）；§4 content-hash 权威失效 + 惰性恢复对账；§5 存储定型 per-file JSONB blob + 内存投影唯一查询面 + DDL 草案（含 works 无级联删除现状的显式 purge 要求）；§6.2 进度先复用 meta 快照 + 轮询先例（SSE 后置）；§8 R1–R5 映射与交互零感知清单；§9 落地序细化为 A0–A5（触点 + 验收 + 依赖）；§10 风险表；否决清单扩至 10 条 |
| 2026-08-12 | **v3（评测归因修订，基于 `d459ca51` 官方 resolve 0/5）**：新增 §0.3 逐指标归因——交卷链/编辑护栏健康，短板集中在 Locate 段（`locate_fuse=0.364`、`incomplete=7`、3/5 题 `grep_ok=0`、Locate 落空后词面漫游烧步数），恰为本索引主责，而 v2 §7「SWE 默认不建」使评测测的是能力被阉割的产品；修复正确性（4/5 `patch_not_resolved`）与 Turn 超时（14182）明确归主方案 Wave 2 / P4，本文不认领。§7 重写为「评测瞬态索引」：checkout 后 StartTurn 前异步构建、纯内存不落 DB、仅通道 ①、失败回落今日基线、开关只在 runner 配置；含公平性辨析（产品固有能力 ≠ 预注入 ≠ gold 泄漏）与三分支决策规则（fuse↑且 resolve≥0 → 默认 on；fuse↑但 resolve 平 → 火力回主方案 W1/W4；fuse 不升 → 按失败原因分桶复盘）。§2.2.1 新增 incomplete 候选回显与排序契约（`candidates[]` 不冒充 definitions、限定名/方法归一化、投影加 container）；§5.1 symbols blob 增 `ct` 字段。§9 排序变更：A0→A1→A3 快车道 + 评测轨 E1（挂主方案 N2 后并行，记 N2.5），A4/A5 后置不进评测轨；归因探针（融合失败原因分桶）列为双轨前置。§1.2 旧口径同步更新；风险表增 4 行、否决清单增 11–13 |
| 2026-08-12 | **v3 代码落地**：`query.py` 归一化/排序；`SymbolRec.ct` + parse 容器链；`locate` incomplete→`candidates[]` + `locate_fuse_fail_reason`；CSI 探针分桶；`run_cold_start(memory_only=)`；runtime rebuild/purge；`suites.coding.workspace_index` + L1 checkout 后 fire-and-forget enqueue；单测覆盖 incomplete/candidates、memory-only、qualified sort |
| 2026-08-12 | **v4（进程边界）**：§0.4 实战复盘——同进程冷启动在 parallel≥2 下与 Turn/Jedi/DB 互抢致假慢与成片 `turn.failed`；思路对标 Cursor/SCIP「索引器与查询端解耦」；目标拓扑 `agent-ast-indexer` 生产、runtime 只消费。新增 §3.0；修订 §3.1/通道①/§7.2 动态预算/§8 R4；§9 增 A6；风险与否决 14–15；明确 parallel=1/加长预算仅为过渡，不得作终态或错误归因依据 |
| 2026-08-13 | **A6 代码落地**：`work_ast_index_jobs` + alembic · queue/worker/snapshot · 默认 remote enqueue · compose `ast-indexer`；正式双轨 n5 仍待本拓扑复跑 |
| 2026-08-13 | **文档回写**：§9 落地序改为状态表（A0–A6 主链已接线）；与六篇正文 / CSI 状态条对齐 |
| 2026-08-13 | **基线对照补记**：主方案 §6.7.9（`b3357dd6`）官方 resolve **3/5**，而 `locate_fuse≈0.27`（主桶 `no_ws_symbol=10/11`）仍弱——强化「本文认领 Locate 段、不认领 resolve 单指标」；双轨 n5 仍待 A6 拓扑复跑 |
| 2026-08-14 | **D2 即时回落落地**：`locate._instant_def_hits`——索引 COLD/miss 时按符号尾名有界扫 `**/Tail.py` 并单文件 parse，再交 LSP 确认（不 await ready、不冒充 definition）；主方案 Wave 3 N6 认领；双轨 n5 数字仍待复跑 |