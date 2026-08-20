#!/usr/bin/env bash
# Safe Docker cleanup by *need*, not recency.
# Keep: running product stack, fast-rebuild cache (deps tags + pip/pnpm mounts +
# Dockerfile bases), eval images. Drop everything else.
# Never touches named deploy_* volumes. Never uses until= (age ≠ usefulness).
#
# Usage:
#   bash scripts/docker_prune_safe.sh           # apply
#   DRY_RUN=1 bash scripts/docker_prune_safe.sh # list only
#   BUILD_CACHE_PRUNE=1 bash scripts/docker_prune_safe.sh  # also drop pip/pnpm mounts (-a)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEEP_FILE="${DOCKER_KEEP_FILE:-$ROOT/deploy/docker-keep.list}"
DRY_RUN="${DRY_RUN:-0}"
BUILD_CACHE_PRUNE="${BUILD_CACHE_PRUNE:-0}"

if [[ ! -f "$KEEP_FILE" ]]; then
  echo "missing keep list: $KEEP_FILE" >&2
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  echo "docker daemon not reachable; start Docker Desktop and retry" >&2
  exit 1
fi

mapfile -t KEEP_PATTERNS < <(
  grep -vE '^\s*(#|$)' "$KEEP_FILE" | sed 's/[[:space:]]*$//'
)

keep_match() {
  local ref="$1" pat
  for pat in "${KEEP_PATTERNS[@]}"; do
    # shellcheck disable=SC2254
    case "$ref" in
      $pat) return 0 ;;
    esac
  done
  return 1
}

# Unreferenced regular layers left after retag. Not cache mounts (pip/pnpm).
prune_unneeded_regular_cache() {
  docker builder prune -f --filter type=regular
}

echo "==> keep list: $KEEP_FILE (${#KEEP_PATTERNS[@]} patterns)"
echo "==> DRY_RUN=$DRY_RUN  BUILD_CACHE_PRUNE=$BUILD_CACHE_PRUNE"

echo "==> scanning stopped/created containers outside product stack"
mapfile -t JUNK_CTRS < <(
  docker ps -aq --filter status=exited --filter status=created --filter status=dead 2>/dev/null || true
)
for cid in "${JUNK_CTRS[@]:-}"; do
  [[ -z "$cid" ]] && continue
  name="$(docker inspect -f '{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##')"
  case "$name" in
    agent-*|*agent-gateway*|*agent-postgres*|*agent-bench* ) continue ;;
  esac
  echo "  drop container: $name ($cid)"
  if [[ "$DRY_RUN" != "1" ]]; then
    docker rm -f "$cid" >/dev/null || true
  fi
done

echo "==> scanning images"
mapfile -t IMAGES < <(docker images --format '{{.Repository}}:{{.Tag}}\t{{.ID}}' | grep -v '<none>' || true)
REMOVE_IDS=()
for line in "${IMAGES[@]:-}"; do
  [[ -z "$line" ]] && continue
  ref="${line%%$'\t'*}"
  iid="${line#*$'\t'}"
  if keep_match "$ref"; then
    echo "  KEEP  $ref"
    continue
  fi
  echo "  DROP  $ref"
  REMOVE_IDS+=("$iid")
done

if [[ "$DRY_RUN" == "1" ]]; then
  dangling_n="$(docker images -f dangling=true -q 2>/dev/null | wc -l | tr -d ' ')"
  echo "==> dry-run: would remove ${#REMOVE_IDS[@]} tagged + ${dangling_n} dangling images;"
  echo "    plus unreferenced regular BuildKit layers (keep pip/pnpm cache mounts)"
  if [[ "$BUILD_CACHE_PRUNE" == "1" ]]; then
    echo "    BUILD_CACHE_PRUNE=1 would also drop cache mounts (next deps rebuild re-fetches)"
  fi
  echo "==> skip apply"
else
  if [[ ${#REMOVE_IDS[@]} -gt 0 ]]; then
    printf '%s\n' "${REMOVE_IDS[@]}" | sort -u | while read -r id; do
      [[ -z "$id" ]] && continue
      docker rmi -f "$id" 2>/dev/null || true
    done
  fi
  docker image prune -f >/dev/null || true
  docker volume ls -qf dangling=true 2>/dev/null | while read -r v; do
    [[ -z "$v" ]] && continue
    case "$v" in
      deploy_*) echo "  KEEP volume $v"; continue ;;
    esac
    echo "  DROP volume $v"
    docker volume rm "$v" 2>/dev/null || true
  done
  echo "==> drop unreferenced regular BuildKit layers (keep pip/pnpm cache mounts)"
  prune_unneeded_regular_cache
  if [[ "$BUILD_CACHE_PRUNE" == "1" ]]; then
    echo "==> BUILD_CACHE_PRUNE=1 → docker builder prune -af (cache mounts too)"
    docker builder prune -af
  fi
fi

echo "==> done; docker system df:"
docker system df || true
echo "==> remaining images:"
docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | sort || true
