# 23 — 写作作品模型（Work over Session）

> **状态：已落地 WW0–WW4（2026-07-20）** · ADR-020 Accepted  
> 关联：[`09-product-modes`](09-product-modes.md) · [`14-writing-quality`](14-writing-quality.md) · [`16-user-session-history`](16-user-session-history.md) · [`20-context-compaction-walkthrough`](20-context-compaction-walkthrough.md) · [ADR-020](adr/020-writing-work-over-session-drafts.md)  
> 约束：须满足 [速率红线 R1–R5](13-rate-redlines.md)

---

## 1. 问题

写作模式当前把 **章节草稿** 落在：

```text
workspace/.agent/sessions/{session_id}/revisions/{turn_id}/{section_id}.md
```

用户心智是：**同一本小说 / 同一份文稿**。工程现实却是：

- 每开一个 Session（常为省 token / 换话题）→ 多一棵 session 目录树
- 第 1–2 章在 session A，第 3–4 章在 session B → **同一作品被会话切开**
- 正式真源本应是 `outline.md` + `sections/`，但实际成稿常停在 turn 草稿里，跨会话续写靠「碰巧还记得路径」或 `@` 引用

这不是路径美丑问题，而是 **作品边界被 Session 边界错误顶替**。

Session 正确含义（见 `07` / `16`）：一次对话线程、transcript、审批与压缩单位。  
Session **不应**拥有章节所有权。

---

## 2. 目标与非目标

### 目标

1. **一本作品一份树**：大纲、草稿、正式章都挂在 workspace（作品）下，不随 session 分叉。
2. **Session 可换、书不断**：新开会话 / `/compact` 只影响对话上下文，不拆散书稿。
3. **与现有主路径兼容**：`draft_section` →（可选审阅）→ `propose_patch` → `sections/`；不引入第二套「静默覆盖正式稿」。
4. **遵守 R1–R5**：不挡 TTFB；启动不额外同步调模型；热路径只做毫秒级路径解析与可选短 TOC 注入。

### 非目标（本方案不做）

- 多作品 / 多租户作品库（`Work` 表、作品切换器）——单 workspace 部署下 **workspace ≡ 当前作品**
- 自动把历史 session 草稿全量迁移为正式稿（可提供一次性脚本，不进热路径）
- 用 DB 存正文替代文件（仍以 workspace 文件为真源）
- 为省 token 强制新会话（token 策略另见 §7，本方案只提供「换会话仍能续写」的前置条件）

---

## 3. 推荐模型

### 3.1 分层（稳定）

| 层 | 路径 | 谁写 | 语义 |
|----|------|------|------|
| 结构 | `outline.md` | `update_outline` | 作品大纲（跨 session） |
| 正式正文 | `manuscript.md`（默认）或 `sections/{id}.md` | `propose_patch` | 全书 / 可选分章 |
| 在编草稿 | `.agent/work/drafts/manuscript.md`（默认追加） | `draft_section` | 同一本书里 upsert 章节块 |
| 回合快照（可选） | `.agent/work/history/{section_id}/{turn_id}.md` | `draft_section` 旁路写 | 审计 / 回滚；可 GC |
| 回合清单 | `.agent/work/turns/{turn_id}.json` | `draft_section` | 本轮触碰了哪些 `section_id`（导出 `current_draft` 用） |
| 对话态 | DB `session_transcripts` + `.agent/sessions/…` 仅若仍需会话私有缓存 | runtime | **不再存章节正文** |

目标树（默认 **monofile**）：

```text
/workspace/
  outline.md
  manuscript.md                 # 正式全书（章节用注释块标记）
  sections/                     # 可选：WRITING_MANUSCRIPT_MODE=sections
  .agent/work/
    drafts/manuscript.md        # 在编全书；新章追加、同 section_id 替换
    history/{section_id}/…
    turns/{turn_id}.json
```

### 3.2 工具语义调整

| 工具 | 变更 |
|------|------|
| `draft_section` | 默认 upsert 到 `.agent/work/drafts/manuscript.md` 的 `<!-- section:id -->` 块；`layout=sections` 可改回一章一文件 |
| `export_document(source=current_draft)` | 从本轮清单指向的稿中 **抽取** 对应章节块 |
| `export_document(source=confirmed)` | 优先 `manuscript.md` 章节块，回退 `sections/{id}.md` |
| `propose_patch` 目标 | 默认 `manuscript.md`；分章布局则 `sections/{id}.md` |
| `read_file` / `@path` | 跨会话稳定：`manuscript.md` / 草稿 manuscript |

**Turn 隔离保留在哪？**  
保留在「本轮导出范围」与「history 快照」，**不**再保留在「正文物理目录按 session 分叉」。

### 3.3 跨 Session 启动（轻量 bootstrap）

每个 writing Turn 开始时（R1/R2：无额外 LLM）：

1. 读磁盘拼一份 **短作品索引**（上限建议 ≤800–1200 chars）：
   - `outline.md` 标题行 / 卷章标题列表（已有 project_context，可收紧为 TOC-only）
   - `sections/` 已有文件名列表
   - `.agent/work/drafts/` 未完成草稿列表
2. 注入 system 旁路或 `runtime_context`（与 writing cards 同级预算），例如：

```text
[work index]
outline: outline.md (… chars)
confirmed: sections/ch1.md, sections/ch2.md
drafts: .agent/work/drafts/ch3.md
```

模型续写第 3 章时默认 `read_file` 草稿或上一章尾，而不是在 session UUID 树里找文件。

---

## 4. 对 Agent 交互速率与逻辑的影响

### 4.1 速率（R1–R5）

| 点 | 影响 | 结论 |
|----|------|------|
| `turn.accepted` / TTFB | 仅增加一次小目录 `list` + 短字符串拼接（毫秒） | **满足 R1/R3** |
| 首 token 前 | **禁止**为「作品摘要」再调模型；索引纯文件元数据 | **满足 R2** |
| 每步 assemble | 不把全书正文塞进 context；索引有硬顶 | 不恶化 fill |
| `draft_section` 写盘 | 路径更短、少一层 UUID；写次数不变 | **持平或略快** |
| 导出 / 投影 | manifest 从 session 迁到 work；逻辑等价 | 持平 |

**不会**改变 AgentEngine loop、工具审批分级、SSE 事件主形状（或仅 path 字段变化）。

### 4.2 逻辑（模型行为）

| 点 | 今天 | 方案后 |
|----|------|--------|
| 「章在哪」 | 绑 session/turn，易丢 | 稳定路径，易 `read_file` |
| 多轮微补丁同一章 | 仍靠 surgical patch | 不变；草稿按章覆盖更符合「改这一章」 |
| `current_draft` 跨 turn | 故意不可见 | **仍故意不可见**（防误导出）；跨 turn 续写读 `.agent/work/drafts/chN.md` |
| 并发两 session 写同一章 | 少见；session 隔离「碰巧」防撞 | 后写覆盖草稿；正式稿仍走 patch。可选：draft 写时带 `turn_id` 乐观锁（非 MVP） |

**对 agent 逻辑的净效果：简化，不复杂化。**  
工具名与主路径不变，只改落盘根与「书在哪」的提示。

---

## 5. 体验是否更佳

| 用户故事 | 今天 | 方案后 |
|----------|------|--------|
| 同一本小说写多章 | 多 session → 多目录树 | 一棵 `sections/` + `drafts/` |
| 为省 token 新开会话 | 书稿「像换了一本」 | 打开即见作品索引，续写同一本 |
| 找第 2 章 | 翻 `.agent/sessions/…/revisions/…` | `sections/ch2.md` 或 drafts |
| 导出已确认正文 | 依赖是否已 patch 进 sections | 不变，且更可能真的落在 sections |
| 工作区浏览器 | UUID 噪音 | 作品目录可读 |

体验提升是 **结构性** 的：对齐「我在写一本书」，而不是「我在堆聊天附件」。

残留摩擦（需产品接受）：

- 草稿 → 正式仍要一步（patch / 「确认进书」）；这是质量护栏，不是缺陷
- 单 workspace 多本书仍会挤在一起——那是后续「多作品」议题，不是本方案假解决

---

## 6. 是否「很优」——诚实评估

### 6.1 结论

在 **当前产品形态**（Docker 单 `workspace/` ≡ 当前写作任务、writing 为默认场景）下：

> **这是正确且应优先落地的方向，属于「优」而不是「花活」。**

理由：

1. **边界与心智一致**：作品 ⊂ workspace；会话 ⊂ 对话。这是写作产品的常识分层，也与 `outline.md` / `sections/` 文档早已宣称的模型对齐（今日实现偏离了文档）。
2. **解锁后续 token 策略**：没有作品真源，就只能靠「新开会话砍 transcript」，却付出「书被切碎」的代价。作品稳定后，才能安全做 `/compact`、按章加载、新会话 bootstrap。
3. **改动面可控**：不动 loop / 契约主模型；主要改 `draft_section` 路径、export 解析、短索引注入、文档与 golden。
4. **不与 ADR-013 冲突**：仍是 ScenarioProfile + core 工具；只是 writing 工作区语义纠偏。

### 6.2 算不上「银弹」之处

| 局限 | 说明 |
|------|------|
| 单 workspace 多书 | 仍混放；真多作品需要 `Work`/`project_id`（可演进，不阻塞本方案） |
| 草稿覆盖语义 | 同章多会话并发会后写覆盖；MVP 可接受，正式稿仍有 patch |
| 历史 session 垃圾 | 旧 `.agent/sessions/**/revisions` 需迁移或 GC 说明 |
| Token 不会自动降 | 本方案 **不直接省钱**；只让「省钱手段」不再拆书。省钱仍靠 compact / 按章上下文 / 少塞 tool 轨迹 |

### 6.3 否决的备选

| 备选 | 否决原因 |
|------|----------|
| A. 保持 session 目录，UI 做「聚合视图」 | 真源仍错；跨会话工具路径仍碎 |
| B. 取消草稿层，`draft_section` 直写 `sections/` | 破坏 diff-first / 误覆盖风险；与 `09` 正式落稿语义冲突 |
| C. 正文进 Postgres | 与文件工作区、`@path`、导出、用户可编辑习惯冲突；过重 |
| D. 一章一 Session 产品化 | 强化错误边界；token 与导航更差 |
| E. 上完整多作品平台再改路径 | 过度设计；单 workspace 已够用，先纠偏路径 |

**优选顺序：** 本方案（作品树）→ 再做按章 context / compact 体验 → 若出现多书需求再引入 Work id。

---

## 7. 与 Token 优化的关系（配套，非本方案本体）

[`23`](23-writing-work-model.md) 已解决「换会话拆书」；**token 输入窗策略见 [`24-writing-token-economy`](24-writing-token-economy.md)**（按章作业面、带书签 `/compact`；不伤速率与成稿效果）。

本方案是 **前置条件**，不是 token 方案本身。配套票：WT1–WT4（见 24 §7）。

---

## 8. 落地切片（建议）

| 票 | 内容 | 验收 |
|----|------|------|
| **WW0** | 文档：本文 + ADR-020；`09` §5.1 路径 | ✅ |
| **WW1** | `draft_section` / manifest / export → `.agent/work`；兼容旧路径 | ✅ |
| **WW2** | Turn 启动注入 work index；writing `system.md` | ✅ |
| **WW3** | UI 提示作品树路径 | ✅（侧栏文案） |
| **WW4** | `scripts/migrate_writing_work_drafts.py`（默认 dry-run） | ✅ |

**引擎 / 契约：** 事件名可不变；若 payload 含 path，允许新前缀。避免改 `AgentEngine` 分支。

---

## 9. 决策摘要（供 ADR）

1. Writing 文稿真源 = workspace 作品树（`outline.md` + `sections/` + `.agent/work/drafts/`）。
2. Session / Turn 只拥有对话与「本轮导出清单」，不拥有章节目录树。
3. 跨 Session 续写靠稳定路径 + 轻量 work index，不靠翻 session UUID。
4. 不取消草稿层；正式进书仍走 patch 主路径。

---

## 10. 开放问题

1. history 默认保留最近 `WRITING_DRAFT_HISTORY_KEEP`（默认 5）份；可调 0 关闭。
2. 「确认进书」一键 UI（draft → `propose_patch`）仍可选增强。
3. 多作品 / 多租户：见 §11；出现并行多书需求再引入 `work_id`。

---

## 11. 多用户演进（不阻塞本方案）

当前部署：`workspace ≡ 当前作品`。多用户 Web 平台时升级为：

```text
User/Org → Work(work_id) → storage root → outline/sections/.agent/work
                └── Session*（对话线程，可多人）
```

路径变为 `{work_root}/.agent/work/drafts/...`；**概念不变**。鉴权挂在 Work ACL，runtime 只解析当前 Work 根。Session 永远不当作品容器。

**完整多租户设计（速率宪法、TenantContext、分期 MT\*、ADR-021）：** 见 [`27-multi-tenancy`](27-multi-tenancy.md)。
