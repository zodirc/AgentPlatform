#!/usr/bin/env bash
# F4 (docs/35): minimal backup — pg_dump + agent_data tarball.
# Usage: ./deploy/backup.sh [output-dir]   (default: deploy/backups)
# Restore:
#   pg_restore  : docker exec -i agent-postgres pg_restore -U agent -d agent --clean < agent.dump
#   agent_data  : docker run --rm -v deploy_agent_data:/data -v "$PWD":/backup alpine \
#                   tar xzf /backup/agent_data.tar.gz -C /data
set -euo pipefail

cd "$(dirname "$0")/.."

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_ROOT="${1:-deploy/backups}"
OUT_DIR="$OUT_ROOT/$STAMP"
mkdir -p "$OUT_DIR"

PG_CONTAINER="${PG_CONTAINER:-agent-postgres}"
PG_USER="${POSTGRES_USER:-agent}"
PG_DB="${POSTGRES_DB:-agent}"
DATA_VOLUME="${DATA_VOLUME:-deploy_agent_data}"

echo "==> pg_dump $PG_DB from $PG_CONTAINER"
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" -Fc > "$OUT_DIR/agent.dump"

echo "==> archiving volume $DATA_VOLUME"
OUT_ABS="$(cd "$OUT_DIR" && pwd)"
docker run --rm \
  -v "$DATA_VOLUME":/data:ro \
  -v "$OUT_ABS":/backup \
  alpine tar czf /backup/agent_data.tar.gz -C /data .

# Keep the newest 7 backups.
KEEP="${BACKUP_KEEP:-7}"
if [ -d "$OUT_ROOT" ]; then
  ls -1d "$OUT_ROOT"/*/ 2>/dev/null | sort | head -n -"$KEEP" | xargs -r rm -rf
fi

echo "==> backup written to $OUT_DIR"
ls -lh "$OUT_DIR"
