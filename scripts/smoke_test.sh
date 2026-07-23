#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

mkdir -p workspace/sections
chmod -R a+rwx workspace 2>/dev/null || true

COMPOSE="docker compose -f deploy/docker-compose.yml --env-file .env"
# CI / Proof gate: use hash runtime-lite so smoke does not bake sentence-transformers
# (HF download often fails on GitHub runners). Daily `make up` still uses Dockerfile.retrieval.
if [[ "${SMOKE_RUNTIME_LITE:-}" == "1" ]] || [[ "${CI:-}" == "true" ]]; then
  COMPOSE="docker compose -f deploy/docker-compose.yml -f deploy/compose/runtime-lite.yml --env-file .env"
  export EMBEDDING_BACKEND="${EMBEDDING_BACKEND:-hash}"
  export EMBEDDING_DIMENSIONS="${EMBEDDING_DIMENSIONS:-256}"
fi
BASE_URL="${SMOKE_BASE_URL:-http://localhost}"
# L0 smoke is a contract path (docs/11 / docs/28): default stub so gate does not
# depend on live provider keys. Override: SMOKE_MODEL_MODE=live make smoke
SMOKE_MODEL_MODE="${SMOKE_MODEL_MODE:-stub}"

# Mirror scripts/eval_run.py: when AUTH_ENABLED=true (or CI), API needs Basic admin
# (admin_session_bypass → system user). .env.example uses inline # comments and may
# have CRLF on some checkouts — strip both so we never silently omit Authorization.
SMOKE_AUTH_USER=$(python3 - <<'PY'
import os
from pathlib import Path

def _env_val(raw: str) -> str:
    v = raw.strip().strip("\r")
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    if "#" in v:
        v = v.split("#", 1)[0].rstrip()
    return v.strip().strip("\r")

env: dict[str, str] = {}
env_path = Path(".env")
if env_path.is_file():
    for line in env_path.read_text().splitlines():
        line = line.strip("\r")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip().strip("\r")] = _env_val(value)

auth_on = env.get("AUTH_ENABLED", "false").lower() in {"true", "1", "yes"}
force = os.environ.get("CI", "").lower() in {"true", "1"} or os.environ.get(
    "SMOKE_FORCE_AUTH", ""
).lower() in {"true", "1"}
if not auth_on and not force:
    raise SystemExit(0)
password = env.get("ADMIN_PASSWORD") or "admin"
print(f"admin:{password}", end="")
PY
)

CURL_AUTH=()
SMOKE_AUTH_HEADER=""
if [[ -n "${SMOKE_AUTH_USER:-}" ]]; then
  # curl -u is more reliable than hand-built Authorization headers in CI.
  CURL_AUTH+=(-u "$SMOKE_AUTH_USER")
  export SMOKE_AUTH_USER
  # urllib SSE helper still wants a raw Authorization header.
  SMOKE_AUTH_HEADER=$(python3 - <<'PY'
import base64
import os

user = os.environ["SMOKE_AUTH_USER"]
print("Authorization: Basic " + base64.b64encode(user.encode()).decode(), end="")
PY
)
fi
export SMOKE_AUTH_HEADER
if [[ -z "${SMOKE_AUTH_USER:-}" ]]; then
  echo "==> smoke auth: (none — AUTH_ENABLED off)"
else
  echo "==> smoke auth: Basic admin (bypass)"
fi

restore_runtime_model_mode() {
  # Put daily stack back to .env MODEL_MODE after stub smoke (best-effort).
  # Must --wait so standalone `make smoke` leaves a healthy runtime.
  echo "==> Restoring runtime MODEL_MODE from .env"
  $COMPOSE up -d --force-recreate --remove-orphans --wait --wait-timeout 180 runtime \
    || echo "WARNING: could not restore runtime; run: make start"
}

# When composed into `make gate`, skip mid-pipeline restore (gate owns final restore).
if [[ "${SMOKE_SKIP_RESTORE:-0}" != "1" ]]; then
  trap restore_runtime_model_mode EXIT
fi

echo "==> Starting stack (smoke MODEL_MODE=${SMOKE_MODEL_MODE})"
MODEL_MODE="${SMOKE_MODEL_MODE}" $COMPOSE up -d --build

echo "==> Waiting for services"
deadline=$((SECONDS + 180))
while true; do
  if curl -fsS "${BASE_URL}/health/live" >/dev/null 2>&1; then
    break
  fi
  if (( SECONDS > deadline )); then
    echo "timeout waiting for /health/live"
    $COMPOSE ps
    $COMPOSE logs --tail=50
    exit 1
  fi
  sleep 3
done

# Ensure runtime picked up smoke MODEL_MODE (compose may have reused a live container).
echo "==> Recreate runtime with MODEL_MODE=${SMOKE_MODEL_MODE}"
MODEL_MODE="${SMOKE_MODEL_MODE}" $COMPOSE up -d --force-recreate --wait --wait-timeout 180 runtime

echo "==> Health OK"

echo "==> Create session"
SESSION_HTTP=$(curl -sS -w "%{http_code}" -o /tmp/smoke_session.json -X POST "${BASE_URL}/api/v1/sessions" \
  -H 'Content-Type: application/json' \
  "${CURL_AUTH[@]}" \
  -d '{}')
if [[ "$SESSION_HTTP" != "201" && "$SESSION_HTTP" != "200" ]]; then
  echo "create session failed HTTP ${SESSION_HTTP}" >&2
  echo "auth_user_set=$([ -n "${SMOKE_AUTH_USER:-}" ] && echo yes || echo no)" >&2
  head -c 500 /tmp/smoke_session.json >&2 || true
  echo >&2
  exit 22
fi
SESSION_JSON=$(cat /tmp/smoke_session.json)
SESSION_ID=$(echo "$SESSION_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "session_id=$SESSION_ID"

echo "==> Start turn"
TURN_JSON=$(curl -fsS -X POST "${BASE_URL}/api/v1/sessions/${SESSION_ID}/turns" \
  -H 'Content-Type: application/json' \
  "${CURL_AUTH[@]}" \
  -d '{"message":"smoke test","scenario_id":"writing","client_request_id":"00000000-0000-4000-8000-000000000001"}')
TURN_ID=$(echo "$TURN_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "turn_id=$TURN_ID"

echo "==> Collect SSE events"
EVENTS=$(SMOKE_AUTH_HEADER="${SMOKE_AUTH_HEADER:-}" python3 - "$BASE_URL" "$TURN_ID" <<'PY'
import json
import os
import sys
import urllib.request

base, turn_id = sys.argv[1], sys.argv[2]
url = f"{base}/api/v1/turns/{turn_id}/stream"
headers = {"Accept": "text/event-stream"}
auth = os.environ.get("SMOKE_AUTH_HEADER", "").strip()
if auth:
    key, value = auth.split(":", 1)
    headers[key.strip()] = value.strip()
req = urllib.request.Request(url, headers=headers)
events = []
failed_payload = None
with urllib.request.urlopen(req, timeout=60) as resp:
    for raw in resp:
        line = raw.decode().strip()
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
            events.append(data["type"])
            if data["type"] == "turn.failed":
                failed_payload = data.get("payload") or data
            if data["type"] in ("turn.completed", "turn.failed", "turn.cancelled"):
                break
if failed_payload is not None:
    print(json.dumps({"events": events, "failed": failed_payload}), file=sys.stderr)
print(json.dumps(events))
PY
)
echo "events=$EVENTS"

echo "==> Assert event sequence (L0 golden)"
python3 - "$EVENTS" <<'PY'
import json
import sys

events = json.loads(sys.argv[1])
required = [
    "turn.accepted",
    "step.started",
    "tool.started",
    "tool.completed",
    "turn.completed",
]
idx = 0
for need in required:
    while idx < len(events) and events[idx] != need:
        idx += 1
    if idx >= len(events):
        print(f"missing {need} in {events}", file=sys.stderr)
        if "turn.failed" in events:
            print(
                "hint: turn.failed usually means live model auth/network error; "
                "L0 smoke defaults to MODEL_MODE=stub (see scripts/smoke_test.sh).",
                file=sys.stderr,
            )
        sys.exit(1)
    idx += 1
print("L0 golden OK")
PY

echo "==> TurnView"
VIEW_JSON=$(curl -fsS "${BASE_URL}/api/v1/turns/${TURN_ID}/view" "${CURL_AUTH[@]}")
echo "$VIEW_JSON" | python3 -c "import sys,json; v=json.load(sys.stdin); assert v['status']=='completed', v; print('view.status=completed')"

echo "==> Web shell"
curl -fsS "${BASE_URL}/" | grep -q "Agent Platform"

echo "==> All smoke checks passed"
