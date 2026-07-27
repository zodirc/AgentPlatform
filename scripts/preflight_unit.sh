#!/usr/bin/env bash
# Local mirror of CI unit.* steps — prefer repo/system Python+pip; else Docker
# (same class as make runtime-test / api-test). No Docker required when a venv exists.
#
# Usage:
#   bash scripts/preflight_unit.sh
#   PREFLIGHT_ALL=1 bash scripts/preflight_unit.sh
#   PREFLIGHT_BASE=origin/main bash scripts/preflight_unit.sh
#   SKIP_PREFLIGHT=1 ...                        # no-op (exit 0)
#   PREFLIGHT_DOCKER=1 ...                      # force Docker runners
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
COMPOSE=(docker compose -f "$ROOT/deploy/docker-compose.yml" --env-file "$ROOT/.env")

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
    scripts/*|.githooks/*|Makefile|README.md)
      need_scripts=1
      ;;
    .github/workflows/*)
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

if [[ "$need_scripts" -eq 1 && "$need_ux" -eq 0 && "$need_runtime" -eq 0 && "$need_api" -eq 0 && "$need_contracts" -eq 0 ]]; then
  need_ux=1
fi

py() {
  if [[ -x "$ROOT/services/runtime/.venv/bin/python" ]]; then
    echo "$ROOT/services/runtime/.venv/bin/python"
  elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    echo "$ROOT/.venv/bin/python"
  elif command -v python3.11 >/dev/null 2>&1; then
    echo python3.11
  else
    echo python3
  fi
}
PY="$(py)"

python_has_pip() {
  "$PY" -m pip --version >/dev/null 2>&1
}

docker_ready() {
  command -v docker >/dev/null 2>&1 || return 1
  "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx runtime
}

use_docker=0
if [[ "${PREFLIGHT_DOCKER:-0}" == "1" ]]; then
  use_docker=1
elif ! python_has_pip; then
  if docker_ready; then
    use_docker=1
    echo "==> preflight: no local pip — using Docker (runtime container)"
  else
    echo ""
    echo "preflight FAILED — no usable Python pip and Docker runtime is not up."
    echo "  Fix one of:"
    echo "    sudo apt install python3-pip python3-venv   # then re-push"
    echo "    cd services/runtime && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
    echo "    make up                                    # then re-push (Docker fallback)"
    echo "    SKIP_PREFLIGHT=1 git push                  # emergency bypass"
    echo ""
    exit 1
  fi
fi

run_ux_self_check_local() {
  echo "==> [preflight] UX signals self-check"
  "$PY" -m pip install -q packages/contracts/python >/dev/null
  "$PY" scripts/ux_signals.py --self-check
}

run_ux_tests_local() {
  echo "==> [preflight] UX signals unit tests"
  "$PY" -m pip install -q packages/contracts/python pytest >/dev/null
  "$PY" -m pytest scripts/tests/test_ux_signals.py -q
}

run_runtime_local() {
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

run_api_ux_local() {
  echo "==> [preflight] API test suite"
  "$PY" -m pip install -q packages/contracts/python >/dev/null
  cd "$ROOT/services/api"
  if [[ -x .venv/bin/pytest ]]; then
    PYTHONPATH=. .venv/bin/pytest tests -q
  else
    "$PY" -m pip install -q -e ".[dev]" 2>/dev/null || "$PY" -m pip install -q -e .
    PYTHONPATH=. "$PY" -m pytest tests -q
  fi
  cd "$ROOT"
}

run_contracts_local() {
  echo "==> [preflight] Contracts tests"
  "$PY" -m pip install -q jsonschema pytest pyyaml >/dev/null
  "$PY" -m pytest packages/contracts/tests -q
  "$PY" -m pip install -q packages/contracts/python >/dev/null
  "$PY" -m pytest packages/contracts/python/tests -q
}

run_ux_self_check_docker() {
  echo "==> [preflight] UX signals self-check (docker/runtime)"
  "${COMPOSE[@]}" exec -T -u root runtime rm -rf /tmp/preflight-ux
  "${COMPOSE[@]}" exec -T -u root runtime mkdir -p /tmp/preflight-ux/packages /tmp/preflight-ux/scripts
  docker cp "$ROOT/scripts/ux_signals.py" agent-runtime:/tmp/preflight-ux/scripts/ux_signals.py
  docker cp "$ROOT/packages/contracts/python" agent-runtime:/tmp/preflight-ux/packages/contracts-python
  "${COMPOSE[@]}" exec -T runtime bash -c \
    'python -m pip install -q /tmp/preflight-ux/packages/contracts-python >/dev/null
     python /tmp/preflight-ux/scripts/ux_signals.py --self-check'
}

run_ux_tests_docker() {
  echo "==> [preflight] UX signals unit tests (docker/runtime)"
  "${COMPOSE[@]}" exec -T -u root runtime rm -rf /tmp/preflight-ux
  "${COMPOSE[@]}" exec -T -u root runtime mkdir -p \
    /tmp/preflight-ux/scripts/tests \
    /tmp/preflight-ux/packages/contracts/python \
    /tmp/preflight-ux/eval
  docker cp "$ROOT/scripts/ux_signals.py" agent-runtime:/tmp/preflight-ux/scripts/ux_signals.py
  docker cp "$ROOT/scripts/tests/test_ux_signals.py" agent-runtime:/tmp/preflight-ux/scripts/tests/test_ux_signals.py
  docker cp "$ROOT/packages/contracts/python/." agent-runtime:/tmp/preflight-ux/packages/contracts/python/
  docker cp "$ROOT/eval/ux_signals" agent-runtime:/tmp/preflight-ux/eval/ux_signals
  "${COMPOSE[@]}" exec -T runtime bash -c \
    'python -m pip install -q pytest >/dev/null
     cd /tmp/preflight-ux && python -m pytest scripts/tests/test_ux_signals.py -q'
}

run_runtime_docker() {
  echo "==> [preflight] Runtime unit tests (docker)"
  "${COMPOSE[@]}" exec -T -u root runtime rm -rf /tmp/runtime-tests /tmp/eval
  "${COMPOSE[@]}" exec -T -u root runtime mkdir -p /tmp/eval/plan_suggest
  docker cp "$ROOT/services/runtime/tests/." agent-runtime:/tmp/runtime-tests/
  if [[ -f "$ROOT/eval/plan_suggest/cases.json" ]]; then
    docker cp "$ROOT/eval/plan_suggest/cases.json" agent-runtime:/tmp/eval/plan_suggest/cases.json
  fi
  "${COMPOSE[@]}" exec -T runtime bash -c \
    'python -m pip install -q pytest pytest-asyncio pytest-cov 2>/dev/null
     PYTHONPATH=/app python -m pytest /tmp/runtime-tests -q --asyncio-mode=auto'
}

run_api_ux_docker() {
  echo "==> [preflight] API test suite (docker)"
  if ! "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx api; then
    echo "api container not running — start with make up / make start"
    return 1
  fi
  "${COMPOSE[@]}" exec -T -u root api rm -rf /tmp/api-tests
  docker cp "$ROOT/services/api/tests/." agent-api:/tmp/api-tests/
  "${COMPOSE[@]}" exec -T api bash -c \
    'python -m pip install -q pytest pytest-asyncio httpx 2>/dev/null
     if [ -d /repo/services/api/app ]; then export PYTHONPATH=/repo/services/api; else export PYTHONPATH=/app; fi
     python -m pytest /tmp/api-tests -q --asyncio-mode=auto'
}

run_contracts_docker() {
  echo "==> [preflight] Contracts tests (docker/runtime)"
  "${COMPOSE[@]}" exec -T -u root runtime rm -rf /tmp/preflight-contracts
  docker cp "$ROOT/packages/contracts" agent-runtime:/tmp/preflight-contracts
  "${COMPOSE[@]}" exec -T runtime bash -c \
    'python -m pip install -q jsonschema pytest pyyaml >/dev/null
     cd /tmp/preflight-contracts && PYTHONPATH=/tmp/preflight-contracts python -m pytest tests -q
     python -m pip install -q /tmp/preflight-contracts/python >/dev/null
     python -m pytest /tmp/preflight-contracts/python/tests -q'
}

run_ux_self_check() {
  if [[ "$use_docker" -eq 1 ]]; then run_ux_self_check_docker; else run_ux_self_check_local; fi
}
run_ux_tests() {
  if [[ "$use_docker" -eq 1 ]]; then run_ux_tests_docker; else run_ux_tests_local; fi
}
run_runtime() {
  if [[ "$use_docker" -eq 1 ]]; then run_runtime_docker; else run_runtime_local; fi
}
run_api_ux() {
  if [[ "$use_docker" -eq 1 ]]; then run_api_ux_docker; else run_api_ux_local; fi
}
run_contracts() {
  if [[ "$use_docker" -eq 1 ]]; then run_contracts_docker; else run_contracts_local; fi
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
