#!/usr/bin/env bash
# Ensure agent-bench-postgres is running when the bench compose profile is enabled.
#
# Docker Desktop on WSL2 can flake on file→file bind mounts during container
# recreate (deploy/docker-compose.yml mounts deploy/init/ as a directory to avoid
# that). If bench-postgres still fails, retry once so `make start` / `make up`
# self-heal without a separate make start-bench.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
CNAME="agent-bench-postgres"

# Explicit COMPOSE_PROFILES= skips bench (constrained hosts).
if [[ -n "${COMPOSE_PROFILES+x}" && -z "${COMPOSE_PROFILES}" ]]; then
  exit 0
fi
profiles="${COMPOSE_PROFILES:-bench}"
case ",${profiles}," in
  *,bench,*);;
  *) exit 0;;
esac

compose_up() {
  set -a
  [[ -f deploy/embedding.defaults.env ]] && . ./deploy/embedding.defaults.env
  [[ -f deploy/embedding.auto.env ]] && . ./deploy/embedding.auto.env
  [[ -f deploy/base-images.env ]] && . ./deploy/base-images.env
  [[ -f deploy/ops-eval.auto.env ]] && . ./deploy/ops-eval.auto.env
  set +a
  local gpu_flag=()
  [[ -f deploy/compose/gpu.auto.yml ]] && gpu_flag=(-f deploy/compose/gpu.auto.yml)
  local ops_flag=()
  case "${OPS_EVAL_DOCKER_SOCK:-0}" in
    1|true|TRUE|yes|YES) ops_flag=(-f deploy/compose/ops-eval.yml) ;;
  esac
  COMPOSE_PROFILES=bench docker compose -f deploy/docker-compose.yml "${gpu_flag[@]}" \
    "${ops_flag[@]}" \
    --env-file .env --env-file deploy/embedding.defaults.env --env-file deploy/embedding.auto.env \
    --env-file deploy/base-images.env \
    up -d bench-postgres
}

is_running() {
  [[ "$(docker inspect -f '{{.State.Running}}' "$CNAME" 2>/dev/null || echo false)" == "true" ]]
}

wait_running() {
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    is_running && return 0
    sleep 1
  done
  return 1
}

if is_running; then
  exit 0
fi

echo "==> ensuring agent-bench-postgres (bench profile)…"
compose_up || true
if wait_running; then
  echo "==> agent-bench-postgres is up"
  exit 0
fi

echo "==> bench-postgres not up — retrying once…"
compose_up || true
if wait_running; then
  echo "==> agent-bench-postgres is up (after retry)"
  exit 0
fi

err="$(docker inspect -f '{{.State.Error}}' "$CNAME" 2>/dev/null || true)"
echo "WARNING: agent-bench-postgres failed to start — Ops 索引会在看板标黄（产品 Agent 不受影响）." >&2
if [[ -n "$err" ]]; then
  echo "  ${err}" >&2
fi
echo "  重试: make start  或  make start-bench" >&2
exit 0
