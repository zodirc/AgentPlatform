# 29 — 资料库索引：速率、RAG 质量与成熟 Agent 对齐

> **性质**：产品 + 后端思路对齐；指导实现优先级；**本文不强制立刻改代码**。  
> **三条硬标尺**（一切方案必须同时满足）：  
> 1. **不影响 Agent 交互速率与交互逻辑**  
> 2. **优化 RAG 质量**（召回准、噪声低、可核对）  
> 3. **成熟 Agent 做法**：交互面与后端面一起想，参考业界常见形态  
> **生产真相档（实际使用）**：`MODEL_MODE=live` + `RETRIEVAL_BACKEND=pgvector` + `EMBEDDING_BACKEND=sentence_transformers`（本地烘焙模型）。**效果验证必须以该档为裁判**；stub / hash / lite 只做契约与隔离，不能代替真效果。  
> **约束继承**：[17](17-execution-plan.md) R1–R5 / A9；[06](06-tools-and-context.md) §0.1；[11](11-product-experience.md)；[23](23-writing-quality.md)；[27](27-rag-evidence-and-doc-search.md) / [28](28-rag-evidence-execution.md)；[03](03-docker-runtime.md)。  
> **票级落地**：[30-sources-index-execution.md](30-sources-index-execution.md)（IX0–IX5；IX0 后质量主线见 §5.5 / 30§0.3）。  
> **现状刺点**（2026-07）：IX0 已使启动异步投影可用、工作台可现 `hybrid`；但**常识友好题 ≠ 排序已验证**；本机 `make retrieval-bench` 仍强制 **json+hash**，**不能**代表生产 ST+pgvector 效果。

---

## 0. 三标尺怎么用

| 标尺 | 过关定义 | 一票否决 |
|------|----------|----------|
| **① 速率 + 交互逻辑** | Turn 热路径无建库；TTFB 不因索引抖动；模型仍自主决定是否搜；polish 0 搜不变 | 查询内 sync；强制每轮检索；等 embedding 堵 SSE |
| **② RAG 质量** | 在**生产真相档**下索引 current、hybrid 可核对；prod-bench 或工作台记录 | 用 stub/hash 绿宣称生产 RAG 已优化；长期 keyword-fallback 冒充向量 RAG |
| **③ 成熟形态** | 目录=真相；索引=后台投影；上传=写入之一；**迈向按租户/owner 的私有库**（见 §6.1） | 「测 RAG 必须上传」；无 ignore 整盘索引；把「永远全局共享一份 sources」当成终局 |

冲突裁决：**① → ② → ③**。宁可短期 keyword 保对话，也不为质量阻塞交互；质量用后台投影补。

---

## 1. 交互面 vs 后端面

```text
┌── 交互面（不得为索引改逻辑）──────────────────────────────────────┐
│ 自然语言 → 工具策略 → 模型自主 search_sources（只读/可降级）       │
│ 成稿可搜 / polish 0 搜 / R1–R5 搜次数                              │
└────────────────────────────────────────────────────────────────────┘
                              ▲ 只读
┌── 后端 Index plane（Turn 外）──────────────────────────────────────┐
│ sources/** → dirty → worker → 切块+本地 ST → pgvector（失败→JSON） │
│ 状态 pending/building/ready + path_current                         │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. 标尺 ①：速率与交互逻辑

| 已定逻辑 | 含义 |
|----------|------|
| RAG=工具，非预注入 | 「讲讲岳飞」由模型决定搜不搜 |
| polish/outline 0 搜 | 索引再好也不能让改稿开始搜 |
| search 永不请求内 sync（A9） | IX* 必须守住 |
| R1–R5 | 质量≠多搜 |

| 允许（后端） | 禁止（热路径） |
|--------------|----------------|
| 启动异步增量投影 | 每条消息前 rebuild |
| 上传/保存入队 | search 内 sync |
| 低频 watch / 一键同步 | empty 就同步 |
| keyword-fallback + 标 lag | 堵 SSE 等向量 |

---

## 3. 标尺 ②：RAG 质量（在 ① 内）

**后端杠杆（优先）：** 索引与磁盘一致、增量 hash、section 切块、path_prefix、two-level、lexical rerank、ignore。  
**交互杠杆（已有）：** 搜次数上限、低分改 read、cite 纪律。  

**禁止：** 模型编得像 = RAG 过关；hash-bench 绿 = 生产召回过关；**仅「有 hybrid」= 排序已好**。

### 3.1 难度与排序（IX0 之后的质量杠）

投影闭环只证明「库被用到」。真 RAG 还要证明 **难问句仍准、噪声低、top 命中可解释**。

| 要验 | 过关直觉 | 不够 |
|------|----------|------|
| **库内特有细节** | 问 md 里模型易错/易忽略的点；改库后答案跟着变 | 「岳飞字鹏举」等常识友好题 |
| **噪声抗性** | 多人物/多域同库时，目标 path 进 top，域外不抢镜 | 只要 `5 hit(s)` 有一段相关摘录 |
| **排序** | 离线 Recall@1/@5 + 噪声 path 率；工作台 top hit path 对 | 只确认 `retrieval=hybrid` |
| **难负例** | 近义、跨章节、`path_prefix` 开/关 A/B（真相档） | 只跑 hash-bench |

**优化顺序：** 先难 qrels + 难自然问句清单（IX4）→ 暴露缺口再调切块/lexical/two-level（条件票 RQ1）→ **默认不开** 热路径 CE / 同步 query rewrite。

### 3.2 优化时对速率与交互逻辑的边界

| 可做（Index / 离线 / 已有预算内） | 不可做（Turn 热路径） |
|----------------------------------|------------------------|
| 更好切块、增量、ignore、后台 ST | `search_sources` 内 sync / 重嵌 |
| 默认 **lexical** rerank（超时降级） | 默认同步 CE；每轮强制搜 |
| two-level、path_prefix（减候选） | 为 ACL/路由再调一轮 LLM |
| 索引状态 UI，**不挡发送** | 等 embedding 完才出首 token |
| 搜次数上限、低分改 `read_file` | 把 RAG 改成预注入 system |

任一「质量优化」PR：若 polish/outline 0 搜被破坏、搜次数无预算地上涨、或交互变成「必须先搜」→ **按标尺 ① 否决**，即使离线分数更好。

---

## 4. 标尺 ③：成熟前后端

| 维度 | 常见做法 | 我们 |
|------|----------|------|
| 语料 | 工作区目录 | `workspace/sources/**` |
| 首次/之后 | 后台全量再增量 | 启动扫 + 上传事件 + 可选 watch |
| 聊天 | 只读；未就绪可降级 | hybrid / keyword-fallback |
| 上传 | = ingest | 已有；非唯一入口 |
| 评测 | CI 快测 + 夜间/发版真测 | 契约轨 + 效果轨（§5） |
| **租户** | 每用户/每组织私有知识库 + 检索带身份 | 今日共享 workspace；**终局按 owner/tenant 隔离**（§6.1） |

---

## 5. 生产真相档与验证矩阵（效果重要 ∧ 不拖交互）

日常使用 = **live + pgvector + 本地 ST**。验证必须**分轨**。

### 5.1 契约轨 vs 效果轨

```text
契约轨（快、可砸）                      效果轨（真、Turn 外）
MODEL_MODE=stub                         日常：live
runtime-lite / keyword 可接受             ST + pgvector + hybrid
isolated → restore 回真相档               sync / prod-bench 后台
证明：协议没写坏                          证明：生产召回与体感真好
```

| 轨 | 代表 | 碰日常 live？ | 证明 |
|----|------|---------------|------|
| 契约 | `eval-path-prefix` / `eval-all` isolated | 临时换，**必须 restore** | 工具/走廊 |
| 离线近似 | 当前 `retrieval-bench`（json+hash） | 否 | 题集/filter 逻辑；**≠ ST 质量** |
| **离线生产** | 规划 `retrieval-bench-prod`（容器内 ST+pgvector 跑同一 qrels） | 不改 MODEL_MODE；不占 Turn | **真** hybrid |
| **体感生产** | Writing **自然语言**问句（index ready 后；见 §5.5） | 就是日常栈 | live + hybrid + **难句可对 md** |
| 同题 | turn-effect / 手工 | 效果结论须含 **live+current** 至少一轮 | 体感 |

### 5.2 效果重要且不拖速率

| 做法 | 速率 | 效果 |
|------|------|------|
| isolated 契约 + restore | 结束后仍 live+ST | 不替代效果 |
| sync / prod-bench 在 Turn 外 | 零 TTFB 税 | 真 ST+pgvector |
| 自然问句仅在 index ready 后下效果结论 | 不边聊边全量 embed | 真 live RAG |
| embed 限流、CE 默认关 | 对话优先 | 质量渐进 |
| fallback + 标 lag | 不堵 SSE | 标明非 hybrid |

对标：IDE 后台 indexer；CI 快测；发版/夜间语义评测——**从不在击键路径全库 embedding**。

### 5.3 每日推荐操作序

1. 栈保持真相档：live + pgvector + ST。  
2. 资料进盘 → **后台 sync**（IX0/一键；上传也可，但非必须）。  
3. **效果**：自然问 → 时间线 **hybrid** → 细节对 md。  
4. **契约**（改协议时）跑 isolated；确认 restore 后仍 live。  
5. **合并检索质量 PR**：契约绿 **且**（prod-bench 绿 **或** 工作台 hybrid 核对）——缺一不可。

### 5.4 缺口

| 缺口 | 补法 |
|------|------|
| 手改 sources 无投影（启动/上传已有；手改 freshen） | IX1（按钮）；可选 IX2 |
| bench 仅 hash；难检索/排序未充分验 | **IX4** ✅ 离线难闸已合；工作台难句见 `HARD_WORKBENCH.md` |
| 排序缺口暴露后才调参 | 条件 **RQ1**（见 30）；禁止无闸先上 CE |
| eval 盖日常镜像 | default/lite 分 tag + restore |
| live 无可用 key | Web 供应商；ready 认 DB profile |
| 多租户私有库 | IX5 / RE4 |

### 5.5 验收纪律：真相档 · 双轨 · 禁止 slash 测 RAG

**裁判栈唯一：** `MODEL_MODE=live` + `RETRIEVAL_BACKEND=pgvector` + `EMBEDDING_BACKEND=sentence_transformers`。

```text
轨 A 契约：runtime-test / golden（可 stub）——只证协议不坏
轨 B 效果：真相档
     ├─ P-offline：retrieval-bench-prod（难 qrels；工程/CI 闸）
     └─ P-workbench：工作台自然语言 + 时间线 hybrid + 可对 md
```

| 允许 | 禁止（效果验收叙事） |
|------|----------------------|
| 工作台输入框里的**自然问句**（可从清单复制粘贴） | 产品内 `/rag-test`、`/sync`、`/bench` 等 **slash 测 RAG** |
| 运维：`make sync-sources`、启动异步（**非**用户验收路径） | 「用户必须敲 make / 必须上传一次才算测过 RAG」 |
| 工程：`make retrieval-bench-prod` 作合并门禁 | 用 hash-bench / stub 绿宣称生产 RAG 已优化 |
| 时间线核对 `hybrid`、path、cite | 只看模型答得像、不看工具与 md |

**P-workbench 最低充分性（IX0 浅题之后）：** 清单须含 ≥1 道库内特有细节、≥1 道噪声/多域干扰、≥1 道「改 md 后重问是否跟着变」（手改后靠启动扫 / IX1 同步，**仍用自然问句验收**）。常识题可作冒烟，**不得单独充当效果充分证明**。

---

## 6. 目标方案

```text
sources/** 变更 ──► dirty → worker ──► pgvector + 本地 ST     （Turn 外）
用户话 → Agent 逻辑不变 → search_sources 只读 ─┬─ hybrid
                                              └─ keyword-fallback + 可观测
```

**P0（已合代码）：** 守 A9；启动异步增量 + 运维 `make sync-sources`；lag 可观测；浅题可 hybrid。  
**P1 质量主线：** **IX4** 难 qrels + prod-bench + 难自然问句清单（§5.5）；IX1 为手改便利（不替代效果闸）。  
**P1 条件：** 仅当 IX4 暴露排序缺口 → **RQ1** 调切块/lexical/two-level（仍守 §3.2）。  
**P2（成熟必做，可排期）：** 多租户私有库 Index plane（§6.1）+ 与 [28](28-rag-evidence-execution.md) **RE4 ACL** 对齐。

**索引范围（分层，勿混淆）：**

| 阶段 | 范围 | 说明 |
|------|------|------|
| **今 / IX0** | **workspace / 部署级** | 挂载的 `sources/**` 一份投影；同机会话共享。**不是** session，也还不是 per-user |
| **成熟终局** | **按 `owner_user_id` / tenant（私有库）** | 业界主流：每人/每组织自己的资料与索引；检索必须带身份。**仍不是** per-session |
| **明确不做** | per-session 索引 | 知识库生命周期 ≫ 聊天；按会话建库是反模式 |

**不做：** 查询 sync；强制每轮搜；测 RAG 必须上传；用 hash-bench 代替生产效果；把「全局共享一份库」写成产品终局。

---

### 6.1 多租户私有库：趋势、必做性、与速率/质量

**判断：** 多租户（或至少 **按登录用户隔离的私有知识库**）是成熟 Agent / 内部知识助手的主流形态，也是本项目线 B（企业文档搜索）对齐岗位叙事的硬门槛——与 [27](27-rag-evidence-and-doc-search.md) G4、[28](28-rag-evidence-execution.md) RE4 同一方向。  
**自用单机可以先共享 workspace，但不能把共享当成架构终点。**

#### 成熟产品常见切法

```text
用户身份 (owner / tenant)
    │
    ├─ 语料根：sources/{owner}/…  或  DB 对象带 owner_id
    ├─ 索引：source_chunks 带 owner_id（或分 schema / 分 collection）
    ├─ 写入：上传/同步只进自己的语料 → 只投影自己的 dirty
    └─ 读取：search_sources 隐式注入 owner（或 ACL 谓词）→ 不可越权命中
              Turn 仍：模型自主决定是否搜；search 仍不 sync
```

| 做法 | 要 | 不要 |
|------|----|------|
| 隔离键 | `owner_user_id` / `tenant_id` | `session_id` |
| 默认策略 | 私有默认 deny 他人；共享库显式标记 | 默认可搜全站 |
| 交互 | 用户无感（登录即自己的库） | 让用户选「索引会话 id」 |
| 速率 | 过滤在索引侧/命中后谓词，毫秒级 | 为 ACL 再调一轮模型 |
| 演进 | IX0 的 path+mtime 逻辑保留，**加 owner 维度** | IX0 写死「全局一张表无 owner 列」无法迁移 |

#### 与三标尺

| 标尺 | 多租户时怎么守 |
|------|----------------|
| **①** | 身份从 session→owner 解析一次；search 热路径只多一个 `WHERE owner_id=?`（或等价）；**不**改工具走廊、不建库 |
| **②** | 每人索引 current；互不污染召回；效果闸加「用户 A 不可命中 B 的 path」 |
| **③** | 对齐 ChatGPT Projects / 企业 KB：私有默认 + 可选共享；上传=写入自己的库 |

#### 排期关系（避免大爆炸）

```text
IX0/IX1 投影闭环（可先全局 workspace）
    │  设计时预留 owner 列 / 路径约定（向前兼容）
    ▼
IX5 / RE4：owner 隔离写入 + 检索谓词（默认开关：单租户=allow-all 兼容今日）
    ▼
可选：共享资料夹、组织 tenant、审计
```

**开闸条件（与 RE4 对齐）：** 真实多用户不可互看资料；默认单租户行为与今日 CI 兼容；deny golden；热路径无 LLM-ACL。

---

## 7. 实现票

| 票 | 内容 | ① | ② 真相档 |
|----|------|---|----------|
| **IX0** | 启动异步增量 + `make sync-sources` | 后台 | current → hybrid |
| **IX1** | Web 同步 + 状态 | 无 Turn 税 | 手改可 freshen |
| **IX2** | 可选低频 watch | 可关 | 少忘同步 |
| **IX3** | 上传冒烟 ≠ 效果闸 | — | 管道≠召回 |
| **IX4** | 难 qrels + `retrieval-bench-prod` + 难自然问句清单（禁止 slash 验收） | Turn 外 | **质量主闸**：Recall/噪声 + 难句可对 md |
| **RQ1** | （条件）切块 / lexical / two-level 调参；默认不开 CE | 热路径只读 | 仅 IX4 暴露缺口后开；须 prod-bench+难句不回归 |
| **IX5** | 多租户私有库：chunks/语料带 `owner_id`；search 默认按 owner 过滤；单租户 allow-all 兼容 | 热路径仅谓词 | 隔离=质量与安全；接 RE4 |

**合并门禁：** 无 Turn 内 sync；契约绿；效果向须 **真相档** prod-bench 与/或 **难** P-workbench（§5.5）；polish 0 搜；restore 后仍 live+ST。  
**IX5 额外：** deny 越权 golden 绿；默认关/单租户时与今日行为一致。

---

## 8. 文档关系

| 文档 | 关系 |
|------|------|
| [30](30-sources-index-execution.md) | **票级执行**：IX0–IX5、两闸、冲刺、风险 |
| [27](27-rag-evidence-and-doc-search.md) / [28](28-rag-evidence-execution.md) | 效果三层；RE4 ACL ↔ IX5 私有库 |
| [17](17-execution-plan.md) A9 | 查询不建库 |
| [03](03-docker-runtime.md) | 默认 = 生产真相档 |
| [06](06-tools-and-context.md) / [23](23-writing-quality.md) | 交互逻辑边界 |
| [20](20-user-session-history-plan.md) | 已有 `owner_user_id` 会话归属——私有库身份应复用，勿另造 session 键 |

---

## 9. 结论口径

1. **使用档 = 效果裁判档**：live + pgvector + 本地 ST。  
2. **验证分轨**：契约可 stub/lite；**效果必须**在真相档；人工验收 = **自然语言**（禁止 slash 测 RAG）；prod-bench = 工程闸。  
3. **速率**：建库与真评测都在 Turn 外；质量优化不得改「自主搜 / polish 0 搜」逻辑。  
4. **质量杠**：hybrid 冒烟不够；要 **难检索 + 排序/噪声指标**（IX4），再条件调参（RQ1）。  
5. **范围演进**：今 = workspace 级投影（IX0 ✅）；**成熟必做 = 按 owner/tenant 私有库（IX5 / RE4）**；永不按 session 建索引。  
6. **当下主线**：**IX4（难闸）** 优先于体验补丁；IX1 便利手改；IX5 开闸后做隔离。
