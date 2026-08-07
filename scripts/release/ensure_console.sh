#!/usr/bin/env bash
# Ensure RELEASE_CONSOLE_SECRET + start release-console in background (host).
# Used by make up / start. Skip with RELEASE_CONSOLE=0.
#
# Important (WSL / Cursor agent): the console must listen in the *host* network
# namespace. Starting it from a Cursor agent sandbox leaves a listen socket only
# inside that netns — the Windows/WSL browser gets "connection refused".
# We refuse to start from the sandbox; start from a normal WSL terminal instead.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
STATUS_DIR="${RELEASE_STATUS_DIR:-$ROOT/reports/release}"
PID_FILE="$STATUS_DIR/console.pid"
LOG_FILE="$STATUS_DIR/console.log"

if [[ "${RELEASE_CONSOLE:-1}" == "0" ]]; then
  echo "==> release-console skipped (RELEASE_CONSOLE=0)"
  exit 0
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: ${ENV_FILE} missing; run: cp .env.example .env" >&2
  exit 1
fi

env_has_key() {
  local key="$1"
  grep -Eq "^[[:space:]]*${key}=" "$ENV_FILE"
}

env_get() {
  local key="$1"
  local line val
  line="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | tail -n1 || true)"
  [[ -z "$line" ]] && return 0
  val="${line#*=}"
  val="${val%%$'\r'}"
  val="${val%%#*}"
  val="${val#"${val%%[![:space:]]*}"}"
  val="${val%"${val##*[![:space:]]}"}"
  if [[ "$val" == \"*\" ]]; then
    val="${val:1:${#val}-2}"
  elif [[ "$val" == \'*\' ]]; then
    val="${val:1:${#val}-2}"
  fi
  printf '%s' "$val"
}

mkdir -p "$STATUS_DIR"

secret="$(env_get RELEASE_CONSOLE_SECRET)"
if ! env_has_key RELEASE_CONSOLE_SECRET; then
  if command -v openssl >/dev/null 2>&1; then
    secret="$(openssl rand -hex 16)"
  else
    secret="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
  fi
  {
    echo ""
    echo "# --- Release console (auto by make up; scripts/release/README.md) ---"
    echo "RELEASE_CONSOLE_SECRET=${secret}"
    echo "RELEASE_CONSOLE_PORT=9090"
  } >>"$ENV_FILE"
  echo "==> RELEASE_CONSOLE_SECRET generated → .env"
elif [[ -z "$secret" ]]; then
  echo "==> RELEASE_CONSOLE_SECRET empty — release-console disabled"
  exit 0
fi

port="$(env_get RELEASE_CONSOLE_PORT)"
port="${port:-9090}"
url="http://127.0.0.1:${port}/"

port_open() {
  python3 - "$port" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket()
s.settimeout(0.6)
try:
    s.connect(("127.0.0.1", port))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
raise SystemExit(0)
PY
}

# Cursor agent shells run in an isolated netns.
in_cursor_sandbox() {
  [[ -n "${CURSOR_SANDBOX:-}" || -n "${CURSOR_AGENT:-}" ]]
}

netns_mismatch_proven() {
  local pid="$1"
  local a b
  a="$(readlink "/proc/$$/ns/net" 2>/dev/null || true)"
  b="$(readlink "/proc/${pid}/ns/net" 2>/dev/null || true)"
  [[ -n "$a" && -n "$b" && "$a" != "$b" ]]
}

kill_console_procs() {
  local old=""
  if [[ -f "$PID_FILE" ]]; then
    old="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
      kill "$old" 2>/dev/null || true
      sleep 0.2
      kill -9 "$old" 2>/dev/null || true
    fi
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
  elif command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
      sleep 0.2
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
    fi
  fi
  pkill -f 'services/release-console/server.py' 2>/dev/null || true
  rm -f "$PID_FILE"
  sleep 0.3
}

if port_open; then
  echo "==> release-console already on ${url}"
  exit 0
fi

# Do not start from Cursor agent sandbox — browser cannot reach that netns.
if in_cursor_sandbox && [[ "${RELEASE_CONSOLE_ALLOW_SANDBOX:-0}" != "1" ]]; then
  # Clear unreachable zombies left by earlier sandboxed starts (same sandbox may see them).
  if [[ -f "$PID_FILE" ]]; then
    old="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
      echo "==> clearing sandboxed zombie pid $old"
      kill_console_procs
    fi
  fi
  echo "==> release-console not started (Cursor agent sandbox would bind an unreachable :${port})"
  echo "    在本机 WSL 终端执行："
  echo "      make release-console-stop; bash scripts/release/ensure_console.sh"
  echo "    然后打开 ${url}"
  exit 0
fi

# Port closed: clear stale / unreachable pid then start.
if [[ -f "$PID_FILE" ]]; then
  old="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
    echo "==> release-console pid $old alive but :${port} unreachable — clearing zombie"
  fi
fi
kill_console_procs

cd "$ROOT"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

setsid env PYTHONUNBUFFERED=1 RELEASE_CONSOLE_PORT="$port" RELEASE_CONSOLE_SECRET="$secret" \
  python3 "$ROOT/services/release-console/server.py" \
  </dev/null >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
new_pid="$(cat "$PID_FILE")"

ok=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if port_open; then
    ok=1
    break
  fi
  if ! kill -0 "$new_pid" 2>/dev/null; then
    break
  fi
  sleep 0.3
done

if [[ "$ok" == "1" ]]; then
  if netns_mismatch_proven "$new_pid"; then
    echo "WARNING: release-console started in a different network namespace." >&2
    echo "         Killing it — run from a normal WSL terminal:" >&2
    echo "         bash scripts/release/ensure_console.sh" >&2
    kill_console_procs
    exit 1
  fi
  echo "==> release-console ${url}  (pid $new_pid · log ${LOG_FILE#"$ROOT"/})"
  exit 0
fi

echo "WARNING: release-console failed to bind :${port} — see ${LOG_FILE#"$ROOT"/}" >&2
if ! kill -0 "$new_pid" 2>/dev/null; then
  rm -f "$PID_FILE"
fi
exit 1
