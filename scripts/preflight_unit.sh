#!/usr/bin/env bash
# Local mirror of CI unit.* steps (scripts/ci_proof.sh) — no Docker / make gate.
# Catch "implementation drifted from tests" before push.
#
# Usage:
#   bash scripts/preflight_unit.sh              # smart: suites for changed files vs upstream/main
#   PREFLIGHT_ALL=1 bash scripts/preflight_unit.sh
#   PREFLIGHT_BASE=origin/main bash scripts/preflight_unit.sh
#   SKIP_PREFLIGHT=1 ...                        # no-op (exit 0)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${SKIP_PREFLIGHT:-0}" == "1" ]]; then
  echo "==> preflight skipped (SKIP_PREFLIGHT=1)"
  exit 0
fi

need_runtime=0
need_api=0
need_contracts=0
need_ux=0
need_scripts=0

mark_all() {
  need_runtime=1
  need_api=1
  need_contracts=1
  need_ux=1
  need_scripts=1
}

classify_path() {
  local f="$1"
  case "$f" in
    services/runtime/*|scripts/ci_proof.sh|scripts/preflight_unit.sh)
      need_runtime=1
      ;;
    services/api/*)
      need_api=1
      ;;
    packages/contracts/*)
      need_contracts=1
      ;;
    scripts/ux_signals.py|scripts/tests/test_ux_signals.py|eval/ux_signals/*)
      need_ux=1
      ;;
    scripts/*)
      need_scripts=1
      ;;
    .github/workflows/*|Makefile)
      mark_all
      ;;
  esac
}

resolve_changed() {
  local base="${PREFLIGHT_BASE:-}"
  if [[ -z "$base" ]]; then
    if git rev-parse --abbrev-ref '@{upstream}' >/dev/null 2>&1; then
      base='@{upstream}'
    elif git rev-parse --verify origin/main >/dev/null 2>&1; then
      base='origin/main'
    elif git rev-parse --verify origin/master >/dev/null 2>&1; then
      base='origin/master'
    else
      base='HEAD~1'
    fi
  fi

  local files
  if ! files="$(git diff --name-only "$base"...HEAD 2>/dev/null)"; then
    echo "==> preflight: cannot diff vs $base — running all unit suites"
    mark_all
    return
  fi
  # Also include unstaged/staged working tree (pre-commit / dirty push habits).
  local dirty
  dirty="$(git diff --name-only HEAD 2>/dev/null || true)"
  dirty+=$'\n'
  dirty+="$(git diff --name-only --cached 2>/dev/null || true)"

  local any=0
  local f
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    any=1
    classify_path "$f"
  done <<< "$(printf '%s\n%s\n' "$files" "$dirty" | sort -u)"

  if [[ "$any" -eq 0 ]]; then
    echo "==> preflight: no file changes vs $base — running runtime unit (safe default)"
    need_runtime=1
  else
    echo "==> preflight: base=$base selective suites (runtime=$need_runtime api=$need_api contracts=$need_contracts ux=$need_ux)"
  fi
}

if [[ "${PREFLIGHT_ALL:-0}" == "1" ]]; then
  echo "==> preflight: PREFLIGHT_ALL=1"
  mark_all
else
  resolve_changed
fi

# Scripts-only changes still need a cheap smoke of ux self-check when ux scripts touched.
if [[ "$need_scripts" -eq 1 && "$need_ux" -eq 0 && "$need_runtime" -eq 0 && "$need_api" -eq 0 && "$need_contracts" -eq 0 ]]; then
  need_ux=1
fi

py() {
  if [[ -x "$ROOT/services/runtime/.venv/bin/python" ]]; then
    echo "$ROOT/services/runtime/.venv/bin/python"
  elif command -v python3.11 >/dev/null 2>&1; then
    echo python3.11
  else
    echo python3
  fi
}
PY="$(py)"

run_ux_self_check() {
  echo "==> [preflight] UX signals self-check"
  "$PY" -m pip install -q packages/contracts/python >/dev/null
  "$PY" scripts/ux_signals.py --self-check
}

run_ux_tests() {
  echo "==> [preflight] UX signals unit tests"
  "$PY" -m pip install -q packages/contracts/python pytest >/dev/null
  "$PY" -m pytest scripts/tests/test_ux_signals.py -q
}

run_runtime() {
  echo "==> [preflight] Runtime unit tests"
  cd "$ROOT/services/runtime"
  if [[ -x .venv/bin/python ]]; then
    .venv/bin/python -m pip install -q -e ".[dev]" >/dev/null
    .venv/bin/python -m pytest tests -q --cov=app --cov-report=term-missing --cov-fail-under=80
  else
    "$PY" -m pip install -q -e ".[dev]"
    "$PY" -m pytest tests -q --cov=app --cov-report=term-missing --cov-fail-under=80
  fi
  cd "$ROOT"
}

run_api_ux() {
  echo "==> [preflight] API UX signals route"
  "$PY" -m pip install -q packages/contracts/python >/dev/null
  cd "$ROOT/services/api"
  if [[ -x .venv/bin/pytest ]]; then
    PYTHONPATH=. .venv/bin/pytest tests/test_ux_signals_api.py -q
  else
    "$PY" -m pip install -q -e ".[dev]" 2>/dev/null || "$PY" -m pip install -q -e .
    PYTHONPATH=. "$PY" -m pytest tests/test_ux_signals_api.py -q
  fi
  cd "$ROOT"
}

run_contracts() {
  echo "==> [preflight] Contracts tests"
  "$PY" -m pip install -q jsonschema pytest pyyaml >/dev/null
  "$PY" -m pytest packages/contracts/tests -q
  "$PY" -m pip install -q packages/contracts/python >/dev/null
  "$PY" -m pytest packages/contracts/python/tests -q
}

failed=0
run_suite() {
  local name="$1"
  shift
  set +e
  "$@"
  local rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    echo "==> [preflight] FAILED: $name (exit $rc)"
    failed=1
  fi
}

if [[ "$need_ux" -eq 1 ]]; then
  run_suite ux_self_check run_ux_self_check
  run_suite ux_tests run_ux_tests
fi
if [[ "$need_runtime" -eq 1 ]]; then
  run_suite runtime run_runtime
fi
if [[ "$need_api" -eq 1 ]]; then
  run_suite api_ux run_api_ux
fi
if [[ "$need_contracts" -eq 1 ]]; then
  run_suite contracts run_contracts
fi

if [[ "$failed" -ne 0 ]]; then
  echo ""
  echo "preflight FAILED — fix tests before push (or SKIP_PREFLIGHT=1 / git push --no-verify)."
  echo "Full CI unit mirror: PREFLIGHT_ALL=1 bash scripts/preflight_unit.sh"
  exit 1
fi

echo "==> preflight OK"
