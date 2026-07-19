# syntax=docker/dockerfile:1

FROM python:3.11-slim AS runtime

# China-friendly mirrors (override at build time if needed)
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
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health/live || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
