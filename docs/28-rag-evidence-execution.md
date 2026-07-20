# 28 — 证据 RAG 与文档检索票级执行方案（RE0–RE5）

> **来源**：[27-rag-evidence-and-doc-search.md](27-rag-evidence-and-doc-search.md) §5–§8.1。  
> **性质**：可排期的票级落地清单；**本文本身不改代码**，落地时按票拆 PR。  
> **速率红线**：继承 [17](17-execution-plan.md) R1–R5。  
> **否决（全程）**：每轮强制 RAG / 预注入向量包 / 默认同步 LLM query rewrite / 热路径 CE rerank / Turn 末自动 judge / Skills 预注入扛检索。  
> **修订**（相对初稿）：效果优先——**RE3 提前**；**RE1 降为条件票**；RE2/RE3 合并须过 **效果闸**（27§8.1），stub 绿不充分。

---

## 0. 总览

| 票 | 对应 27 | 主题 | 线 | 建议顺序 | 效果闸 | 状态 |
|----|---------|------|----|----------|--------|------|
| **RE0** | §1 / §8.1 | 基线盘点 + 离线题集骨架 + 契约草案 | 共用 | 1 | 建骨架 | ✅ 已落地 |
| **RE3** | G2 / §6.1 | `path_prefix` filter + 离线 Recall A/B | B | 2 | **必过层 1**（+ 建议层 3） | ✅ 代码已落地；层 1 跑 `make retrieval-bench` |
| **RE2** | G1 / §5.4 | stub 回归 + 同题 Turn A/B + 工作台清单 | A | 3 | **必过层 2+3** | ✅ 自动化：`writing.14` + `make turn-effect-bench` / `make eval-path-prefix`；层 3 可选手工 |
| **RE1** | G3 / §5.2 | 命中字段对齐（keyword fallback） | A | **条件** | 若做则 **必过层 1** + 耗时预算 | ✅ 已落地（section 字段 + 预算） |
| **RE4** | G4 / §6.2 | 最小 ACL 谓词（默认 allow-all） | B | 产品触发 | deny 用例 | ⏳ 待开闸 |
| **RE5** | G5 / §6.3 | `search_records` 接一张真实表 | B | 产品触发 | ACL/timeout | ⏳ 待开闸 |

依赖：

```text
RE0 → RE3（filter + 离线 A/B）
RE0 → RE2（可与 RE3 部分并行；同题 A/B 建议在 RE3 后做，便于对照「有/无目录隔离」）
RE3 或真实痛点 → RE1（条件；须预算）
RE3 → RE4（开闸）
RE0 → RE5（开闸；独立工具）
```

### 0.1 两闸（合并前）

**契约闸（每票）**：

```bash
make runtime-test
make eval-all          # 必须含 writing.12 / writing.13 绿
make eval-retrieval    # 涉及检索行为时必跑
```

**效果闸（效果向票：RE3 / RE2 / 若做的 RE1）** — 定义见 [27§8.1](27-rag-evidence-and-doc-search.md#81-效果验证三层硬闸定义)：

| 层 | 内容 | 谁必须过 |
|----|------|----------|
| **1 离线 A/B** | 固定语料+题集；Recall@k / section 命中；可选检索 p95 | RE3 必过；RE1 若做则必过 |
| **2 同题 Turn A/B** | 同一成稿句前后对照；人工 2～3 题；搜次数与墙钟 | RE2 必过 |
| **3 工作台清单** | 成稿有用 / polish 0 搜 /（RE3 后）目录隔离 | RE2 必过；RE3 建议过 |

PR 描述须贴：契约命令摘要 + 效果闸结果（表格或截图要点）。**仅 stub 绿不得宣称「优化有效」。**

速率自检（PR 描述粘贴）：

- [ ] 未在 `search_sources` 热路径调用 `store.sync()` / 重嵌
- [ ] 未新增首 token 前的同步 LLM
- [ ] 未默认开启 cross-encoder
- [ ] 检索结果未写入 system / cache 前缀
- [ ] 改稿/polish 路径仍可断言 0×`search_sources`
- [ ] （RE1）单文件大小/时间预算 + 超时降级已测
- [ ] （效果向）层 1/2/3 按上表完成并附结果

---

## 1. RE0 — 基线盘点 + 离线题集骨架

| 项 | 内容 |
|----|------|
| **目标** | 冻结参数名；建好 **层 1 题集骨架**（哪怕先 8～15 题），避免后续票无效果对照基准 |
| **改哪里** | 文档勾选；`eval/retrieval/` 或 `scripts/` 下 bench 目录骨架（语料路径约定 + `qrels` YAML/JSON）；可选 contracts 草案 |
| **做什么** | 1）向量 vs keyword 字段差异表 2）冻结 `path_prefix` Schema（相对 `sources/`、禁 `..`）3）题集：`query → 期望 path/section` + 至少 2 道「易被全库噪声污染」的题（供 RE3 A/B）4）登记否决项 |
| **不做** | 不改 runtime 检索行为；不开 ACL；不接 records |
| **契约** | 若动 schema → contracts 测试绿 |
| **效果** | 题集可空跑（A=B）即算骨架完成；数字可在 RE3 填 |
| **速率** | 🟢 |
| **完成标准** | 差异表 + 参数冻结 + 题集文件存在且文档注明跑法 |

出口清单：

- [ ] 字段差异表已确认
- [ ] `path_prefix` 规则已冻结
- [ ] 离线题集骨架已入库（路径写入本票或 eval README）
- [ ] `writing.12/13` 列为每票回归硬闸

---

## 2. RE3 — `path_prefix` filter + 离线 Recall A/B（优先）

| 项 | 内容 |
|----|------|
| **目标** | 企业/写作分目录降噪；用层 1 **证明** filter 有效，而非只证参数能传 |
| **改哪里** | `tools/bootstrap.py`；`tools/core/tools.py`；store 或命中后过滤；ToolSpec/contracts；`eval/retrieval/` bench |
| **做什么** | 可选 `path_prefix`；非法/`..` → 空 hits + `hint`；向量与 keyword 行为一致；跑题集 **A=无 filter / B=有 filter** |
| **效果闸（必过）** | **层 1**：目标 path Recall 不下降；噪声 path 命中下降（或精确率上升）；可选记录检索耗时 p95（B 不明显差于 A） |
| **效果闸（建议）** | **层 3** 第 3 条：Workbench 限定子目录不出现域外片段 |
| **禁止** | LLM 解析目录；失败时枚举机密路径；用「必须多搜」换召回 |
| **契约** | 单测：子集 / 越界空 / 无参数=旧行为；golden 可选；`eval-all` + `eval-retrieval` |
| **速率** | 🟢 字符串前缀；预期候选更少 |
| **完成标准** | 契约闸绿 + 层 1 结果贴 PR；ToolSpec 已更新 |

出口清单：

- [ ] ToolSpec / 文档已更新
- [ ] 非法前缀单测绿
- [ ] 旧无 filter golden 绿
- [ ] 离线 A/B 表（Recall/噪声）已贴
- [ ] （建议）工作台目录隔离已手测

---

## 3. RE2 — 契约 stub + 同题 Turn A/B + 工作台清单

| 项 | 内容 |
|----|------|
| **目标** | **契约**：没写坏。**效果**：同题对照证明成稿取证更好用或至少不差 |
| **改哪里** | `eval/golden/writing/` stub；PR 或 `eval/reports/` 存放 A/B 记录；手工清单勾选 |
| **做什么（契约）** | ① section/path 命中 stub ② cite 干净 / unverified ③ **回归** `writing.12`/`13` forbidden `search_sources` |
| **做什么（效果）** | 同一成稿句合并前后各 1 Turn（Workbench 或 recorded/live）；人工 2～3 题打分（对/偏/错）；记录搜次数与墙钟；跑完 27§8.1 层 3 清单 |
| **禁止** | live 当 CI 阻断全仓；golden 要求搜满 3 次；只交 stub 绿宣称有效 |
| **速率** | stub 🟢；同题 A/B 为手工/nightly，不挡默认热路径 |
| **完成标准** | 契约闸绿 + 层 2 结果表 + 层 3 清单勾选贴 PR |

建议 stub ID（可改名）：

| ID | 意图 |
|----|------|
| `writing.14_section_hit`（示例） | 成稿取证命中指定 section |
| 扩展 `writing.08` | cite / unverified |
| 保持 `writing.12`/`13` | 0 RAG 硬闸 |

出口清单：

- [ ] section 命中 stub 至少 1 条
- [ ] 假 cite / unverified 仍绿或新增
- [ ] `writing.12`/`13` 绿
- [ ] 同题 A/B（≥2 题）结果已贴
- [ ] 工作台清单三项已勾

---

## 4. RE1 — 命中字段对齐（条件票）

**开做条件（满足其一）**：

1. 生产/自用中索引滞后导致 keyword fallback 频繁，且 cite 不可追溯；或  
2. 离线题集显示 fallback 路径 section 命中明显差于 hybrid。

未满足则 **跳过**，不阻塞 RE2/RE3。

| 项 | 内容 |
|----|------|
| **目标** | fallback 命中字段尽量与向量路径同构，且 **不拖慢工具** |
| **改哪里** | `tools/core/tools.py`；必要时仅对 **命中文件** 调 `split_markdown_sections` |
| **硬约束** | 单文件大小上限 + 解析时间预算；超时 → 仅 `path`+`excerpt`+`citation_id`；**禁止** fallback 时 embedding / 全库重切 / `sync()` |
| **效果闸** | **层 1**：fallback 相关题 Recall/可追溯字段不差于基线；**p95 工具耗时**有预算断言或 bench 记录 |
| **契约** | 单测对齐/降级；`eval-all` + `eval-retrieval` |
| **速率** | 🟡 唯一需盯工具耗时的票 |
| **完成标准** | 开做条件成立 + 契约绿 + 层 1（含耗时）贴 PR |

出口清单：

- [ ] 开做条件已在 PR 写明
- [ ] 预算与超时降级单测
- [ ] 层 1 + p95/耗时记录已贴
- [ ] `eval-all` 绿

---

## 5. RE4 — 最小 ACL 谓词（开闸）

**开闸条件**：① 真实多用户不可互看资料 ② RE3 已合并 ③ 默认 allow-all/关闭不破 CI。

| 项 | 内容 |
|----|------|
| **目标** | deny → 0 hits（不泄露存在性） |
| **改哪里** | 小型 `retrieval/acl.py`；`search_sources` 过滤；settings |
| **禁止** | 权限中台；LLM 判权 |
| **验证** | allow/deny 单测；deny golden；默认关锁死 |
| **速率** | 🟢 |

---

## 6. RE5 — `search_records` 一表（开闸）

**开闸条件**：产品指定表 + ACL 列；继承 [`18`](18-a20-multitable-recall.md)。

| 项 | 内容 |
|----|------|
| **目标** | 结构化检索与文档 RAG 分工具 |
| **做什么** | 一通道 + `wait_for(0.3)` + `degraded`；deny → 0 |
| **禁止** | 多表 join 爆炸；LLM 选表 |
| **验证** | deny / timeout golden |
| **速率** | 🟡 有超时预算 |

---

## 7. 建议冲刺切片（单人）

| 切片 | 票 | 预期体感 | 建议工期 |
|------|----|----------|----------|
| **S-RE0** | RE0 | 题集与参数冻结 | 0.5–1 天 |
| **S-RE-filter** | RE3 | 目录缩小检索 + 离线 A/B 数字 | 1–2 天 |
| **S-RE-effect** | RE2 | stub 回归 + 同题交互对照 | 1–2 天 |
| **S-RE-fallback** | RE1 | 仅开做条件成立时 | 1 天 |
| **S-RE-gate** | RE4 / RE5 | 开闸后 | 各 1–3 天 |

岗位叙事主线：**S-RE-filter**；写作可证明主线：**S-RE-effect**。二者都过效果闸才算「优化有效」。

---

## 8. 合并策略与风险

| 风险 | 缓解 |
|------|------|
| 只绿 stub、无体感 | 效果闸强制层 1/2/3；PR 模板勾选 |
| RE1 拖慢 fallback | 条件开做 + 大小/时间预算 + 层 1 p95 |
| filter 改坏无参数行为 | 单测锁旧行为；旧 golden 全绿 |
| 同题 A/B 不稳定（live） | 优先 Workbench 固定句；允许 recorded；人工分允许「持平」但不得明显变差 |
| ACL 误伤 CI | 默认关；专用 deny golden |
| 范围膨胀成检索中台 | 文首否决表；万档/多租户不做 |

---

## 9. 文档关联

| 文档 | 关系 |
|------|------|
| [27](27-rag-evidence-and-doc-search.md) | 设计、去留、**§8.1 效果三层** |
| [23](23-writing-quality.md) / [24](24-writing-quality-execution.md) | 文风/排版已落地 |
| [17](17-execution-plan.md) | R1–R5 |
| [18](18-a20-multitable-recall.md) | RE5 |
| [12](12-eval-and-golden-turns.md) | 契约 golden；效果闸在其上 |

---

## 10. 执行入口（按此顺序开 PR）

1. **PR0 — RE0**：参数冻结 + 离线题集骨架。  
2. **PR1 — RE3**：`path_prefix` + 层 1 A/B 结果（建议附层 3 目录隔离）。  
3. **PR2 — RE2**：stub + 层 2 同题表 + 层 3 清单。  
4. **PR3 — RE1**（可选）：仅开做条件成立；附耗时预算与层 1。  
5. **RE4/RE5**：开闸 checklist 打勾后再建票。

每 PR 复制 §0.1 两闸与速率自检，并粘贴命令/效果摘要。
