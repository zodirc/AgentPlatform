# 13 — 写作交付链路：问题与现象记录

> **范围**：仅记录 2026-07 写作模式下暴露的问题与用户可观察现象。  
> **结构**：第 1–8 节仅记录历史现象；第 9 节记录最终修复状态与验证证据。

## 1. 触发场景

用户在 **写作模式**（`scenario_id=writing`）中提出类似需求：

> 针对资料，写两章内容（李云龙与张白鹿），需要形成一个文件。

Agent 执行 Turn 后状态为 `completed`，用户打开 `workspace/exports/李云龙与张白鹿.md` 查看交付物。

---

## 2. 用户可见现象

### 2.1 导出文件内容异常

`exports/李云龙与张白鹿.md` 呈现为「拼接怪文件」，而非预期的两章正文：

| 区段 | 内容特征 |
|------|----------|
| 文件开头 | 出现合理的两章**提纲**（`outline.md` 风格） |
| 中部 | `01`、`02` 等章节标题下为占位文本（如「简洁的新正文」「第一节草稿内容」重复多遍） |
| 后部 | 混入与任务无关的内容：`Section A body for export.`、访谈笔记 stub、**《树状数组思考文档》全文**（约 1.2 万字） |

用户感知：**Agent 声称已完成写作并导出，但交付物不可读、与任务无关内容大量混入。**

### 2.2 与 Agent 对话输出的反差

同一 Turn 内，Agent 在对话区给出的总结（资料库结构、亮剑素材说明等）相对正常；  
但 **最终文件产物** 与对话中呈现的质量严重不一致。

### 2.3 资料引用诊断误报（相关现象）

用户提问「你对我们的资料库有什么理解？」时，写作侧 **资料引用诊断** 显示：

- 标题：**未检索资料**
- 说明：已要求引用/资料，但模型未调用 `search_sources`

而实际上该 Turn 通过 `list_dir` / `read_file` 浏览了 `sources/` 并给出了资料库总结；Turn 状态为 `completed`。

用户感知：**诊断结论与任务性质不符**（元问题被当成「必须 RAG 引用」的成稿任务）。

### 2.4 资料库保存后的索引状态不明确（相关现象）

资料库粘贴/上传成功后，UI 曾长期显示「已保存 … · **索引后台重建中**」，  
用户无法从界面上判断索引是否已完成、何时可检索。

---

## 3. 事后核对到的系统状态（与交付物的反差）

> 以下为排查工作区后的客观事实，用于解释「为何用户看到的 export 很离谱」。

### 3.1 正文实际写在另一路径

Turn 执行后，完整章节正文存在于：

- `workspace/.agent/revisions/第一章 金陵春雨.md`（约 4KB）
- `workspace/.agent/revisions/第二章 进退之间.md`（约 6KB）

内容与《亮剑》素材一致，篇幅完整，**并非** export 文件中看到的占位或无关文本。

### 3.2 导出文件未包含上述 revisions

`exports/李云龙与张白鹿.md` 在生成时**未纳入** `.agent/revisions/` 下的两章正文（提交前版本的 `export_document` 行为）。

### 3.3 `sections/` 目录存在历史残留

`workspace/sections/` 中同时存在多类与当前写作任务无关的文件，例如：

| 文件 | 典型内容 / 来源特征 |
|------|---------------------|
| `01.md` | 「简洁的新正文」（改稿测试残留） |
| `02.md` | 「第一节草稿内容」× 多遍（与 stub `draft_section` 输出一致） |
| `a.md` | `Section A body for export.`（golden `writing.09` fixture 语义） |
| `notes.md` | 访谈要点 stub |
| `树状数组思考文档.md` | 算法笔记，与《亮剑》任务无关 |

上述文件被拼进 export 后，造成用户看到的「怪文件」后半部分。

---

## 4. 写作工具链上的现象归纳

### 4.1 写入路径与导出路径不一致

| 工具 | 写入/读取位置（现象） |
|------|----------------------|
| `draft_section` | 写入 `workspace/.agent/revisions/{section_id}.md` |
| `export_document`（问题版本） | 优先读取并拼接 `workspace/sections/*.md` 全部文件 |
| `update_outline` | 写入 `workspace/outline.md` |

现象：**同一次写作任务中，「成稿」与「导出」操作的数据源不是同一目录。**

### 4.2 `export_document` 无范围概念

问题版本下，`export_document` 对 `sections/` 使用通配拼接（`sections/*.md` 排序后全部并入），  
不区分：当前 Turn 所属章节、历史测试残留、其他主题文档。

现象：**一次导出可把整个 `sections/` 目录历史一并交付给用户。**

### 4.3 工作区与 eval fixture 共用目录

Golden 用例（如 `writing.09_export_document`）的语义依赖 `outline.md` + `sections/a.md` 合并导出；  
用户日常写作的 `workspace/sections/` 与 eval 测试、stub 运行产生的文件**位于同一目录**。

现象：**开发/测试残留与用户文稿在文件系统层面无隔离，可进入同一次 export。**

### 4.4 Turn 完成不等于交付物正确

Turn 事件链可正常结束（`turn.completed`），  
但 export 产物仍可能：缺正文、含占位、含无关大段内容。

现象：**平台缺少对「导出文件是否包含本轮成稿」的可见失败信号；用户只能在打开文件后发现问题。**

---

## 5. 资料库上传链路相关现象（同期暴露）

| 现象 | 说明 |
|------|------|
| 上传 API 返回 500 | 早期版本在保存后同步向量索引，embedding 冷启动耗时长，超过 api→runtime 代理超时 |
| 文件可能已写入但请求失败 | 超时发生在索引阶段，用户侧看到失败，但 `sources/` 下文件有时已落盘 |
| `healthy` 不等于 embedding 已加载 | runtime 健康检查不涵盖 embedder；首次索引仍可能触发长时间加载 |
| `.env` 中 `EMBEDDING_*` 未传入容器 | 仅改 `.env` 而不走 retrieval compose profile 时，容器内仍为默认 `hash` 后端 |

---

## 6. 观测层与执行层现象错位（RAG 诊断）

写作模式 **资料引用诊断** 使用关键词判断用户是否「需要引用资料」（含「资料」等字样即可能命中）。

现象：

- 「你对资料库有什么理解？」类 **元问题** 被判定为需要 `search_sources`；
- Agent 用 `read_file` / `list_dir` 完成浏览并回答，诊断仍报「未检索资料」；
- 用户容易理解为：**RAG 未启用或必须说固定口令**，与「工具实际可用、模型走了另一条合理路径」相矛盾。

---

## 7. 小结：问题表象一览

| # | 问题表象 |
|---|----------|
| P1 | 用户要求的「形成一个文件」得到的是多源拼接的异常 export，而非两章正文 |
| P2 | 完整章节写在 `.agent/revisions/`，未出现在用户打开的 export 路径 |
| P3 | `sections/` 历史测试/无关文档可进入同一次导出 |
| P4 | `draft_section` 与 `export_document` 读写目录不一致 |
| P5 | Turn `completed` 无法保证交付物质量 |
| P6 | 资料引用诊断对「资料库」类元问题误报「未检索」 |
| P7 | 资料库上传后索引完成状态一度对用户不可见；上传曾因索引同步超时返回 500 |

---

## 8. 参考路径（便于复现核对）

```text
workspace/
├── outline.md                          # 两章提纲（正常）
├── .agent/revisions/
│   ├── 第一章 金陵春雨.md              # 实际成稿（用户未直观看到）
│   └── 第二章 进退之间.md
├── sections/                           # 被 export 拼接的来源（含历史残留）
│   ├── 01.md, 02.md, a.md, notes.md
│   └── 树状数组思考文档.md
└── exports/
    └── 李云龙与张白鹿.md               # 用户看到的异常交付物
```

相关 Turn 示例：`c0211427-7b1d-4b96-980f-44684e1ba7bc`（资料库理解）；写作导出任务见同目录 export 文件时间戳与 revisions 修改时间（2026-07-09 前后）。

---

## 9. 修复状态（2026-07-10）

本节记录对上述历史问题的闭环结果；第 1–8 节仍保留问题发生时的原始现象与路径。

| 问题 | 状态 | 修复与验证 |
|------|------|------------|
| P1 | 已修复 | `export_document` 强制接收有序 `section_ids`，禁止全目录通配导出 |
| P2 | 已修复 | `current_draft` 按本轮 manifest 读取 `.agent/revisions/{turn_id}/` |
| P3 | 已修复 | eval 默认使用 `.eval-workspace`，每个 case 重置；日常 `workspace/` 默认拒绝作为 eval 目录 |
| P4 | 已修复 | 导出显式支持 `source=current_draft\|confirmed`，不再通过目录存在性猜测数据源 |
| P5 | 已修复 | `tool.completed` 与 `turn.completed` 增加 `delivery_status`、问题列表和导出路径；UI 区分执行完成与交付异常 |
| P6 | 已修复并加固 | 元问题继续判定为 `not_needed`；stub 同步排除资料库元问题，明确引用请求仍触发检索 |
| P7 | 已修复并加固 | 上传保持异步索引与状态轮询；补齐后台失败、API pending/status 代理和 UI 四态测试 |

### 9.1 当前写作交付数据模型

```text
workspace/
├── outline.md
├── sections/{section_id}.md                         # 已确认正式稿
├── .agent/revisions/{turn_id}/{section_id}.md      # 本轮草稿
├── .agent/turns/{turn_id}/manifest.json            # 本轮草稿清单
└── exports/{name}.md                               # 显式章节集合的导出结果
```

`source=confirmed` 只读取指定的正式章节；`source=current_draft` 只读取当前 Turn manifest
指向的草稿。任一指定章节缺失或为空时不写半成品，并返回 `delivery_status=failed`。

### 9.2 回归证据

- Runtime：`141 passed`
- API：`64 passed`
- Web：`34 passed`，TypeScript typecheck 通过
- Contracts 与 eval runner：JSON schema / Python contracts / workspace isolation 共 `58 passed`
- Phase 2 Golden：`7 passed`，包含：
  - `writing.09_export_document`：正式稿显式范围，排除同目录历史文件
  - `writing.10_export_current_turn_draft`：本轮草稿导出，排除旧 revisions 与无关 sections
