from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import HTTPException, Request

from app.services.end_user.auth import resolve_end_user
from app.services.resource.works import ensure_default_work, get_work
from app.settings import settings


class WorkspaceProxyError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def resolve_workspace_tenant(
    request: Request,
    *,
    work_id: UUID | None = None,
) -> dict[str, str]:
    """Map the calling end-user to Work scope for Sources / workspace browser."""
    user = await resolve_end_user(request)
    if user is None:
        return {}
    if work_id is not None:
        work = await get_work(work_id)
        if work is None or work.owner_user_id != user.id:
            raise HTTPException(status_code=404, detail="work not found")
    else:
        work = await ensure_default_work(user.id)
    return {
        "work_id": str(work.id),
        "work_root": work.work_root,
        "owner_user_id": str(user.id),
    }


def _tenant_params(tenant: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in tenant.items() if v}


async def list_entries(
    *,
    path: str = ".",
    tenant: dict[str, str] | None = None,
) -> dict:
    base = settings.runtime_url.rstrip("/")
    params: dict[str, str] = {"path": path, **_tenant_params(tenant or {})}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{base}/internal/workspace/entries",
            params=params,
            headers={"X-Internal-Token": settings.internal_service_token},
        )
    if resp.status_code >= 400:
        raise WorkspaceProxyError(resp.status_code, resp.text)
    return resp.json()


async def read_file(*, path: str, tenant: dict[str, str] | None = None) -> dict:
    base = settings.runtime_url.rstrip("/")
    params: dict[str, str] = {"path": path, **_tenant_params(tenant or {})}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{base}/internal/workspace/file",
            params=params,
            headers={"X-Internal-Token": settings.internal_service_token},
        )
    if resp.status_code >= 400:
        raise WorkspaceProxyError(resp.status_code, resp.text)
    return resp.json()


async def upload_source(
    *,
    filename: str,
    content: str,
    tenant: dict[str, str] | None = None,
) -> dict:
    base = settings.runtime_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/internal/workspace/sources/upload",
                params=_tenant_params(tenant or {}),
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


async def sources_index_status(
    *,
    path: str | None = None,
    tenant: dict[str, str] | None = None,
) -> dict:
    base = settings.runtime_url.rstrip("/")
    params: dict[str, str] = {**_tenant_params(tenant or {})}
    if path:
        params["path"] = path
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base}/internal/workspace/sources/index-status",
                params=params or None,
                headers={"X-Internal-Token": settings.internal_service_token},
            )
    except httpx.HTTPError as exc:
        raise WorkspaceProxyError(502, f"runtime unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise WorkspaceProxyError(resp.status_code, resp.text)
    return resp.json()


async def sync_sources(
    *,
    force: bool = False,
    tenant: dict[str, str] | None = None,
) -> dict:
    """Queue Turn-external incremental sync (IX1). Does not wait for embedding."""
    del force  # reserved; runtime always incremental
    base = settings.runtime_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/internal/workspace/sources/sync",
                params=_tenant_params(tenant or {}),
                headers={"X-Internal-Token": settings.internal_service_token},
            )
    except httpx.TimeoutException as exc:
        raise WorkspaceProxyError(
            504,
            "runtime timed out while queueing sources sync",
        ) from exc
    except httpx.HTTPError as exc:
        raise WorkspaceProxyError(502, f"runtime unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise WorkspaceProxyError(resp.status_code, resp.text)
    return resp.json()


async def delete_paths(
    *,
    paths: list[str],
    tenant: dict[str, str] | None = None,
) -> dict:
    base = settings.runtime_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/internal/workspace/entries/delete",
                params=_tenant_params(tenant or {}),
                json={"paths": paths},
                headers={"X-Internal-Token": settings.internal_service_token},
            )
    except httpx.HTTPError as exc:
        raise WorkspaceProxyError(502, f"runtime unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise WorkspaceProxyError(resp.status_code, resp.text)
    return resp.json()
