# ADR-020: Writing 作品树优先于 Session 草稿目录

## 状态

已接受（2026-07-20）

## 背景

写作模式将 `draft_section` 落在 `.agent/sessions/{session_id}/revisions/{turn_id}/`。用户为省 token 或换话题新开 Session 时，同一本小说的章节被切到多棵 session 目录树下，与「一本作品」心智冲突，也与 `docs/09` 宣称的 `outline.md` + `sections/` 真源不一致。

Session 应是对话与上下文压缩单位，不应拥有章节所有权。

## 决策

1. **作品真源**固定在 workspace：`outline.md`、`sections/{id}.md`、`.agent/work/drafts/{id}.md`。
2. **`draft_section`** 按 `section_id` 写入作品草稿树；Turn 仅保留「本轮触碰清单」供 `export_document(source=current_draft)`。
3. **可选** `.agent/work/history/{id}/{turn_id}.md` 作快照；不作为跨会话寻址主路径。
4. Writing Turn 启动可注入 **短作品索引**（纯文件元数据，无额外 LLM，有字符硬顶）。
5. 正式进书仍走 `propose_patch` / `apply_patch`；不取消草稿层、不直写覆盖 `sections/` 作为默认生成路径。

完整方案、速率/体验评估与否决备选见 [`docs/23-writing-work-model.md`](../23-writing-work-model.md)。

## 理由

- 边界与用户心智、既有产品文档对齐
- 使「新会话 / compact 省 token」不再以拆散书稿为代价
- 不改 AgentEngine loop；满足 R1–R5
- 改动面限于 writing 落盘与 bootstrap，可渐进兼容旧路径

## 后果

### 正面

- 多 Session 续写同一本书路径稳定
- 工作区可导航；降低「章丢在 UUID 下」的支持成本
- 为按章 context / token 策略提供前置条件

### 负面

- 需迁移或兼容旧 `.agent/sessions/**/revisions`
- 同章多 Session 并发时草稿后写覆盖（正式稿仍有 patch 护栏）
- 不直接降低单次生成费用

### 对速率与逻辑

- 热路径仅目录列举 + 短索引；不增同步 LLM
- 工具主路径与审批语义不变；模型寻址更简单

## 备选方案

| 方案 | 结论 |
|------|------|
| UI 聚合 session 树 | 否决：真源仍错 |
| `draft_section` 直写 `sections/` | 否决：破坏 diff-first |
| 正文进 DB | 否决：过重，破坏文件工作区 |
| 先做多作品 Work 表 | 延后：单 workspace 下本 ADR 足够 |

## 关联

- `09-product-modes` §5.1（落地时改路径图）
- `14-writing-quality`、`16-user-session-history`
- 实施票：WW0–WW4（见 `23` §8）
