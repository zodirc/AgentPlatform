"""宿主回合运行。直接调用 AgentEngine，不经过 LangGraph 或数据库。"""

from __future__ import annotations

import json
import threading
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
from app.tenant_context import bind_tenant_context, reset_tenant_context
from app.tools.writing_registry import build_writing_registry
from app.writing.intents import resolve_intent
from app.writing.turn_assembly import assemble_writing_turn
from app.writing_host.errors import Busy, HostError, classify_model_error
from app.writing_host.events import (
    TurnEventLog,
    completed_payload,
    failed_payload,
    publish,
)
from app.writing_host.files import (
    FileCheckpointStore,
    FileEvaluationStore,
    NullSummaryStore,
    PlatformPrefsSource,
    ensure_sidecar_format,
)
from app.writing_host.protocol import (
    ModelConfig,
    ProbeCheck,
    ProbeReport,
    TurnBudget,
    TurnResult,
)
from app.writing_host.works import snapshot_turn

_CANCELLED: set[str] = set()
_RESULTS: dict[str, TurnResult] = {}
_ACTIVE: str | None = None
_GATE = threading.Lock()


def cancel_turn(turn_id: str) -> None:
    _CANCELLED.add(str(turn_id))


def turn_busy() -> bool:
    return _ACTIVE is not None


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


def _begin(turn_id: str | None) -> tuple[str, TurnResult | None]:
    global _ACTIVE
    with _GATE:
        if turn_id and turn_id in _RESULTS and turn_id != _ACTIVE:
            return turn_id, _RESULTS[turn_id]
        if _ACTIVE:
            raise Busy()
        chosen = turn_id or str(uuid4())
        _ACTIVE = chosen
        return chosen, None


def _occupy(turn_id: str) -> None:
    global _ACTIVE
    with _GATE:
        if _ACTIVE:
            raise Busy()
        _ACTIVE = turn_id


def _release(turn_id: str, result: TurnResult | None) -> None:
    global _ACTIVE
    with _GATE:
        if _ACTIVE == turn_id:
            _ACTIVE = None
        if result is not None:
            _RESULTS[turn_id] = result
            if len(_RESULTS) > 32:
                for key in list(_RESULTS)[:-32]:
                    _RESULTS.pop(key, None)


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
    turn_id: str | None = None,
    intent: dict | None = None,
) -> TurnResult:
    root = Path(work_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    ensure_sidecar_format(root)
    work_id, owner = _host_ids(root)
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
    recordings_dir = (model.capabilities or {}).get("recordings_dir")
    emit = on_event or (lambda _event: None)
    result: TurnResult | None = None
    log: TurnEventLog | None = None
    ids: dict[str, str] = {}
    terminal = False
    try:
        store = FileCheckpointStore(root)
        if resume_turn_id:
            state, _interrupt, _step = store.load(resume_turn_id)
            profile = ScenarioRegistry.get(state.scenario_id or "writing")
            text = state.turn_user_text
            phase = state.plan_phase
        else:
            profile = ScenarioRegistry.get("writing")
            text, phase = resolve_intent(
                intent, message=message or "", workspace_root=root
            )
            if plan_phase:
                phase = plan_phase
            state = TurnState(
                turn_id=UUID(turn_id),
                session_id=uuid4(),
                run_id=uuid4(),
                trace_id=uuid4(),
                scenario_id="writing",
                max_steps=budget.max_steps or profile.max_steps,
                messages=[user_message(text)],
                turn_user_text=text,
                plan_phase=phase,
            )
        state.max_steps = budget.max_steps or state.max_steps
        state.max_input_tokens = int(budget.max_input_tokens or 0)
        state.max_output_tokens = int(budget.max_output_tokens or 0)
        state.turn_token_budget = 0
        registry = build_writing_registry(host=host)
        assembly = assemble_writing_turn(
            profile=profile,
            registry=registry,
            message=text if resume_turn_id is None else state.turn_user_text,
            plan_phase=phase if resume_turn_id is None else state.plan_phase,
            seed_visible=True,
        )
        if resume_turn_id is None:
            state.volatile_context = assembly.volatile_context
            snapshot_turn(root, str(state.turn_id))
        log = TurnEventLog(root, str(state.turn_id))
        ids = {
            "turn_id": str(state.turn_id),
            "run_id": str(state.run_id),
            "trace_id": str(state.trace_id),
        }
        held: dict[str, Any] | None = None

        def _emit(event_type: str, payload: dict[str, Any], step_index: int) -> None:
            nonlocal terminal
            publish(
                log,
                emit,
                event_type=event_type,
                payload=payload,
                step_index=step_index,
                **ids,
            )
            if event_type in {"turn.completed", "turn.failed", "turn.cancelled"}:
                terminal = True

        if resume_turn_id is None:
            accepted = {
                "scenario_id": "writing",
                "user_input_preview": (state.turn_user_text or "")[:256],
                "model_name": model.model[:128],
            }
            if state.plan_phase in {"planning", "executing"}:
                accepted["plan_phase"] = state.plan_phase
            _emit("turn.accepted", accepted, 0)
            if str(state.turn_id) in _CANCELLED:
                _emit("turn.cancelled", {"reason": "user_requested", "cancelled_at_phase": "step_boundary"}, 0)
                result = TurnResult(str(state.turn_id), "", "user_requested", "cancelled")
                return result

        async def write_event(**kwargs: Any) -> None:
            nonlocal held
            event_type = str(kwargs.get("event_type") or "")
            payload = kwargs.get("payload") if isinstance(kwargs.get("payload"), dict) else {}
            step_index = int(kwargs.get("step_index") or payload.get("step_index") or 0)
            if event_type == "step.completed":
                held = {"payload": dict(payload), "step_index": step_index}
                return
            _emit(event_type, payload, step_index)

        async def on_step_checkpoint(current: TurnState, step_index: int) -> None:
            nonlocal held
            await store.save(state=current, step_index=step_index)
            if held is None:
                return
            payload = held["payload"]
            payload["usage"] = {
                "input_tokens": current.usage.input_tokens,
                "output_tokens": current.usage.output_tokens,
                "cache_read_input_tokens": current.usage.cache_read_input_tokens,
                "cache_creation_input_tokens": current.usage.cache_creation_input_tokens,
            }
            _emit("step.completed", payload, int(held["step_index"]))
            held = None

        async def check_cancel() -> tuple[bool, bool]:
            return str(state.turn_id) in _CANCELLED, False

        if recording:
            gateway = ModelGateway(
                RecordedModelProvider(recording, recordings_dir=str(recordings_dir) if recordings_dir else None)
            )
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
        reason = state.termination_reason or "final"
        status = "ok"
        if state.cancelled:
            status = "cancelled"
            _emit("turn.cancelled", {"reason": "user_requested", "cancelled_at_phase": "step_boundary"}, state.step_count)
            reason = "user_requested"
        else:
            if state.budget_exceeded:
                status = "budget_exceeded"
                reason = "budget_exceeded"
            _emit("turn.completed", completed_payload(state, summary or ""), state.step_count)
        result = TurnResult(str(state.turn_id), summary or "", reason, status)
        return result
    except Exception as exc:
        error = exc if isinstance(exc, HostError) else classify_model_error(exc)
        if log is not None and not terminal:
            detail = f"{error.detail} {error.user_message}".lower()
            reason = "model_timeout" if "timeout" in detail or "timed out" in detail else "fatal_error"
            try:
                publish(
                    log,
                    emit,
                    event_type="turn.failed",
                    payload=failed_payload(
                        termination_reason=reason,
                        message=error.user_message,
                        error_kind=error.code,
                    ),
                    step_index=0,
                    **ids,
                )
            except Exception:
                pass
        if isinstance(exc, HostError):
            raise
        raise error from exc
    finally:
        from app.writing.intents import clear_turn_choice

        clear_turn_choice()
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
    message: str = "",
    model: ModelConfig,
    budget: TurnBudget,
    plan_phase: str | None = None,
    on_event=None,
    recording: str | None = None,
    host: bool = True,
    turn_id: str | None = None,
    intent: dict | None = None,
) -> TurnResult:
    chosen, cached = _begin(turn_id)
    if cached is not None:
        return cached
    result: TurnResult | None = None
    try:
        result = await _run(
            work_root=work_root,
            message=message,
            model=model,
            budget=budget,
            plan_phase=plan_phase,
            on_event=on_event,
            recording=recording,
            resume_turn_id=None,
            host=host,
            turn_id=chosen,
            intent=intent,
        )
        return result
    finally:
        _release(chosen, result)


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
    _occupy(turn_id)
    result: TurnResult | None = None
    try:
        result = await _run(
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
        return result
    finally:
        _release(turn_id, None)


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
