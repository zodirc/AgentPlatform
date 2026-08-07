#!/usr/bin/env bash
# Ensure RELEASE_CONSOLE_SECRET + start release-console in background (host).
# Used by make up / start. Skip with RELEASE_CONSOLE=0.
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
s.settimeout(0.4)
try:
    s.connect(("127.0.0.1", port))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
raise SystemExit(0)
PY
}

if port_open; then
  echo "==> release-console already on ${url}"
  exit 0
fi

# Stale pid?
if [[ -f "$PID_FILE" ]]; then
  old="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
    echo "==> release-console pid $old alive but port ${port} closed — restarting"
    kill "$old" 2>/dev/null || true
    sleep 0.3
  fi
  rm -f "$PID_FILE"
fi

cd "$ROOT"
# Load .env into child (server also reads .env itself).
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
nohup env PYTHONUNBUFFERED=1 RELEASE_CONSOLE_PORT="$port" RELEASE_CONSOLE_SECRET="$secret" \
  python3 services/release-console/server.py >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
sleep 0.6
if port_open; then
  echo "==> release-console ${url}  (secret in .env · log ${LOG_FILE#"$ROOT"/})"
else
  echo "WARNING: release-console failed to bind :${port} — see ${LOG_FILE#"$ROOT"/}" >&2
  exit 1
fi
