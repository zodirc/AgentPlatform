# syntax=docker/dockerfile:1
# Ops Bench worker: official small suites with real ST embeddings.
# Decoupled from agent runtime Turn path — only shares the baked MiniLM
# weights from the runtime image when available (no HF download at build).

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
ARG TORCH_FIND_LINKS=https://mirrors.aliyun.com/pytorch-wheels/cpu
ARG APT_MIRROR=mirrors.aliyun.com
ARG RUNTIME_IMAGE=agent-platform-runtime:default
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

FROM ${RUNTIME_IMAGE} AS model-src

FROM python:3.11-slim AS deps
ARG PIP_INDEX_URL
ARG PIP_TRUSTED_HOST
ARG TORCH_FIND_LINKS
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
RUN pip install --no-cache-dir torch -f "${TORCH_FIND_LINKS}" \
    && pip install --no-cache-dir -r /tmp/bench-requirements.txt \
    && rm -f /tmp/bench-requirements.txt

# Reuse MiniLM weights already baked into the retrieval runtime image.
COPY --from=model-src --chown=app:app /app/models-baked /app/models-baked

FROM deps AS app
ARG EMBEDDING_MODEL
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    EMBEDDING_MODEL_DIR=/app/models-baked \
    HF_HOME=/data/models \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_OFFLINE=1
COPY services/bench/app /app/app
USER app
EXPOSE 8002
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -f http://127.0.0.1:8002/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
