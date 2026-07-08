#!/bin/sh
set -e

# Sync build-time baked models into the data volume when empty (docs/03 §5.2).
if [ -d /app/models-baked ] && [ -n "$(ls -A /app/models-baked 2>/dev/null)" ]; then
  mkdir -p /data/models
  if [ -z "$(ls -A /data/models 2>/dev/null)" ]; then
    echo "entrypoint: seeding /data/models from /app/models-baked"
    cp -a /app/models-baked/. /data/models/
  fi
fi

exec "$@"
