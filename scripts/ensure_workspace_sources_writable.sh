#!/usr/bin/env bash
# Ensure /workspace (and sources/) is writable by the runtime app user (uid 1000).
#
# Docker creates the bind-mount parent as root when first mounting
# SEED_SOURCES_HOST_PATH → /workspace/sources/seed/writing:ro. That leaves
# /workspace root:root 755, so writing tools cannot create outline.md or
# drafts/manuscript.md (Permission denied). sources/ itself was the same
# bug for web「保存到资料库」.
#
# Safe to re-run: chowns the workspace root + top-level dirs except the RO
# seed tree. Never recurses into sources/seed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f deploy/docker-compose.yml -f deploy/compose/planes.yml --env-file .env)
if [[ -f deploy/compose/gpu.auto.yml ]]; then
  COMPOSE+=(-f deploy/compose/gpu.auto.yml)
fi

if ! "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx runtime; then
  echo "==> ensure_workspace_sources_writable: runtime not running; skip"
  exit 0
fi

echo "==> ensuring /workspace writable by app (uid 1000)"
"${COMPOSE[@]}" exec -u 0 -T runtime sh -c '
set -e
# Root of the bind mount must be writable or outline.md / drafts/ cannot be created.
chown 1000:1000 /workspace || chmod 0777 /workspace
mkdir -p /workspace/drafts /workspace/exports /workspace/.agent \
  /workspace/sources /workspace/sources/cards
chown 1000:1000 /workspace/drafts /workspace/exports /workspace/.agent \
  /workspace/sources /workspace/sources/cards || true
# Top-level entries except sources/ (seed lives under sources/).
find /workspace -mindepth 1 -maxdepth 1 ! -name sources -exec chown -R 1000:1000 {} + || true
chown 1000:1000 /workspace/sources /workspace/sources/cards
find /workspace/sources -mindepth 1 -maxdepth 1 ! -name seed -exec chown -R 1000:1000 {} +
'

if ! "${COMPOSE[@]}" exec -u 1000 -T runtime sh -c \
  'touch /workspace/.write_probe && rm -f /workspace/.write_probe \
   && mkdir -p /workspace/drafts \
   && touch /workspace/drafts/.write_probe && rm -f /workspace/drafts/.write_probe \
   && touch /workspace/sources/.write_probe && rm -f /workspace/sources/.write_probe'; then
  echo "ERROR: /workspace still not writable by uid 1000 (outline.md / drafts/ / sources/)" >&2
  exit 1
fi
echo "==> workspace root, drafts/, and sources/ writable for uid 1000"
