"""宿主回合运行。直接调用 AgentEngine，不经过 LangGraph 或数据库。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

from app.engine.agent_engine import AgentEngine
from app.engine.state import TurnState, user_message
from app.model.gateway import ModelGateway
from app.model.openai_provider import OpenAIProvider, openai_chat_completions_url
from app.model.recorded_provider import RecordedModelProvider
from app.ports import (
    bind_buffered_writer,
    bind_embedder,
    bind_evaluation_store,
    bind_pool_factory,
    bind_prefs_source,
    bind_model_envelope,
    bind_raw_snapshot,
    bind_summary_store,
    reset_buffered_writer,
    reset_embedder,
    reset_evaluation_store,
    reset_model_envelope,
    reset_pool_factory,
    reset_prefs_source,
    reset_raw_snapshot,
    reset_summary_store,
)
from app.scenarios.registry import ScenarioRegistry
from app.settings import settings
from app.tenant_context import bind_tenant_context, reset_tenant_context
from app.tools.writing_registry import build_writing_registry
from app.writing.turn_assembly import assemble_writing_turn
from app.writing_host.errors import HostError, classify_model_error
from app.writing_host.files import (
    FileCheckpointStore,
    FileEvaluationStore,
    FileEventLog,
    NullSummaryStore,
    PlatformPrefsSource,
    ensure_sidecar_format,
)
from app.writing_host.protocol import (
    HostEvent,
    ModelConfig,
    ProbeCheck,
    ProbeReport,
    TurnBudget,
    TurnResult,
)

_CANCELLED: set[str] = set()


def cancel_turn(turn_id: str) -> None:
    _CANCELLED.add(str(turn_id))


def _host_ids(work_root: Path) -> tuple[UUID, UUID]:
    path = work_root / ".agent" / "host.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        return UUID(data["work_id"]), UUID(data["owner_user_id"])
    work_id, owner = uuid4(), uuid4()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"work_id": str(work_id), "owner_user_id": str(owner)}),
        encoding="utf-8",
    )
    return work_id, owner


async def _no_database():
    raise RuntimeError("writing host has no database")


def _map_engine_event(event_type: str, payload: dict[str, Any]) -> HostEvent | None:
    if event_type == "step.started":
        return HostEvent("step_started", {"step_index": payload.get("step_index")})
    if event_type == "tool.completed":
        changed = [
            str(payload[key])
            for key in ("path", "new_path", "output_path")
            if payload.get(key)
        ]
        return HostEvent(
            "tool_finished",
            {
                "name": payload.get("tool_name") or "",
                "summary": payload.get("summary") or "",
                "changed_files": changed,
            },
        )
    if event_type == "usage.reported":
        return HostEvent(
            "usage",
            {
                "input_tokens": payload.get("step_input_tokens", payload.get("input_tokens", 0)),
                "output_tokens": payload.get("step_output_tokens", payload.get("output_tokens", 0)),
                "cache_read_input_tokens": payload.get("cache_read_input_tokens", 0),
                "cache_creation_input_tokens": payload.get("cache_creation_input_tokens", 0),
            },
        )
    return None


async def _run(
    *,
    work_root: Path,
    message: str | None,
    model: ModelConfig,
    budget: TurnBudget,
    plan_phase: str | None,
    on_event,
    recording: str | None,
    resume_turn_id: str | None,
    host: bool,
) -> TurnResult:
    root = Path(work_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    ensure_sidecar_format(root)
    work_id, owner = _host_ids(root)
    previous_root = settings.workspace_root
    settings.workspace_root = str(root)
    tenant = bind_tenant_context(
        work_root=str(root),
        work_id=work_id,
        owner_user_id=owner,
        visibility_seed=True,
    )
    class _LiveWriter:
        def start_stream_liveness(self, step_index: int) -> None:
            del step_index

        async def stop_stream_liveness(self) -> None:
            return None

    eval_token = bind_evaluation_store(FileEvaluationStore(root))
    buffered_token = bind_buffered_writer(lambda _turn_id: _LiveWriter())
    prefs_token = bind_prefs_source(PlatformPrefsSource())
    embed_token = bind_embedder(None)
    pool_token = bind_pool_factory(_no_database)
    summary_token = bind_summary_store(NullSummaryStore())

    async def _noop(**_kwargs):
        return None

    raw_token = bind_raw_snapshot(_noop)
    envelope_token = bind_model_envelope(_noop)
    previous_recordings = settings.recordings_dir
    recordings_dir = (model.capabilities or {}).get("recordings_dir")
    if recordings_dir:
        settings.recordings_dir = str(recordings_dir)
    emit = on_event or (lambda _event: None)
    try:
        store = FileCheckpointStore(root)
        if resume_turn_id:
            state, _interrupt, _step = store.load(resume_turn_id)
            profile = ScenarioRegistry.get(state.scenario_id or "writing")
        else:
            profile = ScenarioRegistry.get("writing")
            turn_id = uuid4()
            state = TurnState(
                turn_id=turn_id,
                session_id=uuid4(),
                run_id=uuid4(),
                trace_id=uuid4(),
                scenario_id="writing",
                max_steps=budget.max_steps or profile.max_steps,
                messages=[user_message(message or "")],
                turn_user_text=message or "",
            )
        state.max_steps = budget.max_steps or state.max_steps
        state.max_input_tokens = int(budget.max_input_tokens or 0)
        state.max_output_tokens = int(budget.max_output_tokens or 0)
        state.turn_token_budget = 0
        registry = build_writing_registry(host=host)
        assembly = assemble_writing_turn(
            profile=profile,
            registry=registry,
            message=message if message is not None else state.turn_user_text,
            plan_phase=plan_phase if plan_phase is not None else state.plan_phase,
            seed_visible=True,
        )
        if resume_turn_id is None:
            state.volatile_context = assembly.volatile_context
        log = FileEventLog(root, str(state.turn_id))
        _CANCELLED.discard(str(state.turn_id))

        async def write_event(**kwargs: Any) -> None:
            event_type = str(kwargs.get("event_type") or "")
            payload = kwargs.get("payload") if isinstance(kwargs.get("payload"), dict) else {}
            await log.append({"event_type": event_type, "payload": payload})
            mapped = _map_engine_event(event_type, payload)
            if mapped is not None:
                emit(mapped)

        async def on_step_checkpoint(current: TurnState, step_index: int) -> None:
            await store.save(state=current, step_index=step_index)
            emit(
                HostEvent(
                    "step_committed",
                    {
                        "step_index": step_index,
                        "input_tokens": current.usage.input_tokens,
                        "output_tokens": current.usage.output_tokens,
                        "cache_read_input_tokens": current.usage.cache_read_input_tokens,
                        "cache_creation_input_tokens": current.usage.cache_creation_input_tokens,
                    },
                )
            )

        async def check_cancel() -> tuple[bool, bool]:
            return str(state.turn_id) in _CANCELLED, False

        if recording:
            gateway = ModelGateway(RecordedModelProvider(recording))
        else:
            gateway = ModelGateway(
                OpenAIProvider(
                    api_key=model.api_key,
                    model_name=model.model,
                    base_url=model.base_url,
                )
            )
        engine = AgentEngine(
            gateway=gateway,
            tools=assembly.tools,
            system_prompt=assembly.system_prompt,
            write_event=write_event,
            check_cancel=check_cancel,
            on_step_checkpoint=on_step_checkpoint,
            context_window_tokens=model.context_window_tokens,
            volatile_context=state.volatile_context or assembly.volatile_context,
        )
        summary = await engine.run(state)
        if state.delivery:
            emit(HostEvent("delivery", {"summary": str(state.delivery)}))
        reason = state.termination_reason or "final"
        status = "ok"
        if state.cancelled:
            status = "cancelled"
        elif state.budget_exceeded:
            status = "budget_exceeded"
        emit(HostEvent("turn_finished", {"status": status, "reason": reason}))
        return TurnResult(
            turn_id=str(state.turn_id),
            summary=summary or "",
            termination_reason=reason,
            status=status,
        )
    except HostError:
        raise
    except Exception as exc:
        raise classify_model_error(exc) from exc
    finally:
        settings.workspace_root = previous_root
        settings.recordings_dir = previous_recordings
        reset_model_envelope(envelope_token)
        reset_raw_snapshot(raw_token)
        reset_summary_store(summary_token)
        reset_pool_factory(pool_token)
        reset_embedder(embed_token)
        reset_prefs_source(prefs_token)
        reset_buffered_writer(buffered_token)
        reset_evaluation_store(eval_token)
        reset_tenant_context(tenant)


async def start_turn(
    *,
    work_root: Path,
    message: str,
    model: ModelConfig,
    budget: TurnBudget,
    plan_phase: str | None = None,
    on_event=None,
    recording: str | None = None,
    host: bool = True,
) -> TurnResult:
    return await _run(
        work_root=work_root,
        message=message,
        model=model,
        budget=budget,
        plan_phase=plan_phase,
        on_event=on_event,
        recording=recording,
        resume_turn_id=None,
        host=host,
    )


async def resume_turn(
    *,
    work_root: Path,
    turn_id: str,
    model: ModelConfig,
    budget: TurnBudget,
    on_event=None,
    recording: str | None = None,
    host: bool = True,
) -> TurnResult:
    return await _run(
        work_root=work_root,
        message=None,
        model=model,
        budget=budget,
        plan_phase=None,
        on_event=on_event,
        recording=recording,
        resume_turn_id=turn_id,
        host=host,
    )


async def probe_model(model: ModelConfig) -> ProbeReport:
    url = openai_chat_completions_url(model.base_url)
    headers = {"Authorization": f"Bearer {model.api_key}"}
    checks: list[ProbeCheck] = []
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        auth, returned = await _probe_auth(client, url, headers, model)
        checks.append(auth)
        if auth.ok:
            checks.append(await _probe_stream(client, url, headers, model))
            checks.append(await _probe_tools(client, url, headers, model))
            same = (not returned) or returned == model.model or returned.split("/")[-1] == model.model.split("/")[-1]
            checks.append(ProbeCheck("model_name", same, returned or model.model))
        else:
            checks.append(ProbeCheck("stream", False, "鉴权未通过"))
            checks.append(ProbeCheck("tools", False, "鉴权未通过"))
            checks.append(ProbeCheck("model_name", False, "鉴权未通过"))
    return ProbeReport(ok=all(item.ok for item in checks), checks=checks)


async def _probe_auth(client, url, headers, model: ModelConfig) -> tuple[ProbeCheck, str]:
    try:
        response = await client.post(
            url,
            headers=headers,
            json={"model": model.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
        )
    except httpx.HTTPError as exc:
        return ProbeCheck("auth", False, classify_model_error(exc).user_message), ""
    if response.status_code in {401, 403}:
        return ProbeCheck("auth", False, "模型密钥无效或无权访问该模型。"), ""
    if response.status_code >= 400:
        return ProbeCheck("auth", False, f"模型服务返回 {response.status_code}"), ""
    body = response.json()
    returned = str((body.get("model") or "")).strip()
    return ProbeCheck("auth", True, returned or model.model), returned


async def _probe_stream(client, url, headers, model: ModelConfig) -> ProbeCheck:
    try:
        async with client.stream(
            "POST",
            url,
            headers=headers,
            json={
                "model": model.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "stream": True,
            },
        ) as response:
            if response.status_code >= 400:
                return ProbeCheck("stream", False, f"流式请求返回 {response.status_code}")
            async for _line in response.aiter_lines():
                if _line:
                    return ProbeCheck("stream", True, "")
    except httpx.HTTPError as exc:
        return ProbeCheck("stream", False, classify_model_error(exc).user_message)
    return ProbeCheck("stream", False, "没有收到流式数据")


async def _probe_tools(client, url, headers, model: ModelConfig) -> ProbeCheck:
    tool = {
        "type": "function",
        "function": {
            "name": "ping_tool",
            "description": "ping",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    try:
        response = await client.post(
            url,
            headers=headers,
            json={
                "model": model.model,
                "messages": [{"role": "user", "content": "call ping_tool"}],
                "tools": [tool],
                "tool_choice": "required",
                "max_tokens": 32,
            },
        )
    except httpx.HTTPError as exc:
        return ProbeCheck("tools", False, classify_model_error(exc).user_message)
    if response.status_code >= 400 and "thinking" in response.text.lower():
        response = await client.post(
            url,
            headers=headers,
            json={
                "model": model.model,
                "messages": [{"role": "user", "content": "call ping_tool"}],
                "tools": [tool],
                "tool_choice": "required",
                "thinking": {"type": "disabled"},
                "max_tokens": 32,
            },
        )
    if response.status_code >= 400:
        return ProbeCheck("tools", False, f"工具请求返回 {response.status_code}")
    body = response.json()
    message = ((body.get("choices") or [{}])[0].get("message") or {})
    calls = message.get("tool_calls") or []
    if not calls:
        return ProbeCheck("tools", False, "响应里没有 tool_call")
    return ProbeCheck("tools", True, str(calls[0].get("function", {}).get("name") or ""))
