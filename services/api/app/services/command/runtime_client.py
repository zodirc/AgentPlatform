from __future__ import annotations

from uuid import UUID

import httpx

from app.context import get_request_id
from app.middleware.request_context import REQUEST_ID_HEADER
from app.settings import settings


_clients: dict[str, httpx.AsyncClient] = {}


async def close_runtime_clients() -> None:
    """Close process-wide runtime connections during API shutdown."""
    clients = list(_clients.values())
    _clients.clear()
    for client in clients:
        await client.aclose()


class RuntimeClient:
    def __init__(self, *, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.runtime_url).rstrip("/")
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

    async def _post(
        self,
        path: str,
        *,
        timeout: float,
        json: dict | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        response = await self._client().post(
            path,
            json=json,
            params=params,
            headers=self._headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        return response

    async def _get(
        self,
        path: str,
        *,
        timeout: float,
        params: dict | None = None,
    ) -> httpx.Response:
        response = await self._client().get(
            path,
            params=params,
            headers=self._headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        return response

    async def start_turn(
        self,
        *,
        turn_id: UUID,
        run_id: UUID,
        session_id: UUID,
        scenario_id: str,
        message: str,
        client_request_id: UUID | None,
        trace_id: UUID,
        plan_phase: str | None = None,
        work_id: UUID | None = None,
        work_root: str | None = None,
        owner_user_id: UUID | None = None,
        visibility_seed: bool = True,
        model_mode: str | None = None,
        model_override: dict | None = None,
        ops_eval: bool = False,
    ) -> None:
        payload = {
            "turn_id": str(turn_id),
            "run_id": str(run_id),
            "session_id": str(session_id),
            "scenario_id": scenario_id,
            "message": message,
            "trace_id": str(trace_id),
            "ops_eval": bool(ops_eval),
            "visibility_seed": bool(visibility_seed),
        }
        if client_request_id is not None:
            payload["client_request_id"] = str(client_request_id)
        if plan_phase is not None:
            payload["plan_phase"] = plan_phase
        if work_id is not None:
            payload["work_id"] = str(work_id)
        if work_root is not None:
            payload["work_root"] = work_root
        if owner_user_id is not None:
            payload["owner_user_id"] = str(owner_user_id)
        if ops_eval and model_mode is not None:
            payload["model_mode"] = model_mode
        if ops_eval and model_override is not None:
            payload["model_override"] = model_override

        await self._post("/internal/commands/start-turn", timeout=30.0, json=payload)

    async def cancel_turn(
        self,
        *,
        turn_id: UUID,
        run_id: UUID,
        trace_id: UUID,
        reason: str = "user_requested",
        force: bool = False,
    ) -> None:
        payload = {
            "turn_id": str(turn_id),
            "run_id": str(run_id),
            "trace_id": str(trace_id),
            "reason": reason,
            "force": force,
        }
        await self._post("/internal/commands/cancel-turn", timeout=30.0, json=payload)

    async def approve_tool_call(
        self,
        *,
        turn_id: UUID,
        run_id: UUID,
        tool_call_id: str,
        trace_id: UUID,
    ) -> None:
        payload = {
            "turn_id": str(turn_id),
            "run_id": str(run_id),
            "tool_call_id": tool_call_id,
            "trace_id": str(trace_id),
        }
        await self._post("/internal/commands/approve-tool-call", timeout=30.0, json=payload)

    async def deny_tool_call(
        self,
        *,
        turn_id: UUID,
        run_id: UUID,
        tool_call_id: str,
        trace_id: UUID,
        reason: str = "user_denied",
    ) -> None:
        payload = {
            "turn_id": str(turn_id),
            "run_id": str(run_id),
            "tool_call_id": tool_call_id,
            "trace_id": str(trace_id),
            "reason": reason,
        }
        await self._post("/internal/commands/deny-tool-call", timeout=30.0, json=payload)

    async def accept_patch(
        self,
        *,
        turn_id: UUID,
        run_id: UUID,
        patch_id: str,
        trace_id: UUID,
    ) -> None:
        payload = {
            "turn_id": str(turn_id),
            "run_id": str(run_id),
            "patch_id": patch_id,
            "trace_id": str(trace_id),
        }
        await self._post("/internal/commands/patch-accept", timeout=30.0, json=payload)

    async def reject_patch(
        self,
        *,
        turn_id: UUID,
        run_id: UUID,
        patch_id: str,
        trace_id: UUID,
        reason: str = "user_rejected",
    ) -> None:
        payload = {
            "turn_id": str(turn_id),
            "run_id": str(run_id),
            "patch_id": patch_id,
            "trace_id": str(trace_id),
            "reason": reason,
        }
        await self._post("/internal/commands/patch-reject", timeout=30.0, json=payload)

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
        resp = await self._post(
            "/internal/commands/sync-sources-index",
            timeout=timeout,
            params=params or None,
        )
        return resp.json()

    async def cancel_sources_index(self, *, timeout: float = 15.0) -> dict:
        """Abort in-flight / queued sources index sync on runtime."""
        resp = await self._post(
            "/internal/commands/cancel-sources-index",
            timeout=timeout,
        )
        return resp.json()

    async def sources_index_status(
        self,
        *,
        work_id: UUID | None = None,
        work_root: str | None = None,
        owner_user_id: UUID | None = None,
        timeout: float = 15.0,
    ) -> dict:
        """Poll runtime ingestion progress (sync_progress.json via workspace API)."""
        params: dict[str, str] = {}
        if work_id is not None:
            params["work_id"] = str(work_id)
        if work_root is not None:
            params["work_root"] = work_root
        if owner_user_id is not None:
            params["owner_user_id"] = str(owner_user_id)
        resp = await self._get(
            "/internal/workspace/sources/index-status",
            timeout=timeout,
            params=params or None,
        )
        return resp.json()

    async def verify_pass(self, *, session_id: str | None = None) -> dict:
        params = {"session_id": session_id} if session_id else None
        resp = await self._post(
            "/internal/commands/verify-pass", timeout=60.0, params=params
        )
        return resp.json()

    async def warmup_retrieval(self, *, prefix: str = "") -> dict:
        params = {"prefix": prefix} if prefix else None
        resp = await self._post(
            "/internal/commands/warmup-retrieval", timeout=15.0, params=params
        )
        return resp.json()
