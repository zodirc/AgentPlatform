#!/usr/bin/env bash
# Soft-restart release-console after /api/action restart-console returns.
# Spawned detached from server.py so the HTTP reply can finish before we die.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATUS_DIR="${RELEASE_STATUS_DIR:-$ROOT/reports/release}"
LOG_DIR="$STATUS_DIR/logs"
LOG_FILE="$LOG_DIR/misc.log"
mkdir -p "$LOG_DIR"

stamp() { date '+%Y-%m-%d %H:%M:%S'; }
# stdout is already misc.log when spawned from the console API.
log() { echo "[$(stamp)] restart_console: $*"; }

log "waiting for HTTP to finish…"
sleep 1.2

log "stopping…"
bash "$ROOT/scripts/release/stop_console.sh" || true
sleep 0.5

log "starting…"
# Host console must not inherit Cursor sandbox markers (would refuse bind / be unreachable).
unset CURSOR_SANDBOX CURSOR_AGENT || true
export RELEASE_CONSOLE="${RELEASE_CONSOLE:-1}"
bash "$ROOT/scripts/release/ensure_console.sh"
log "done"
