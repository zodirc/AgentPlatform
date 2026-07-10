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


async def upload_source(*, filename: str, content: str) -> dict:
    base = settings.runtime_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/internal/workspace/sources/upload",
                json={"filename": filename, "content": content},
                headers={"X-Internal-Token": settings.internal_service_token},
            )
    except httpx.TimeoutException as exc:
        raise WorkspaceProxyError(
            504,
            "runtime timed out while saving source (index may still be rebuilding)",
        ) from exc
    except httpx.HTTPError as exc:
        raise WorkspaceProxyError(502, f"runtime unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise WorkspaceProxyError(resp.status_code, resp.text)
    return resp.json()


async def sources_index_status(*, path: str | None = None) -> dict:
    base = settings.runtime_url.rstrip("/")
    params = {"path": path} if path else None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base}/internal/workspace/sources/index-status",
                params=params,
                headers={"X-Internal-Token": settings.internal_service_token},
            )
    except httpx.HTTPError as exc:
        raise WorkspaceProxyError(502, f"runtime unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise WorkspaceProxyError(resp.status_code, resp.text)
    return resp.json()
