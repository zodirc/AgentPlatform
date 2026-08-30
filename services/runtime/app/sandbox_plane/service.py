"""Sandbox-plane microservice — OS-isolated command execution (ADR-020)."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.settings import settings

logger = logging.getLogger(__name__)


def verify_internal_token(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    if not x_internal_token or not hmac.compare_digest(
        x_internal_token, settings.internal_service_token
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


class ExecBody(BaseModel):
    command: str = Field(min_length=1)
    cwd: str | None = None
    timeout_seconds: float = 60.0
    work_id: str | None = None
    argv: list[str] | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.observability.logging import configure_logging
    from app.platform_bus.streams import GROUP_SANDBOX, ensure_consumer_group

    settings.validate_production_security()
    configure_logging(service="sandbox", level=settings.log_level)
    # Ensure local sandbox exec (never recurse to remote URL).
    settings.service_role = "sandbox"
    settings.sandbox_plane_url = ""
    if (getattr(settings, "redis_url", "") or "").strip():
        try:
            await asyncio.to_thread(ensure_consumer_group, GROUP_SANDBOX)
        except Exception:
            logger.exception("sandbox bus group create failed")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Sandbox Plane", version="0.1.0", lifespan=lifespan)

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "ok", "role": "sandbox"}

    @app.get("/health/ready")
    async def health_ready() -> dict[str, Any]:
        from app.tools.core.sandbox import sandbox_status

        return {"status": "ready", "role": "sandbox", "sandbox": sandbox_status()}

    @app.post(
        "/internal/sandbox/exec",
        dependencies=[Depends(verify_internal_token)],
    )
    async def exec_command(body: ExecBody) -> dict[str, Any]:
        from app.tools.core.sandbox import run_sandboxed

        result = await run_sandboxed(
            body.command,
            cwd=body.cwd,
            timeout=body.timeout_seconds,
            argv=body.argv,
        )
        if isinstance(result, dict):
            return {"accepted": True, **result}
        return {"accepted": True, "result": result}

    return app


app = create_app()


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8004"))
    uvicorn.run(
        "app.sandbox_plane.service:app",
        host="0.0.0.0",
        port=port,
        log_level=(settings.log_level or "info").lower(),
    )


if __name__ == "__main__":
    main()
