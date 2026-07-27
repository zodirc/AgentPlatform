#!/usr/bin/env bash
# Full CI proof of record — GitHub Actions + Ops Eval Console (suite=ci).
# Steps mirror .github/workflows/ci.yml (unit job + make gate).
#
# Usage:
#   bash scripts/ci_proof.sh                  # all steps
#   PROOF_STEP=unit.runtime bash scripts/ci_proof.sh
#   GATE_SKIP_RESTORE=1 bash scripts/ci_proof.sh   # CI / no restore
#
# Prefers services/runtime/.venv (or python3.11+) — bare ``python3`` on
# developer machines is often 3.9 and cannot install agent-contracts (>=3.11).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STEP="${PROOF_STEP:-all}"

resolve_python() {
  if [[ -n "${PROOF_PYTHON:-}" ]]; then
    echo "$PROOF_PYTHON"
  elif [[ -x "$ROOT/services/runtime/.venv/bin/python" ]]; then
    echo "$ROOT/services/runtime/.venv/bin/python"
  elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    echo "$ROOT/.venv/bin/python"
  elif command -v python3.11 >/dev/null 2>&1; then
    echo python3.11
  elif command -v python3.12 >/dev/null 2>&1; then
    echo python3.12
  else
    echo python3
  fi
}

PY="$(resolve_python)"
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo ""
  echo "ci_proof FAILED — need Python >= 3.11 (got: $("$PY" -V 2>&1) via $PY)."
  echo "  Fix one of:"
  echo "    cd services/runtime && python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
  echo "    PROOF_PYTHON=/path/to/python3.11 bash scripts/ci_proof.sh"
  echo "    # or skip units and use Docker gate only after make up:"
  echo "    PROOF_STEP=gate bash scripts/ci_proof.sh"
  echo ""
  exit 1
fi
echo "==> ci_proof using $($PY -V) ($PY)"

pip_q() {
  "$PY" -m pip install -q "$@"
}

pytest_q() {
  "$PY" -m pytest "$@"
}

run_unit_ux_self_check() {
  echo "==> [unit] UX signals self-check"
  pip_q packages/contracts/python
  "$PY" scripts/ux_signals.py --self-check
}

run_unit_ux_tests() {
  echo "==> [unit] UX signals unit tests"
  pip_q packages/contracts/python pytest
  pytest_q scripts/tests/test_ux_signals.py -q
}

run_unit_runtime() {
  echo "==> [unit] Runtime unit tests"
  cd services/runtime
  if [[ -x .venv/bin/python ]]; then
    .venv/bin/python -m pip install -q -e ".[dev]"
    .venv/bin/python -m pytest tests -q --cov=app --cov-report=term-missing --cov-fail-under=80
  else
    pip_q -e ".[dev]"
    pytest_q tests -q --cov=app --cov-report=term-missing --cov-fail-under=80
  fi
  cd "$ROOT"
}

run_unit_api_ux() {
  echo "==> [unit] API test suite"
  pip_q packages/contracts/python
  cd services/api
  # Prefer api/.venv only when it can install/run tests; a broken venv
  # (python without pip) must not block proof — fall back to $PY.
  if [[ -x .venv/bin/pytest ]] && .venv/bin/python -m pip --version >/dev/null 2>&1; then
    .venv/bin/python -m pip install -q -e ".[dev]" 2>/dev/null || .venv/bin/python -m pip install -q -e .
    PYTHONPATH=. .venv/bin/pytest tests -q
  else
    pip_q -e ".[dev]" 2>/dev/null || pip_q -e .
    PYTHONPATH=. pytest_q tests -q
  fi
  cd "$ROOT"
}

run_unit_contracts() {
  echo "==> [unit] Contracts tests"
  pip_q jsonschema pytest pyyaml
  pytest_q packages/contracts/tests -q
  pip_q packages/contracts/python
  pytest_q packages/contracts/python/tests -q
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
