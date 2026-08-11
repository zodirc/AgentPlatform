# SWE-bench Lite · structural lane (Ops L1)

See [docs/plan/coding-structural-intelligence.md](../../docs/plan/coding-structural-intelligence.md).

Structural navigation / diagnostics are **fused into the agent Profile** (not a
`STRUCTURAL_ENABLED` feature flag). Measure agent coding with checkout on; process
metrics live under `eval.swebench.metrics`.

## Frozen slices

| File | N | Notes |
|------|---|--------|
| `lite50.txt` | 50 | Stratified by repo, `seed=20260810` |
| `../official/swe_lite_slices/swe_lite_slice_50.txt` | 50 | Same IDs |
| `../official/swe_lite_slices/instance_order.txt` | 300 | Full Lite test order |

## Ops L1 wiring

```bash
# Deny egress for ops_eval Turns (answer-leak ban). Recreate runtime so env applies.
OPS_EVAL_DENY_NETWORK=true \
  docker compose -f deploy/docker-compose.yml up -d --force-recreate runtime
# Confirm: curl runtime /health/ready → structural.fused=true, ops_eval_deny_network=true
make official-bench-coding-infer-agent OFFICIAL_SWE_N=50
make official-bench-coding-eval
```

Daily agent Profile / `system.md` stays egress-allowed; only ops_eval Turns deny net.

## Process metrics

```bash
python3 -m eval.swebench.metrics \
  --pred path/to/predictions.jsonl \
  --gold path/to/gold.jsonl \
  --out eval/reports/swebench/process_metrics.json
```

Gold is used **only** for post-hoc localization hit rate — never for prompt tuning.

Health check: `GET /health/ready` → `structural.{fused,prewarm,ops_eval_deny_network}`.
