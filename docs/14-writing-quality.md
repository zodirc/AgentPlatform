# 14 — 写作质量（模块正文）

> **本模块唯一维护入口**（含原执行票 WQ0–WQ4）。历史交付事故见 git。  
> **关联**：RAG/资料库 → [15](15-rag-and-sources.md)；速率 → [13](13-rate-redlines.md) R1–R5；Harness cache → [12](12-model-harness.md)；Skills **非**质量主路径 → [19](19-skills-layer.md)；**写作下一刀提案（WN1–WN3）在 [30](30-quality-and-agility.md) 维护**，落地后状态回写本文。

**现状（2026-07）：WQ0–WQ4 已全部落地。** 本文维护去留、场景杠杆与验收；不再另开「执行方案」文。

---

## 0. 票状态与验收

| 票 | 主题 | 状态 |
|----|------|------|
| **WQ0** | cache 地基 + style 卡模板 / 选卡预算 | ✅ |
| **WQ1** | Don't / Samples 深化 | ✅ |
| **WQ2** | Export 模板 + 结构 lint | ✅ |
| **WQ3** | `/polish` `/outline` 确定性展开 | ✅ |
| **WQ4** | writing.12/13 golden + 离线 rubric | ✅ |

```bash
cd services/runtime && python3 -m pytest \
  tests/test_writing_cards.py \
  tests/test_writing_prefix_stability.py \
  tests/test_export_lint.py \
  tests/test_input_compiler.py \
  tests/test_eval_rubric.py -q
make eval-all   # 含 writing.12 / writing.13
```

**全程否决：** 默认 judge · 每轮强制 RAG · Skills 预注入扛质量 · 自动串联 polish pipeline。

落地索引：`writing/export_lint.py` · `expand_writing_slash` · `sources/cards/` style 模板 · `eval/golden/writing/12_*` `13_*` · `offline/rubric.py`（仅离线）。

---

## 1. 去留

| 方向 | 做？ | 理由 |
|------|------|------|
| 每轮强制 retrieval | **否** | 改稿被检索绑架 |
| Turn 末强制 judge | **否** | 多一轮 + 延迟 |
| 默认 Skills 扛质量 | **否** | 主路径在卡 / system / 工具 |
| 加厚 style 卡（进稳定前缀） | **是（已落地）** | 与 cache 同向 |
| export 确定性 lint | **是（已落地）** | 少模型；可测 |
| RAG 只服务证据、不进 cache 前缀 | **保持** | 见 31 |
| 用户触发 `/polish` | **是（已落地）** | 不计默认热路径 |
| pass 走廊（用户驱动多 Turn） | **是** | 平台不自动串联 |

```text
上传资料 → sources/     → RAG：事实（31）
整理卡片 → sources/cards/ → Pin：人物 / 情节 / 文风
成稿工具 → draft / patch → 交付
```

**质量 ≠ 资料越多。** 资料解决「对得上材料」；文风卡解决「像不像、排得齐」。

---

## 2. 场景杠杆（W1–W7）

| 场景 | 用户在做 | 主杠杆 | RAG？ |
|------|----------|--------|-------|
| W1 立人设 | 建角色/文风卡 | 卡 pin | 否 |
| W2 据材料新写 | 按资料写章 | RAG + cite + 卡 | **要**（≤2–3） |
| W3 局部改稿 | 改一段 | patch + 卡 | **通常跳过** |
| W4 去 AI 味 | `/polish` | 卡 Don't/Samples | **跳过** |
| W5 大纲 | `/outline` | `update_outline` | 否 |
| W6 交稿排版 | 导出 | export lint | 否 |
| W7 核对引用 | `/verify` | check_citation | 按需 |

**pass 走廊：** 每个 pass = 用户显式 Turn；同一稳定前缀吃 cache；**不**自动串成 pipeline。

```text
意图 → 大纲 → 成稿(RAG) → 改稿(0搜) → /polish(0搜) → 导出 → /verify
```

---

## 3. RAG 与写作的边界

- 成稿取证：模型自主 `search_sources`；预算见 system / golden。  
- polish / outline：**断言 0×`search_sources`**（writing.12/13）。  
- 检索结果进工具后缀，**永不**进 cache 前缀。  
- 细节与效果闸 → [15](15-rag-and-sources.md)。

---

## 4. Cache 与前缀纪律（摘要）

优先加厚 **style 卡 + 稳定 system/tools 前缀**（AH2）。微调越多次，前缀越要确定性（C1–C5 见 [12](12-model-harness.md)）。禁止为「写得更好」破坏前缀哈希。

---

## 5. 以后若再改写作质量

1. 先答 §1 去留三问（速率 / 验证 / 成熟）。  
2. 改代码 + 更新 **本节票表与验收命令**（不要再开 `24-*-execution`）。  
3. 效果向改动过 [15](15-rag-and-sources.md) 效果闸（若动检索）。  
4. polish/outline 0 搜不得破坏。
