# syntax=docker/dockerfile:1

FROM python:3.11-slim AS runtime

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
      curl ca-certificates docker-cli docker-compose \
    && rm -rf /var/lib/apt/lists/* \
    && docker --version \
    && docker-compose version

RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY packages/contracts/python /contracts/python
COPY services/api/pyproject.toml /tmp/api/pyproject.toml
COPY services/api/app /tmp/api/app
RUN pip install --no-cache-dir /contracts/python \
    && pip install --no-cache-dir /tmp/api \
    && rm -rf /tmp/api
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
