#!/usr/bin/env bash
# Local mirror of CI unit.* steps — prefer repo/system Python+pip; else Docker
# (same class as make runtime-test / api-test). No Docker required when a venv exists.
#
# Default git pre-push target. Full CI mirror: make preflight-ci / PREFLIGHT_CI=1.
#
# Usage:
#   bash scripts/preflight_unit.sh
#   PREFLIGHT_ALL=1 bash scripts/preflight_unit.sh
#   PREFLIGHT_BASE=origin/main bash scripts/preflight_unit.sh
#   SKIP_PREFLIGHT=1 ...                        # no-op (exit 0)
#   PREFLIGHT_DOCKER=1 ...                      # force Docker runners
#   PREFLIGHT_VERBOSE_PIP=0 ...                 # quieter pip (default: show progress)
#   PREFLIGHT_SKIP_RUNTIME_REBUILD=1 ...        # do not auto make up-runtime when image stale
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
COMPOSE=(docker compose -f "$ROOT/deploy/docker-compose.yml" --env-file "$ROOT/.env")
PREFLIGHT_STARTED_AT=$(date +%s)
VERBOSE_PIP="${PREFLIGHT_VERBOSE_PIP:-1}"

if [[ "${SKIP_PREFLIGHT:-0}" == "1" ]]; then
  echo "==> preflight skipped (SKIP_PREFLIGHT=1)"
  exit 0
fi

elapsed() {
  echo "$(( $(date +%s) - PREFLIGHT_STARTED_AT ))s"
}

# Print a heartbeat while a long command runs (pip lock waits, installs, etc.).
with_heartbeat() {
  local label="$1"
  shift
  local hb_pid=""
  (
    local t=0
    while sleep 15; do
      t=$((t + 15))
      echo "==> [preflight] … still: ${label} (${t}s elapsed, total $(elapsed))"
    done
  ) &
  hb_pid=$!
  # Do not let a killed heartbeat fail the suite under pipefail/set -e.
  set +e
  "$@"
  local rc=$?
  set -e
  kill "$hb_pid" 2>/dev/null || true
  wait "$hb_pid" 2>/dev/null || true
  return "$rc"
}

# Fail fast if another installer holds the venv lock (looks like a hang otherwise).
assert_venv_lock_free() {
  local venv_dir="$1"
  local lock="${venv_dir}/.lock"
  [[ -e "$lock" ]] || return 0

  local holders="" pid fd target
  # Prefer /proc scan — fuser is noisy/unreliable under WSL Docker.
  for pid in /proc/[0-9]*; do
    [[ -d "$pid/fd" ]] || continue
    for fd in "$pid"/fd/*; do
      target="$(readlink "$fd" 2>/dev/null || true)"
      if [[ "$target" == "$lock" ]]; then
        holders+=" ${pid##*/}"
        break
      fi
    done
  done
  if [[ -z "${holders// /}" ]] && command -v lsof >/dev/null 2>&1; then
    holders=" $(lsof -t "$lock" 2>/dev/null | tr '\n' ' ' || true)"
  fi
  holders="$(echo "$holders" | tr -s ' ' | sed 's/^ //;s/ $//')"
  [[ -n "$holders" ]] || return 0

  echo ""
  echo "==> [preflight] BLOCKED: ${venv_dir}/.lock held by PID(s): ${holders}"
  echo "    Another uv/pip install is using this venv (previously looked like a hang)."
  echo "    Fix: kill those PIDs, then re-push. Example: kill ${holders}"
  ps -o pid,etime,cmd -p ${holders// /,} 2>/dev/null || true
  echo ""
  return 1
}

pip_install() {
  local py="$1"
  shift
  echo "==> [preflight] pip install ($*)  [$(elapsed)]"
  if [[ "$VERBOSE_PIP" == "1" ]]; then
    with_heartbeat "pip $*" "$py" -m pip install --progress-bar on "$@"
  else
    with_heartbeat "pip $*" "$py" -m pip install -q "$@"
  fi
}

# True only when editable runtime + key deps import. Pytest alone is not enough
# (a half-installed venv still has pytest from a prior partial install).
runtime_local_deps_ready() {
  local py="$1"
  "$py" -c '
import asyncpg
import httpx
import jsonschema
import langgraph
import pydantic
import pytest
import pytest_asyncio
import pytest_cov
import yaml
' >/dev/null 2>&1
}

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

# Hash of runtime app/*.py — detect when preflight copies new tests onto an old image.
runtime_app_fingerprint_from_dir() {
  local root="$1"
  (cd "$root" && find app -type f -name '*.py' ! -path '*/__pycache__/*' -print0 \
    | sort -z | xargs -0 md5sum 2>/dev/null) | md5sum | awk '{print $1}'
}

runtime_app_fingerprint_in_container() {
  docker exec agent-runtime bash -c \
    'cd /app && find app -type f -name "*.py" ! -path "*/__pycache__/*" -print0 \
       | sort -z | xargs -0 md5sum' \
    | md5sum | awk '{print $1}'
}

ensure_docker_runtime_matches_tree() {
  if [[ "${PREFLIGHT_SKIP_RUNTIME_REBUILD:-0}" == "1" ]]; then
    echo "==> preflight: skip runtime image freshness check (PREFLIGHT_SKIP_RUNTIME_REBUILD=1)"
    return 0
  fi
  docker_ready || return 0
  local host_fp cont_fp
  host_fp="$(runtime_app_fingerprint_from_dir "$ROOT/services/runtime")"
  cont_fp="$(runtime_app_fingerprint_in_container || true)"
  if [[ -z "$cont_fp" ]]; then
    echo "==> preflight: could not fingerprint runtime container — rebuilding  [$(elapsed)]"
    with_heartbeat "make up-runtime" make -C "$ROOT" up-runtime
    return 0
  fi
  if [[ "$host_fp" == "$cont_fp" ]]; then
    echo "==> preflight: runtime image matches services/runtime/app (${host_fp:0:12}…)  [$(elapsed)]"
    return 0
  fi
  echo "==> preflight: runtime image STALE vs tree (host=${host_fp:0:12}… image=${cont_fp:0:12}…) — make up-runtime  [$(elapsed)]"
  with_heartbeat "make up-runtime" make -C "$ROOT" up-runtime
}

use_docker=0
if [[ "${PREFLIGHT_DOCKER:-0}" == "1" ]]; then
  use_docker=1
  echo "==> preflight: PREFLIGHT_DOCKER=1 — using Docker"
elif [[ -x "$ROOT/services/runtime/.venv/bin/python" ]] \
  && ! runtime_local_deps_ready "$ROOT/services/runtime/.venv/bin/python" \
  && docker_ready; then
  # Half-installed local venvs (pytest present, asyncpg/jsonschema missing) used to
  # skip install and fail collection; prefer the already-baked runtime container.
  use_docker=1
  echo "==> preflight: local runtime venv incomplete — using Docker (runtime container)"
elif python_has_pip; then
  use_docker=0
elif docker_ready; then
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

run_ux_self_check_local() {
  echo "==> [preflight] UX signals self-check  [$(elapsed)]"
  pip_install "$PY" packages/contracts/python
  "$PY" scripts/ux_signals.py --self-check
}

run_ux_tests_local() {
  echo "==> [preflight] UX signals unit tests  [$(elapsed)]"
  pip_install "$PY" packages/contracts/python pytest
  echo "==> [preflight] pytest scripts/tests/test_ux_signals.py  [$(elapsed)]"
  with_heartbeat "pytest ux_signals" "$PY" -m pytest scripts/tests/test_ux_signals.py -q
}

run_runtime_local() {
  echo "==> [preflight] Runtime unit tests  [$(elapsed)]"
  cd "$ROOT/services/runtime"
  local py="$PY"
  if [[ -x .venv/bin/python ]]; then
    py=".venv/bin/python"
    assert_venv_lock_free "$ROOT/services/runtime/.venv"
  fi
  # Always refresh editable + deps. A pytest-only "ready" check previously skipped
  # install on half-broken venvs (missing asyncpg/jsonschema/langgraph) and failed
  # collection. Satisfied installs are usually a few seconds.
  if runtime_local_deps_ready "$py"; then
    echo "==> [preflight] runtime deps look present — refreshing editable install  [$(elapsed)]"
  else
    echo "==> [preflight] runtime deps incomplete — installing .[dev]  [$(elapsed)]"
  fi
  pip_install "$py" "$ROOT/packages/contracts/python"
  pip_install "$py" -e ".[dev]"
  echo "==> [preflight] pytest services/runtime/tests (+cov≥80)  [$(elapsed)]"
  with_heartbeat "pytest runtime" \
    "$py" -m pytest tests -q --cov=app --cov-report=term-missing --cov-fail-under=80
  cd "$ROOT"
}

run_api_ux_local() {
  echo "==> [preflight] API test suite  [$(elapsed)]"
  cd "$ROOT/services/api"
  if [[ -x .venv/bin/pytest ]]; then
    if .venv/bin/python -m pip --version >/dev/null 2>&1; then
      pip_install .venv/bin/python "$ROOT/packages/contracts/python"
    else
      echo "==> [preflight] api .venv has no pip — using import fallback for command_allowlist  [$(elapsed)]"
    fi
    echo "==> [preflight] pytest services/api/tests  [$(elapsed)]"
    with_heartbeat "pytest api" env PYTHONPATH=. .venv/bin/pytest tests -q
  else
    pip_install "$PY" "$ROOT/packages/contracts/python"
    pip_install "$PY" -e ".[dev]" || pip_install "$PY" -e .
    echo "==> [preflight] pytest services/api/tests  [$(elapsed)]"
    with_heartbeat "pytest api" env PYTHONPATH=. "$PY" -m pytest tests -q
  fi
  cd "$ROOT"
}

run_contracts_local() {
  echo "==> [preflight] Contracts tests  [$(elapsed)]"
  pip_install "$PY" jsonschema pytest pyyaml
  echo "==> [preflight] pytest packages/contracts/tests  [$(elapsed)]"
  with_heartbeat "pytest contracts" "$PY" -m pytest packages/contracts/tests -q
  pip_install "$PY" packages/contracts/python
  echo "==> [preflight] pytest packages/contracts/python/tests  [$(elapsed)]"
  with_heartbeat "pytest contracts-py" "$PY" -m pytest packages/contracts/python/tests -q
}

run_ux_self_check_docker() {
  echo "==> [preflight] UX signals self-check (docker/runtime)  [$(elapsed)]"
  # scripts/ux_signals.py resolves CORE as <repo>/packages/contracts/python/agent_contracts/…
  # relative to the copied tree root (/tmp/preflight-ux), so the layout must match the repo.
  "${COMPOSE[@]}" exec -T -u root runtime rm -rf /tmp/preflight-ux
  "${COMPOSE[@]}" exec -T -u root runtime mkdir -p \
    /tmp/preflight-ux/scripts \
    /tmp/preflight-ux/packages/contracts/python \
    /tmp/preflight-ux/eval/reports
  docker cp "$ROOT/scripts/ux_signals.py" agent-runtime:/tmp/preflight-ux/scripts/ux_signals.py
  docker cp "$ROOT/packages/contracts/python/." agent-runtime:/tmp/preflight-ux/packages/contracts/python/
  # docker cp as root leaves the tree root-owned; runtime runs as app.
  "${COMPOSE[@]}" exec -T -u root runtime chown -R app:app /tmp/preflight-ux
  with_heartbeat "docker ux self-check" "${COMPOSE[@]}" exec -T runtime bash -c \
    'echo "==> [preflight/docker] pip install contracts…"
     python -m pip install --progress-bar on /tmp/preflight-ux/packages/contracts/python
     python /tmp/preflight-ux/scripts/ux_signals.py --self-check'
}

run_ux_tests_docker() {
  echo "==> [preflight] UX signals unit tests (docker/runtime)  [$(elapsed)]"
  "${COMPOSE[@]}" exec -T -u root runtime rm -rf /tmp/preflight-ux
  "${COMPOSE[@]}" exec -T -u root runtime mkdir -p \
    /tmp/preflight-ux/scripts/tests \
    /tmp/preflight-ux/packages/contracts/python \
    /tmp/preflight-ux/eval
  docker cp "$ROOT/scripts/ux_signals.py" agent-runtime:/tmp/preflight-ux/scripts/ux_signals.py
  docker cp "$ROOT/scripts/tests/test_ux_signals.py" agent-runtime:/tmp/preflight-ux/scripts/tests/test_ux_signals.py
  docker cp "$ROOT/packages/contracts/python/." agent-runtime:/tmp/preflight-ux/packages/contracts/python/
  docker cp "$ROOT/eval/ux_signals" agent-runtime:/tmp/preflight-ux/eval/ux_signals
  with_heartbeat "docker pytest ux" "${COMPOSE[@]}" exec -T runtime bash -c \
    'echo "==> [preflight/docker] pip install pytest…"
     python -m pip install --progress-bar on pytest
     cd /tmp/preflight-ux && python -m pytest scripts/tests/test_ux_signals.py -q'
}

run_runtime_docker() {
  echo "==> [preflight] Runtime unit tests (docker)  [$(elapsed)]"
  ensure_docker_runtime_matches_tree
  "${COMPOSE[@]}" exec -T -u root runtime rm -rf /tmp/runtime-tests /tmp/eval /tmp/preflight-contracts
  "${COMPOSE[@]}" exec -T -u root runtime mkdir -p /tmp/eval/plan_suggest /tmp/preflight-contracts/python
  docker cp "$ROOT/services/runtime/tests/." agent-runtime:/tmp/runtime-tests/
  docker cp "$ROOT/packages/contracts/python/." agent-runtime:/tmp/preflight-contracts/python/
  if [[ -f "$ROOT/eval/plan_suggest/cases.json" ]]; then
    docker cp "$ROOT/eval/plan_suggest/cases.json" agent-runtime:/tmp/eval/plan_suggest/cases.json
  fi
  with_heartbeat "docker pytest runtime" "${COMPOSE[@]}" exec -T runtime bash -c \
    'echo "==> [preflight/docker] pip install pytest extras + contracts…"
     python -m pip install --progress-bar on pytest pytest-asyncio pytest-cov
     python -m pip install --progress-bar on /tmp/preflight-contracts/python
     echo "==> [preflight/docker] pytest /tmp/runtime-tests…"
     PYTHONPATH=/app python -m pytest /tmp/runtime-tests -q --asyncio-mode=auto'
}

run_api_ux_docker() {
  echo "==> [preflight] API test suite (docker)  [$(elapsed)]"
  if ! "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx api; then
    echo "api container not running — start with make up / make start"
    return 1
  fi
  "${COMPOSE[@]}" exec -T -u root api rm -rf /tmp/api-tests /tmp/preflight-contracts
  "${COMPOSE[@]}" exec -T -u root api mkdir -p /tmp/api-tests /tmp/preflight-contracts/python
  docker cp "$ROOT/services/api/tests/." agent-api:/tmp/api-tests/
  docker cp "$ROOT/packages/contracts/python/." agent-api:/tmp/preflight-contracts/python/
  with_heartbeat "docker pytest api" "${COMPOSE[@]}" exec -T api bash -c \
    'echo "==> [preflight/docker] pip install pytest extras + contracts…"
     python -m pip install --progress-bar on pytest pytest-asyncio httpx pyyaml
     python -m pip install --progress-bar on /tmp/preflight-contracts/python
     if [ -d /repo/services/api/app ]; then export PYTHONPATH=/repo/services/api; else export PYTHONPATH=/app; fi
     if [ -f /repo/packages/contracts/openapi/public.yaml ]; then
       export PUBLIC_OPENAPI_YAML=/repo/packages/contracts/openapi/public.yaml
     fi
     echo "==> [preflight/docker] pytest /tmp/api-tests…"
     python -m pytest /tmp/api-tests -q --asyncio-mode=auto'
}

run_contracts_docker() {
  echo "==> [preflight] Contracts tests (docker/runtime)  [$(elapsed)]"
  "${COMPOSE[@]}" exec -T -u root runtime rm -rf /tmp/preflight-contracts
  docker cp "$ROOT/packages/contracts" agent-runtime:/tmp/preflight-contracts
  with_heartbeat "docker pytest contracts" "${COMPOSE[@]}" exec -T runtime bash -c \
    'echo "==> [preflight/docker] pip install jsonschema pytest pyyaml…"
     python -m pip install --progress-bar on jsonschema pytest pyyaml
     cd /tmp/preflight-contracts && PYTHONPATH=/tmp/preflight-contracts python -m pytest tests -q
     echo "==> [preflight/docker] pip install contracts python package…"
     python -m pip install --progress-bar on /tmp/preflight-contracts/python
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
  echo "==> [preflight] ▶ start suite: $name  [$(elapsed)]"
  set +e
  "$@"
  local rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    echo "==> [preflight] FAILED: $name (exit $rc)  [$(elapsed)]"
    failed=1
  else
    echo "==> [preflight] ✓ suite ok: $name  [$(elapsed)]"
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
  echo "preflight FAILED — fix tests before push (or SKIP_PREFLIGHT=1 / git push --no-verify).  [$(elapsed)]"
  echo "Full CI unit mirror: PREFLIGHT_ALL=1 bash scripts/preflight_unit.sh"
  exit 1
fi

echo "==> preflight OK  [$(elapsed)]"
