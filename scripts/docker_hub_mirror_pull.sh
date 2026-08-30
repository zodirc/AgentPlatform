#!/usr/bin/env bash
# Pull Hub library images via a China-friendly mirror, then retag to canonical names.
# Prefer configuring Docker Desktop registry-mirrors (see script header comment);
# this one-shot works when daemon.json is unchanged.
#
# Usage:
#   bash scripts/docker_hub_mirror_pull.sh
#   MIRROR=docker.m.daocloud.io bash scripts/docker_hub_mirror_pull.sh
#
# Docker Desktop → Settings → Docker Engine → add (then Apply & restart):
#   "registry-mirrors": ["https://docker.m.daocloud.io"]
set -euo pipefail

MIRROR="${MIRROR:-docker.m.daocloud.io}"
# Images compose needs from Docker Hub (not local agent-platform-* bakes).
IMAGES=(
  "library/redis:7-alpine|redis:7-alpine"
  "library/caddy:2-alpine|caddy:2-alpine"
)

pull_one() {
  local remote="$1" local_tag="$2"
  echo "==> $local_tag  ←  ${MIRROR}/${remote}"
  docker pull "${MIRROR}/${remote}"
  docker tag "${MIRROR}/${remote}" "$local_tag"
}

for spec in "${IMAGES[@]}"; do
  remote="${spec%%|*}"
  local_tag="${spec##*|}"
  if docker image inspect "$local_tag" >/dev/null 2>&1; then
    echo "==> skip (already local): $local_tag"
    continue
  fi
  pull_one "$remote" "$local_tag"
done

echo "==> done. Retry: make up"
