# SWE-bench Lite · structural dual-track (Ops L1)

See [docs/plan/coding-structural-intelligence.md](../../docs/plan/coding-structural-intelligence.md) §8–§9.

## Frozen slices

| File | N | Notes |
|------|---|--------|
| `lite50.txt` | 50 | Stratified by repo, `seed=20260810` |
| `../official/swe_lite_slices/swe_lite_slice_50.txt` | 50 | Same IDs |
| `../official/swe_lite_slices/instance_order.txt` | 300 | Full Lite test order |

## Ops dual-track (required wiring)

`STRUCTURAL_ENABLED` / `OPS_EVAL_DENY_NETWORK` are **runtime container** settings
(`deploy/docker-compose.yml`). Host `export` alone does **not** flip the flag for Turns.

```bash
# Track OFF (baseline)
STRUCTURAL_ENABLED=false OPS_EVAL_DENY_NETWORK=true \
  docker compose -f deploy/docker-compose.yml up -d --force-recreate runtime
# Confirm: curl runtime /health/ready → structural.enabled=false, ops_eval_deny_network=true
make official-bench-coding-infer-agent OFFICIAL_SWE_N=50

# Track ON
STRUCTURAL_ENABLED=true STRUCTURAL_PREWARM=true OPS_EVAL_DENY_NETWORK=true \
  docker compose -f deploy/docker-compose.yml up -d --force-recreate runtime
make official-bench-coding-infer-agent OFFICIAL_SWE_N=50

# Score both prediction files with official harness
make official-bench-coding-eval
```

Or: `make swebench-structural-dual-track` (dry-run) / `EXECUTE=1 make swebench-structural-dual-track`.

Network **must** be denied for ops_eval Turns (`OPS_EVAL_DENY_NETWORK=true` → bwrap `--unshare-net`).
Daily agent Profile / `system.md` stays egress-allowed.

## Process metrics

```bash
python3 -m eval.swebench.metrics \
  --pred path/to/predictions.jsonl \
  --gold path/to/gold.jsonl \
  --out eval/reports/swebench/process_metrics.json
```

Gold is used **only** for post-hoc localization hit rate — never for prompt tuning.

Health check fields for Ops: `GET /health/ready` → `structural.{enabled,prewarm,ops_eval_deny_network}`.
