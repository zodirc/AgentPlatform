from __future__ import annotations

from uuid import UUID

import httpx

from app.context import get_request_id
from app.middleware.request_context import REQUEST_ID_HEADER
from app.settings import settings


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

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/internal/commands/start-turn",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()

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
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/internal/commands/cancel-turn",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()

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
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/internal/commands/approve-tool-call",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()

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
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/internal/commands/deny-tool-call",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()

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
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/internal/commands/patch-accept",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()

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
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/internal/commands/patch-reject",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()

    async def sync_sources_index(self) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/internal/commands/sync-sources-index",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def verify_pass(self, *, session_id: str | None = None) -> dict:
        params = {"session_id": session_id} if session_id else None
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/internal/commands/verify-pass",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def warmup_retrieval(self, *, prefix: str = "") -> dict:
        params = {"prefix": prefix} if prefix else None
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/internal/commands/warmup-retrieval",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
