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
| `MODEL_API_KEY` | yes* | Provider key（live 时；也可 Web 配置供应商） |
| `MODEL_MODE` | no | 默认 compose：`live`；`auto` \| `stub` \| `recorded` \| `live` |
| `WORKSPACE_ROOT` | no | Default `/workspace` |
| `DATA_DIR` | no | Default `/data` |
| `RETRIEVAL_MODE` | no | `keyword` \| `vector` \| `hybrid`（默认 hybrid） |
| `RETRIEVAL_BACKEND` | no | `pgvector`（默认）\| `json` |
| `INDEX_VIA_WORKER` | no | `true` 时索引经 outbox → Redis Streams → sources-retrieval |
| `SERVICE_ROLE` | no | `orchestrator`（默认 compose）\| `monolith`（测试）\| `retrieval` |
| `SOURCES_RETRIEVAL_URL` | no | 远程 embed / 同步平面（ADR-020） |
| `REDIS_URL` | no | 平台任务总线 `agent.jobs` |
| `EMBEDDING_BACKEND` | no | 编排：`remote`；检索服务：`sentence_transformers`；lite：`hash` |
| `EMBEDDING_MODEL` | no | 默认 `thenlper/gte-small`（仅 retrieval 服务加载） |
| `EMBEDDING_MODEL_DIR` | no | 运行时模型目录（默认 `/data/models`） |
| `EMBEDDING_DIMENSIONS` | no | hash 后端向量维度（默认 256） |
| `RUNTIME_RUNNER_ID` | no | HA 路由标识 |
| `STALL_*` | no | Stall watchdog（ADR-016） |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | 启用 OTel 导出 |

## Local (in container)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001
```
