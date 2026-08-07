# Official live scorecard

- **protocol**: `official-small-2026-08-m3`
- **eval_path**: `agent`（L1 agent-path 主栏）
- **updated_at**: `2026-08-07T19:07:00+00:00`（**bge-m3 / INDEX 12** free smoke 已记入冒烟趋势 · **主栏锚点档仍空** · 不 `update-baseline`）
- **含义**: **主栏 = 锚点档**（全量/自由臂/官方裁判）；冒烟档仅作迭代方向盘，**不作效果结论**。
- **embed**: `make resolve-embedding` → GPU **`BAAI/bge-m3@1024`**（INDEX **12** · `max_seq=512`，**中英共用**）；CPU **`gte-small@384`**。Ops 仅分图：BEIR → `retrieval_ops` · C-MTEB → `retrieval_ops_zh`（同模同维，独立 HNSW）。
- **明细**: Ops 官方页 / `eval/reports/official/runs/<id>/`（不进 git）；扁平镜像可落根目录 `TEST.log`
- **L0 对照**: 旁路组件史见同目录 `official-small-2026-08-m1.json`（不进本表主栏）
- **过渡**: `m2.json` 为强制臂史；现行协议 `m3` 自由主臂

## 主栏 · 锚点档（唯一效果结论）

| 套件 | 主指标 | 值 | run_id | 备注 |
|------|--------|----|--------|------|
| — | — | — | — | 尚无锚点档入库 |

## 冒烟趋势（不作效果结论）

| 套件 | 主指标 | 值 | run_id | 备注 |
|------|--------|----|--------|------|
| retrieval | agent nDCG@10 | **0.4755** | `cd16092c-5b35-478b-ba1f-4bbada5876b4` | 2026-08-07 · **bge-m3@1024 / INDEX 12** · smoke · free · BEIR 20q/库 · R@10 **0.4908** · MAP@1 **0.246** · vs gte-large 史 `d31375a5` 0.5435（**不可跨模直接比**） · 明细 Free-L1 brief §7.4 |
| retrieval_zh | agent nDCG@10 | **0.6780** | `f84fd420-9fba-4f43-8e81-618ce0e2d7d3` | 2026-08-07 · 同栈 · C-MTEB smoke · free · R@10 **0.8667** · MAP@1 **0.517** · infra_rate 0 · **勿与 BEIR 混宏分** |
| context | agent F1 / EM | **0.5288 / 0.2500** | `b9bcf931-9a7d-4528-af8b-bc5506be6955` | 2026-08-07 · 同栈 · smoke · free · scorer=v2 · 近 gte-large 史 `46df8722`（0.539/0.233） |
| retrieval（史） | agent nDCG@10 | **0.5435** | `d31375a5-6884-4007-9bdb-a0d1d65b6d9d` | 2026-08-06 · **gte-large 历史** · smoke · free · 换代前对照 |
| context（史） | agent F1 / EM | **0.5393 / 0.2333** | `46df8722-f2c3-4cc6-8ad5-58efc21d974e` | 2026-08-06 · gte-large 同期 · scorer=v2 |
| retrieval（史） | agent nDCG@10 | 0.4425 | `307ea1d0-6502-468b-85ea-c209f1377567` | 更旧 smoke；保留对照 |
| context（史） | agent F1 / EM | 0.3677 / 0.2500 | `9998d9eb-9973-4938-bacf-3207aca4f781` | 旧 smoke（v1 口径附近）；保留对照 |

## Retrieval / Context cases

明细见 Ops / `eval/reports/official/runs/<id>/`；分桶报告：`python -m official_bench.bucket_report <manifest.json>`。

## 怎么用（live 调优）

```bash
make official-bench-retrieval-agent context-agent coding-infer-agent   # L1 实测
make official-bench-compare       # latest vs 本 scorecard/baseline 打 Δ 表（同档才比）
make official-bench-update-baseline  # 认可后写 JSON + 刷新本文件（协议跟 latest）
```
