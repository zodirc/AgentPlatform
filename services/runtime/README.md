# Runtime Service

Agent execution plane: TurnController, AgentEngine, tools, retrieval index.

| Item | Value |
|------|-------|
| Port | `8001` (internal only) |
| Health | `GET /health/live`, `GET /health/ready` |

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | yes | PostgreSQL |
| `INTERNAL_SERVICE_TOKEN` | yes | Validates api commands |
| `MODEL_API_KEY` | yes* | Provider key（`MODEL_MODE=stub` 时可用占位） |
| `MODEL_MODE` | no | `auto` \| `stub` \| `recorded` \| `live` |
| `WORKSPACE_ROOT` | no | Default `/workspace` |
| `DATA_DIR` | no | Default `/data` |
| `RETRIEVAL_MODE` | no | `keyword` \| `vector` \| `hybrid` |
| `INDEX_VIA_WORKER` | no | `true` 时索引经 outbox worker 异步同步 |
| `EMBEDDING_BACKEND` | no | `hash`（默认镜像）\| `sentence_transformers`（**retrieval profile 默认**） |
| `EMBEDDING_MODEL` | no | 默认 `sentence-transformers/all-MiniLM-L6-v2`（`Dockerfile.retrieval` 构建期烘焙） |
| `EMBEDDING_MODEL_DIR` | no | 运行时模型目录（默认 `/data/models`） |
| `EMBEDDING_DIMENSIONS` | no | hash 后端向量维度（默认 256） |
| `RUNTIME_RUNNER_ID` | no | HA 路由标识 |
| `STALL_*` | no | Stall watchdog（ADR-016） |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | 启用 OTel 导出 |

## Local (in container)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001
```
