# syntax=docker/dockerfile:1

FROM python:3.11-slim AS runtime

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's/deb.debian.org/mirrors.aliyun.com/g; s/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
      sed -i 's/deb.debian.org/mirrors.aliyun.com/g; s/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app
RUN mkdir -p /data/vectorstore /data/models && chown -R app:app /data
WORKDIR /app
COPY packages/contracts/python /contracts/python
COPY services/runtime/pyproject.toml /tmp/runtime/pyproject.toml
COPY services/runtime/app /tmp/runtime/app
RUN pip install --no-cache-dir /contracts/python \
    && pip install --no-cache-dir /tmp/runtime \
    && rm -rf /tmp/runtime
COPY services/runtime/app /app/app
COPY services/runtime/app/scenarios /app/app/scenarios
COPY packages/contracts/schemas/events/payloads /app/contracts/events/payloads
COPY packages/contracts/validate_payload.py /app/packages/contracts/validate_payload.py
COPY packages/contracts/plan_suggest /app/packages/contracts/plan_suggest
COPY eval/recordings /app/eval/recordings
USER app
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://127.0.0.1:8001/health/live || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
