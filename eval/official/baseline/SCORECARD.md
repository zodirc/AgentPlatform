# Official live scorecard

- **protocol**: `official-small-2026-08-m2`（过渡史；现行 runner 戳记 **`m3`**）
- **eval_path**: `agent`（L1 agent-path）
- **updated_at**: `2026-08-02T14:59:11.335475+00:00`
- **含义**: **主栏 = 锚点档**（全量 / 自由臂 / 官方裁判）；冒烟档仅作迭代方向盘，**不作效果结论**。
- **明细**: Ops 官方页 / `eval/reports/official/runs/<id>/`（不进 git）
- **L0 对照**: `official-small-2026-08-m1.json`（不进本表主栏）
- **过渡**: 下表 m2 数值为强制臂冒烟史；m3 锚点入库后写入主栏

## 主栏 · 锚点档（唯一效果结论）

| 套件 | 主指标 | 值 | run_id | 备注 |
|------|--------|----|--------|------|
| — | — | — | — | 尚无 m3 锚点档入库（全量 + free + harness） |

## 冒烟趋势（不作效果结论）

| 套件 | 主指标 | 值 | run_id | 备注 |
|------|--------|----|--------|------|
| retrieval | agent nDCG@10 | 0.4030 | `4996145f-8c51-4d70-92c1-d32493ad1384` | m2 强制单搜 · n_queries=20 · R@100=0.6019 |
| context | agent F1 / EM | 0.3149 / 0.0500 | `ebc6abfd-8943-423c-a539-de922af81af6` | m2 强制单读 · model=`deepseek-v4-flash` |
| coding | patch_rate | 0.4000 | `32ede212-8cfd-4664-a097-4c8c8fda05ce` | m2 无 repo/harness · n5 · 无效果含义 |

## Retrieval / Context cases

明细见 Ops / `eval/reports/official/runs/<id>/`；分桶：`python -m official_bench.bucket_report <manifest.json>`。

## 怎么用（live 调优）

```bash
make official-bench-retrieval-agent context-agent coding-infer-agent   # L1 实测（m3）
make official-bench-compare       # latest vs baseline（同档才比 Δ）
make official-bench-update-baseline  # 认可后写 JSON + 刷新本文件
```
