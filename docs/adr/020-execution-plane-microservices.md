# ADR-020: Execution-plane microservices + job bus

## Status

Accepted (implementation in progress).

## Context

Runtime was a fat execution monolith: Turn orchestration, embedding weights,
sources sync, model egress, and sandbox shared one process. That couples
memory (gte-small / bge-m3 × replicas), failure domains, and scale axes.
Control plane (API + PG CAS + NOTIFY) is already separate.

## Decision

Deploy the execution plane as microservices with a Redis Streams job bus:

| Service | Owns | Does not own |
|---------|------|----------------|
| **api** | Admission, CAS, SSE, outbox → bus | Embed weights, sandbox CPU |
| **runtime** (orchestrator) | Claim, Engine, tools schedule, writing | ST weights, startup sync, heavy sandbox |
| **sources-retrieval** | Single embedding pool, sync/watch, query embed | Turns |
| **model-gateway** | Upstream LLM stream, timeouts, egress | Tools / embed |
| **sandbox** | bwrap/landlock command execution | Model / embed |
| **ast-indexer** | AST jobs (existing) | — |

**Sync path (rate red line):** orchestrator → HTTP → retrieval embed / model-gateway.
Never put first-token or query-embed on the bus.

**Async path:** Redis Streams (`agent.jobs`) for `sources.index_sync`, sandbox
jobs, and turn wake hints. PostgreSQL remains business truth (runs, events, CAS).
See [020-job-bus.md](./020-job-bus.md).

**Memory:** embedding weights load only in `sources-retrieval` (one pool).
Orchestrator uses `EMBEDDING_BACKEND=remote`.

**Companion surfaces (required):**
- Compose: `deploy/compose/planes.yml` (default via Makefile `COMPOSE`)
- Release console / `paths.env` / `plan.py`: modules `sources_retrieval`,
  `model_gateway`, `sandbox`; embedding actions → `up-sources-retrieval`
- Ops overview expected containers + plane status; eval recreate includes
  `sources-retrieval` + `planes.yml`
- Service images: `services/{sources-retrieval,model-gateway,sandbox}/Dockerfile`
  (retrieval ← `runtime:default` ST bake; gateway/sandbox ← `runtime:slim` hash Dockerfile)
- Live cutover: orchestrator → remote embed / model-gateway NDJSON /
  sandbox HTTP exec (stub/recorded/monolith stay local)

## Consequences

- Compose topology and `SERVICE_ROLE` / URLs are the source of truth for scale-out.
- GPU overlay attaches to `sources-retrieval` (and bench), not orchestrator replicas.
- HA scales orchestrator without copying bge-m3.
- Physical package extract (separate Python projects) can follow; identity +
  deploy modules are already split.
