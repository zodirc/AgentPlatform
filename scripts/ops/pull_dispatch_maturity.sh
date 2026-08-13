#!/usr/bin/env bash
# Maturity smoke for pull-dispatch (no kill-9). Run inside compose network or with make.
set -euo pipefail

API="${API_CONTAINER:-agent-api}"
PG="${PG_CONTAINER:-agent-postgres}"
RUNTIME="${RUNTIME_CONTAINER:-agent-runtime}"

echo "==> settings / listeners"
docker exec "$API" python -c "from app.settings import settings; assert settings.turn_dispatch=='pull', settings.turn_dispatch; print('api turn_dispatch=pull')"
docker exec "$RUNTIME" python -c "from app.settings import settings; assert settings.turn_dispatch=='pull'; print('runtime turn_dispatch=pull')"
if docker logs "$RUNTIME" 2>&1 | grep 'turn dispatch LISTEN started' >/dev/null 2>&1; then
  echo "runtime: turn dispatch LISTEN ok"
else
  echo "WARN: turn dispatch LISTEN not found in logs (check runtime health)"
fi
if docker logs "$RUNTIME" 2>&1 | grep 'run_commands LISTEN started' >/dev/null 2>&1; then
  echo "runtime: run_commands LISTEN ok"
else
  echo "WARN: run_commands LISTEN not found in logs"
fi

echo "==> schema"
docker exec "$PG" psql -U agent -d agent -v ON_ERROR_STOP=1 -Atc \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_name IN ('run_commands','runners')" \
  | grep -qx '2'
docker exec "$PG" psql -U agent -d agent -v ON_ERROR_STOP=1 -Atc \
  "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='runs' AND column_name='lease_expires_at'" \
  | grep -qx '1'
echo "schema: runners/run_commands/lease_expires_at ok"

echo "==> alembic head"
docker exec -w /app "$API" alembic current 2>&1 | grep -q '0022_phase2_events_retention'
echo "alembic: 0022 ok"

echo "==> retention deletes aged stream events"
docker exec "$PG" psql -U agent -d agent -v ON_ERROR_STOP=1 <<'SQL'
DO $$
DECLARE
  tid uuid := gen_random_uuid();
  rid uuid := gen_random_uuid();
  sid uuid;
BEGIN
  SELECT id INTO sid FROM sessions LIMIT 1;
  IF sid IS NULL THEN
    RAISE NOTICE 'no session; skip retention row insert';
    RETURN;
  END IF;
  INSERT INTO turns (id, session_id, scenario_id, status, user_input, created_at, updated_at)
  VALUES (tid, sid, 'writing', 'completed', 'retention-smoke', now() - interval '30 days', now() - interval '30 days');
  INSERT INTO runs (id, turn_id, status, created_at, updated_at)
  VALUES (rid, tid, 'completed', now() - interval '30 days', now() - interval '30 days');
  INSERT INTO turn_events (event_id, turn_id, stream_id, sequence, type, run_id, step_index, trace_id, ts, payload)
  VALUES (gen_random_uuid(), tid, tid, 1, 'thinking.delta', rid, 0, gen_random_uuid(), now() - interval '30 days', '{}'::jsonb);
END $$;
SQL
# Prefer /repo if mounted; else /app (after up-api).
docker exec -e PYTHONPATH=/app -w /tmp "$API" python - <<'PY'
import asyncio
from app.services.projection.events_retention import run_events_retention
out = asyncio.run(run_events_retention())
print("retention", out)
assert isinstance(out.get("stream"), int)
assert isinstance(out.get("structural"), int)
PY

echo "==> metrics endpoint"
TOKEN="$(docker exec "$API" printenv INTERNAL_SERVICE_TOKEN)"
METRICS="$(docker exec "$API" curl -sf -H "Authorization: Bearer ${TOKEN}" http://127.0.0.1:8000/metrics || true)"
echo "$METRICS" | grep -E 'dispatch_|turn_ttfb|event_pipeline|runner_lease|TYPE ' | head -40 || echo "(no samples yet — gauges appear after traffic)"

echo "OK pull-dispatch maturity smoke"
