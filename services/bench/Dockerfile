# syntax=docker/dockerfile:1@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
# Ops Bench worker: official small suites with real ST embeddings.
# Self-contained GTE bake (does NOT FROM agent-platform-runtime:default).
# CI smoke uses runtime-lite and omits the compose profile "bench" so gate
# never needs the heavy ST runtime image just to start api.
# Base digest pinned (deploy/base-images.env) so Hub tag moves do not bust deps.

ARG PYTHON_BASE=python:3.11-slim@sha256:a630a63cdb314e2d138a2fca3e375e319e8568346ffafac5b980f888630ac4f1
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
ARG TORCH_FIND_LINKS=https://mirrors.aliyun.com/pytorch-wheels/cpu
ARG TORCH_INDEX_URL=
ARG APT_MIRROR=mirrors.aliyun.com
ARG HF_ENDPOINT=https://hf-mirror.com
ARG EMBEDDING_MODEL=thenlper/gte-small

FROM ${PYTHON_BASE} AS model-baker
ARG EMBEDDING_MODEL
ARG PIP_INDEX_URL
ARG PIP_TRUSTED_HOST
ARG TORCH_FIND_LINKS
ARG HF_ENDPOINT
ARG APT_MIRROR
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_ENDPOINT=${HF_ENDPOINT} \
    HUGGINGFACE_HUB_ENDPOINT=${HF_ENDPOINT}

RUN set -eux; \
    if [ -n "${APT_MIRROR}" ]; then \
      if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g; s/security.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list.d/debian.sources; \
      elif [ -f /etc/apt/sources.list ]; then \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g; s/security.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list; \
      fi; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=bind,from=torch_wheel_cache,target=/tmp/torch-wheels,ro \
    --mount=type=cache,target=/root/.cache/pip \
    set -eux; \
    if ls /tmp/torch-wheels/*.whl >/dev/null 2>&1; then \
      echo "model-baker: installing torch from offline wheel cache ($(ls /tmp/torch-wheels/*.whl | wc -l) files)"; \
      pip install --no-index --find-links=/tmp/torch-wheels torch; \
    else \
      echo "model-baker: no wheel cache → torch from ${TORCH_FIND_LINKS}"; \
      pip install torch -f "${TORCH_FIND_LINKS}"; \
    fi; \
    pip install "sentence-transformers>=3.0"
# Named context `model_bake_cache` (compose additional_contexts) — not main context.
RUN --mount=type=bind,from=model_bake_cache,target=/models-bake-cache,ro \
    set -eux; \
    if find /models-bake-cache -mindepth 1 -maxdepth 1 ! -name '.keep' -print -quit | grep -q .; then \
      echo "model-baker: seeding /models-baked from deploy/model-bake-cache (offline)"; \
      mkdir -p /models-baked; \
      cp -a /models-bake-cache/. /models-baked/; \
    else \
      echo "model-baker: cache empty → download ${EMBEDDING_MODEL}"; \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}', cache_folder='/models-baked')"; \
    fi

FROM ${PYTHON_BASE} AS deps
ARG PIP_INDEX_URL
ARG PIP_TRUSTED_HOST
ARG TORCH_FIND_LINKS
ARG TORCH_INDEX_URL
ARG APT_MIRROR
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
    apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app
RUN mkdir -p /data/ops-official/data /data/ops-official/reports /data/models /app/models-baked \
    && chown -R app:app /data /app
WORKDIR /app

COPY services/bench/requirements.txt /tmp/bench-requirements.txt
# Named context `torch_wheel_cache` (compose additional_contexts).
# BuildKit pip cache mount: if deps layer is GC'd and re-RUN, wheels stay local.
# Do not use pip --no-cache-dir here — that bypasses the mount.
RUN --mount=type=bind,from=torch_wheel_cache,target=/tmp/torch-wheels,ro \
    --mount=type=cache,target=/root/.cache/pip \
    if ls /tmp/torch-wheels/*.whl >/dev/null 2>&1; then \
      echo "deps: installing torch from offline wheel cache ($(ls /tmp/torch-wheels/*.whl | wc -l) files)"; \
      pip install --no-index --find-links=/tmp/torch-wheels torch; \
    elif [ -n "${TORCH_INDEX_URL}" ]; then \
      echo "deps: installing CUDA torch from ${TORCH_INDEX_URL}"; \
      pip install --default-timeout=300 --retries=5 torch --index-url "${TORCH_INDEX_URL}"; \
    else \
      echo "deps: installing CPU torch from ${TORCH_FIND_LINKS}"; \
      pip install --default-timeout=300 --retries=5 torch -f "${TORCH_FIND_LINKS}"; \
    fi \
    && pip install -r /tmp/bench-requirements.txt \
    && rm -f /tmp/bench-requirements.txt

COPY --from=model-baker --chown=app:app /models-baked /app/models-baked

FROM deps AS app
ARG EMBEDDING_MODEL
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    EMBEDDING_MODEL_DIR=/app/models-baked \
    HF_HOME=/data/models \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_OFFLINE=1 \
    # Fallback when the live /repo bind-mount is empty (Docker Desktop/WSL glitch).
    PYTHONPATH=/app/repo-baked/scripts:/app/repo-baked/services/runtime
# Live-mount preferred at runtime; baked copy keeps model probe + script imports working
# when /repo is an empty tmpfs.
COPY scripts/official_bench_run.py /app/repo-baked/scripts/official_bench_run.py
COPY scripts/official_bench /app/repo-baked/scripts/official_bench
COPY services/bench/app /app/app
USER app
EXPOSE 8002
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -f http://127.0.0.1:8002/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
