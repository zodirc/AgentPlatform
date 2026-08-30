# Model gateway plane (ADR-020)

LLM egress outside the Turn orchestrator.

## Contract

`POST /internal/v1/complete` — NDJSON stream:

- `{"t":"delta","text":"..."}`
- `{"t":"activity","kind":"...","text":"..."}`
- `{"t":"final",...}` / `{"t":"error",...}`

Orchestrator (`SERVICE_ROLE=orchestrator` + `MODEL_GATEWAY_URL`) uses
`RemoteModelProvider` for **live** mode; stub/recorded stay local.

## Image

`FROM agent-platform-runtime:slim` (hash Dockerfile — **no** torch/ST).
Build: `make up-model-gateway` (builds `runtime-slim` then this tag).
