from __future__ import annotations

import httpx

from app.settings import settings


class WorkspaceProxyError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def list_entries(*, path: str = ".") -> dict:
    base = settings.runtime_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{base}/internal/workspace/entries",
            params={"path": path},
            headers={"X-Internal-Token": settings.internal_service_token},
        )
    if resp.status_code >= 400:
        raise WorkspaceProxyError(resp.status_code, resp.text)
    return resp.json()


async def read_file(*, path: str) -> dict:
    base = settings.runtime_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{base}/internal/workspace/file",
            params={"path": path},
            headers={"X-Internal-Token": settings.internal_service_token},
        )
    if resp.status_code >= 400:
        raise WorkspaceProxyError(resp.status_code, resp.text)
    return resp.json()
