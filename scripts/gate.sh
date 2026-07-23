#!/usr/bin/env bash
# One-shot Proof gate (docs/28 PX0): smoke → eval-all → runtime-test.
# Avoids mid-pipeline runtime recreate races (smoke restore vs eval recreate).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE="docker compose -f deploy/docker-compose.yml --env-file .env"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> Created .env from .env.example (edit MODEL_API_KEY / auth as needed)"
fi

restore_daily_runtime() {
  echo ""
  echo "==> Gate cleanup: restore daily runtime + workspace from .env"
  env -u WORKSPACE_HOST_PATH $COMPOSE \
    up -d --force-recreate --remove-orphans --wait --wait-timeout 180 runtime \
    || echo "WARNING: restore failed; run: make start"
}

# Always leave the machine in a usable daily state after gate (success or fail).
trap restore_daily_runtime EXIT

echo "========================================"
echo " GATE (docs/28) — one shot"
echo "   1) L0 smoke (stub)"
echo "   2) L1 eval-all (isolated stub)"
echo "   3) runtime-test"
echo "========================================"

echo ""
echo "==> [1/3] smoke"
# Skip smoke's own restore — we restore once at the end (and eval also isolates).
SMOKE_SKIP_RESTORE=1 SMOKE_MODEL_MODE="${SMOKE_MODEL_MODE:-stub}" \
  CI="${CI:-}" SMOKE_RUNTIME_LITE="${SMOKE_RUNTIME_LITE:-${CI:+1}}" \
  bash scripts/smoke_test.sh

echo ""
echo "==> [2/3] eval-all"
# eval-run-isolated has its own EXIT restore; disable nested double-restore by
# letting gate own the final restore: EVAL_SKIP_RESTORE=1
	EVAL_SKIP_RESTORE=1 PYTHONUNBUFFERED=1 make eval-all

echo ""
echo "==> [3/3] runtime-test"
make runtime-test

echo ""
echo "==> Gate PASSED"
# trap runs restore_daily_runtime on exit
