# Official live scorecard

- **protocol**: `official-small-2026-08-m3`
- **eval_path**: `agent`（L1 agent-path 主栏）
- **updated_at**: `2026-08-06T12:30:00+00:00`（冒烟趋势仍记 gte-large #1；**GPU 默认已切 bge-m3@1024 / index 11**，重嵌后须另记 smoke · **主栏锚点档仍空**）
- **含义**: **主栏 = 锚点档**（全量/自由臂/官方裁判）；冒烟档仅作迭代方向盘，**不作效果结论**。
- **embed**: `make resolve-embedding` → GPU **`BAAI/bge-m3@1024`**（INDEX **11**，**中英共用**）；CPU **`gte-small@384`**。Ops 仅分图：BEIR → `retrieval_ops` · C-MTEB → `retrieval_ops_zh`（同模同维，独立 HNSW）。
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
| retrieval | agent nDCG@10 | **0.5435** | `d31375a5-6884-4007-9bdb-a0d1d65b6d9d` | 2026-08-06 · **gte-large 历史** · smoke · free · 20q/库 · **栈已切 bge-m3 → 不作当前读数** · vs `61f00a6d`≈0.483 · 明细 Free-L1 brief §7.4 |
| context | agent F1 / EM | **0.5393 / 0.2333** | `46df8722-f2c3-4cc6-8ad5-58efc21d974e` | 2026-08-06 · tier=smoke · arm=free · scorer=v2 · 落在 v2 常态带 · 非工程抬分叙事 |
| retrieval（史） | agent nDCG@10 | 0.4425 | `307ea1d0-6502-468b-85ea-c209f1377567` | 旧 smoke；保留对照 |
| context（史） | agent F1 / EM | 0.3677 / 0.2500 | `9998d9eb-9973-4938-bacf-3207aca4f781` | 旧 smoke（v1 口径附近）；保留对照 |

## Retrieval / Context cases

明细见 Ops / `eval/reports/official/runs/<id>/`；分桶报告：`python -m official_bench.bucket_report <manifest.json>`。

## 怎么用（live 调优）

```bash
make official-bench-retrieval-agent context-agent coding-infer-agent   # L1 实测
make official-bench-compare       # latest vs 本 scorecard/baseline 打 Δ 表（同档才比）
make official-bench-update-baseline  # 认可后写 JSON + 刷新本文件（协议跟 latest）
```
