# Official live 基线（调优账本）

**一眼看分：** 打开同目录 [`SCORECARD.md`](SCORECARD.md)（表格 · **现行 L1 m3**；主栏锚点待全量入库）。  
**手记附录：** [`SCORECARD.notes.md`](SCORECARD.notes.md)（生成 SCORECARD 时拼接，改手记只改 notes）。  
**机器可读：** `official-small-2026-08-m3` 为现行 L1 协议（主栏 `suites` 锚点档；冒烟进 `smoke_suites`）；`m2.json` 为强制臂过渡史；`m1.json` 为 L0 组件对照。  
**题集（case）：** `../suites.small.yaml` + `../swe_lite_slices/` —— 不是本目录。  
**调优纲领：** [`docs/topics/official-bench-agent-tuning.md`](../../../docs/topics/official-bench-agent-tuning.md)。

完整跑次明细在 Ops / `eval/reports/official/`（**不进 git**）。

## Live 调优怎么用

```bash
# 1) L1 实测（Ops「评测路径 = L1 agent」或 make *-agent；需 BENCH_MODEL_*）
make official-bench-retrieval-agent
make official-bench-context-agent
make official-bench-coding-infer-agent   # OFFICIAL_SWE_TIER=n5|n10|n25|…

# 2) 看 Δ（latest 协议戳记优先 → 对 m3 锚点；同档才比）
make official-bench-compare

# 3a) 从 latest_* 写入（smoke→冒烟栏；anchor→主栏）
make official-bench-update-baseline

# 3b) 按 run_id 升主栏（须 sample_tier=anchor；不依赖 latest 时序）
make official-bench-promote-run RUN_ID=<uuid>

git add eval/official/baseline/
```

Ops 官方页 L1 全量等价；跑完同样 `compare` / `update-baseline` / `promote-run`。

## 可比条件

同 `protocol_version` + 同 `eval_path`；编码同 `coding_tier` + `instance_fingerprint`；同模型再谈 Δ。  
排除：context dry、coding skip_api、hash 冒烟。  
**锚点档准入**：retrieval 全量（无 QUERY_LIMIT）、context `limit=0`、coding **`n25`/`full300` + harness**。
