# Sources retrieval plane (ADR-020)

Sole owner of embedding weights (`gte-small` / `bge-m3`), sources sync/watch,
query embed HTTP (`POST /internal/embed`), and Redis Streams consumer for
`sources.index_sync`.

## Image

```text
services/sources-retrieval/Dockerfile
  FROM agent-platform-runtime:default
  → agent-platform-sources-retrieval:latest
```

`make up-sources-retrieval` builds the runtime bake first, then this thin image.

## Code

Shared library: `services/runtime/app/retrieval/` + `platform_bus/`.
Entrypoint: `app.retrieval.service:app`.
