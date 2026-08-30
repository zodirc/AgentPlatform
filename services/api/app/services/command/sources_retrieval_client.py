"""HTTP client for sources-retrieval (ADR-020 retrieval plane)."""

from __future__ import annotations

from uuid import UUID

import httpx

from app.context import get_request_id
from app.middleware.request_context import REQUEST_ID_HEADER
from app.settings import settings

_clients: dict[str, httpx.AsyncClient] = {}


class SourcesRetrievalClient:
    """Commands against ``sources-retrieval`` (sync / cancel / status)."""

    def __init__(self, *, base_url: str | None = None) -> None:
        self.base_url = (
            base_url or settings.sources_retrieval_url or settings.runtime_url
        ).rstrip("/")
        self._base_headers = {"X-Internal-Token": settings.internal_service_token}

    def _headers(self) -> dict[str, str]:
        headers = dict(self._base_headers)
        request_id = get_request_id()
        if request_id is not None:
            headers[REQUEST_ID_HEADER] = str(request_id)
        return headers

    def _client(self) -> httpx.AsyncClient:
        client = _clients.get(self.base_url)
        if client is None:
            client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
            _clients[self.base_url] = client
        return client

    async def sync_sources_index(
        self,
        *,
        work_id: UUID | None = None,
        work_root: str | None = None,
        owner_user_id: UUID | None = None,
        wait: bool = True,
        timeout: float = 60.0,
    ) -> dict:
        params: dict[str, str] = {}
        if work_id is not None:
            params["work_id"] = str(work_id)
        if work_root is not None:
            params["work_root"] = work_root
        if owner_user_id is not None:
            params["owner_user_id"] = str(owner_user_id)
        if work_id is not None and work_root is not None:
            params["wait"] = "true" if wait else "false"
        response = await self._client().post(
            "/internal/commands/sync-sources-index",
            params=params or None,
            headers=self._headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    async def cancel_sources_index(self, *, timeout: float = 15.0) -> dict:
        response = await self._client().post(
            "/internal/commands/cancel-sources-index",
            headers=self._headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    async def sources_index_status(
        self,
        *,
        work_id: UUID | None = None,
        work_root: str | None = None,
        owner_user_id: UUID | None = None,
        timeout: float = 15.0,
    ) -> dict:
        params: dict[str, str] = {}
        if work_id is not None:
            params["work_id"] = str(work_id)
        if work_root is not None:
            params["work_root"] = work_root
        if owner_user_id is not None:
            params["owner_user_id"] = str(owner_user_id)
        response = await self._client().get(
            "/internal/workspace/sources/index-status",
            params=params or None,
            headers=self._headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
