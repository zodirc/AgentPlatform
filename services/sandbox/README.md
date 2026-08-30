# Sandbox plane (ADR-020)

OS-isolated command execution (`bwrap` / landlock) outside the orchestrator.

## Contract

`POST /internal/sandbox/exec` with `{command, cwd, timeout_seconds, argv?}`.

Orchestrator routes `run_shell_command` / `run_argv_command` here when
`SANDBOX_PLANE_URL` is set and `SERVICE_ROLE` is not `sandbox`/`monolith`.

## Image

`FROM agent-platform-runtime:slim` (hash Dockerfile — **no** torch/ST).
Build: `make up-sandbox` (builds `runtime-slim` then this tag).
