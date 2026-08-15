# syntax=docker/dockerfile:1@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
# Lightweight runtime (hash embedding). BR2 (docs/38): deps/app stages so
# app/** changes do not re-run pip.
# Base digest pinned (deploy/base-images.env) so Hub tag moves do not bust deps.

ARG PYTHON_BASE=python:3.11-slim@sha256:a630a63cdb314e2d138a2fca3e375e319e8568346ffafac5b980f888630ac4f1
FROM ${PYTHON_BASE} AS deps

# Defaults favor China local builds. CI / GitHub Actions override via compose
# build-args (see scripts/proof_compose_env.sh).
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
ARG APT_MIRROR=mirrors.aliyun.com
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN set -eux; \
    if [ -n "${APT_MIRROR}" ]; then \
      if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g; s/security.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list.d/debian.sources; \
      elif [ -f /etc/apt/sources.list ]; then \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g; s/security.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list; \
      fi; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends curl bubblewrap \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app
RUN mkdir -p /data/vectorstore /data/models && chown -R app:app /data
WORKDIR /app

COPY packages/contracts/python /contracts/python
COPY services/runtime/pyproject.toml /tmp/runtime/pyproject.toml
# BuildKit pip cache mount: if deps layer is GC'd and re-RUN, wheels stay local.
# Do not use pip --no-cache-dir here — that bypasses the mount.
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir -p /tmp/runtime/app && printf '%s\n' '# deps-layer stub' > /tmp/runtime/app/__init__.py \
    && pip install /contracts/python \
    && pip install "/tmp/runtime[structural]" \
    && rm -rf /tmp/runtime

# Bake tree-sitter grammars at build time (no runtime GitHub download / GIL hang).
# Prefer offline seed from named context `ts_grammar_cache`; else prefetch().
COPY services/runtime/scripts/bake_ts_grammars.py /tmp/bake_ts_grammars.py
RUN --mount=type=bind,from=ts_grammar_cache,target=/tmp/ts-grammar-seed,ro \
    mkdir -p /home/app/.cache \
    && chown -R app:app /home/app \
    && su -s /bin/bash app -c 'HOME=/home/app TS_GRAMMAR_SEED_DIR=/tmp/ts-grammar-seed python -u /tmp/bake_ts_grammars.py' \
    && rm -f /tmp/bake_ts_grammars.py

FROM deps AS app
COPY services/runtime/app /app/app
COPY packages/contracts/schemas/events/payloads /app/contracts/events/payloads
COPY packages/contracts/validate_payload.py /app/packages/contracts/validate_payload.py
COPY packages/contracts/plan_suggest /app/packages/contracts/plan_suggest
COPY eval/recordings /app/eval/recordings
USER app
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://127.0.0.1:8001/health/live || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
