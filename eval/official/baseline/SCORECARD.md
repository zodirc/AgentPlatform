# Official live scorecard

- **protocol**: `official-small-2026-08-m3`
- **eval_path**: `agent`（L1 agent-path 主栏）
- **updated_at**: `2026-08-03T16:21:02.389205+00:00`
- **含义**: **主栏 = 锚点档**（全量/自由臂/官方裁判）；冒烟档仅作迭代方向盘，**不作效果结论**。
- **明细**: Ops 官方页 / `eval/reports/official/runs/<id>/`（不进 git）
- **L0 对照**: 旁路组件史见同目录 `official-small-2026-08-m1.json`（不进本表主栏）
- **过渡**: `m2.json` 为强制臂史；现行协议 `m3` 自由主臂

## 主栏 · 锚点档（唯一效果结论）

| 套件 | 主指标 | 值 | run_id | 备注 |
|------|--------|----|--------|------|
| — | — | — | — | 尚无锚点档入库 |

## 冒烟趋势（不作效果结论）

| 套件 | 主指标 | 值 | run_id | 备注 |
|------|--------|----|--------|------|
| retrieval | agent nDCG@10 | 0.4425 | `307ea1d0-6502-468b-85ea-c209f1377567` | tier=smoke · arm=free · n_queries=20 · R@100=0.5252 |
| context | agent F1 / EM | 0.3677 / 0.2500 | `9998d9eb-9973-4938-bacf-3207aca4f781` | tier=smoke · arm=free · model=`deepseek-v4-flash` |

## Retrieval / Context cases

明细见 Ops / `eval/reports/official/runs/<id>/`；分桶报告：`python -m official_bench.bucket_report <manifest.json>`。

## 怎么用（live 调优）

```bash
make official-bench-retrieval-agent context-agent coding-infer-agent   # L1 实测
make official-bench-compare       # latest vs 本 scorecard/baseline 打 Δ 表（同档才比）
make official-bench-update-baseline  # 认可后写 JSON + 刷新本文件（协议跟 latest）
```
