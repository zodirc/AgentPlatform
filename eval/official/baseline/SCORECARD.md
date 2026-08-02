# Official live scorecard

- **protocol**: `official-small-2026-08-m2`
- **eval_path**: `agent`（L1 agent-path 主栏）
- **updated_at**: `2026-08-02T14:59:11.335475+00:00`
- **含义**: live 实测官方小量的分数锚点（调优看 Δ）；题集在 `suites.small.yaml` / SWE slices。
- **明细**: Ops 官方页 / `eval/reports/official/runs/<id>/`（不进 git）
- **L0 对照**: 旁路组件史见同目录 `official-small-2026-08-m1.json`（不进本表主栏）

## 主指标（一眼）

| 套件 | 主指标 | 值 | run_id | 备注 |
|------|--------|----|--------|------|
| retrieval | agent nDCG@10 | 0.4030 | `4996145f-8c51-4d70-92c1-d32493ad1384` | n_queries=20 · R@100=0.6019 |
| context | agent F1 / EM | 0.3149 / 0.0500 | `ebc6abfd-8943-423c-a539-de922af81af6` | arms equal on L1 · model=`deepseek-v4-flash` |
| coding | patch_rate | 0.4000 | `32ede212-8cfd-4664-a097-4c8c8fda05ce` | tier=`n5` · n=5.0000 · resolve=no · `platform_turn` |

## Retrieval / Context cases

L1 首基线以套件宏分为主；per-query / per-turn 明细见 Ops / `eval/reports/official/runs/<id>/`。

## 怎么用（live 调优）

```bash
make official-bench-retrieval-agent context-agent coding-infer-agent   # L1 实测
make official-bench-compare       # latest vs 本 scorecard/baseline 打 Δ 表
make official-bench-update-baseline  # 认可后写 JSON + 刷新本文件（协议跟 latest）
```
