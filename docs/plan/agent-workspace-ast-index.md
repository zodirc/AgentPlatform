# 方案：Agent 工作区异步 AST 索引（Cursor 式 codebase index）

> **状态**：候选方案 v2（2026-08-11 深度评审后修订）· **未实施**  
> **与主方案关系**：从 [Coding 结构智能（LSP / AST）](coding-structural-intelligence.md) 拆出；主方案负责 **已落地 LSP Locate/Impact + SWE/Ops 评测揉合**；本文只谈 **Agent 仓库工作区的异步符号索引**  
> **非目标**：不替代 LSP；不携带 RAG / embedding；不服务 writing/intel 的 `search_sources`  
> **约束权威**：[架构 · R1–R5](../core/architecture.md) · [RAG 两平面](../topics/rag.md)（对照隔离）· 主方案 §3 场景分型  

本文回答：

1. 为什么要在 LSP + 词面之外，再给 Agent 一条 **工作区 AST 旁路**；它是否可行、成熟（§0.1 评审结论）。  
2. AST 与 LSP 的 **结合面矩阵**（§2）：索引买什么、LSP 保留什么、二者如何在同一条 Locate 漏斗里协作。  
3. 生命周期 / **变更捕获三通道** / content-hash 失效（§3–§4）。  
4. **本地存储**（Postgres schema 草案 + 内存投影）、GUI、多账号 / 多 Work、GC（§5–§7）。  
5. 如何 **零感知** 于 agent 交互速率与交互逻辑（§8 红线映射）。

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
| **Cursor** codebase index | 客户端 Merkle 式 content-hash 树做增量同步；重启/重连只对账差异，不全量重建 | content-hash 失效判据；「重启从快照恢复 + 只追差异」的对账语义（§4.2） | 服务端 embedding 检索（本文无向量红线） |
| **ctags / gtags** | 纯 definitions 符号表，几十年 IDE/编辑器验证；refs 交给更精确的工具 | 索引最小面 = **definitions only**（name/kind/位置）；references/类型一律归 LSP（§2.1） | 全局单库（我们按 `work_id` 分域） |
| **Zed / Helix** | tree-sitter 单文件即时 parse（毫秒级）做 outline/符号，无持久层也可用 | stale 时的回落路径 = **单文件即时 parse**，不必等索引追平（§4.1） | 无持久化（我们要「重启点回 Agent 还能用」，故 DB 快照） |
| **Sourcegraph SCIP / LSIF** | 快照式符号索引 + 由 commit/内容驱动失效；索引器与查询端解耦 | `generation` 世代语义；索引是**可丢弃的加速快照**，权威在源码与 LSP（§4） | 跨仓全局图（超出 Work 边界） |
| **Aider** repo map | tree-sitter tags 抽符号骨架，按引用密度排序 | 本索引即未来 Wave 3 `repo_map` 按需工具的**现成数据源**（§2.3），一份投入两处消费 | 预注入形态（主方案否决 8） |

共同规律与主方案 §7.2 一致：**收益来自把结构信息焊进模型无法绕开的路径，而不是加新入口催用**。本文消费面设计（§2.2）是同一决策的延伸。

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
- SWE/ops-l1 临时 Work **默认不建**（或极短 TTL）——评测主链仍见主方案（LSP + 词面）。

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

### 2.3 其余消费面（只读、按需、后置）

| 消费者 | 形态 | 排期 |
|--------|------|------|
| GUI outline / 符号面板 | 读该 work 内存投影的 per-file 符号 | A5 后可选 |
| `edit_file` span 失配候选（主方案 W3） | 用符号表把候选搜索限定到相关文件，降噪 | 可选增强，W3 不依赖 |
| Wave 3 `repo_map` 按需工具 | 以本索引为数据源，避免首查现算冷启动 | 等主方案 Wave 2 数据后复议 |

---

## 3. 生命周期

### 3.1 冷启动

```text
Work 启用 Agent 索引（首次进入 agent-workbench 或显式开启）
  → advisory-lock 单飞 enqueue 异步 job（复用 index_scheduler 单飞先例；不挡 StartTurn / 首 token）
  → 走 work_root（复用现有 ignore 规则：.git/.venv/node_modules/dist/…，与 grep 排除表同源）
  → 每文件一趟顺带完成：读取 → content-hash → tree-sitter 抽符号（def/class/method/顶层赋值等 definitions）
       · 解析用 asyncio.to_thread + semaphore 限并发（建议 2–4）；单文件失败跳过不崩 job
       · 不支持语言 / 超大文件（>1MB 或行数上限）→ 记 lang=skipped，只存 hash 供失效判断
  → 每 N 文件（如 200）一事务批量 upsert work_ast_files + 更新 meta 进度
  → 写内存投影
  → status: cold → building (files_done/files_total) → ready | error
```

### 3.2 增量：变更捕获三通道（v2 新增）

Agent 工作区与 `sources/` 的关键差异：**变更的主要制造者就是 runtime 自己**。因此不需要重型 watcher，用「钩子为主、扫描兜底」：

| 通道 | 触发 | 精度 | 成本 |
|------|------|------|------|
| **① 工具钩子（主）** | `edit_file` / `write_file` / 删除类工具**成功后**，同进程将 path 投入脏队列 | 精确到文件，零延迟 | ~0（一次 enqueue） |
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
    symbols       jsonb NOT NULL,           -- [{"n":name,"k":kind,"l":line,"c":col,"el":end_line}, …]
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

## 7. 与 SWE / Ops 评测

| 项 | 约定 |
|----|------|
| 默认 | ops-l1 / SWE 临时 Work **不建** 或短 TTL、不面向评测 GUI（与「harness 工作区无预建索引」口径一致） |
| 评测主链 | 仍以主方案为准：LSP + 词面 + Wave 2 揉合；官方 resolve 靠 harness |
| 若未来开浅索引 | 不得挡 Turn；不得把索引缺失当 case fail；若开，须进主方案 §8.2 双轨对照（索引 on/off 是新的 structural 变量，禁止跨配置比数字） |

---

## 8. 速率红线映射（R1–R5）与交互零感知

| 红线 | 本文如何遵守 | 违规示例（禁止） |
|------|--------------|------------------|
| **R1** 不挡受理/TTFB | 冷启动/增量全部异步 job；StartTurn 不 await 索引任何状态 | `turn.accepted` 前 await building 完成 |
| **R2** 首 token 前无同步模型 | 索引纯语法层，无任何模型调用 | 用 LLM 抽符号 |
| **R3** 热路径 CPU 毫秒级 | 查询 = 内存 dict/倒排查找；候选校验 = 单次 stat；**热路径零 DB 查询、零同步 parse**（stale 单文件即时 parse 是毫秒级且有 timeout） | 查询现查 Postgres；查询触发重建 |
| **R4** 重活异步 | parse/hash/DB 写全在 job（to_thread + 限并发）；通道 ② 轻扫有硬预算 | `search_codebase` 内 rebuild |
| **R5** 可测才合并 | 每步验收见 §9；A3 需 Locate 墙钟 + definitions 命中率 on/off 对照 | 「手感快了」无对照合入 |

交互逻辑零变化清单：

- 工具面：**零新工具名**、零签名变更、零 `system.md` 文案变更（prompt 前缀字节不变 → cache 不失效）。  
- Engine：零新节点、零 `if scenario`。  
- 失败面：索引任何故障 = 回到今日行为；LSP 失败语义不变（显式 `failed`）。  
- writing/intel：零感知（不起 job 于其面板、不展示进度、不注册查询 API）。

---

## 9. 落地序（未排进 Wave 2 主轨；每步独立可回退）

| 步 | 内容 | 触点（实施时） | 验收 |
|----|------|----------------|------|
| A0 | 表结构（§5.1）+ meta 读写 + 内存投影骨架（load/replace/lookup） | 新增 `structural/workspace_index/`（store / projection）；Alembic 独立迁移 | 单测：upsert/恢复/ACL 过滤；与 RAG 迁移零交集 |
| A1 | 单 Work 冷启动 job（walk + hash + parse + 批量 upsert）+ 进度 GET endpoint | job + `main.py` 路由；解析复用 chunking/tree-sitter 基建 | GUI 显示 building→ready；R1 延迟对照持平（TTFB / assemble_ms 不变） |
| A2 | 通道 ① 工具钩子 + 脏队列 + content-hash 失效 + stale 单文件回落 | `edit_file`/`write_file` handler 成功路径加 enqueue（一行级侵入） | 编辑后 generation 变；篡改 mtime 场景下 hash 仍判对；delete 后查询无幽灵条目 |
| A3 | **Locate 粗筛接入**（§2.2，焊进 `search_codebase` 符号路径） | `tools/core/tools.py` Locate 分支加「索引候选 → LSP 确认」前置 | golden：索引 on/off 双轨——definitions 命中率不降、符号 Locate p50 墙钟下降；索引 off 行为与今日逐字节一致；**不以任何新工具调用数为 KPI** |
| A4 | 通道 ② run_command 轻扫（预算内）+ 通道 ③ 低频兜底轮询 | `run_command` handler 尾部 + lifespan 定时任务（仿 sources_watch） | 外部 `git checkout` 后 ≤1 轮询周期内追平；轻扫超预算正确转 `scan_pending` 不阻塞工具返回 |
| A5 | 多 Work LRU 淘汰 + GC purge job + 多账号 ACL 端到端 | 淘汰策略 + purge | 跨用户不可见；删 Work 级联清；投影内存有上限且淘汰可观测 |

依赖关系：A0→A1→A2 串行；A3 依赖 A1（有索引可查即可，不依赖 A2/A4 全齐）；A4/A5 可与 A3 并行。主方案 Wave 2（Verify/失败恢复等）**不依赖** 本文任何一步。

---

## 10. 风险与对策

| 风险 | 对策 |
|------|------|
| 大仓冷启动 parse 耗时/耗 CPU | 限并发（2–4）+ 单文件超时跳过 + 文件数/大小上限进 settings；building 期 Locate 走现行为，用户无感 |
| 投影内存膨胀（多 Work 常驻） | 惰性加载 + LRU/idle 淘汰（与 LSP 池 600s 同纪律）；每 Work 投影字节数进观测 |
| hash 计算成本 | 冷启动与重 parse 时和读文件同趟算（读都读了）；扫描快速路径只 stat 不读内容 |
| 索引候选与 LSP 结果不一致 | LSP 永远权威；候选仅决定「先看哪个文件」；错位候选被确认步自然过滤 |
| Postgres 写放大 | per-file blob + 批量事务（冷启动每 200 文件一批；增量单文件单事务，天然低频） |
| 多副本重复建索引 | advisory lock 单飞（复用 index_scheduler 先例）；无锁副本只读 |
| tree-sitter 语言覆盖不全 | `lang=skipped` 显式记录，只存 hash；该文件 Locate 走现行为；语言矩阵 Python-first（与主方案 §9.1 一致），grammar 构建期打入镜像，禁运行时下载 |
| `run_command` 轻扫误判/超时 | 只比 stat 不读内容；硬预算 + `scan_pending` 显式转兜底轮询；误判由 hash 权威层兜住 |
| 与用户/agent 并发编辑竞态 | 投影替换为原子操作（整 FileEntry 换）；查询时校验（§4.1）是最后一道闸 |

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

---

## 12. 修订记录

| 日期 | 修订 |
|------|------|
| 2026-08-11 | 从 `coding-structural-intelligence.md` §3.3.2–3.3.5 等拆出独立草案：工作区异步 AST、GUI、Work/DB、与 RAG/LSP/评测隔离 |
| 2026-08-11 | **v2（深度评审修订）**：新增 §0.1 可行性结论（三处不成熟：消费面未闭环 / 失效仅 mtime / 存储粒度未定，逐一修正）与 §0.2 成熟参照系（Cursor 对账、ctags defs-only、Zed 即时 parse 回落、SCIP 世代、Aider repo map 数据源）；§2 重写为 AST×LSP×词面结合面矩阵 + Locate 漏斗消费契约（焊进 `search_codebase`/`grep`，零新工具名）；§3.2 变更捕获三通道（工具钩子主 / run_command 轻扫 / 低频轮询兜底，对齐 sources_watch poll 先例）；§4 content-hash 权威失效 + 惰性恢复对账；§5 存储定型 per-file JSONB blob + 内存投影唯一查询面 + DDL 草案（含 works 无级联删除现状的显式 purge 要求）；§6.2 进度先复用 meta 快照 + 轮询先例（SSE 后置）；§8 R1–R5 映射与交互零感知清单；§9 落地序细化为 A0–A5（触点 + 验收 + 依赖）；§10 风险表；否决清单扩至 10 条 |
