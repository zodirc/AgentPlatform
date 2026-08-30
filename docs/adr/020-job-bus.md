# Platform job bus (ADR-020)

## Transport

- **Redis Streams** stream name: `agent.jobs`
- Compose service: `redis` → `agent-redis`
- Env: `REDIS_URL=redis://redis:6379/0`

## Message fields

| Field | Meaning |
|-------|---------|
| `id` | Job UUID |
| `type` | e.g. `sources.index_sync` |
| `payload` | JSON object string |
| `ts` | Unix epoch seconds |

## Consumer groups

| Group | Service | Types |
|-------|---------|--------|
| `sources-retrieval` | `agent-sources-retrieval` | `sources.index_sync` |
| `sandbox` | `agent-sandbox` | (reserved) |
| `runtime` | orchestrator | (reserved; turn wake) |

## Rules

- **Sync hot path** (first token, query embed): HTTP RPC only — never this bus.
- **PG** remains business truth (runs, events, CAS). Streams are delivery only.
- Maxlen approximate trim: 100_000 entries.

## Schema note

No Alembic migration: the bus is Redis-native. Product/Ops vector tables stay
in Postgres (`source_index_meta`, pgvector) unchanged by the plane split.
