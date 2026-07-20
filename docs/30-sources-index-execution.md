# 30 — 资料索引与私有库票级执行方案（IX0–IX5）

> **来源**：[29-sources-index-and-interaction-rate.md](29-sources-index-and-interaction-rate.md)。  
> **性质**：可排期的票级落地清单；**本文本身不改代码**，落地时按票拆 PR。  
> **生产真相档**：`MODEL_MODE=live` + `RETRIEVAL_BACKEND=pgvector` + `EMBEDDING_BACKEND=sentence_transformers`。效果闸以该档为准。  
> **三标尺**：① 不改交互速率/逻辑 ② RAG 质量 ③ 成熟形态（含多租户私有库终局）。裁决顺序 ①→②→③。  
> **关联**：[28](28-rag-evidence-execution.md) RE3/RE4；[17](17-execution-plan.md) A9 / R1–R5；[20](20-user-session-history-plan.md) `owner_user_id`；[03](03-docker-runtime.md)。

---

## 0. 总览

| 票 | 主题 | 阶段 | 建议顺序 | ① 速率 | ② 效果闸 | 状态 |
|----|------|------|----------|--------|----------|------|
| **IX0** | 启动异步增量投影 + `make sync-sources`；DDL/元数据预留 owner | P0 | 1 | Turn 外 | 手测/自然问句须 hybrid | ✅ 代码已合（效果闸手测） |
| **IX1** | Web「同步资料库」+ 索引状态展示 | P1 | 2（可与 IX4 并行） | 无 Turn 税 | 手改 md 可 freshen | ⏳ |
| **IX4** | `retrieval-bench-prod`（容器内 ST+pgvector） | P1 | 2 | Turn 外 | **必过** qrels 在真相档 | ⏳ |
| **IX2** | 可选低频 mtime watch | P1 | 3 | 可关 | 减少忘同步 | ⏳ |
| **IX3** | 上传冒烟与效果闸分离（文档+可选 golden） | P1 | 任意 | — | 管道≠召回 | ⏳ |
| **IX5** | 多租户私有库（owner 隔离）+ 接 RE4 ACL | P2 成熟必做 | 开闸后 | 热路径仅谓词 | deny 越权 + 单租户兼容 | ⏳ |

依赖：

```text
IX0（投影闭环 + owner 预留）
 ├──► IX1（UI 同步）
 ├──► IX4（生产离线效果闸）  ← 可与 IX1 并行
 ├──► IX2（watch，依赖 IX0 入队语义）
 └──► IX5 / RE4（多租户；须 IX0 元数据可演进）
IX3 可随时（文档纪律为主）
```

**不依赖、禁止挡路：** 不改 Scenario 工具走廊；不开「每轮强制 RAG」；不按 `session_id` 建索引。

### 0.1 两闸（合并前）

**契约闸（每票触及 runtime/api/web 时）：**

```bash
make runtime-test          # 若动 Python
make eval-path-prefix      # 若动检索/工具协议；跑完确认 restore → live
# 涉及 writing 走廊时：
# make eval-all 或至少 writing.12/13
```

**效果闸（真相档，效果向票）：**

| 层 | 内容 | 谁必须过 |
|----|------|----------|
| **P-offline** | `make retrieval-bench-prod`（IX4 落地后）同一套 qrels | IX4 必过；IX0/IX1 建议附「sync 后 hybrid」记录 |
| **P-workbench** | live + index ready 下自然问句；时间线 hybrid；细节可对 md | IX0/IX1 必过（可手工贴日志） |
| **P-isolation** | 用户 A 不可命中 B 私有 path | IX5 / RE4 必过 |
| 近似层 | 现有 `make retrieval-bench`（hash） | 仅回归 filter/题集；**不得单独充当效果证明** |

**速率自检（PR 粘贴）：**

- [ ] 未在 `search_sources` 热路径 `store.sync()` / 重嵌
- [ ] 未改 polish/outline 0 搜契约
- [ ] 未新增首 token 前同步 LLM / 强制检索
- [ ] 索引任务与 Turn 预算隔离（后台/worker/限流）
- [ ] eval isolated 后 restore 仍为 live + `agent-platform-runtime:default`
- [ ] （IX0+）schema/路径约定不阻挡后续 `owner_id`
- [ ] （效果向）真相档证据已附（prod-bench 或工作台 hybrid 日志）

### 0.2 全程否决

| 否决 | 原因 |
|------|------|
| 查询路径建库 | 毁 ① / A9 |
| per-session 索引 | 反模式；知识库 ≫ 聊天 |
| 用 stub/hash 绿宣称生产 RAG 优化 | 毁 ② |
| 为 ACL/路由再调一轮模型 | 毁 ① / R3 |
| IX0 焊死「无 owner 的全局表且无法迁移」 | 毁 ③ 终局 |
| 测效果强制「必须上传」 | 入口≠架构 |

---

## 1. 横切设计（所有票共用）

### 1.1 数据与身份

| 概念 | 今 | IX0 预留 | IX5 |
|------|----|----------|-----|
| 语料根 | `WORKSPACE_ROOT/sources/**` | 同左；可选约定 `sources/_shared/` vs 未来 `sources/u/{owner}/` | 私有根 + 可选共享根 |
| 索引行 | `source_chunks(path, …)` 无 owner | **增加可空 `owner_user_id`**（或并行 meta 表）；单租户填 NULL=共享/全站 | NOT NULL 或默认当前用户；检索强制谓词 |
| 会话 | `sessions.owner_user_id` | 只读复用 | search 从 session→owner |
| 模型配置 | 已 per-owner | 不变 | 不变 |

**原则：** 隔离键 = `owner_user_id`（或日后 `tenant_id`），**不是** `session_id`。

### 1.2 增量语义（IX0 核心算法）

```text
for each file under sources/ (respect ignore):
  fingerprint = (path, mtime, size[, content_hash])
  if fingerprint unchanged vs index meta → skip
  else → enqueue re-embed + upsert chunks for that path
delete index rows whose path no longer exists on disk
```

- **全量**仅：空库、显式 `--full`、或 meta 损坏。  
- **忽略：** 超大文件、非文本、密钥类扩展名（列表写进 settings，可配）。  
- **后端：** 优先 pgvector + ST；失败记录 error，search 仍可 keyword-fallback。

### 1.3 并发与资源（保 ①）

| 机制 | 要求 |
|------|------|
| 单飞 | 全局（或 per-owner）最多 1 个重索引循环；新请求合并 dirty 集合 |
| 限流 | embedding 批次大小 + 间歇 sleep；不占满 CPU 导致 TTFB 抖动 |
| 优先级 | Turn / SSE ≫ 索引；可选 nice / 独立线程池 |
| 失败 | 单文件失败标记 error，不中断整库；可重试 |

### 1.4 可观测

| 信号 | 用途 |
|------|------|
| `index-status`：pending/building/ready/error、`path_current`、`indexed_files` | UI / 运维 |
| `retrieval.completed`：`index_lag`、`keyword-fallback`、`retrieval=hybrid\|keyword` | 效果核对 |
| 结构化日志：sync started/finished、files dirty/ok/err、耗时 | 排障 |
| （IX5）deny 计数 / 越权尝试 | 安全 |

### 1.5 交互面冻结清单（回归必测）

- [ ] 自然问句：模型仍自主决定是否 `search_sources`
- [ ] `/polish` 或改稿：0×`search_sources`（writing.12/13）
- [ ] 无预注入 chunks 进 system
- [ ] 索引 building 时仍可发消息（可答，可 fallback）

### 1.6 验证矩阵（落实 29§5）

| 轨 | 命令/动作 | 何时跑 |
|----|-----------|--------|
| 契约 | `eval-path-prefix` / 相关 golden | 每票改协议 |
| 近似 | `retrieval-bench` hash | 可选快回归 |
| **生产离线** | `retrieval-bench-prod` | IX4+；效果向 PR |
| **生产体感** | sync 后自然问句 + 时间线截图/日志 | IX0/IX1 |
| 隔离 | A/B 用户 deny | IX5 |

---

## 2. IX0 — 启动异步增量 + sync-sources（P0）

| 项 | 内容 |
|----|------|
| **目标** | 手改/已有 `workspace/sources` 在 **Turn 外**进入 pgvector+ST；结束「只能靠上传才像建过库」；**预留 owner** |
| **改哪里** | runtime lifespan / entrypoint 钩子；`sync_sources_index` 增量；可选 alembic/`ensure_schema` 加 `owner_user_id` 可空列；Makefile `sync-sources`；docs/03·29 勾选 |
| **做什么** | 1）启动后 `asyncio.create_task`（或等价）跑增量 sync，**不阻塞** `/health/live` 2）`make sync-sources` → `docker compose exec` 调内部命令 3）dirty 检测 4）单飞+限流 5）schema 预留 owner（NULL=共享/单租户） |
| **不做** | search 内 sync；Web UI（IX1）；强制多租户行为；改工具策略 |
| **契约** | 单测：未改文件 skip；删文件掉 chunks；search 仍无 sync；`eval-path-prefix` 绿 + restore live |
| **效果** | **必过 P-workbench**：sync 后自然问句 → `hybrid`（非长期 keyword-fallback）+ 细节可对 md |
| **速率** | 🟢 启动异步；健康检查仍用 live |
| **完成标准** | 冷启动后几分钟内（语料小则更快）index ready；手测 hybrid；owner 列或迁移说明已存在 |

出口清单：

- [x] 启动异步增量已落地且可关（env 开关，默认开）
- [x] `make sync-sources` 文档化
- [x] 增量跳过逻辑有单测
- [x] search 热路径无 sync（审计）
- [x] owner 预留已合入或 ADR/注释标明下一票接法
- [ ] P-workbench 证据贴 PR
- [ ] restore 后仍 live+ST

**落地备注（2026-07-20）：** `index_scheduler` + lifespan 延后 `create_task`；`SOURCES_STARTUP_SYNC_*`；`source_files`/`source_chunks.owner_user_id` 可空；`EMBEDDING_DIMENSIONS` 默认 384（ST）。若库里仍是旧 `vector(256)` 表，需 drop 后重建再 sync。

**风险：** 启动抢 CPU → 限流+延后数秒再扫；大语料首次慢 → 状态「building」可答。

---

## 3. IX1 — Web 同步 + 状态（P1）

| 项 | 内容 |
|----|------|
| **目标** | 手改 md 的用户有一键投影；状态可见，**不挡发送** |
| **改哪里** | api admin/workspace（或 end-user 资料 API）；web 设置/资料面板；复用 `index-status` + 触发 sync 内部命令 |
| **做什么** | 「同步资料库」按钮 → 入队/调用与 IX0 同一增量逻辑；展示 ready/building/error/indexed_files；可选 per-path current |
| **不做** | 同步完成前禁用输入；在浏览器做 embedding |
| **契约** | API 鉴权；失败返回 error 态 |
| **效果** | 手改文件 → 点同步 → 同句 hybrid（P-workbench） |
| **速率** | 🟢 |
| **完成标准** | 按钮+状态可用；与上传共用 Index plane |

出口清单：

- [ ] 同步触发走后台同一入口
- [ ] UI 不阻塞 Turn
- [ ] 与 upload 状态模型一致

---

## 4. IX4 — retrieval-bench-prod（P1，效果硬闸）

| 项 | 内容 |
|----|------|
| **目标** | 在 **ST+pgvector** 上跑同一 `eval/retrieval/qrels`，证明生产召回；替代「仅 hash-bench」 |
| **改哪里** | `scripts/retrieval_bench.py` 增 `--prod` / 新 `Makefile` target；docker exec 进 runtime；**隔离**语料前缀或临时表/临时 workspace，避免污染用户 `sources` |
| **做什么** | 1）把 corpus 拷到隔离路径或 `sources/_bench/`（可 gitignore）2）sync（Turn 外）3）跑 A/B qrels 4）打印 pass/fail 5）可选清理 |
| **不做** | 改 MODEL_MODE；占用用户会话；在 CI 无 ST 镜像时硬失败（可 skip+明确标记） |
| **契约** | hash-bench 仍保留为快回归 |
| **效果** | **必过**：真相档下 qrels 全绿（或基线表+阈值写入 README） |
| **速率** | 🟢 人工/CI 夜间跑；不进 Turn |
| **完成标准** | `make retrieval-bench-prod` 文档化；28/29 效果闸指向它 |

出口清单：

- [ ] prod target 存在且用 ST+pgvector
- [ ] 与用户语料隔离策略写清
- [ ] eval README / 29§5 已改「效果以 prod 为准」

**风险：** 污染生产 chunks → 必须隔离路径或 owner=`bench`；耗时长 → 不入默认 `contracts-test` 热路径。

---

## 5. IX2 — 低频 watch（P1，可选）

| 项 | 内容 |
|----|------|
| **目标** | 减少「忘了同步」；默认保守 |
| **改哪里** | runtime 后台任务；settings：`SOURCES_WATCH_ENABLED`（默认 false）、`SOURCES_WATCH_INTERVAL_SECONDS`（≥30） |
| **做什么** | 定时比对 mtime → 合并 dirty → 调 IX0 入队 |
| **不做** | inotify 强依赖（可后补）；默认狂扫 |
| **效果** | 改文件后 ≤1～2 个间隔进入 building/ready |
| **速率** | 🟢 默认可关 |
| **完成标准** | 开关文档化；开启时单测/手工验证不堵 Turn |

---

## 6. IX3 — 上传冒烟与效果闸分离

| 项 | 内容 |
|----|------|
| **目标** | 文档与可选 golden 明确：上传=管道；效果=IX4/工作台 |
| **改哪里** | `eval/retrieval/EFFECT_CHECKLIST.md`、29/30、可选 1 条 upload→ready API 测 |
| **做什么** | 清单分栏；禁止「只上传一次当 RAG 验收」 |
| **完成标准** | 清单与 README 口径一致 |

---

## 7. IX5 — 多租户私有库（P2，成熟必做）

| 项 | 内容 |
|----|------|
| **目标** | 按 `owner_user_id` 隔离语料与索引；检索不可越权；单租户/开关兼容今日共享行为 |
| **改哪里** | DDL `source_chunks.owner_user_id`；upload/sync 写入 owner；`search_sources` / store.search 谓词；api 鉴权绑 end_user；web 上传进私有根；接 [28 RE4](28-rag-evidence-execution.md)；deny golden |
| **做什么** | 1）路径约定 `sources/u/{owner_id}/…` 或等价元数据 2）共享库 `sources/_shared/` 或 `owner IS NULL` + 显式策略 3）search 从 session 解析 owner，**模型无感知**（工具层注入 filter）4）默认 `SOURCES_ACL_MODE=off\|owner`（off=今日行为）5）迁移：旧全局行 → shared 或绑定默认 owner |
| **不做** | per-session 库；LLM 判断 ACL；默认破坏 CI 共享语料 |
| **开闸** | ① 真实多用户不可互看 ② IX0 owner 预留已合 ③ RE3 已在 ④ deny 用例就绪 |
| **契约** | allow/deny 单测 + golden；`eval-all` 在 mode=off 下行为不变 |
| **效果** | **P-isolation** 必过；两用户同 query 命中集合不交叉（私有语料） |
| **速率** | 🟢 谓词/索引列；禁止热路径 LLM |
| **完成标准** | mode=owner 下越权 0 hits；mode=off 兼容；文档与 RE4 状态同步 |

出口清单：

- [ ] owner 写入与检索谓词一致
- [ ] 开关默认不破现有 CI
- [ ] deny golden 绿
- [ ] 无 session 级索引
- [ ] 与 docs/20 身份模型一致

**风险：** 迁移误把共享料划给单用户 → 迁移脚本+备份；忘记工具层注入 → 单测锁 search 必带 owner。

---

## 8. 冲刺叙事（建议）

| 冲刺 | 票 | 交付物 | 合并故事 |
|------|----|--------|----------|
| **S-IX-core** | IX0 | 启动增量 + make sync + owner 预留 | 「手改 sources，sync 后 hybrid」 |
| **S-IX-gate** | IX4 + IX1 | prod-bench + Web 同步 | 「效果闸真跑 ST+pgvector；UI 可 freshen」 |
| **S-IX-ops** | IX2 + IX3 | watch 可选 + 清单分轨 | 「少忘同步；口径不混」 |
| **S-IX-tenant** | IX5 ↔ RE4 | 私有库 + ACL | 「成熟 Agent：我的库只有我能搜到」 |

岗位/成熟叙事主线：**S-IX-tenant**；自用质量主线：**S-IX-core + S-IX-gate**。两者都过真相档效果闸才算「索引/RAG 基建完成」。

---

## 9. 风险登记

| 风险 | 缓解 |
|------|------|
| 索引抢 CPU 影响 live TTFB | 延后启动扫、限流、单飞、可关 |
| prod-bench 污染用户库 | 隔离路径 / bench owner |
| eval restore 丢 ST 镜像 | 坚持 image tag 分离；restore 检查 |
| IX5 破坏单机共享语料 | ACL mode 默认 off；迁移可选 |
| 只绿契约宣称优化 | PR 模板强制真相档证据 |
| 范围做成 per-session | 设计评审否决；文档三处写明 |

---

## 10. 与 28/29 的衔接

| 文档 | 衔接点 |
|------|--------|
| 29 | 思路与标尺；本票落地 |
| 28 RE3 | path_prefix 已有；IX 不重复造 filter |
| 28 RE4 | 与 IX5 同开闸；可同 PR 或 IX5 先做 owner 谓词、RE4 扩通用 ACL |
| 17 A9 | 每票速率自检第一条 |
| 20 | owner 身份唯一来源 |

---

## 11. 完成史诗的定义

当且仅当：

1. **IX0**：日常真相档下，workspace 语料可 Turn 外投影；自然问句稳定 hybrid。  
2. **IX4**：prod-bench 成为检索质量合并门禁（或等价书面豁免+工作台记录模板）。  
3. **IX5**（成熟必做，可晚于自用验收）：owner 隔离可开；deny 证明；默认兼容单租户。  
4. 全程：**交互逻辑未改**；**search 不建库**；**效果不以 hash/stub 冒充**。

未完成 IX5 前：产品可自用，但文档须标明「共享 workspace，尚未多租户私有库」——与 29「不把共享当终局」一致。
