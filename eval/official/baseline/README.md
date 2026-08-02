# Official live 基线（调优账本）

**一眼看分：** 打开同目录 [`SCORECARD.md`](SCORECARD.md)（表格）。  
**机器可读：** `official-small-*.json`（协议键）。  
**题集（case）：** `../suites.small.yaml` + `../swe_lite_slices/` —— 不是本目录。  
**调优纲领：** [`docs/topics/official-bench-agent-tuning.md`](../../../docs/topics/official-bench-agent-tuning.md)（L1=主 agent 路径；本目录 m1 现为 L0 组件对照史，待 m2 迁主栏）。

完整跑次明细在 Ops / `eval/reports/official/`（**不进 git**）。

## Live 调优怎么用

```bash
# 1) 实测（禁 dry / skip_api；需 BENCH_MODEL_*）
make official-bench-live
# 默认 SWE=n25，可改： OFFICIAL_SWE_TIER=n10 make official-bench-live

# 2) 看 Δ（latest vs 仓库锚点）
make official-bench-compare

# 3) 认可效果 → 更新锚点 + SCORECARD → commit
make official-bench-update-baseline
git add eval/official/baseline/
```

Ops 页面一键 live 全量等价；跑完同样 `compare` / `update-baseline`。

## 可比条件

同 `protocol_version`；编码同 `coding_tier` + `instance_fingerprint`；同模型再谈 Δ。  
排除：context dry、coding skip_api、hash 冒烟。
