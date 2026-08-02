# Official live scorecard

- **protocol**: `official-small-2026-08-m1`
- **updated_at**: `2026-08-02T04:58:49.880906+00:00`
- **含义**: live 实测官方小量的分数锚点（调优看 Δ）；题集在 `suites.small.yaml` / SWE slices。
- **明细**: Ops 官方页 / `eval/reports/official/runs/<id>/`（不进 git）

## 主指标（一眼）

| 套件 | 主指标 | 值 | run_id | 备注 |
|------|--------|----|--------|------|
| retrieval | hybrid nDCG@10 | 0.4123 | `8f507709-c087-483f-81b2-1ac8f8ebf4c8` | ΔBM25 nDCG@10=0.0093 · R@100=0.5525 |
| context | compact F1 / retention | 0.2728 / 0.6724 | `958f5568-618c-4239-9c97-03416a44019b` | full=0.4057 · truncate=0.4138 · model=`deepseek-v4-flash` |
| coding | patch_rate | 0.6667 | `88dcb9d7-d088-42a6-b9dc-8096c6469a60` | tier=`n3` · n=3 · resolve=no · `bench_model` |

## Retrieval · hybrid cases (nDCG@10)

| case | nDCG@10 | R@100 |
|------|---------|-------|
| `beir.fiqa.hybrid` | 0.2670 | 0.5808 |
| `beir.nfcorpus.hybrid` | 0.3231 | 0.2307 |
| `beir.scifact.hybrid` | 0.6469 | 0.8460 |

## Context · per task

| case | full F1 | truncate F1 | compact F1 | compact retention |
|------|---------|-------------|------------|-------------------|
| `longbench.hotpotqa` | 0.5372 | 0.5135 | 0.4244 | 0.7900 |
| `longbench.multifieldqa_en` | 0.4879 | 0.5031 | 0.1797 | 0.3682 |
| `longbench.narrativeqa` | 0.1920 | 0.2248 | 0.2143 | 1.1162 |

## 怎么用（live 调优）

```bash
make official-bench-live          # 实测三套（需 BENCH_MODEL_*；禁止 dry/skip）
make official-bench-compare       # latest vs 本 scorecard/baseline 打 Δ 表
make official-bench-update-baseline  # 认可后写 JSON + 刷新本文件
```
