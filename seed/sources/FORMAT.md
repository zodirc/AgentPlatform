# 写作既定事实库 — 文档格式规范

> **权威格式文档**。给联网 AI 生成内容时，优先复制 [`PROMPT_FOR_RESEARCH_AI.md`](PROMPT_FOR_RESEARCH_AI.md)。  
> 放置说明见 [`README.md`](README.md)。  
> 检索切块 / embed / 表格外挂口径见 [`docs/15-rag-and-sources.md` §9](../docs/15-rag-and-sources.md)（RQ1b 已落地：叶软顶约 4000 字 ≈ 2000 token 当量）。

---

## 0. 默认约定（先读这条）

| 情况 | 怎么放 |
|------|--------|
| **默认（推荐）** | **一部作品 / 一个人物 / 一个时期 = 一个 `.md` 文件** |
| 例外 | 单文件将超过约 1 MiB，或你主观上觉得必须拆册时，再建成目录包 |

不要为一部小说默认拆成 overview、人物、剧情等多个文档——对作者和检索 AI 都过重。长内容靠文内 `##` / `###` 分层即可。

---

## 1. 系统如何索引（决定标题怎么写）

1. 按 `#` / `##` / `###` 分节（`####` 不参与分节）；
2. 单节优先整节保留；超过约 **4000 字**（≈2000 token 当量，可配置）再滑窗切分；
3. **宽表**在索引时改为短指针（磁盘原文不动）；大表请外挂（见 §1.1）。

因此：**长文可以很长；必须用密而带专名的 `##`/`###`。**

### 1.1 表格外挂

| 情况 | 做法 |
|------|------|
| 小表（约 ≤5 行数据、短列） | 可留在正文 |
| 宽表 / 长表（时间线、对照、多列表） | **外挂**到同主题旁路文件，正文只留一行说明 + 路径 |

推荐布局：

```text
seed/sources/writing/dramas/<slug>.md          # 主文：叙事与可引用细节
seed/sources/writing/dramas/tables/<slug>-*.md # 外挂表（仍可被 search / read_file）
```

主文示例：

```markdown
## 时间线要点

完整对照表见 `tables/<slug>-timeline.md`（勿把整表粘进本节）。
```

索引器会对文内过宽的 GFM `|…|` 表写入 `[table detached: …]` 指针，避免整表污染 embedding；需要全表时用 `read_file`。
---

## 2. 放置路径（默认单文件）

```text
seed/sources/writing/persons/<slug>.md
seed/sources/writing/periods/<slug>.md
seed/sources/writing/dramas/<slug>.md
seed/sources/writing/novels/<slug>.md
seed/sources/writing/movie/<slug>.md      # 电影（可与 dramas 并列）
```

**文件名不必等于作品中文名。** `movie1.md` 只要正文标题/概要写清《心花路放》，检索靠内容命中即可。  
推荐仍用拼音 slug（如 `xin-hua-lu-fang.md`）便于人读；`movie1.md` 也合法。

**可选多文件包**（仅当默认单文件不够用时）见文末附录。

---

## 3. 单文件必填结构

```markdown
# <正式名>

> 类型: person | period | drama | novel
> 体裁: note | volume
> 别名: <异名1>, <异名2>
> tags: <可选，少量高差标签，逗号分隔>   ← RQ1c；宁少勿滥
> 时期: <可选>
> 主题slug: <与文件名一致>
> 分册: 单篇
> 来源说明: 演示用既定事实资料，非学术论文；请勿粘贴受版权保护的大段原文

## 概要

## 世界观与背景          ← 人物可改为「生平背景」；时期可改为分域综述

## 人物                  ← 或「重要人物」；纯人物篇可细化生平阶段

### <专名>

## 主线剧情              ← 人物用「生平阶段」；时期用「重要事件」

### <阶段名>

## 时间线要点            ← 可选

## 可引用细节

## 勿混淆                ← 推荐
```

速查卡可删减小节；长文保留以上骨架并加长各节即可。可复制 [`_template.md`](_template.md)。

| 字段 | 必填 |
|------|------|
| `# 标题`、`类型`、`体裁`、`主题slug`、`来源说明`、`## 概要` | 是 |
| `别名`、人物/剧情类小节、`可引用细节` | 强烈推荐 |

`体裁`：短用 `note`，长用 `volume`（仍是**一个文件**）。

---

## 4. 篇幅

| 项 | 说明 |
|----|------|
| 长度 | **不设必须很短**；数千～上万字常见 |
| 单节 | 过长请再拆 `###`（标题含专名） |
| 单文件软顶 | 建议 < ~200KB；硬顶（Web 上传）约 **1 MiB** |
| 版权 | 复述归纳，禁止大段原文 |

---

## 5. 交稿自检

- [ ] 落在 `seed/sources/writing/{persons|periods|dramas|novels}/<slug>.md`
- [ ] 元数据齐全；`主题slug` = 文件名（无 `.md`）
- [ ] 有足够的 `##`/`###`；无大段原文
- [ ] 未写入 `eval/retrieval/corpus/`；稿件只放本仓库 `seed/sources/writing/`（运行时只读挂载，勿手拷 workspace）

---

## 附录：何时才用多文件包

仅当单文件过大或你明确要拆册时：

```text
seed/sources/writing/novels/<slug>/
  00-overview.md
  01-….md
```

模板：[`_template_volume_overview.md`](_template_volume_overview.md)、[`_template_volume_part.md`](_template_volume_part.md)。  
**默认不要走附录。**

运行时：Compose 将 `seed/sources/writing` **只读挂载**为 `/workspace/sources/seed/writing`（不拷贝）。改稿后 `make seed-sources` 只重建索引；Agent 不可写 `sources/seed/**`。
