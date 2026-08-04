#!/usr/bin/env bash
# CTX-8 free N≥2 quick acceptance (LongBench small: 3 tasks × 20 = 60).
# LLM-bound — GPU does not accelerate this path.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
[ -f .env ] && . ./.env
set +a
PY="${OFFICIAL_BENCH_PY:-services/runtime/.venv/bin/python}"
OUT=eval/reports/official/batch14
mkdir -p "$OUT"
LIMIT="${OFFICIAL_CONTEXT_LIMIT:-20}"
# Match proven Ops UI speed (parallel 3). Override with OPS_L1_MAX_PARALLEL if needed.
export OPS_L1_MAX_PARALLEL="${OPS_L1_MAX_PARALLEL:-6}"
# Prefer explicit bench model env (do not rely on empty MODEL_NAME → literal "model").
export BENCH_MODEL_PROVIDER="${BENCH_MODEL_PROVIDER:-openai}"
export BENCH_MODEL_NAME="${BENCH_MODEL_NAME:-deepseek-v4-flash}"
export BENCH_MODEL_BASE_URL="${BENCH_MODEL_BASE_URL:-https://api.deepseek.com}"

echo "NOTE: CTX-8 LLM-bound; parallel=$OPS_L1_MAX_PARALLEL model=$BENCH_MODEL_NAME"
echo "CTX8_PASS1_START $(date -Is)" | tee -a "$OUT/ctx8_pass1.log"
set +e
"$PY" scripts/official_bench_run.py context --eval-path agent --limit "$LIMIT" \
  2>&1 | tee -a "$OUT/ctx8_pass1.log"
ec1=${PIPESTATUS[0]}
set -e
echo "CTX8_PASS1_END exit=$ec1 $(date -Is)" | tee -a "$OUT/ctx8_pass1.log"

echo "CTX8_PASS2_START $(date -Is)" | tee -a "$OUT/ctx8_pass2.log"
set +e
"$PY" scripts/official_bench_run.py context --eval-path agent --limit "$LIMIT" \
  2>&1 | tee -a "$OUT/ctx8_pass2.log"
ec2=${PIPESTATUS[0]}
set -e
echo "CTX8_PASS2_END exit=$ec2 $(date -Is)" | tee -a "$OUT/ctx8_pass2.log"
exit $(( ec1 != 0 ? ec1 : ec2 ))
