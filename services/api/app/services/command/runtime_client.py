"""Runtime 服务内部 HTTP 客户端（``X-Internal-Token`` + request_id 透传）。

按 base_url 复用 ``httpx.AsyncClient``；封装 start/cancel turn、工具审批、
索引同步、writing/verify 等 ``/internal/*`` 命令与查询。
"""

from __future__ import annotations

from uuid import UUID

import httpx

from app.context import get_request_id
from app.middleware.request_context import REQUEST_ID_HEADER
from app.settings import settings


_clients: dict[str, httpx.AsyncClient] = {}


async def close_runtime_clients() -> None:
    """关闭进程内全部 runtime HTTP 连接（API shutdown 钩子）。

    参数:
        无。

    返回:
        无。
    """
    clients = list(_clients.values())
    _clients.clear()
    for client in clients:
        await client.aclose()


class RuntimeClient:
    """指向单个 runtime replica 的异步命令/查询客户端。"""

    def __init__(self, *, base_url: str | None = None) -> None:
        """构造客户端。

        参数:
            base_url: Runtime 根 URL；默认 ``settings.runtime_url``。
        """
        self.base_url = (base_url or settings.runtime_url).rstrip("/")
        self._base_headers = {"X-Internal-Token": settings.internal_service_token}

    def _headers(self) -> dict[str, str]:
        """合并内部 token 与当前 request_id 头。"""
        headers = dict(self._base_headers)
        request_id = get_request_id()
        if request_id is not None:
            headers[REQUEST_ID_HEADER] = str(request_id)
        return headers

    def _client(self) -> httpx.AsyncClient:
        """按 base_url 获取或创建共享 AsyncClient。"""
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
        """POST 内部路径并在非 2xx 时 ``raise_for_status``。"""
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
        """GET 内部路径并在非 2xx 时 ``raise_for_status``。"""
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
        """向 runtime 下发 StartTurn 命令。

        参数:
            turn_id, run_id, session_id, scenario_id, message, trace_id: 命令主键与上下文。
            client_request_id: API 侧幂等键（可选）。
            plan_phase: Plan 轨道阶段（可选）。
            work_id, work_root, owner_user_id: 工作区归属（可选）。
            visibility_seed: 是否种子可见性索引。
            model_mode, model_override: 仅 ops_eval 时透传模型覆盖。
            ops_eval: Ops 评测模式标记。

        返回:
            无。

        异常:
            httpx.HTTPStatusError: runtime 返回错误状态。
        """
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
        timeout: float = 30.0,
    ) -> None:
        """向 runtime 下发 CancelTurn。

        参数:
            turn_id, run_id, trace_id: 命令关联 id。
            reason: 取消原因字符串。
            force: 是否强制终止。
            timeout: HTTP 超时秒数。

        异常:
            httpx.HTTPStatusError: runtime 拒绝或不可达。
        """
        payload = {
            "turn_id": str(turn_id),
            "run_id": str(run_id),
            "trace_id": str(trace_id),
            "reason": reason,
            "force": force,
        }
        await self._post(
            "/internal/commands/cancel-turn", timeout=float(timeout), json=payload
        )

    async def approve_tool_call(
        self,
        *,
        turn_id: UUID,
        run_id: UUID,
        tool_call_id: str,
        trace_id: UUID,
    ) -> None:
        """批准 waiting_approval 状态下的工具调用。"""
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
        """拒绝 waiting_approval 状态下的工具调用。"""
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
        """接受 runtime 提出的 patch 提议。"""
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
        """拒绝 patch 提议。"""
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
        """触发 sources 索引同步；可选阻塞至完成。

        参数:
            work_id, work_root, owner_user_id: 工作区作用域。
            wait: 两者均提供时是否等待完成。
            timeout: HTTP 超时。

        返回:
            runtime JSON 响应 dict。
        """
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
        """中止 runtime 上进行中或排队的 sources 索引同步。

        返回:
            runtime JSON 响应 dict。
        """
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
        """轮询 ingestion 进度（workspace sync_progress.json）。

        返回:
            含进度字段的 dict。
        """
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
        """触发离线 verify-pass（exports/drafts 校验）。

        参数:
            session_id: 可选限定会话。

        返回:
            报告 dict。
        """
        params = {"session_id": session_id} if session_id else None
        resp = await self._post(
            "/internal/commands/verify-pass", timeout=60.0, params=params
        )
        return resp.json()

    async def warmup_retrieval(self, *, prefix: str = "") -> dict:
        """预热 retrieval 索引/cache。

        参数:
            prefix: 可选路径前缀过滤。

        返回:
            runtime 响应 dict。
        """
        params = {"prefix": prefix} if prefix else None
        resp = await self._post(
            "/internal/commands/warmup-retrieval", timeout=15.0, params=params
        )
        return resp.json()

    async def writing_exemplars(self, *, timeout: float = 15.0) -> dict:
        """读取 writing 范例库列表。

        返回:
            exemplars JSON dict。
        """
        resp = await self._get("/internal/writing/exemplars", timeout=timeout)
        return resp.json()

    async def writing_score(
        self,
        *,
        text: str | None = None,
        fragment: str | None = None,
        slug: str | None = None,
        prefs: dict | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """调用 runtime writing 打分接口。

        参数:
            text, fragment, slug: 待评内容与片段/范例 slug（互斥组合由 runtime 校验）。
            prefs: 用户写作偏好权重。
            timeout: HTTP 超时。

        返回:
            打分结果 dict。
        """
        payload: dict = {}
        if text is not None:
            payload["text"] = text
        if fragment is not None:
            payload["fragment"] = fragment
        if slug is not None:
            payload["slug"] = slug
        if prefs is not None:
            payload["prefs"] = prefs
        resp = await self._post("/internal/writing/score", timeout=timeout, json=payload)
        return resp.json()

    async def writing_surface(self, *, timeout: float = 15.0) -> dict:
        """读取章级表面层 sidecar（只观测）。"""
        resp = await self._get("/internal/writing/surface", timeout=timeout)
        return resp.json()
