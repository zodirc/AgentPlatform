# syntax=docker/dockerfile:1@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
# BR1 (docs/38): deps stage installs pip from pyproject + stub package only;
# app stage COPY real sources. Changing app/** must not re-run pip.
# Base digest pinned (deploy/base-images.env) so Hub tag moves do not bust deps.

ARG PYTHON_BASE=python:3.11-slim@sha256:a630a63cdb314e2d138a2fca3e375e319e8568346ffafac5b980f888630ac4f1
FROM ${PYTHON_BASE} AS deps

# China-friendly defaults; override at build time for CI (see proof_compose_env.sh).
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
    apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates docker-cli docker-compose git \
    && rm -rf /var/lib/apt/lists/* \
    && docker --version \
    && docker-compose version

RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY packages/contracts/python /contracts/python
COPY services/api/pyproject.toml /tmp/api/pyproject.toml
# Minimal stub so hatchling can build the wheel without copying real app sources
# into the deps layer input (docs/38 §3.3).
# BuildKit cache mount: if deps layer is GC'd and re-RUN, wheels stay local (no mirror re-fetch).
# Do not use pip --no-cache-dir here — that bypasses the mount.
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir -p /tmp/api/app && printf '%s\n' '# deps-layer stub' > /tmp/api/app/__init__.py \
    && pip install /contracts/python \
    && pip install /tmp/api \
    && pip install 'datasets>=2.14.0' 'huggingface_hub>=0.20.0' \
    && pip install 'swebench>=2.1.0,<5' \
    && rm -rf /tmp/api

FROM deps AS app
COPY services/api/app /app/app
COPY services/api/alembic.ini /app/alembic.ini
COPY services/api/alembic /app/alembic
COPY packages/contracts/schemas/ddl /app/contracts/ddl
COPY eval/golden /app/eval/golden
# Ops Eval's optional docker.sock overlay may require host root/docker group access.
# Standard production compose does not mount the socket.
USER root
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health/live || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
