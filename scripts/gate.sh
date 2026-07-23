#!/usr/bin/env bash
# One-shot docker proof: smoke → eval-all [→ runtime-test].
# Full CI parity is `scripts/ci_proof.sh` / Ops suite=ci (unit + this gate).
# When unit.runtime already ran, set GATE_SKIP_RUNTIME_TEST=1 to avoid a second pytest.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE="docker compose -f deploy/docker-compose.yml --env-file .env"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> Created .env from .env.example (edit MODEL_API_KEY / auth as needed)"
fi

restore_daily_runtime() {
  if [[ "${GATE_SKIP_RESTORE:-}" == "1" ]]; then
    echo ""
    echo "==> Gate cleanup skipped (GATE_SKIP_RESTORE=1)"
    return 0
  fi
  echo ""
  echo "==> Gate cleanup: restore daily runtime + workspace from .env"
  env -u WORKSPACE_HOST_PATH $COMPOSE \
    up -d --force-recreate --remove-orphans --wait --wait-timeout 180 runtime \
    || echo "WARNING: restore failed; run: make start"
  if [[ "${DOCKER_AUTO_PRUNE:-1}" == "1" ]]; then
    echo "==> auto-prune dangling images"
    docker image prune -f >/dev/null || true
  fi
}

# Always leave the machine in a usable daily state after gate (success or fail),
# unless CI / caller opts out.
trap restore_daily_runtime EXIT

# Match CI: prefer hash embedding via runtime-lite (no HF bake). Override with
# SMOKE_RUNTIME_LITE=0 for full SentenceTransformer smoke.
SMOKE_RUNTIME_LITE="${SMOKE_RUNTIME_LITE:-1}"
SKIP_RT="${GATE_SKIP_RUNTIME_TEST:-0}"

echo "========================================"
echo " GATE — smoke → eval-all"
if [[ "$SKIP_RT" != "1" ]]; then
  echo "         → runtime-test"
fi
echo " (lite smoke=${SMOKE_RUNTIME_LITE})"
echo "========================================"

echo ""
echo "==> [1/3] smoke"
# Skip smoke's own restore — we restore once at the end (and eval also isolates).
SMOKE_SKIP_RESTORE=1 SMOKE_MODEL_MODE="${SMOKE_MODEL_MODE:-stub}" \
  CI="${CI:-}" SMOKE_RUNTIME_LITE="$SMOKE_RUNTIME_LITE" \
  bash scripts/smoke_test.sh

echo ""
echo "==> [2/3] eval-all"
# eval-run-isolated has its own EXIT restore; disable nested double-restore by
# letting gate own the final restore: EVAL_SKIP_RESTORE=1
EVAL_SKIP_RESTORE=1 PYTHONUNBUFFERED=1 make eval-all

if [[ "$SKIP_RT" == "1" ]]; then
  echo ""
  echo "==> [3/3] runtime-test skipped (GATE_SKIP_RUNTIME_TEST=1; covered by unit.runtime)"
else
  echo ""
  echo "==> [3/3] runtime-test"
  make runtime-test
fi

echo ""
echo "==> Gate PASSED"
# trap runs restore_daily_runtime on exit
