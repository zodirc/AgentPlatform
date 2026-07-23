#!/usr/bin/env bash
# Ensure workspace/sources is writable by the runtime app user (uid 1000).
#
# Docker creates parent dirs as root when bind-mounting
# SEED_SOURCES_HOST_PATH → /workspace/sources/seed/writing:ro. That leaves
# sources/ owned by root, so web「保存到资料库」hits PermissionError (500).
#
# Safe to re-run: only chowns the sources directory itself (+ cards/ and
# non-seed children), never recurses into the RO seed mount.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f deploy/docker-compose.yml --env-file .env)

if ! "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx runtime; then
  echo "==> ensure_workspace_sources_writable: runtime not running; skip"
  exit 0
fi

echo "==> ensuring /workspace/sources writable by app (uid 1000)"
"${COMPOSE[@]}" exec -u 0 -T runtime sh -c '
set -e
mkdir -p /workspace/sources /workspace/sources/cards
chown 1000:1000 /workspace/sources /workspace/sources/cards
find /workspace/sources -mindepth 1 -maxdepth 1 ! -name seed -exec chown -R 1000:1000 {} +
'

if ! "${COMPOSE[@]}" exec -u 1000 -T runtime sh -c \
  'touch /workspace/sources/.write_probe && rm -f /workspace/sources/.write_probe'; then
  echo "ERROR: /workspace/sources still not writable by uid 1000" >&2
  exit 1
fi
echo "==> sources writable for uploads"
