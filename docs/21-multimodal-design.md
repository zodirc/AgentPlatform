# 21 — 多模态（图片 / 文本附件）设计方案

> **性质**：可排期的设计方案；**本文本身不改代码**，落地时按 Phase 拆 PR，并宜配套 ADR-020。  
> **产品目标（一期）**：对话中可上传**图片**与**文本文件**；Agent 能读准文本、在有 Vision 时看懂图片；**不拖慢** Turn 热路径。  
> **一期范围**：仅 `kind = text | image`。**不做** PDF / Office / 音视频（见 §1）。  
> **约束继承**：[17-execution-plan.md](17-execution-plan.md) 速率红线 R1–R5；[11-product-experience.md](11-product-experience.md) TTFB ≤ 300ms、首模型 token ≤ 800ms（P95）；[ADR-014](adr/014-turn-intake-over-intent-pipeline.md) Intake 确定性编译。  
> **现状基线**（2026-07）：Turn 契约仅 `message: string`；Provider 丢弃非 text；写作 `sources/upload` 仅 UTF-8 文本 ≤ **1 MiB**。聊天附件尚无。  
> **前序分析**：优先「预上传 + Turn 只带 id」；文本走 `read_file` / 短预读；图片走 Vision 首轮物化。

---

## 0. 需求对照

| # | 需求 | 方案落点 | 不做则失败的表现 |
|---|------|----------|------------------|
| 1 | **交互性能** | 预上传；Turn 只带 `attachment_ids`；transcript 不存 base64；超限在上传门拒绝 | 点发送长时间无 `turn.accepted`；或大文件拖垮首 token / 长会话 |
| 2 | **文本读取准确度** | UTF-8 文本直读；超字符预算分页/`truncated`；禁止假 decode | 乱码当正文；大文件一次塞爆上下文 |
| 3 | **图片理解** | 有 `supports_vision` 时**首轮**注入 image；之后 `file_ref` stub | 每轮重传原图；无 Vision 却静默「已看见图」 |
| 4 | **文件大小限制** | 单文件 / 单 Turn / Session 三级硬顶；api + Web 双检；超限 **413/422** | 无限上传打满磁盘与模型账单 |
| 5 | **可证明** | MIME/大小单测；golden；超限用例 | 「能传」但超限不拒绝或文本读不准 |

**验收一句话**：用户上传合法大小的 `.txt`/`.md`/图片 → Turn 立即 accepted → 文本可核对读准（或 Vision 看见图）→ 超限上传被拒绝且有明确错误 → 后续 Turn 不因附件体积线性变慢。

---

## 1. 一期范围与非目标

### 1.1 一期允许（白名单）

| kind | 扩展名（示例） | MIME（示例） |
|------|----------------|--------------|
| **text** | `.txt` `.md` `.markdown` `.json` `.yaml` `.yml` `.csv` `.py` `.ts` `.tsx` `.js` `.log` | `text/*`；`application/json`；`application/yaml`（声明与探测双检） |
| **image** | `.png` `.jpg` `.jpeg` `.webp` `.gif` | `image/png` \| `jpeg` \| `webp` \| `gif` |

扩展名与 MIME **双检**：不一致 → 拒绝上传（不落盘或落盘后 `kind=reject` 且不可引用进 Turn）。

### 1.2 非目标（一期否决 / 延期）

| 项 | 说明 |
|----|------|
| **PDF / DOCX / PPT / 压缩包 / 可执行文件** | 二期再议；一期上传即 **415 Unsupported Media Type** |
| OCR / `extract_document` / 扫描件流水线 | 无 PDF 则一期不做 |
| 音视频、摄像头流 | 否决 |
| 默认全模型 Vision | 无 capability 不得注入 image |
| 聊天附件无限配额 | 必须有大小与数量硬顶（§5.3） |
| Turn body 直传整文件 multipart | 破坏 TTFB；必须预上传 |
| 借机改 Agentic Loop 为固定 pipeline | 禁止（ADR-005/006/014） |
| 公网对象存储全家桶 | 一期本地 `uploads/` 即可 |

---

## 2. 设计原则（性能 × 准确度 × 大小）

### 2.1 性能：引用优先，字节后置（R1–R5）

```text
上传（可与打字并行）──► 大小/MIME 门禁 ──► blob 落盘 + 元数据
                                              │
用户点发送 ──► CreateTurn{ message, attachment_ids[] }  ← 仅 UUID
              │
              ▼
         turn.accepted（TTFB 目标不变）
              │
              ▼
         InputCompiler：id → file_ref（path、mime、byte_size、truncated?）
              │
         ┌────┴────┐
         │ text    │ 小文件可同步短预读（硬顶）；大文件只 ref，模型 read_file 分页
         │ image   │ supports_vision 且「首见」→ 注入最多 N 张 image 块
         └─────────┘
```

| 红线 | 一期含义 |
|------|----------|
| **R1** | 上传与 Turn 解耦；Turn 不做整文件拷进 prompt（文本预读有硬顶） |
| **R2** | 禁止「先开模型做 OCR/描述再开聊」作为默认路径 |
| **R3** | Intake 只查元数据 + 可选短文本预读 |
| **R4** | writing 若要把文本附件进资料库，索引仍异步 |
| **R5** | 超限拒绝、文本截断、vision stub 均须可测 |

**Transcript**：禁止 base64/原图入 JSONB；只存 `text` + `file_ref`；Vision 仅首见物化，之后 stub。

### 2.2 准确度（一期：文本 + 图片）

| 类型 | 准确度路径 | 工具 / 行为 |
|------|------------|-------------|
| text | UTF-8 读取；非法序列 `errors=replace` 须在 tool_result 标明；超 `READ_CHAR_BUDGET` → `truncated` + `offset` 续读 | `read_file`（增强分页）、`grep` |
| image | 有 Vision → 首轮看图；无 Vision → **显式错误/引导**，禁止假摘要 | Provider image parts；可选后续再开 `describe_image` |
| 其它 MIME | 上传阶段拒绝 | — |

**反模式**：图片当文本 decode；无 Vision 装看懂；超限仍 200；大文本一次灌满 user message。

### 2.3 大小限制（硬顶，可 env 覆盖）

对齐现有写作资料 **1 MiB** 习惯，聊天附件略放宽图片、文本保持同级或略高，避免「能传但不能聊」。

| 限制项 | 建议默认 | 配置键（草案） | 超限行为 |
|--------|----------|----------------|----------|
| 文本单文件 | **1 MiB**（1_048_576） | `ATTACHMENT_TEXT_MAX_BYTES` | 上传 **413**；文案「文本最大 1 MiB」 |
| 图片单文件 | **5 MiB** | `ATTACHMENT_IMAGE_MAX_BYTES` | 上传 **413**；文案「图片最大 5 MiB」 |
| 单 Turn 附件个数 | **4** | `ATTACHMENT_MAX_PER_TURN` | Turn **422**；未计入模型 |
| 单 Turn 附件字节合计 | **8 MiB** | `ATTACHMENT_MAX_BYTES_PER_TURN` | Turn **422** |
| Session 附件总字节 | **50 MiB** | `ATTACHMENT_MAX_BYTES_PER_SESSION` | 上传 **413** |
| Session 附件总个数 | **40** | `ATTACHMENT_MAX_COUNT_PER_SESSION` | 上传 **413** |
| 文本 Intake 预读 | **32 KiB** 字符（对齐现 `read_file` 截断） | `ATTACHMENT_TEXT_PREREAD_CHARS` | 预读截断并标 `truncated`；全文靠工具续读 |
| 单 Turn Vision 图片数 | **2** | `ATTACHMENT_VISION_MAX_IMAGES_PER_TURN` | 超出仅带 `file_ref`，事件 warning |
| 网关/反向代理 body | ≥ 单文件上限 + 余量（建议 **10 MiB**） | Caddy / uvicorn 显式配置 | 避免代理先于应用掐断且无结构化错误 |

**校验顺序（上传）**：

```text
1. Content-Length / 流式累计字节 > kind 单文件上限 → 立即中断，413
2. MIME + 扩展名白名单 → 失败 415
3. Session 个数 / 总字节配额 → 413
4. 落盘 + 写 attachments 行
```

**校验顺序（CreateTurn）**：

```text
1. attachment_ids ⊆ 本 session 且均为 text|image
2. len(ids) ≤ MAX_PER_TURN
3. sum(byte_size) ≤ MAX_BYTES_PER_TURN
4. 通过后才下发 StartTurn
```

Web 须在选文件时做**同款客户端预检**（体验），但**以服务端为准**（安全）。

---

## 3. 现状与复用点

| 能力 | 位置 | 本方案用法 |
|------|------|------------|
| `sources/upload` 1 MiB UTF-8 | `api` admin workspace | **保留**；聊天附件独立 API；文本上限可对齐 1 MiB |
| `read_file` 32KB 截断 | `tools/core/tools.py` | 文本附件主读路径；补 `offset/limit` 更佳 |
| InputCompiler `@path` | `input_compiler.py` | 扩展 `attachments` → `file_ref` |
| Provider text-only 转换 | openai / anthropic | 图片路径需改；文本不变 |
| 端用户 session 归属 | docs/20 | attachment 归属 session；Turn 前校验 |

---

## 4. 目标架构

```text
 Web                      api                         runtime
  │                        │                            │
  │  POST /attachments     │  大小/MIME/配额门禁         │
  │  (multipart)           │  落盘 + DB                  │
  │◄─ { id, kind, bytes } ─┤                            │
  │                        │                            │
  │  POST /turns           │  校验 ids + 每 Turn 配额     │
  │  { message,            │  StartTurn + attachment_ids│
  │    attachment_ids }    │───────────────────────────►│
  │                        │                            │ InputCompiler → file_ref
  │  SSE turn.accepted     │◄── events ────────────────┤ 文本短预读 / 图 needs_vision
  │                        │                            │ AgentEngine
  │                        │                            │  read_file | vision parts
```

**原则**：字节与 Turn 解耦；超限失败在 api 门，不进 runtime 热路径；准确度靠 UTF-8 文本工具 + 显式 Vision。

---

## 5. 数据模型与契约草案

### 5.1 表 `attachments`

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | UUID PK | |
| `session_id` | UUID FK | |
| `filename` | TEXT | 展示名；落盘名安全化 |
| `mime` | TEXT | 探测结果为准 |
| `byte_size` | INT | 原始字节（门禁用） |
| `sha256` | CHAR(64) | |
| `storage_path` | TEXT | 如 `uploads/<session>/<id>.png` |
| `kind` | TEXT | 一期仅 `text` \| `image`（`reject` 可不落或审计用） |
| `meta` | JSONB | 图：width/height；文本：`encoding`、`truncated` 预检等 |
| `created_at` | TIMESTAMPTZ | |

一期**不需要** `extract_status` / `extract_path`（无 PDF 抽取）。若表结构预留二期字段，默认为 null，代码路径不读。

### 5.2 契约

**预上传**：`POST /api/v1/sessions/{id}/attachments`  
→ `201 { id, filename, mime, byte_size, kind }`  
→ `413` 超大小/配额；`415` 类型不支持；`400` 空文件

**Turn**：

```json
{
  "message": "请概括这份说明，并描述配图里的流程",
  "scenario_id": "agent",
  "attachment_ids": ["uuid-text", "uuid-image"]
}
```

- `attachment_ids` 可选，默认 `[]`
- 示例文件为文本与图片，**不是** PDF

**`file_ref` 块**：

```json
{
  "type": "file_ref",
  "attachment_id": "...",
  "path": "uploads/…/note.md",
  "mime": "text/markdown",
  "kind": "text",
  "byte_size": 1200,
  "meta": { "truncated": false }
}
```

**`image` 临时块**（仅出站组装，不长期进 transcript）：

```json
{
  "type": "image",
  "attachment_id": "...",
  "source": { "path": "uploads/…/shot.png" },
  "detail": "auto"
}
```

### 5.3 安全（与大小并列）

| 规则 | 一期默认 |
|------|----------|
| MIME + 扩展名白名单 | 仅 §1.1 |
| 空文件（0 byte） | 拒绝 |
| 文件名 | 安全字符集；禁止 `..` / 路径段 |
| 归属 | 仅 session owner；Turn 引用前校验 |
| 病毒扫描 | 可记「未扫描」；不阻塞一期 |

---

## 6. Runtime 行为详设

### 6.1 InputCompiler

`compile(message, *, selection=None, attachments: list[AttachmentMeta]=None)`

1. 保留 slash / `@path` / selection。
2. 每个附件 append `file_ref`（含 `byte_size`）。
3. `kind=text` 且 `byte_size` 小：按 `ATTACHMENT_TEXT_PREREAD_CHARS` 同步预读进短 `text` 块，超则标截断。
4. `kind=image` 且 vision：标 `needs_vision`（注意单 Turn 张数硬顶）。
5. 不计 PDF/抽取状态。

### 6.2 工具（一期）

| 工具 | 行为 | 速率 |
|------|------|------|
| `read_file` | 文本附件主路径；建议支持 `offset`/`limit`；对 `kind=image` path **拒绝**并提示走 Vision/看图模型 | 🟢 |
| `list_attachments` | 列出本 session 附件 id/mime/bytes/kind | 🟢 |
| `grep` / `list_dir` | 对已落盘文本照常 | 🟢 |

**不做** `extract_document`（一期）。`describe_image` 默认关；有 Vision 时优先直挂模型。

### 6.3 ContextEngine / Provider

1. 文本：预读或 tool 结果进上下文；超 budget 走现有 compact/snip。
2. 图片：首见且未超 `VISION_MAX_IMAGES` 时物化；计入 token 估算。
3. 无 vision：用户本 Turn 仅图或图为必要依据 → 明确失败文案。
4. 出站可读盘转 data URL / base64，**写回 transcript 前 stub 为 file_ref**。

### 6.4 时序

```text
文本：
  upload(≤1MiB) → send(ids) → accepted → （短预读或）read_file → 作答

图片 + vision：
  upload(≤5MiB) → send → accepted → 首轮带 1～2 张 image → 作答
  → transcript 只留 file_ref；追问不再传像素

超限：
  upload 10MiB 图 → 413，Send 前 UI 已提示；不产生 Turn
```

---

## 7. 准确度与 Eval

### 7.1 上传 / 大小门禁

| 用例 | 期望 |
|------|------|
| 文本 1 MiB 边界内 | 201 |
| 文本 1 MiB + 1 字节 | 413 |
| 图 5 MiB + 1 | 413 |
| `.pdf` / `.docx` / `.exe` | 415 |
| MIME 与扩展名不符 | 415 |
| 单 Turn 5 个附件 | 422 |
| Session 超总配额 | 413 |

### 7.2 文本 / 图片行为

| 用例 | 期望 |
|------|------|
| 小 `.md` 附件「原文说了什么」 | 预读或 `read_file` 命中关键词；无乱码装懂 |
| 文本 > 预读预算 | `truncated` 可见；续读可拿到后文 |
| 图 + vision on | 能答图中明确可见内容 |
| 图 + vision off | 明确不可视，无假摘要 |
| 第二轮只追问同图 | 请求体无原图字节；transcript 无 base64 |

### 7.3 性能抽检

1. 上传 4 MiB 图（合法）后发 Turn：TTFB 仍达标。  
2. 50 Turn 会话含若干历史附件：单 Turn P95 无明显线性恶化。

---

## 8. Web UX（最小集）

| 项 | 要求 |
|----|------|
| `accept` | 仅文本与图片扩展名（与 §1.1 一致） |
| 选文件预检 | 超 1 MiB 文本 / 5 MiB 图片立刻红字，不发起上传 |
| 进度 / 错误 | 展示 413/415 服务端文案 |
| 芯片 | 文件名 + 体积（如 `notes.md · 12KB`） |
| 缩略图 | 图片可小图预览；不进巨图气泡 |
| 文案 | 「附件」≠ writing「资料库」 |

**禁止**：把整文件当作 Turn JSON/multipart 一并发出。

---

## 9. 分阶段落地（一期收窄后）

| Phase | 主题 | 交付 | 速率 | 准确度 |
|-------|------|------|------|--------|
| **M0** | 存储 + **大小/MIME 门禁** | 表；预上传；三级配额；Web `accept`+预检 | 🟢 | 超限必拒 |
| **M1** | 文本附件进 Turn | `attachment_ids`；`file_ref`；预读预算；`read_file`/`list_attachments` | 🟢 | UTF-8 读准、截断可续 |
| **M2** | Vision 图片 | capabilities；首轮物化；张数硬顶；transcript stub；provider 转换 | 🟡 token | 能看图；无 capability 显式失败 |
| **M3**（可选） | 写作合流 | 文本附件「加入资料」异步索引 | 索引异步 | 检索命中附件要点 |

依赖：`M0 → M1 → M2`；`M3` 依赖 M1。

**二期（本文不排期）**：PDF/Office、`extract_document`、OCR——须单独立项，并重定文档类大小上限。

**默认合并**：M0+M1 先合（文本已可用）；M2 跟能力开关。

---

## 10. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 大图费用与延迟 | 5 MiB 单文件顶；每 Turn ≤2 张 Vision；首轮后 stub |
| 大文本灌爆上下文 | 1 MiB 上传顶 + 32KiB 预读顶 + `read_file` 分页 |
| 代理默默截断 | Caddy body 显式 ≥ 应用上限，错误可识别 |
| 用户传 PDF 预期落空 | UI/API 明确「一期仅文本与图片」；415 文案给出类型列表 |
| 与 `sources/upload` 混淆 | 双入口；上限都要提示 |
| 无限 Session 囤积 | Session 50 MiB / 40 个；后续 TTL 清理 |

---

## 11. 速率影响自评

| 改动 | 预估 | 说明 |
|------|------|------|
| 上传门禁（长度累计） | 🟢 离 Turn 热路径 | |
| Turn 校验 ids + sum(size) | 🟢 | |
| 文本短预读 ≤32KiB | 🟢 | |
| Vision 出站编码 ≤2 张 | 🟡 | 计入首 token，受大小顶约束 |
| 误把大文件进 Turn body | 🔴 | 否决 |

---

## 12. 开放决策（实现前拍板）

| # | 问题 | 建议默认 |
|---|------|----------|
| D1 | 存储位置 | workspace 下 `uploads/<session_id>/` |
| D2 | 文本上限是否与资料库同为 1 MiB | **是**，降低心智负担 |
| D3 | 图片 5 MiB 是否再降到 3 MiB | 先 5；若首 token 实测差再降 |
| D4 | GIF 动图是否允许 | 允许上传但 Vision `detail` 慎用；或一期只静帧 png/jpeg/webp |
| D5 | writing 文本附件是否自动进资料库 | 默认否；M3 显式「加入资料」 |

---

## 13. 文档与 ADR 联动（落地时）

1. **ADR-020**：Attachments by reference；一期仅 text/image；**强制大小配额**；Vision 首轮物化。  
2. 更新 `05` Intake「附件」指针到本文。  
3. 更新 contracts / OpenAPI / golden（含 413/415 用例）。  
4. 更新 `11`：附件大小与类型体验门槛。  
5. Caddy/compose 注明上传 body 上限。

---

## 14. 一页总结

| 维度 | 一期决策 |
|------|----------|
| **范围** | 仅图片 + 文本；PDF/Office 延期 |
| **性能** | 预上传 + Turn 只传 id；transcript 无 base64；Vision 首见物化 |
| **准确度** | 文本 UTF-8 工具可读可截断；图片靠 Vision + 显式 capability |
| **大小** | 文本 **1 MiB** / 图 **5 MiB**；Turn **4 个 / 8 MiB**；Session **40 个 / 50 MiB**；预读 **32 KiB**；Vision **≤2 张/Turn** |
| **节奏** | M0 门禁与存储 → M1 文本 Turn → M2 Vision →（可选）M3 写作索引 |

**一期成功标准**：合法文本/图片好用且读得准；非法类型与超限**坚决拒绝**；交互速率红线不回退。
