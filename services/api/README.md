# API Service

HTTP control plane: sessions, turns, SSE, projection, optional outbox worker.

| Item | Value |
|------|-------|
| Port | `8000` |
| Health | `GET /health/live`, `GET /health/ready` |

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | yes | PostgreSQL connection string |
| `RUNTIME_URL` | yes | Runtime base URL (default `http://runtime:8001`) |
| `RUNTIME_URL_MAP` | no | HA 多副本 JSON 路由表 |
| `INTERNAL_SERVICE_TOKEN` | yes | Token for api → runtime calls |
| `AUTH_ENABLED` | no | Enable HTTP Basic auth (default `false`) |
| `ADMIN_PASSWORD` | if auth | Basic auth password (user `admin`) |
| `WORKER_MODE` | no | `inline`（默认）\| `outbox`（配合 `compose/queue.yml`） |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | 启用 OTel 导出 |

> outbox 队列基于 PostgreSQL `outbox_jobs` 表（`FOR UPDATE SKIP LOCKED`），不依赖 Redis。

## Local (in container)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
python -m app.db.migrate
```
