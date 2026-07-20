# Workbench interaction checklist (docs/15)

**Automated (run first):**

```bash
make retrieval-bench                    # layer 1（本地 venv Python 3.11+）
make migrate                          # 若缺列 / alembic 落后
# 日常栈：.env 需 MODEL_MODE=stub，或 live + 有效 MODEL_API_KEY / 设置页供应商
make turn-effect-bench                # 需栈 healthy
make eval-path-prefix                 # writing.14 隔离 stub（勿再用重 retrieval 镜像）
```

Fill remaining rows on effect-gate PRs (~15 min in Writing Workbench).

**IX3 — 禁止把摄取当效果：**

- ❌ 「上传成功 / 索引 ready / 同步绿」当作召回质量验收
- ❌ slash `/rag-test` 或必须上传才能测
- ✅ `make retrieval-bench-prod` + 下表自然问句

| # | Step | Pass? | Notes |
|---|------|-------|-------|
| 1 | 成稿：按资料写一节，能搜到并可核对材料细节 | ☐ | |
| 2 | `/polish`：时间线无 `search_sources` | ☐ | covered by `writing.12` in turn-effect-bench |
| 3 | （RE3）限定 `path_prefix` / 子目录后，不出现域外片段 | ☐ | covered by `writing.14` filters assertion |
| 4 | （IX2）手改 `workspace/sources/*.md` 后无需点同步即可被检索（等 debounce） | ☐ | |
| 5 | （IX3）资料库状态文案含「投影/摄取」且不宣称效果过关 | ☐ | |

Same-question A/B (layer 2 manual supplement) — attach to PR if turn-effect-bench is not enough:

| Prompt | A (before) cite/quality | B (after) cite/quality | search_sources count A/B | wall-clock A/B |
|--------|-------------------------|------------------------|--------------------------|----------------|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
