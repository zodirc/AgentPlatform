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
BASE_URL="${SMOKE_BASE_URL:-http://localhost}"

# Mirror scripts/eval_run.py: when AUTH_ENABLED=true, API routes require Basic auth.
SMOKE_AUTH_HEADER=$(python3 - <<'PY'
import base64
from pathlib import Path

env: dict[str, str] = {}
for line in Path(".env").read_text().splitlines():
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip()

if env.get("AUTH_ENABLED", "false").lower() != "true":
    print("")
else:
    password = env.get("ADMIN_PASSWORD", "admin")
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    print(f"Authorization: Basic {token}")
PY
)

CURL_AUTH=()
if [[ -n "$SMOKE_AUTH_HEADER" ]]; then
  CURL_AUTH+=(-H "$SMOKE_AUTH_HEADER")
fi

echo "==> Starting stack"
$COMPOSE up -d --build

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

echo "==> Health OK"

echo "==> Create session"
SESSION_JSON=$(curl -fsS -X POST "${BASE_URL}/api/v1/sessions" \
  -H 'Content-Type: application/json' \
  "${CURL_AUTH[@]}" \
  -d '{}')
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
with urllib.request.urlopen(req, timeout=60) as resp:
    for raw in resp:
        line = raw.decode().strip()
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
            events.append(data["type"])
            if data["type"] in ("turn.completed", "turn.failed", "turn.cancelled"):
                break
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
