# 27 — 多租户（Tenant / Work 绑定）

> **状态：设计已定 · 未开闸落地** · 2026-07-22  
> **定位：** 把单机自用栈升级为**更大的多人 Web 平台**时的划分结构——「谁登录、打开哪本作品/哪片世界、别人能不能看见」；迈向成熟 Agent 的关键一步。**不是** SaaS 清单打勾，也**不是**用多容器/多线程本身冒充租户隔离。  
> **硬约束：** [`13` R1–R5](13-rate-redlines.md)；不改 `AgentEngine` while；不改用户可见交互哲学（流式 / 取消 / Plan 同意门 / diff-first）。  
> **前置已落地：** [`16`](16-user-session-history.md) `owner_user_id` · [`23`](23-writing-work-model.md) Work-over-Session · [`15` §6](15-rag-and-sources.md) IX5/RE4 私有库草图 · [`17`](17-search-records.md) 多表 ACL 槽位  
> **关联：** [`02`](02-architecture.md) · [`03`](03-docker-runtime.md)（含多副本预案 §8.5）· [`07`](07-domain-model.md) · [`12`](12-model-harness.md) Intake/Guard

---

## 0. 一句话

多租户 = **在进 loop 之前**把本次 Turn 钉死到一个 **TenantScope（主体）+ WorkRoot（磁盘/索引作用域）**；loop / 工具 / 模型只看见「当前世界」，隔离靠**确定性谓词与路径沙箱**，禁止靠模型「记得别碰别人的数据」。

产品一句话：**同一套 api / runtime / web，服务多人；每人（每作品）有自己的划分，互不串味。**

```text
今天：  部署级 /workspace ≡ 全世界 ≡ 当前作品   （适合自用）
目标：  更大的 Web 平台：Principal → Tenant → Work → work_root
              └── Session*（对话线程，可换）
                    └── Turn/Run（仍 1:1；loop 不变）
```

**成熟度自检（目标态）：** 隔离结构成熟；执行面零感；**划分默认开启**；每个登录账号都是普通 Principal（含部署者本人）；Org/共享后置。

### 0.0 产品立场：默认开启 · 你就是普通用户

> **结论：** Tenant / Work 是默认骨架，不是开关。  
> **个人自用 = 你登录后的普通账号**，与第二、第三个用户走同一条路径——没有「主人模式 / 自用特例 / 管理员免划分」。

之前文档里「自用怕麻烦」的措辞容易误导：**对用户而言本来就不该麻烦。**  
麻烦只可能出在工程迁移（把旧 `/workspace` 认领成默认 Work）；产品路径上，你和任何用户一样：

```text
登录账号 (Principal)
  → 若尚无 Work：自动创建一个默认 Work（跟账号走）
  → 打开/恢复一个 Session（跟账号走，且绑在某个 Work 上）
  → 发消息跑 Turn（跟 Session；作用域来自 Session.work_id）
```

| 错误心智 | 正确心智 |
|----------|----------|
| 部署者是特殊上帝用户 | 部署者登录后也是 **普通 Principal** |
| 自用要关多租户才不烦 | 自用 = 普通用户 + 通常只有 1 个默认 Work |
| 多租户是给「别人」用的 | 划分对**每一个**账号生效；一人时库里刚好只有你的数据 |
| 要用户理解 tenant/mode | 用户只看见：登录、会话列表、（可选）作品；Agent 交互不变 |

Web：不强迫选租户；单 Work 时甚至不必露「作品」控件。多人同栈时自然各看各的——因为各是各的账号。

---

## 0.1 你的理解对齐：平台划分 vs 多容器 / 多线程

**对：** 这件事的本质是 **Web 平台的多人划分**——登录用户 A/B、作品 1/2、资料与会话列表按归属切开；Agent 仍是「打开一个世界里干活」。多用户并发变多以后，**往往会**需要多进程 / 多容器 / worker 线程来扛吞吐，所以体感上「和多容器有关」。

**需要拆开的两层（相关、但不是同一个问题）：**

| 层 | 回答的问题 | 典型手段 | 没有它会怎样 |
|----|------------|----------|--------------|
| **划分面（本文）** | 谁能看见哪片世界？ | `owner` / `work_id` / `work_root` / 检索谓词 | 即使用一个容器，两人同栈也会串资料 |
| **扩容面（[`03` §8.5](03-docker-runtime.md)）** | 同时跑多少 Turn？挂了谁接手？ | api/runtime 多副本、worker、Turn 亲和、共享卷 | 划对了也会挤在单 runtime 上变慢 |

```text
多人 Web 平台
  ├─ 划分面  Tenant / Work / ACL / 列表过滤     ← 多租户（逻辑产品边界）
  └─ 扩容面  多容器 · 多 worker · 队列 · 亲和   ← 水平扩展（部署边界）
         │
         └─ 两者接头：任意副本执行某 Turn 时，都必须能解析同一 TenantContext
                      + 读到同一 work_root（共享存储或按 work 路由）
```

**结构结论：**

1. **先划分、后扩容**——没有 `work_id`/`work_root`，加副本只会让串味更快、更难查。  
2. **多容器 ≠ 多租户**——「一用户一容器」是运维级硬隔离备选，成本高；本设计默认 **同栈逻辑多租户**，容器数跟负载走，不跟用户数 1:1。  
3. **多线程 / 多 worker ≠ ACL**——并发只保证「同时跑」；「不能读别人的」仍靠谓词与路径沙箱。  
4. **扩容时多租户的约束**（与 [`03` §8.5](03-docker-runtime.md) 对齐）：共享 `/data`（或对象存储）上按 `works/{work_id}` 分区；`runs.runner_id` + 命令路由；同 Work 写冲突策略；**禁止**把隔离赌在「请求碰巧打到同一进程的内存」。

一句话：**多租户是平台「怎么切用户世界」；多容器是平台「怎么切机器负载」——成熟大平台两层都要，但第一刀是划分面。**

---

## 0.2 跟着什么走？活跃态？冷启动 / 热启动？

### 跟着账号走的（Principal / `owner_user_id`）

| 对象 | 是否跟账号 | 说明 |
|------|------------|------|
| 登录会话（cookie / token） | ✅ | 已有 [`16`](16-user-session-history.md) |
| 默认 Work、名下 Work 列表 | ✅ | 账号首登保证 ≥1 个默认 Work |
| Session 列表与硬删除权 | ✅ | `sessions.owner_user_id` |
| 私有资料 / 记忆的**归属** | ✅（经 Work） | 行上 `owner_id`；执行仍看 `work_id` |
| Agent loop / 工具表 / Plan | ❌ | 跟 Scenario + 当前 Turn，不跟「是不是你本人」变逻辑 |

**书稿与 sources 的真源跟 Work 走，不跟「当前聊天窗口」走**（续 ADR-020）：换 Session 书还在；换账号则进别人的世界（看不见）。

### 活跃态（产品层 · 不进 loop）

「活跃」是**控制面 + Web 的指针**，不是 runtime 里常驻的用户进程：

```text
浏览器 / 客户端
  last_principal          ← 登录态
  last_work_id            ← 当前打开的世界（单 Work 时可省略 UI）
  last_session_id         ← 当前对话线程
       │
       ▼ 每次 POST /turns
Session 已绑定 work_id → 解析 TenantContext → StartTurn
       │
       ▼
Run 在跑 = 唯一真正的「执行活跃」；Cancel 只打这个 run_id
```

| 状态 | 存哪 | 丢失会怎样 |
|------|------|------------|
| 登录 | cookie / DB | 要重新登录；Work/书稿仍在 |
| 当前 Work | 服务端偏好或 Session 绑定 | 回默认 Work |
| 当前 Session | Web 路由 + DB | 从历史抽屉再点开；transcript 在 DB |
| 正在跑的 Turn | `runs` + 事件 | 刷新可 SSE 续；Cancel 走 DB 标志（ADR-015） |

**不**为每个在线用户保一个热进程或热容器。在线只是「能发命令」；忙的是**并发活跃 Turn**（见 §8.2）。

### 冷启动 / 热启动（拆三层，避免混谈）

| 层 | 冷 | 热 | 与多租户关系 | 速率纪律 |
|----|----|----|--------------|----------|
| **账号 / 产品** | 首次注册：建 Principal + 默认 Work +（可选）空 Session | 再登录：恢复 last_session / 列表 | 冷启动多一次「确保默认 Work 存在」（Turn **外**，毫秒～一次插入） | **禁止**把建 Work 塞进首 token 前的同步重活以外；若缺 Work，在建 Session/进工作台时补齐，可早于发消息 |
| **Work / 索引** | 新 Work 或久未访问：索引空或滞后 → 检索 keyword 兜底 + `index_lag` | 近期搜过/watch 过：索引在 PG / 内存缓存 | 按 `work_id` 分区预热；**禁止**为「某人打开了页面」同步全量建索引 | R4：索引旁路；与今日 IX 铁律一致 |
| **进程 / 基础设施** | 容器刚起：加载嵌入模型、连库、watch 启动 | 模型已在内存、池已热 | **全站共享**热路径，不按用户各烧一份大模型到内存 | 预热属部署/旁路（已有 debounce 预热方向）；**不**按账号冷启一个 runtime |

```text
你打开网页
  ├─ 产品热？  有 cookie + 默认 Work + 可点的 Session    → 普通用户日常
  ├─ 索引热？  该 Work 的 chunks 是否已 sync            → 旁路；冷则降级搜
  └─ 进程热？  runtime/api 是否已 healthy + 模型已加载 → 与有多少用户无关
```

**委托 / 子 Agent：** 继承父 Turn 的 `TenantContext`（同一账号同一 Work），不单独冷启一套租户世界。

**CI：** 每个 case 相当于「临时普通用户 + 一个 Work」的热/冷由夹具控制，无上帝旁路。

---

## 1. 为什么这是「成熟 Agent」的关键一步

### 1.1 成熟 Agent 真正隔离的是什么

Cursor / Claude Code 类产品的体感不是「每个工具参数里带 tenant_id」，而是：

| 成熟形态 | 含义 |
|----------|------|
| **一个打开的世界** | 当前 project / workspace 是工具的根；出界即失败 |
| **对话 ≠ 世界** | 可新开 chat，世界不跟着拆（对齐已做的 Work-over-Session） |
| **权限在平台** | 读不到的文件根本不在工具可见面；不是靠 system 文案劝阻 |
| **检索同界** | 搜只命中当前世界（及显式共享集）；不靠 LLM 做 ACL |

本仓库已验证同一哲学的两刀：

1. **Session 不当作品容器**（[`23`](23-writing-work-model.md) / ADR-020）  
2. **RAG 热路径不加裁判模型**（[`15`](15-rag-and-sources.md)；否决 LLM-ACL）

多租户是同一刀的**第三面**：把「单机自用默认全世界可读」升级为「主体有私有世界」，否则：

- 多用户同栈时资料/书稿/记忆串味 → **交付诚实性与信任崩盘**（比慢更致命）  
- 评测与线上无法证明「deny 成立」→ **Proof 面缺口**  
- 后续 `search_records`、Skills、多作品切换会被迫在错误边界上打补丁  

### 1.2 多租户 ≠ 改 Agent 交互

| 用户仍应感到 | 平台在底下多做的 |
|--------------|------------------|
| 发消息 → 立刻受理 → 流式 | StartTurn 解析 `work_root`（毫秒级） |
| Stop / Cancel 语义不变 | 作用域已钉死，取消只停本 Run |
| 工具名、Plan、diff 不变 | 工具执行落在 `work_root` 内；越界确定性拒绝 |
| 检索「像以前一样按需」 | `search_*` 自动带 owner/work 谓词；模型无感 |

**禁止**把多租户做成：每轮意图分类「这是谁的数据」、每工具多一轮授权对话、或租户选择器挡在首 token 前。

---

## 2. 两条硬门槛（本文宪法）

> 任何实施方案若触碰下列红线，直接否决——与 [`26`](26-plan-suggest-complexity.md) 同级。

### 2.1 不影响 Agent 交互逻辑

**冻结（多租户全程零改动语义）：**

| 冻结项 | 说明 |
|--------|------|
| `AgentEngine` while | 仍 assemble → model → tools → checkpoint |
| 工具主路径哲学 | 能力走工具；不预灌他租户资料 |
| Plan 同意门 / `plan_phase` 硬闸 | [`25`](25-writing-runway.md) 不动 |
| Cancel / 超时 / stall | ADR-015/016 语义不动 |
| Scenario 扩展方式 | 仍 Profile + 工具白名单；**禁止** `if tenant` 进引擎业务分叉 |
| Writing 作品树概念 | 仍 outline / manuscript / `.agent/work`；只是根路径上移到 `work_root` |

**允许改的（仅绑定面 / 存储面）：**

- api 鉴权后解析 `TenantContext`，写入 StartTurn 命令（或 Run 侧只读快照）  
- 磁盘与索引按 `work_id` / `owner_id` 分区  
- 工具执行器与检索层注入**确定性**路径根与 SQL 谓词  
- Web：作品/空间切换（Turn **外**）；列表按 owner 过滤（已有会话历史同型）

### 2.2 不影响 Agent 交互速率（R1–R5）

| 红线 | 对本方案的含义 |
|------|----------------|
| **R1** | 租户解析不得推迟 `turn.accepted`：用会话已绑定的 `work_id` 做主键查找 / 进程内缓存；禁止 Turn 内同步扫盘枚举全部租户 |
| **R2** | **禁止**为 ACL / 路由再调模型（含小模型分类器） |
| **R3** | 热路径仅：解析 UUID、拼路径前缀、SQL `AND owner_id = $1`；禁止重加密握手挡在 assemble 前 |
| **R4** | 建索引、权限变更扩散、配额结算 → 异步 / 离线 |
| **R5** | deny/allow golden；**单默认 Work 自用路径**与双用户 deny 均须绿 |

**否决清单（速率 × 成熟度）：**

- 查询路径建库 / per-session 索引（已否，见 [`15`](15-rag-and-sources.md)）  
- **LLM-ACL**（「模型判断能不能看」）  
- 每条工具调用远程问权限服务且无缓存、无超时预算  
- 把「选择租户」做成 Turn 内必答问卷  
- 为多租户恢复固定 pipeline 或监督者图  

---

## 3. 结构模型（核心）

### 3.1 四层对象（稳定分层）

```text
Principal          登录主体（user_id；远期 org_member）
  └── Tenant       计费/隔离边界（个人租户 = user；组织租户 = org）
        └── Work   一个「打开的世界」：书稿 + sources + 记忆命名空间 + 沙箱根
              └── Session*   对话线程（可多条；可换；不拥有作品文件）
                    └── Turn/Run/Step   现有领域模型不变
```

| 对象 | 拥有什么 | 不拥有什么 |
|------|----------|------------|
| **Principal** | 凭证、默认租户 | 文件真源 |
| **Tenant** | 成员关系、配额、默认可见性策略 | loop 状态 |
| **Work** | `work_root`、作品树、私有 sources、索引分区键 | 对话 transcript |
| **Session** | transcript、审批、压缩窗、**绑定的 work_id** | 章节目录树（已由 [`23`](23-writing-work-model.md) 否定） |

**铁律：**

1. **隔离键 ≠ `session_id`**（[`15` §6](15-rag-and-sources.md) 已写；此处升级为宪法）  
2. **隔离键主键 = `work_id`（执行）+ `tenant_id`/`owner_id`（归属与索引）**  
3. Session **必须**绑定恰好一个 `work_id`（创建时写入；变更走显式「切换作品」API，不在 Turn 中默变）  
4. Runtime **只解析当前 Work 根**；不枚举兄弟 Work  

### 3.2 普通用户路径（含部署者本人）

**没有自用特例，也没有 `TENANT_MODE`。** 任何人登录都是同一套：

| 场景 | 结构上发生什么 | 用户感到什么 |
|------|----------------|--------------|
| **任意账号（含你）** | 确保默认 Work → Session 绑定 `work_id` → Turn 带 TenantContext | 登录、聊天、写书；单 Work 时无额外步骤 |
| **CI / golden** | 夹具账号或夹具 Work；谓词始终在 | 评测稳定；无「关 ACL」分叉 |
| **第二账号同栈** | 另一个 Principal + 其默认 Work | 互相不可见 private——同一产品行为 |
| **多作品 UI（后置）** | 同账号多个 Work；切换在 Turn 外 | 可选；单作品用户不必看见 |

迁移：旧「整盘 `/workspace`」在**第一个账号**首登时认领为该账号的默认 `work_root`（一次），不是永久旁路。

种子/只读语料（现有 `sources/seed/**`）继续 **只读挂载进每个 work 的逻辑视图或全局可读分区**，索引行带 `visibility=seed|shared|private`，避免为种子复制 N 份实体文件。

**原则：** 工具与写作路径语义（`manuscript.md`、`.agent/work/drafts/...`）**相对 work_root 不变**——多租户是根上移，不是再发明一套写作模型。

### 3.3 路径布局（推荐）

```text
/data/works/{work_id}/          # work_root
  outline.md
  manuscript.md
  sources/
  .agent/work/...
```

个人单默认 Work 部署：允许 `work_root` **原地等于**今日 `WORKSPACE_ROOT`（`/workspace`），避免强迫搬家；多 Work 或多人时再落到 `works/{id}` 分区。

### 3.4 TenantContext（进 Run 的只读快照）

在 **Turn Intake / StartTurn 边界**（控制面或 runtime 入口一次）解析并冻结：

```text
TenantContext {
  tenant_id
  principal_id          # = owner_user_id 复用 16
  work_id
  work_root             # 绝对路径；工具沙箱 chroot/前缀
  visibility_seed       # 是否可搜全局 seed
  resolved_at
}
```

- **无 `mode` 字段**——划分始终生效；差异只在「有几个 Work / 是否 Org 成员」，不在开关  
- 写入 Run 侧只读字段或 execution checkpoint 旁路；**逐步不变**  
- 模型 **不可见** 完整 TenantContext（勿塞进 messages）；需要时只以「当前项目根」类短 runtime_context 出现（字符硬顶，对齐 work index）  
- 切换 Work = 新 Session 或显式 rebind API；**禁止**同 Run 中途换根  

这与 Harness **Intake** 面同构：确定性编译输入，不把策略塞进引擎分叉。

---

## 4. 平面分工（结构合理的关键）

成熟平台把「租户」拆到不同平面，避免一个中间件包打天下：

```text
┌─────────────────────────────────────────────────────────┐
│ Identity / Control（api）                                │
│  鉴权 · Session CRUD 按 owner · Work 绑定 · StartTurn    │
│  租户解析毫秒级；失败 → 4xx，不进 runtime loop           │
└───────────────────────────┬─────────────────────────────┘
                            │ TenantContext（冻结快照）
┌───────────────────────────▼─────────────────────────────┐
│ Execution（runtime loop）                                │
│  无租户业务分支；ToolExecutor 强制 path ∈ work_root      │
│  search_* / remember 自动 AND 作用域谓词                 │
└───────────────────────────┬─────────────────────────────┘
                            │ 异步
┌───────────────────────────▼─────────────────────────────┐
│ Index（旁路）                                            │
│  chunks 带 work_id/owner_id/visibility；变更才重建       │
│  热路径只 load+search（15 铁律）                         │
└─────────────────────────────────────────────────────────┘
```

| 平面 | 多租户职责 | 禁止 |
|------|------------|------|
| **控制面** | 谁能建 Session、绑哪 Work、SSE 只推自己的 Turn | 在 SSE 里做 ACL 推理 |
| **执行面** | 沙箱根 + 工具边界拒绝 | `if tenant_id` 改写作文案逻辑 |
| **索引面** | 行级归属；异步同步 | 查询时建库 |
| **记忆面** | `remember`/`recall` 命名空间含 `work_id` 或 `tenant_id` | 每轮盲召跨租户记忆 |
| **投影面** | TurnView / 历史列表按 owner | 用关键词「猜」可见性 |

---

## 5. 能力切片如何挂接（不改交互）

### 5.1 文件与沙箱

- 所有相对路径解析：`abspath = work_root / rel`；规范化后必须仍以 `work_root` 为前缀  
- `run_command` / 写工具：工作目录默认 `work_root`；审批策略不变  
- 越界 → 工具失败结果（确定性），**不**升级为模型可协商的「申请访问」默认流（若未来做共享，走控制面授权，不进热路径问卷）

### 5.2 RAG / sources（落地 IX5 / RE4）

对齐 [`15` §6](15-rag-and-sources.md)，本文定序：

| 要 | 不要 |
|----|------|
| 索引行带 `owner_id` / `work_id` / `visibility` | 用 `session_id` 当隔离键 |
| `search_sources` 入口注入谓词 | 模型传 `owner_id` 参数（可伪造） |
| seed 只读全局或显式 shared | 默认可搜全站 private |
| 单默认 Work 自用路径与今日等价（相对路径语义） | IX0 焊死无 owner/work 列又无法迁 |
| 谓词始终由服务端注入 | 靠「关掉 ACL」过日子 |

开闸：真实多用户不可互看；deny golden；**单人默认 Work** 交互与今日同型。身份复用 [16](16-user-session-history.md) 的 `owner_user_id`；作品根见 [23](23-writing-work-model.md) / [27](27-multi-tenancy.md)。

### 5.3 记忆（Tool / Memory）

- `remember` / `recall` 的存储键：`ns = (work_id | tenant_id, name)`  
- 禁止跨 Work 默认同名合并  
- 仍由模型**按需**调工具；系统不因多租户改为每轮预注入  

### 5.4 `search_records`（[`17`](17-search-records.md)）

- 开闸时每个 RecordChannel 与查询同层带 ACL 谓词  
- 空结果 vs 超时 vs deny 可区分；禁止同步全表扫描  
- 多租户是 RE5 的前置结构，不是并行另一套 graph  

### 5.5 写作作品与多作品

[`23` §11](23-writing-work-model.md) 升级为第一公民：

```text
User/Tenant → Work(work_id) → work_root → outline/sections/.agent/work
                  └── Session*（对话，可多人只读协作后置）
```

- **多作品** = 多 Work 切换（控制面 + Web），不是多 Session 目录树  
- 短 work index 仍相对当前 `work_root` 生成（R2：无额外 LLM）  

### 5.6 委派 / 子 Agent

- 子 Run **继承**父 `TenantContext`（同一 work_root）  
- 禁止委派时传入「更高权限」或跨 Work 指针  
- 摘要回灌仍只含文本/相对路径；路径解析仍受父根约束  

---

## 6. 控制面 API 形状（示意）

> 契约细节落地时进 `packages/contracts`；此处定边界。

| API | 作用 | 热路径？ |
|-----|------|----------|
| `POST /works` | 创建作品（分配 work_id + 初始化树） | 否（Turn 外） |
| `GET /works` | 当前主体可见作品列表 | 否 |
| `POST /sessions` | **必填或默认** `work_id`；写入绑定 | 否 |
| `POST .../turns` | 只读 Session 上已绑定 work；解析 TenantContext | 是（须毫秒） |
| `POST /works/{id}/shares`（后置） | 显式共享 | 否 |

会话历史 [`16`](16-user-session-history.md) 过滤规则扩展为：`owner_user_id` **且**（可选）`work_id` 范围；不把全文塞进历史抽屉。

---

## 7. 安全默认值

| 默认 | 理由 |
|------|------|
| **默认 deny** 他人 private | 成熟产品默认；共享显式 |
| **模型不可选隔离键** | 防提示注入伪造 `owner_id` |
| **Context 冻结在 Run 始** | 防中途提权 / 换根 |
| **日志脱敏已有 Guard 保留** | 多租户不取代 PII 规则 |
| **错误信息少泄漏** | deny 与 miss 对外可同型「0 hits / not found」，对内可观测字段区分 |

**威胁模型（最小）：** 恶意用户改 tool 参数路径、提示注入「忽略 ACL」、越权调内部 API。缓解：路径沙箱 + 服务端注入谓词 + 内网 runtime 不暴露。

---

## 8. 性能、容量、空间与一致性

> 本节回答：「会不会拖慢 Agent？」「能撑多少人？」「要几个容器/多少线程？」「数据会不会乱？」  
> **口径：** 多租户划分面**不**自动等于扩容面；数字是**工程预算与默认拓扑下的数量级**，不是已压测 SLA。上线前须用并发 Turn 压测校准。

### 8.1 全流程交互速率预算（注册 → 聊天 → 工具 → 切换）

> **口径：** 下表是「相对**今日无 Work 划分**」的**增量**，不是绝对耗时。  
> 绝对体验仍由模型 TTFT、网络、磁盘主导。数字为工程预算（单机 Postgres、索引命中时）；落地用计时断言校准。  
> SLO 仍以 [`10`](10-product-experience.md) 为准：**不因本方案放宽**。

#### 总判

| 问题 | 答案 |
|------|------|
| 对日常发消息 / 流式 / Stop 的体感？ | **通常无感**（增量 ≪ 模型与网络噪声） |
| 哪里会多一点时间？ | **仅一次**：注册/首登确保默认 Work；以及检索 SQL 多一个等值条件（微秒～亚毫秒级） |
| 哪里绝对不许变慢？ | `turn.accepted`（TTFB）、Cancel、首 token 前不得加同步 LLM/建索引 |
| 交互逻辑变了吗？ | **不变**——多的是账号下多一个 Work 指针，不是新对话剧情 |

#### 旅程逐段

```text
注册/登录 → 进工作台 → 列会话 → 开/建 Session → 发消息(TTFB)
  → 首 token → 工具(搜/读/写) → 流式续 → Stop/Cancel
  → 切会话 /（可选）切 Work → 再发消息
```

| # | 步骤 | 今日大致成本 | 本方案增量 | 体感 | 纪律 |
|---|------|--------------|------------|------|------|
| 1 | **注册** `POST /register` | 写用户 + hash 密码 | **+1～2 次写**：默认 Work 行 + 可选认领/建 `work_root` 目录 | 注册本就「等一下」；+**数 ms～几十 ms**（本机盘）通常无感；若同步拷贝大资料则禁止——只建空树或认领路径 | Turn 外；可 `201` 后异步 init 树，但 **Session 创建前**须 Work 已存在 |
| 2 | **登录** | 验密 + Set-Cookie | **+0～1 次读**「默认 work_id」（可并进用户行） | **无感** | 不进 Turn |
| 3 | **打开 Web / 工作台** | 拉 bootstrap、场景壳 | 单 Work：**+0 UI**；多 Work 才多一次 `GET /works`（Turn 外） | **无感**（单账号单作品） | 列表分页；禁止首屏扫全站 Works |
| 4 | **会话列表** [`16`](16-user-session-history.md) | `WHERE owner_id=` | 可选再 `AND work_id=`（有索引则同量级） | **无感** | 离 Turn 热路径 |
| 5 | **新建 Session** | INSERT session | **+绑定 work_id**（默认 Work，无用户选择） | **无感** | 缺默认 Work 则此处补建（仍 Turn 外） |
| 6 | **打开旧 Session** | 切 `sessionId` + 载 transcript | 读出已绑 `work_id`，无额外轮次 | **无感**；续聊逻辑不变 | 不改 loop |
| 7 | **发消息 → TTFB**（`turn.accepted`） | api 建 Turn/Run + 转发 runtime | **+一次 PK/缓存解析** TenantContext（Session→Work→root） | **目标增量 ≤ 1～5 ms**（本地库）；相对 SLO 300ms 可忽略 | **R1**：Work 必须已在 Session 上；禁止此处建目录/建索引/调模型 |
| 8 | **首模型 token** | Intake + assemble + provider | 路径沙箱已在 Context 里；**不**为 ACL 加模型 | **增量 ≈ 0**（相对 TTFT 百 ms～数 s） | **R2** |
| 9 | **写作 work index 短注入** | 已有目录列举 | 根换为 `work_root`，列举量不变 | **与今日同阶** | 字符硬顶；无 LLM |
| 10 | **`search_sources` 等检索** | BM25/向量/RRF | `AND work_id=$1`（或 owner） | **通常无感**；错误实现（无索引、先搜全表再滤）才会变慢——**禁止** | 复合索引；(work_id, …)；热路径不 sync |
| 11 | **`read_file` / patch / 写盘** | 路径拼 WORKSPACE_ROOT | 改拼 `work_root` + 前缀校验 | **微秒级**；与今日沙箱同类 | 越界立即失败，不重试模型 |
| 12 | **`remember` / `recall`** | 按 ns 查 | ns 含 work_id | **无感** | 不盲召 |
| 13 | **`delegate`** | 子 Run | 继承同一 TenantContext，**零解析税 × 子步** | **无感** | 禁止子 Agent 换根 |
| 14 | **流式 SSE / 投影** | 按 turn 推事件 | 不按租户多一轮鉴权推理 | **无感**；鉴权仍是「是否本人的 turn」 | 不在 SSE 里做 ACL 模型 |
| 15 | **Stop / Cancel** | 双通道 DB + 命令 | 不改语义；仍打 `run_id` | **无感**；SLO 不放宽 | ADR-015 |
| 16 | **切 Session** | 换 id + 载 transcript | 换绑带的 work（通常同一默认 Work） | **无感** | Turn 外 |
| 17 | **切 Work**（后置、可选） | — | 新 Session 或 rebind + 可能冷索引 | **仅切换瞬间**可能感到「这本作品检索尚在建」；**不**挡别的 Session 发消息 | 切换在 Turn 外；索引 R4 旁路 |
| 18 | **登出 / 再登录** | 清 cookie | 无额外租户握手 | **无感** | — |

#### 用户可感知的「总时间」里多租户占多少

一次典型「登录 → 发一句 → 等回复」：

```text
登录网络+验密     ~ 50–200ms+     增量 ~0
建/开 Session     ~ 10–50ms       增量 ~0–5ms（绑 work_id）
TTFB accepted     SLO ≤300ms      增量 ~1–5ms
首 token / 全文   数百 ms～数 s   增量 ~0（模型）
工具检索          数十～数百 ms   增量 ≪1ms（谓词）或 0（未搜）
────────────────────────────────
多租户占端到端    通常 < 1%～数 %；注册当日首次略高（建默认 Work）
```

**结论一句话：** 全流程里，多租户是**控制面指针与查询谓词**的税，不是 Agent 交互税；注册多一次轻量写，聊天主路径在噪声以下——**前提是不把建索引/搬文件/LLM-ACL 塞进热路径。**

#### 反模式（会把「无感」做成「明显卡」）

| 反模式 | 后果 |
|--------|------|
| 每次发消息同步 `ENSURE WORK` + 扫盘建树 | TTFB 抖 |
| 每次 search 先全库再在应用层滤 owner | 用户越多越慢 |
| 注册时同步复制 seed 语料到私有目录 | 注册卡死 |
| 打开工作台为所有 Work 预热嵌入 | 首屏变部署 |
| 为「确认是你的数据」同步调小模型 | 破 R2，首 token 明显变慢 |

#### 验收建议（速率）

| 门禁 | 做法 |
|------|------|
| 回归 | 单默认 Work：关键 golden / smoke 与今日同阶（允许计时 ±噪声） |
| TTFB | 对比补丁前后 P95 `turn.accepted`；增量预算 **≤5ms**（同机）或相对基线 **≤2%** |
| 注册 | 建用户+默认 Work P95 预算单独列（如 ≤200ms 本机 DB），不计入 Turn SLO |
| 检索 | 同题 `search_sources` 延迟分布；有 `work_id` 索引时不得系统性变差 |
| 禁止项 | 热路径无 sync index、无 LLM-ACL（日志/代码扫描） |

**多租户本身几乎不吃交互预算**；真正吃预算的仍是：模型 TTFT、工具 I/O、同进程并发 Turn 争用、嵌入/索引旁路。

### 8.2 能支撑多少人同时用？（先分清三个「同时」）

| 指标 | 含义 | 默认单栈（今日拓扑）数量级 | 主要瓶颈 |
|------|------|---------------------------|----------|
| **注册/登录用户** | 账号与会话列表 | **10²～10³** 轻松（api + Postgres） | DB 连接、历史列表分页 |
| **在线空闲会话** | 开着页、偶发 SSE | **几十～一百+** | api SSE / DB LISTEN；几乎不跑 loop |
| **并发活跃 Turn** | 正在跑 agent（等人回） | **约 5～15**（单 `runtime` 副本、共享模型供应商） | 模型限流与延迟、runtime 事件循环争用、检索/嵌入 CPU |
| **同 Work 并发写** | 两人改同一书稿 | **默认按 1 活跃写者**设计 | 文件后写覆盖；须产品策略（见 §8.5） |

解读：

1. **「同时使用」若指登录人数** → 划分面（多租户）是关键；容量主要在 api/Postgres，**不是**一人一容器。  
2. **「同时使用」若指同时有人在等 Agent 回复** → 看 **并发活跃 Turn**；与租户数弱相关，与 **runtime 副本数 × 每副本软上限 × 模型配额** 强相关。  
3. 今日实现：`POST /start-turn` → `BackgroundTasks` 进**同一** asyncio 进程（单 uvicorn worker 典型形态）；**无**硬编码「最多 N 个 Turn」闸——过载时先表现为变慢/供应商 429，而不是干净排队（**缺口：MT 扩容期应加可观测的并发闸 + 队列**）。

**粗算示例（规划用，非承诺）：**

```text
目标：50 个登录用户，高峰 10% 同时在跑 Turn → ~5 并发 Turn
  → 默认 1×runtime 通常可撑（模型配额充足时）
目标：200 登录，高峰 10% → ~20 并发 Turn
  → 需 ≥2 runtime 副本 + 共享存储 + Turn 亲和（03 §8.5），或限流排队保 SLO
```

多租户 **不**把「200 用户」变成「200 容器」；它只保证这 200 人的世界不串。

### 8.3 容器数量要求？

| 组件 | 默认（compose） | 多租户第一刀 | 何时加副本 |
|------|-----------------|--------------|------------|
| gateway / web | 1 | 1 | 静态流量大时 |
| api | 1 | 1～2 | SSE/REST 成为瓶颈；无状态宜扩 |
| **runtime** | **1（强制到 Phase 2）** | **仍 1，直到并发 Turn 顶 SLO** | Phase 3+：须 `runner_id`、命令路由、共享卷（[`03` §8.5](03-docker-runtime.md)） |
| postgres | 1 | 1（可上托管） | 连接数/IO；与租户数弱相关 |
| outbox worker | 常 inline | 索引量大时独立 | 旁路，不挡 Turn 受理 |

**硬要求：**

- **不要求**「用户数 = 容器数」或「租户数 = runtime 数」。  
- **要求**所有 runtime 副本看到**同一逻辑存储**（共享 `/data` 或按 `work_id` 可寻址的对象存储），否则划分面在副本间破裂。  
- **要求** Cancel / Approve 能路由到持有该 `run_id` 的 runner（已有 `runner_id` 字段方向）；多副本前保持 `replicas: 1`。

### 8.4 线程 / 进程数量要求？

| 模型 | 本设计立场 |
|------|------------|
| 线程/用户 | **否**。不按用户起线程 |
| 进程/Turn | **否**。Turn 是 asyncio 任务（BackgroundTasks） |
| 进程/runtime 副本 | **是**扩容单位；每副本内并发跑多个 Turn |
| 临时线程池 | 仅局部（如 dual-lane 检索 `max_workers=2`、嵌入库内部）；**不**随租户线性涨 |

**建议运维旋钮（落地时再做成 settings，此处定方向）：**

| 旋钮 | 作用 | 与交互关系 |
|------|------|------------|
| `RUNTIME_MAX_INFLIGHT_TURNS` | 单副本并发 Turn 软上限；超额 503/排队 | 保 TTFB/首 token；**不**改 loop 语义 |
| uvicorn workers | 默认 1（与内存 checkpoint/亲和更简单）；多 worker 须视同多副本纪律 | 乱开 workers 而无 runner 路由 → 审批/取消可能打空 |
| DB pool size | api/runtime 连接池 | 过小会拖 TTFB；过大冲垮 Postgres |
| 索引/watch | 旁路；可降频 | 禁止抬进热路径 |

### 8.5 空间（磁盘 / 索引）需求

| 数据 | 增长因子 | 策略 |
|------|----------|------|
| `works/{work_id}/` 书稿与 sources | ∝ 用户上传与成稿 | 每 Work 配额（后置）；超限拒上传，不挡已开 Turn 的受理 |
| pgvector chunks | ∝ 私有资料体量 × 用户数 | 行带 `work_id`；按 Work 增量同步；GC 删除 Work 时级联 |
| seed 语料 | 常数（只读挂载） | **禁止**按租户复制实体；`visibility=seed` 共享 |
| session transcript / events | ∝ Turn 数 | 已有滚动/压缩；按 owner 可删会话（[`16`](16-user-session-history.md)） |
| `.agent/work/history` | ∝ 草稿快照 | 已有 keep 上限（[`23`](23-writing-work-model.md)） |

**空间铁律：** 多租户增加的是**分区与配额维度**，不是「每人一份完整模型镜像」。嵌入模型仍在共享 `DATA_DIR/models`。

### 8.6 数据一致性与其它后端要求

多租户把「一致性」拆成几条必须同时成立的纪律（与现有事件模型对齐）：

| 域 | 要求 | 做法 |
|----|------|------|
| **Turn 执行** | 同一 `run_id` 仅一个 runner 执行 | claim + `runner_id`；多副本前单副本 |
| **事件序** | SSE/投影可重建 | `turn_events.sequence` 单调；并发 append 已有测 |
| **投影** | `TurnView` ≡ 事件终态 | 异步投影；以事件为真相（[`08`](08-event-projection-pipeline.md)） |
| **Cancel** | 双通道最终生效 | DB 标志 + 命令转发（ADR-015）；不依赖「打到同一内存」 |
| **TenantContext** | Run 期间不可变 | StartTurn 冻结快照；禁止中途换 `work_root` |
| **文件真源** | 同 Work 多写者 | **默认乐观**：后写覆盖草稿；正式稿仍走 patch；产品可加「单活跃编辑锁」（Turn 外，不进 loop） |
| **检索索引** | 与磁盘最终一致 | 异步 sync；允许短暂 `index_lag`；查询不建库（[`15`](15-rag-and-sources.md)） |
| **ACL 生效** | 权限变更 | 下一 Turn / 下一查询生效即可；**禁止**为立刻全局一致而同步重建全库 |
| **跨副本存储** | 读己之写 | 共享卷或强一致对象存储；本地盘仅单副本 |

**明确不追求（本阶段）：** 跨区域多活、租户级可串行快照隔离、文件 CRDT 协同编辑。

### 8.7 对「当前这套方案」的诚实结论

| 问题 | 结论 |
|------|------|
| 会影响 Agent 交互逻辑吗？ | **设计上不允许**；落地门禁 = 单默认 Work 路径回归 + 无引擎分叉 |
| 会影响交互速率吗？ | **划分面增量应可忽略**；速率风险来自并发 Turn 与模型，不来自 `work_id` 列 |
| 现在能撑多少人？ | **登录很多；同时跑 Agent 约个位数～十余路 / 单 runtime**（视模型配额） |
| 容器要多少？ | **默认各 1**；按并发 Turn 加 runtime，不按用户数加 |
| 线程要多少？ | **不按用户开线程**；asyncio 多 Turn + 少量工具线程池 |
| 一致性？ | **事件 + claim + 冻结 Context + 索引最终一致**；同 Work 多写者需产品锁或接受后写覆盖 |

未做并发闸与多副本路由前，**不要**对外承诺「百人同时写作都跟手」——应承诺「百人划分不串味；同时活跃 Turn 按副本与配额扩展」。

---

## 9. 分期落地（建议票）

| 票 | 内容 | 验收 |
|----|------|------|
| **MT0** | 本文 + ADR-021；`README` / `15` / `16` / `23` 交叉引用 | 设计评审通过 |
| **MT1** | `TenantContext` 始终解析；首启自动默认 Work；`work_root` 可认领 `/workspace` | runtime-test + eval-all 全绿；个人路径零仪式 |
| **MT2** | `works` 表 + Session.`work_id`；路径沙箱；写作相对根不变 | 双用户不能互相 `read_file` 对方稿（deny） |
| **MT3** | 索引行 `owner_id`/`work_id`；`search_sources` 谓词；seed visibility | IX5 deny golden + 单默认 Work 回归 |
| **MT4** | `remember`/`recall` 命名空间隔离 | 跨用户 recall 空 |
| **MT5** | Web 作品列表/切换（Turn 外） | 切换后新 Session 绑新 Work；旧 Session 不变根 |
| **MT5b** | `RUNTIME_MAX_INFLIGHT_TURNS` + 过载可观测（排队/503） | 压测下 TTFB 不因无限并发塌掉；loop 语义不变 |
| **MT6**（后置） | Org、显式 share、`search_records` ACL | RE4/RE5 开闸条件 |
| **MT7**（后置） | runtime 多副本 + 命令亲和（接 [`03` §8.5](03-docker-runtime.md)） | 并发 Turn 水平扩展；Cancel/Approve 打到正确 runner |

**引擎 / 契约纪律：** 不改 while；事件名尽量不变；StartTurn payload 可增只读 scope 字段。避免 `if scenario` 式 `if tenant` 业务分叉——差异留在 ToolExecutor / retrieval store / api 鉴权。

---

## 10. 决策摘要（供 ADR-021）

1. **多租户是作用域绑定问题，不是编排问题**：TenantContext 在 Intake/控制面冻结；loop 无感。  
2. **执行隔离主键是 `work_id`/`work_root`；归属键是 `tenant_id`/`owner_id`；禁止 `session_id` 当隔离键。**  
3. **划分默认开启**：无主开关；**每个登录账号都是普通用户**（含部署者）；自动默认 Work；旧 `/workspace` 一次认领即可。  
4. **ACL 仅确定性谓词与路径沙箱；否决 LLM-ACL 与热路径权限模型调用。**  
5. **写作 / RAG / 记忆 / 委派 全部挂到同一 Work 根；概念复用 [`23`](23-writing-work-model.md)，不平行发明。**  
6. **服从 R1–R5；可测（deny golden）才算成熟度达标。**  
7. **容量上：按并发活跃 Turn 扩 runtime，不按用户数扩容器；不按用户开线程。**  
8. **一致性：Run claim + 事件序 + Context 冻结 + 索引最终一致；同 Work 多写者默认乐观，锁在产品面。**

---

## 11. 非目标（本设计明确不做）

| 非目标 | 说明 |
|--------|------|
| K8s 命名空间级硬隔离 / 每租户一集群 | 部署拓扑另案；本方案先**同栈逻辑多租户**（见 §0.1） |
| 用「加副本 / 加线程」代替 ACL | 扩容面解决吞吐，不解决「谁能看见」 |
| 公网 SSO 全家桶 / SCIM | 身份可后接；先复用 [`16`](16-user-session-history.md) |
| 字段级加密 / BYOK | Guard 内容防护保留；合规套件后置 |
| 同 Turn 多 Work 联邦检索 | 复杂度爆炸；要搜别的世界先切换 Work |
| 租户市场 / MCP 插件商店 | 平台非目标（见 [`01`](01-problems-and-goals.md)） |
| 用多租户「顺便」加意图 pipeline | 否决 |

---

## 12. 开放问题

1. **个人默认 Work 何时自动创建？** 注册时 vs 首次发消息（倾向注册/首次建 Session 时，避免挡 TTFB）。  
2. **seed 语料计费与配额是否计入租户？** 倾向不计入；仅 private 摄入计数。  
3. **协作编辑同一 Work：** 后置；若做，Session 可多 principal 只读/读写角色挂在 Work ACL，仍不把 Session 当文件容器。  
4. **跨 Work 只读引用（素材库）：** 用 `visibility=shared` 或显式 share 行，不用模型拼绝对路径。  
5. **单测夹具：** eval workspace 是否每 case 独立 work_id（倾向是，避免并行污染）。

---

## 13. 与评分缺口的对应

| 评分弱项 | 本文如何结构性地还债 |
|----------|----------------------|
| 企业就绪 4.5 | 给出可关默认、可渐进的 Tenant/Work 骨架，而非空喊 SaaS |
| RAG 规模 7.0 | 补齐 IX5 隔离键与谓词面，使万档/多用户可证明 deny |
| 写作多作品 | 落实 [`23` §11](23-writing-work-model.md)，Session 继续不管书 |
| 交付诚实性 | 根路径一致 → 导出/检索不再「串到别人的树」 |

**一句话收束：** 多租户做成 **Harness Intake + 存储作用域** 的加厚，而不是 Agent 交互上的新剧情——这才同时满足「成熟 Agent」「不伤速率/逻辑」「结构合理」。
