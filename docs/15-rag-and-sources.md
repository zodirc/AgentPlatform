# 15 — RAG 与资料库（模块正文）

> **本模块唯一维护入口**（含原证据 RAG / 索引设计与执行文）。历史细节见 git。  
> **关联**：文风/成稿走廊 → [14](14-writing-quality.md)；工具宪法 → [06](06-tools-and-context.md)；速率 → [13](13-rate-redlines.md) R1–R5；部署默认栈 → [03](03-docker-runtime.md)。

---

## 0. 去留（合并前必答）

| # | 问题 | 不通过则 |
|---|------|----------|
| Q1 速率 | 是否推迟首 token / 热路径重嵌 / 同步 LLM？ | **否决** |
| Q2 验证 | 契约闸？效果向是否过效果闸？polish 仍 0 搜？ | **否决** |
| Q3 成熟 | 是否对应真实知识库场景，而非再造 pipeline？ | **降级或延后** |

| 方向 | 做？ | 理由 |
|------|------|------|
| 每轮强制 retrieval / 预注入向量 | **否** | 伤 cache 与 TTFB |
| Turn 末自动 judge | **否** | 违 R2 |
| 热路径默认 CE / query rewrite | **否** | 仅离线/可选 |
| `path_prefix` + 离线 A/B | **是（已落地）** | RE3 |
| 成稿取证 + cite 纪律 | **是（已落地）** | RE2 |
| keyword 字段对齐 | **条件（已落地）** | RE1 |
| ACL / 私有库 | **产品开闸** | RE4 / IX5 |
| `search_records` 真表 | **产品开闸** | RE5 / [17](17-search-records.md) |

```text
素材卡 pin     → 文风 / 规范（稳定前缀）
search_sources → 事实 / 可引用片段（按需工具）
search_records → 结构化业务行（可选；非写作主路径）
```

**常设既定事实种子（写作）：** 填充路径与格式见 [`seed/sources/FORMAT.md`](../seed/sources/FORMAT.md)；文件放在 `seed/sources/writing/{persons,periods,dramas,novels}/`。  
运行时：**只读挂载**到 `/workspace/sources/seed/writing`（不拷贝进用户沙箱）；索引路径 `sources/seed/writing/...`。与 `eval/retrieval/corpus/`（效果闸）分离。手动重建索引：`make seed-sources`。

---

## 1. 三标尺与两平面

冲突裁决：**① 速率/交互 → ② RAG 质量 → ③ 成熟形态**。

| 标尺 | 过关 | 一票否决 |
|------|------|----------|
| **①** | Turn 无建库；自主搜；polish/outline **0 搜** | 查询内 sync；强制每轮搜；堵 SSE |
| **②** | 真相档 hybrid；**prod-bench** | stub/hash 冒充生产效果 |
| **③** | 目录=真相；索引=后台投影；终局 owner 私有库 | 「必须上传才测 RAG」；per-session 索引 |

```text
交互面（不改）          Index plane（Turn 外）
自然语言 → 自主 search   sources/** → dirty → ST+pgvector
成稿可搜 / polish 0 搜   启动扫 + 目录监视 + 上传 + Web 同步
```

**A9：** `search_sources` 永不在查询路径 `sync()` / 重嵌。

| 阶段 | 索引范围 |
|------|----------|
| 今 | workspace `sources/**`（含 RO 挂载的 `sources/seed/writing/**`） |
| 终局 | `owner_user_id` / tenant 私有库（IX5） |
| 不做 | per-session 索引 |

---

## 2. 真相档与命令

**裁判栈：** `MODEL_MODE=live` + `RETRIEVAL_BACKEND=pgvector` + `EMBEDDING_BACKEND=sentence_transformers`。

| 命令 | 证明 |
|------|------|
| `make sync-sources` | 手改 md → 索引（运维） |
| `make retrieval-bench` | hash 契约/filter；**≠** 生产召回 |
| `make retrieval-bench-prod` | **真相档**难 qrels（IX4 主闸） |
| `make eval-path-prefix` | RE3；跑完 **restore live** |
| `make turn-effect-bench` | RE2 同题 Turn（stub） |
| Web「同步资料库」 | IX1；不替代 IX4 |
| 目录监视自动投影 | IX2（`SOURCES_WATCH_*`） |
| `index-status.plane=ingestion` | IX3；`effect_ready` 恒 false |

**每日序：** 真相档 → 后台 sync → 自然问句看 `hybrid` → 改协议时 isolated+restore → 质量 PR 须 prod-bench 绿。

题集布局：[`eval/retrieval/README.md`](../eval/retrieval/README.md)；可选人工难句：[`HARD_WORKBENCH.md`](../eval/retrieval/HARD_WORKBENCH.md)。

---

## 3. 验证：契约闸 ≠ 效果闸

```text
轨 A 契约：runtime-test / golden（可 stub）
轨 B 效果：真相档
     ├─ P-offline：retrieval-bench-prod
     └─ P-workbench：自然问句 + 时间线 hybrid + 对 md
```

### 3.1 效果三层（硬闸定义）

| 层 | 内容 | 谁必过 |
|----|------|--------|
| **1 离线 A/B** | 固定语料+qrels；Recall@k；可选 p95 | IX4/RE3；RQ1 |
| **2 同题 Turn** | 同一成稿句前后对照；搜次数与墙钟 | RE2 |
| **3 工作台** | 成稿有用 / polish 0 搜 / 目录隔离 | RE2；IX4 建议 |

**仅 stub 绿不得宣称「优化有效」。**

| 允许 | 禁止（效果叙事） |
|------|------------------|
| 输入框自然问句 | slash `/rag-test` 等 |
| `make retrieval-bench-prod` | 「必须上传才算测过」 |
| 时间线核对 hybrid/path/cite | hash/stub 冒充生产 |

### 3.2 术语

| 词 | 含义 |
|----|------|
| A/B（bench） | A=无 path_prefix；B=带目录过滤（非流量实验） |
| path | workspace 相对路径 |
| Recall@k / hit | 期望 path 是否在 top-k |
| keyword-fallback / index_lag | 降级与索引落后可观测信号 |

---

## 4. 票状态（RE + IX）

| 票 | 主题 | 状态 |
|----|------|------|
| RE0 / RE3 / RE2 / RE1 | 题集、path_prefix、Turn A/B、keyword 字段 | ✅ |
| RE4 / IX5 | ACL + owner 私有库 | ⏳ 产品开闸 |
| RE5 | `search_records` 真表 | ⏳ 见 [17](17-search-records.md) |
| IX0 / IX1 / IX2 / IX3 / IX4 | 启动 sync、Web 同步、目录 watch、上传≠效果闸、prod-bench | ✅ |
| RQ1 | 切块/lexical/two-level（不开 CE） | ⏳ 仅 IX4 暴露缺口 |

```text
IX0 ✅ → IX4 ✅ → RQ1（条件）
      → IX1 ✅
      → IX2 ✅（目录监视 → debounce 投影）
      → IX3 ✅（摄取面 ≠ 效果闸）
      → IX5 / RE4（多租户）
```

**主线：** 质量闸已过；Index plane 自动跟上目录；RQ1 仅回归失败时；IX5 等多用户。

---

## 5. 合并门禁

```bash
make runtime-test
make eval-path-prefix    # 跑完 restore → live
# writing：make eval-all 或 writing.12/13
make retrieval-bench-prod   # 效果向必过
```

PR 自检：热路径无 sync · polish 0 搜 · 无默认同步 LLM/CE · restore 后仍 live+ST · 附 prod-bench 证据 · 无 slash 验收。

**否决：** 查询建库 · per-session 索引 · stub 冒充效果 · LLM-ACL · 无难闸上 CE · slash 测 RAG。

---

## 6. 多租户私有库（IX5 / RE4）

自用可先共享 workspace，**不能把共享当终局**。

```text
owner / tenant
  ├─ 语料：sources/u/{owner}/… 或行带 owner_id
  ├─ 索引：chunks 带 owner_id
  └─ search：工具层注入谓词（模型无感）；仍不 sync
```

| 要 | 不要 |
|----|------|
| 隔离键 = `owner_user_id` | `session_id` |
| 默认 deny 他人；共享显式 | 默认可搜全站 |
| 热路径仅 SQL 谓词 | 为 ACL 再调模型 |
| 单租户 mode=off 兼容今日 CI | IX0 焊死无 owner 列 |

开闸：真实多用户不可互看；deny golden；mode=off 行为不变。身份复用 [16](16-user-session-history.md) 的 `owner_user_id`。

---

## 7. 完成定义

| 里程碑 | 条件 |
|--------|------|
| 投影可用 | IX0 ✅ |
| 目录自动跟上 | IX2 ✅ |
| 摄取≠效果口径 | IX3 ✅ |
| **生产质量已验收** | IX4 ✅ prod-bench |
| 成熟多租户 | IX5/RE4 |
| 全程 | 交互未改；search 不建库；不以 hash/浅常识/上传成功冒充效果 |

---

## 8. 代码索引

| 项 | 路径 |
|----|------|
| path_prefix | `services/runtime/app/retrieval/path_filter.py` |
| keyword section | `…/keyword_hit.py` |
| 索引调度 | `…/index_scheduler.py` |
| 目录监视（IX2） | `…/sources_watch.py` |
| 摄取状态（IX3） | `services/runtime/app/services/workspace_browser.py` → `sources_index_status` |
| 层 1 runner | `scripts/retrieval_bench.py` |
| 题集 | `eval/retrieval/qrels*.yaml` |
