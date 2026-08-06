#!/bin/sh
set -e

# Sync build-time baked models into the data volume.
# Re-seed when empty, stamp mismatch, OR requested model folder missing
# (avoids stamp=bge-m3 with leftover gte-large weights).
if [ -d /app/models-baked ] && [ -n "$(ls -A /app/models-baked 2>/dev/null)" ]; then
  mkdir -p /data/models
  stamp=/data/models/.baked_embedding_model
  expected="${EMBEDDING_MODEL:-thenlper/gte-small}"
  cache_name="models--$(echo "$expected" | sed 's|/|--|g')"
  need_seed=0
  if [ -z "$(ls -A /data/models 2>/dev/null | grep -v '^\.baked_embedding_model$' || true)" ]; then
    need_seed=1
  elif [ ! -f "$stamp" ] || [ "$(cat "$stamp" 2>/dev/null)" != "$expected" ]; then
    need_seed=1
  elif [ ! -d "/data/models/${cache_name}" ]; then
    need_seed=1
  fi
  if [ "$need_seed" = "1" ]; then
    echo "entrypoint: seeding /data/models from /app/models-baked (model=${expected})"
    # Drop prior bake (e.g. MiniLM/gte-large) so query/index cannot mix spaces.
    find /data/models -mindepth 1 -maxdepth 1 ! -name '.baked_embedding_model' -exec rm -rf {} +
    cp -a /app/models-baked/. /data/models/
    printf '%s\n' "$expected" >"$stamp"
  fi
fi

exec "$@"
