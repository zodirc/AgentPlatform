# syntax=docker/dockerfile:1

FROM python:3.11-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl \
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
