# 24 — 写作质量票级执行方案（WQ0–WQ4）

> **来源**：[23-writing-quality.md](23-writing-quality.md) §7 / §9.1（D1–D7）。  
> **性质**：可排期的票级落地清单；速率红线继承 [17](17-execution-plan.md) R1–R5。  
> **否决（全程）**：默认 judge / 每轮强制 RAG / Skills 预注入扛质量 / 自动串联 polish pipeline。

---

## 0. 总览

| 票 | 对应 23 | 主题 | 动作 | 状态 |
|----|---------|------|------|------|
| **WQ0** | Q0 | cache 地基 + style 模板 | D2 D3 D1 | ✅ 已落地 |
| **WQ1** | Q1 | Don't / Samples 深化 | D1 深化 | ✅ 已落地 |
| **WQ2** | Q2 | Export 模板 + 结构 lint | D6 | ✅ 已落地 |
| **WQ3** | Q3 | `/polish` `/outline` 确定性展开 | D4 D5 | ✅ 已落地 |
| **WQ4** | Q4 | 写作质量 golden + 离线 rubric | D4 D7 收口 | ✅ 已落地 |

依赖：

```text
WQ0 → WQ1（内容）
WQ0 → WQ2（交付，可并行）
WQ1 → WQ3（有文风约束再润色）
WQ0～WQ2 → WQ4（有行为可断言再黄金化）
```

验收总闸：

```bash
cd services/runtime && python3 -m pytest \
  tests/test_writing_cards.py \
  tests/test_writing_prefix_stability.py \
  tests/test_export_lint.py \
  tests/test_input_compiler.py \
  tests/test_eval_rubric.py -q
make eval-all   # 含 writing.12 / writing.13
```

---

## 1. WQ0 — cache 地基 + style 卡模板（已落地）

见既有 §1：库存确定性选卡、按 kind 预算、`prefix_hash`、style 模板。

---

## 2. WQ1 — Don't / Samples 深化（已落地）

| 项 | 落地 |
|----|------|
| Samples 导入 | `extract_sample_paragraphs` / `import_samples_into_style_body`（无 LLM） |
| Don't 开关 | frontmatter `dont_enabled: false` → pin 时替换为「已关闭」 |
| 模板 | `style_card.md` Don't 清单加厚 |
| 测试 | `test_import_samples_from_chapter` / `test_dont_enabled_frontmatter` |

---

## 3. WQ2 — Export 模板 + markdown 结构 lint（已落地）

| 项 | 落地 |
|----|------|
| 模块 | `writing/export_lint.py`：`heading_skip` / `empty_section` / `html_forbidden` |
| 工具 | `export_document(..., profile=novel-zh\|essay\|none)`；失败不写盘 |
| 设置 | `writing_export_profile`（默认 `novel-zh`） |
| 测试 | `tests/test_export_lint.py` |

---

## 4. WQ3 — `/polish` `/outline`（已落地）

| 项 | 落地 |
|----|------|
| 展开 | `expand_writing_slash` → 用户消息附言；`should_query=True`；**不改 system** |
| Stub | `[polish]`/`[outline]` 跳过 `search_sources`；分别走 `propose_patch` / `update_outline` |
| system.md | 文档化 slash 纪律 |
| 测试 | `test_expand_polish_and_outline_*`；前缀 hash 不变 |

---

## 5. WQ4 — golden + 离线 rubric（已落地）

| 项 | 落地 |
|----|------|
| Golden | `writing.12_polish_skip_retrieval`；`writing.13_outline_slash` |
| Eval | `tool.forbidden_names` / `tool.max_calls`（`eval_run.py` + schema） |
| 检索预算 | `writing.05` 断言 `search_sources` ≤ 3 |
| Rubric | `offline/rubric.py` 加禁词/套话惩罚与标题跳跃惩罚（**仅离线**） |

---

## 6. 文档关联

| 文档 | 关系 |
|------|------|
| [23](23-writing-quality.md) | 设计与场景切片；本文为票级拆分 |
| [14](14-model-harness.md) | 先 cache 再加厚 |
| [22](22-skills-layer.md) | 质量主路径不依赖 Skills |
