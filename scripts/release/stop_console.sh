#!/usr/bin/env bash
# Stop background release-console started by ensure_console.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATUS_DIR="${RELEASE_STATUS_DIR:-$ROOT/reports/release}"
PID_FILE="$STATUS_DIR/console.pid"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"

port=9090
if [[ -f "$ENV_FILE" ]]; then
  line="$(grep -E '^[[:space:]]*RELEASE_CONSOLE_PORT=' "$ENV_FILE" | tail -n1 || true)"
  if [[ -n "$line" ]]; then
    port="${line#*=}"
    port="${port%%#*}"
    port="${port// /}"
  fi
fi

stopped=0
if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 0.2
    kill -9 "$pid" 2>/dev/null || true
    stopped=1
  fi
  rm -f "$PID_FILE"
fi

# Best-effort: anything still bound to the port / matching cmdline (incl. sandboxed zombies).
if command -v fuser >/dev/null 2>&1; then
  if fuser "${port}/tcp" >/dev/null 2>&1; then
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
    stopped=1
  fi
elif command -v lsof >/dev/null 2>&1; then
  pids="$(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.2
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
    stopped=1
  fi
fi
if pkill -f 'services/release-console/server.py' 2>/dev/null; then
  stopped=1
fi

if [[ "$stopped" == "1" ]]; then
  echo "==> release-console stopped"
else
  echo "==> release-console not running"
fi
