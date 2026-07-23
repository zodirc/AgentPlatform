#!/usr/bin/env bash
# Full CI proof of record — GitHub Actions + Ops Eval Console (suite=ci).
# Steps mirror .github/workflows/ci.yml (unit job + make gate).
#
# Usage:
#   bash scripts/ci_proof.sh                  # all steps
#   PROOF_STEP=unit.runtime bash scripts/ci_proof.sh
#   GATE_SKIP_RESTORE=1 bash scripts/ci_proof.sh   # CI / no restore
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STEP="${PROOF_STEP:-all}"

run_unit_ux_self_check() {
  echo "==> [unit] UX signals self-check"
  pip install -q packages/contracts/python
  python3 scripts/ux_signals.py --self-check
}

run_unit_ux_tests() {
  echo "==> [unit] UX signals unit tests"
  pip install -q packages/contracts/python pytest
  python3 -m pytest scripts/tests/test_ux_signals.py -q
}

run_unit_runtime() {
  echo "==> [unit] Runtime unit tests"
  cd services/runtime
  pip install -q -e ".[dev]"
  pytest tests -q --cov=app --cov-report=term-missing --cov-fail-under=80
  cd "$ROOT"
}

run_unit_api_ux() {
  echo "==> [unit] API UX signals route"
  pip install -q packages/contracts/python
  cd services/api
  pip install -q -e ".[dev]" 2>/dev/null || pip install -q -e .
  PYTHONPATH=. pytest tests/test_ux_signals_api.py -q
  cd "$ROOT"
}

run_unit_contracts() {
  echo "==> [unit] Contracts tests"
  pip install -q jsonschema pytest pyyaml
  pytest packages/contracts/tests -q
  pip install -q packages/contracts/python
  pytest packages/contracts/python/tests -q
}

run_gate() {
  echo "==> [gate] make gate (smoke + eval-all; runtime-test already in unit.runtime)"
  # Default restore after gate when Ops runs on a daily machine.
  # CI sets GATE_SKIP_RESTORE=1.
  # Skip duplicate pytest: unit.runtime already ran the same suite.
  CI="${CI:-true}" GATE_SKIP_RESTORE="${GATE_SKIP_RESTORE:-0}" \
    GATE_SKIP_RUNTIME_TEST=1 \
    SMOKE_RUNTIME_LITE="${SMOKE_RUNTIME_LITE:-1}" \
    make gate
}

run_all() {
  run_unit_ux_self_check
  run_unit_ux_tests
  run_unit_runtime
  run_unit_api_ux
  run_unit_contracts
  run_gate
}

case "$STEP" in
  all) run_all ;;
  unit.ux_self_check) run_unit_ux_self_check ;;
  unit.ux_tests) run_unit_ux_tests ;;
  unit.runtime) run_unit_runtime ;;
  unit.api_ux) run_unit_api_ux ;;
  unit.contracts) run_unit_contracts ;;
  gate) run_gate ;;
  *)
    echo "Unknown PROOF_STEP=$STEP" >&2
    echo "Expected: all | unit.ux_self_check | unit.ux_tests | unit.runtime | unit.api_ux | unit.contracts | gate" >&2
    exit 2
    ;;
esac

echo "==> CI proof step OK: $STEP"
