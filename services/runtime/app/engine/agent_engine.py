from __future__ import annotations

import asyncio
from copy import copy, deepcopy
import json
import logging
import re
import time
from contextlib import suppress
from typing import Any, Awaitable, Callable

from app.context.engine import ContextEngine, ToolExecutor
from app.context.policy import CompactionPolicy
from app.engine.read_registry import (
    consume_evicted_reread,
    deny_redundant_read,
    is_mutating_file_tool_failure,
    note_edit_failure_allows_reread,
    path_from_tool_arguments,
    record_successful_read,
    user_facing_policy_summary,
)
from app.engine.state import TurnState, assistant_text, assistant_tool_uses, tool_result_message
from app.model.gateway import ModelError, ModelGateway, ModelResponse, StreamActivity
from app.observability.metrics import record_step_duration, record_tool_call, record_tool_misuse
from app.settings import settings
from app.tools.registry import ToolSpec
from app.tools.validate import extract_citation_ids

logger = logging.getLogger(__name__)

EventWriter = Callable[..., Awaitable[None]]
CancelChecker = Callable[[], Awaitable[tuple[bool, bool]]]


class StepTimeoutError(Exception):
    """Raised when a step exceeds the configured wall-clock budget."""


def _compact_edit_file_event_meta(result: dict[str, Any]) -> dict[str, Any]:
    """Ops-facing CSI fields for edit_file tool.completed (slim; model still gets full result)."""
    out: dict[str, Any] = {}
    if "applies" in result:
        out["applies"] = bool(result.get("applies"))
    impact = result.get("impact")
    if isinstance(impact, dict) and impact:
        compact: dict[str, Any] = {}
        if impact.get("status") is not None:
            compact["status"] = str(impact.get("status"))[:32]
        if impact.get("symbol") is not None:
            compact["symbol"] = str(impact.get("symbol"))[:256]
        if impact.get("reference_count") is not None:
            try:
                compact["reference_count"] = int(impact["reference_count"])
            except (TypeError, ValueError):
                refs = impact.get("references")
                if isinstance(refs, list):
                    compact["reference_count"] = len(refs)
        elif isinstance(impact.get("references"), list):
            compact["reference_count"] = len(impact["references"])
        if impact.get("reason"):
            compact["reason"] = str(impact.get("reason"))[:256]
        if compact:
            out["impact"] = compact
    checks = result.get("checks")
    if isinstance(checks, dict) and checks:
        compact_c: dict[str, Any] = {}
        if checks.get("status") is not None:
            compact_c["status"] = str(checks.get("status"))[:32]
        if checks.get("syntax") is not None:
            compact_c["syntax"] = str(checks.get("syntax"))[:32]
        if checks.get("baseline_count") is not None:
            try:
                compact_c["baseline_count"] = int(checks["baseline_count"])
            except (TypeError, ValueError):
                pass
        issues = checks.get("new_issues")
        if isinstance(issues, list):
            compact_c["new_issue_count"] = len(issues)
        if checks.get("reason"):
            compact_c["reason"] = str(checks.get("reason"))[:256]
        if compact_c:
            out["checks"] = compact_c
    candidates = result.get("candidates")
    if isinstance(candidates, list) and candidates:
        out["candidate_count"] = len(candidates)
    if result.get("match_count") is not None:
        try:
            out["match_count"] = int(result["match_count"])
        except (TypeError, ValueError):
            pass
    return out


def _compact_locate_event_meta(result: dict[str, Any]) -> dict[str, Any]:
    """Ops-facing Locate fields for grep / search_codebase tool.completed."""
    out: dict[str, Any] = {}
    if result.get("redirected_from"):
        out["redirected_from"] = str(result.get("redirected_from"))[:64]
    if result.get("mode") is not None:
        out["locate_mode"] = str(result.get("mode"))[:32]
    if "locate_incomplete" in result:
        out["locate_incomplete"] = bool(result.get("locate_incomplete"))
    defs = result.get("definitions")
    if isinstance(defs, list):
        out["definition_count"] = len(defs)
    elif result.get("definition_count") is not None:
        try:
            out["definition_count"] = int(result["definition_count"])
        except (TypeError, ValueError):
            pass
    status = str(result.get("status") or "")
    if status == "failed" or (
        str(result.get("degraded_reason") or "").startswith("timeout_or_error")
        or str(result.get("degraded_reason") or "") in {"lsp_unavailable", "no_provider", "start_failed"}
    ):
        out["locate_status"] = "failed"
    elif out.get("definition_count"):
        out["locate_status"] = "ok"
    elif out.get("locate_incomplete"):
        out["locate_status"] = "incomplete"
    elif out.get("locate_mode") == "lexical" and not out.get("redirected_from"):
        out["locate_status"] = "lexical"
    elif out.get("redirected_from"):
        out["locate_status"] = "incomplete"
    if result.get("degraded_reason"):
        out["degraded_reason"] = str(result.get("degraded_reason"))[:256]
    # §0.3 fuse-fail reason buckets (probe; observation only).
    fuse = result.get("locate_fuse_fail_reason")
    if fuse:
        out["locate_fuse_fail_reason"] = str(fuse)[:64]
    cands = result.get("candidates")
    if isinstance(cands, list) and cands:
        out["candidate_count"] = len(cands)
        if result.get("candidates_from"):
            out["candidates_from"] = str(result.get("candidates_from"))[:32]
    return out


_TOOL_EVENTS: dict[str, str] = {
    "update_outline": "outline.updated",
    "update_plan": "turn.plan",
}

_CACHEABLE_TOOLS = frozenset(
    {
        "list_dir",
        "glob",
        "grep",
        "read_file",
        "search_sources",
        "enrich_ioc",
        "lookup_indicator",
    }
)

# Returned only by control paths in _run_tool / _run_tool_batch — never as a
# normal tool summary string (delegate used to echo subagent "waiting_approval").
_CONTROL_OUTCOMES = frozenset({"waiting_approval", "CANCELLED", "TERMINATE"})

# Match packages/contracts/.../tool.completed.json — long summaries (e.g. delegate
# echoing verbatim code) must not abort the Turn via schema_validation_error.
_TOOL_COMPLETED_SUMMARY_MAX = 4096
_TOOL_COMPLETED_SPAN_MAX = 65536
_EVENT_STR_TRUNC_SUFFIX = "\n...[truncated]"


def _clamp_event_str(value: Any, max_len: int) -> str:
    text = str(value or "")
    if max_len < 0:
        max_len = 0
    if len(text) <= max_len:
        return text
    # When the budget is smaller than the suffix, hard-cut (never exceed max_len).
    if max_len <= len(_EVENT_STR_TRUNC_SUFFIX):
        return text[:max_len]
    # Suffix length must be exact — off-by-one here still fails maxLength.
    keep = max_len - len(_EVENT_STR_TRUNC_SUFFIX)
    return text[:keep] + _EVENT_STR_TRUNC_SUFFIX


def _tool_completed_base(
    *,
    tool_call_id: str,
    tool_name: str,
    status: str,
    summary: Any = "",
    **extra: Any,
) -> dict[str, Any]:
    """Build a schema-safe tool.completed payload (no illegal keys; clamped strings)."""
    payload: dict[str, Any] = {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "status": status,
        "summary": _clamp_event_str(summary, _TOOL_COMPLETED_SUMMARY_MAX),
    }
    if "path" in extra and extra["path"]:
        payload["path"] = _clamp_event_str(extra.pop("path"), 4096)
    if "policy" in extra and extra["policy"]:
        payload["policy"] = _clamp_event_str(extra.pop("policy"), 128)
    # Drop known-illegal keys callers might pass through habitually.
    extra.pop("error", None)
    payload.update(extra)
    return payload


def _domain_event_payload(event_type: str, result: dict[str, Any]) -> dict[str, Any] | None:
    """Project tool results onto closed domain-event schemas (avoid additionalProperties / maxLength kills)."""
    if event_type == "turn.plan":
        items: list[dict[str, str]] = []
        raw_items = result.get("items")
        if isinstance(raw_items, list):
            for it in raw_items:
                if not isinstance(it, dict):
                    continue
                status = str(it.get("status") or "pending")
                if status not in {"pending", "in_progress", "done", "completed", "cancelled"}:
                    status = "pending"
                items.append(
                    {
                        "id": str(it.get("id") or len(items) + 1),
                        "title": _clamp_event_str(it.get("title") or "item", 512),
                        "status": status,
                    }
                )
        if not items:
            return None
        out: dict[str, Any] = {
            "plan_id": str(result.get("plan_id") or "plan"),
            "items": items,
            "summary": _clamp_event_str(result.get("summary") or "", _TOOL_COMPLETED_SUMMARY_MAX),
        }
        phase = str(result.get("plan_phase") or "")
        if phase in {"planning", "executing"}:
            out["plan_phase"] = phase
        if "awaiting_consent" in result:
            out["awaiting_consent"] = bool(result.get("awaiting_consent"))
        return out
    if event_type == "outline.updated":
        mode = str(result.get("mode") or "")
        out = {
            "path": str(result.get("path") or "outline.md") or "outline.md",
            "content": _clamp_event_str(result.get("content") or "", _TOOL_COMPLETED_SPAN_MAX),
            "summary": _clamp_event_str(result.get("summary") or "", _TOOL_COMPLETED_SUMMARY_MAX),
        }
        if result.get("outline_path"):
            out["outline_path"] = str(result.get("outline_path"))
        if mode in {"replace", "append"}:
            out["mode"] = mode
        return out
    return dict(result)


def _tool_batch_outcome(summary: str) -> str:
    text = str(summary or "")
    if text in _CONTROL_OUTCOMES:
        return f"tool_summary:{text}"
    return text


class AgentEngine:
    def __init__(
        self,
        *,
        gateway: ModelGateway,
        tools: list[ToolSpec],
        system_prompt: str,
        write_event: EventWriter,
        check_cancel: CancelChecker,
        on_step_checkpoint: Callable[[TurnState, int], Awaitable[None]] | None = None,
        context_window_tokens: int | None = None,
        volatile_context: str = "",
    ) -> None:
        self._gateway = gateway
        self._executor = ToolExecutor(tools)
        self._system_prompt = system_prompt
        self._volatile_context = volatile_context or ""
        self._write_event = write_event
        self._check_cancel = check_cancel
        self._on_step_checkpoint = on_step_checkpoint
        policy = CompactionPolicy.from_settings()
        if context_window_tokens is not None:
            policy = policy.with_window(context_window_tokens)
        self._context = ContextEngine(policy=policy)
        self.pending_approval: dict[str, Any] | None = None
        self._tool_result_cache: dict[str, dict[str, Any]] = {}
        self._tool_repeat_counts: dict[str, int] = {}
        self._search_sources_calls = 0
        self._read_file_calls = 0
        self._evidence_citation_ids: set[str] = set()
        self._tool_specs = list(tools)
        self._openai_tools = self._tools_payload(tools)

    async def _abort_gateway_when_cancelled(self, state: TurnState) -> None:
        """Poll cancel while blocked on provider chunks (incl. long thinking gaps).

        Interval matches tool cancel (~50ms). Does not run on the happy-path
        critical path between tokens — only a background sleeper until cancel.
        """
        while not state.cancelled:
            cancelled, force = await self._check_cancel()
            if cancelled:
                state.cancelled = True
                state.cancel_force = force
                abort = getattr(self._gateway, "abort_stream", None)
                if abort is not None:
                    abort()
                return
            await asyncio.sleep(0.05)

    @staticmethod
    def _tools_payload(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    def _scoped_openai_tools(self, state: TurnState) -> list[dict[str, Any]]:
        from app.tools.bootstrap import stage_tool_scope

        scoped = stage_tool_scope(
            self._tool_specs,
            step_count=state.step_count,
            max_steps=state.max_steps,
            delivery=state.delivery,
        )
        return self._tools_payload(scoped)

    async def run(self, state: TurnState) -> str | None:
        final_summary: str | None = None
        self._search_sources_calls = 0
        self._evidence_citation_ids = set()

        while state.step_count < state.max_steps:
            if self._budget_exceeded(state):
                state.budget_exceeded = True
                state.termination_reason = "budget_exceeded"
                break

            cancelled, force = await self._check_cancel()
            if cancelled:
                state.cancelled = True
                state.cancel_force = force
                break

            state.step_count += 1
            step_index = state.step_count - 1
            step_started_at = time.monotonic()
            step_outcome = "completed"
            await self._write_event(
                event_type="step.started",
                payload={"step_index": step_index, "label": f"step-{step_index}"},
                step_index=step_index,
            )

            def _step_elapsed() -> float:
                return time.monotonic() - step_started_at

            async def _ensure_step_within_budget() -> None:
                if _step_elapsed() > settings.step_timeout_seconds:
                    raise StepTimeoutError(
                        f"step {step_index} exceeded {settings.step_timeout_seconds:.0f}s wall clock"
                    )

            try:
                await _ensure_step_within_budget()
                cancelled, force = await self._check_cancel()
                if cancelled:
                    state.cancelled = True
                    state.cancel_force = force
                    break

                step_tools = self._scoped_openai_tools(state)
                # HM2: fire-and-forget raw snapshot before assemble (never model-facing).
                try:
                    import asyncio

                    from app.controller.session_raw import append_raw_snapshot

                    asyncio.get_running_loop().create_task(
                        append_raw_snapshot(
                            session_id=state.session_id,
                            turn_id=state.turn_id,
                            step_index=step_index,
                            messages=list(state.messages),
                            tools=step_tools,
                        ),
                        name=f"raw-snap-{state.turn_id}-{step_index}",
                    )
                except RuntimeError:
                    pass

                messages = await self._context.assemble_async(
                    system_prompt=self._system_prompt,
                    state=state,
                    gateway=self._gateway,
                    tools=step_tools,
                    volatile_context=self._volatile_context,
                )

                from app.context.engine import estimate_window_breakdown

                report = self._context.last_budget_report
                # HM4: async envelope persist (hash always; full body default sample_rate=1).
                try:
                    import asyncio

                    from app.observability.model_envelope import maybe_persist_model_envelope

                    asyncio.get_running_loop().create_task(
                        maybe_persist_model_envelope(
                            turn_id=state.turn_id,
                            session_id=state.session_id,
                            step_index=step_index,
                            messages=messages,
                            tools=step_tools,
                            fill_ratio=float(report.get("fill_ratio") or 0.0),
                        ),
                        name=f"envelope-{state.turn_id}-{step_index}",
                    )
                except RuntimeError:
                    pass
                breakdown = estimate_window_breakdown(
                    messages=messages,
                    tools=step_tools,
                )
                strategies = [
                    str(t.get("strategy", ""))
                    for t in self._context.last_compaction_trace
                    if t.get("strategy")
                ]
                await self._write_event(
                    event_type="context.reported",
                    payload={
                        "step_index": step_index,
                        "tokens_before": int(report.get("tokens_before", 0)),
                        "tokens_after": int(report.get("tokens_after", 0)),
                        "token_budget": int(report.get("token_budget", settings.context_window_tokens)),
                        "system_tokens": int(report.get("system_tokens", 0)),
                        "tools_tokens": int(report.get("tools_tokens", 0)),
                        "messages_tokens": int(report.get("messages_tokens", 0)),
                        "project_tokens": int(report.get("project_tokens", 0)),
                        "runtime_tokens": int(report.get("runtime_tokens", 0)),
                        "volatile_tokens": int(report.get("volatile_tokens", 0)),
                        "reserve_tokens": int(report.get("reserve_tokens", 0)),
                        "fill_ratio": float(report.get("fill_ratio", 0.0)),
                        "assemble_ms": float(report.get("assemble_ms", self._context.last_assemble_ms)),
                        "breakdown": breakdown,
                        "source": "estimated",
                        "strategies": strategies,
                        "budget_truncated_n": int(report.get("budget_truncated_n", 0)),
                        "budget_truncated_by_tool": dict(
                            report.get("budget_truncated_by_tool") or {}
                        ),
                        "estimated_tokens": int(
                            report.get("estimated_tokens")
                            or report.get("tokens_after")
                            or 0
                        ),
                    },
                    step_index=step_index,
                )
                if self._context.last_compaction_trace:
                    logger.info(
                        "context strategies turn_id=%s trace=%s",
                        state.turn_id,
                        self._context.last_compaction_trace,
                    )

                response_text = ""
                tool_calls: list[dict[str, Any]] = []
                step_input_tokens = 0
                step_output_tokens = 0
                step_cache_read = 0
                step_cache_creation = 0
                usage_source = "estimated"

                try:
                    await self._write_event(
                        event_type="turn.thinking",
                        payload={"step_index": step_index, "label": f"step-{step_index}"},
                        step_index=step_index,
                    )
                    stream = self._gateway.stream(messages=messages, tools=step_tools)
                    cancel_watch = asyncio.create_task(
                        self._abort_gateway_when_cancelled(state)
                    )
                    try:
                        async for chunk in stream:
                            # Cancellation is detected by the 50ms background
                            # watcher (sets state.cancelled + aborts the gateway
                            # stream); a per-chunk DB round-trip here is redundant.
                            if state.cancelled:
                                step_outcome = "cancelled"
                                break
                            await _ensure_step_within_budget()

                            if isinstance(chunk, StreamActivity):
                                # Liveness (+ optional reasoning text). Never append to
                                # assistant tokens / durable latest_output.
                                reasoning = str(chunk.text or "")
                                if reasoning:
                                    await self._write_event(
                                        event_type="turn.thinking.delta",
                                        payload={
                                            "delta": reasoning,
                                            "step_index": step_index,
                                        },
                                        step_index=step_index,
                                    )
                                continue
                            if isinstance(chunk, str):
                                response_text += chunk
                                await self._write_event(
                                    event_type="turn.token",
                                    payload={"delta": chunk},
                                    step_index=step_index,
                                )
                            elif isinstance(chunk, ModelResponse):
                                # Streaming providers emit text as str deltas AND repeat the
                                # full text in the terminal ModelResponse; only adopt the
                                # terminal text when nothing was streamed (non-streaming path).
                                if chunk.text and not response_text:
                                    response_text += chunk.text
                                if chunk.tool_calls:
                                    tool_calls.extend(chunk.tool_calls)
                                if chunk.input_tokens:
                                    step_input_tokens = chunk.input_tokens
                                    usage_source = "provider"
                                if chunk.output_tokens:
                                    step_output_tokens = chunk.output_tokens
                                    if usage_source != "provider":
                                        usage_source = "mixed"
                                if chunk.cache_read_input_tokens:
                                    step_cache_read = chunk.cache_read_input_tokens
                                if chunk.cache_creation_input_tokens:
                                    step_cache_creation = chunk.cache_creation_input_tokens
                                state.usage.input_tokens += chunk.input_tokens
                                state.usage.output_tokens += chunk.output_tokens
                    finally:
                        cancel_watch.cancel()
                        with suppress(asyncio.CancelledError):
                            await cancel_watch
                except ModelError:
                    # Mid-stream aclose after Cancel can still raise; prefer cancelled.
                    if state.cancelled:
                        step_outcome = "cancelled"
                        break
                    cancelled, force = await self._check_cancel()
                    if cancelled:
                        state.cancelled = True
                        state.cancel_force = force
                        step_outcome = "cancelled"
                        break
                    step_outcome = "failed"
                    raise

                if state.cancelled:
                    break

                if step_input_tokens == 0 and step_output_tokens == 0:
                    # Fallback estimate when provider did not report usage.
                    step_input_tokens = int(report.get("tokens_after", 0))
                    step_output_tokens = max(1, len(response_text) // 4) if response_text else 0
                    state.usage.input_tokens += step_input_tokens
                    state.usage.output_tokens += step_output_tokens
                    usage_source = "estimated"
                elif step_input_tokens == 0:
                    step_input_tokens = int(report.get("tokens_after", 0))
                    state.usage.input_tokens += step_input_tokens
                    usage_source = "mixed" if usage_source == "provider" else "estimated"

                retry_count = int(getattr(self._gateway, "retry_count", 0) or 0)
                estimated = int(
                    report.get("estimated_tokens") or report.get("tokens_after") or 0
                )
                usage_payload: dict[str, Any] = {
                    "step_index": step_index,
                    "input_tokens": state.usage.input_tokens,
                    "output_tokens": state.usage.output_tokens,
                    "step_input_tokens": step_input_tokens,
                    "step_output_tokens": step_output_tokens,
                    "source": usage_source,
                    "retry_count": retry_count,
                    "estimated_tokens": estimated,
                }
                # C3: estimate / provider ratio for offline calibration (1.0 = perfect).
                if usage_source == "provider" and step_input_tokens > 0 and estimated > 0:
                    usage_payload["estimate_to_provider_ratio"] = round(
                        float(estimated) / float(step_input_tokens), 4
                    )
                if step_cache_read or step_cache_creation:
                    usage_payload["cache_read_input_tokens"] = step_cache_read
                    usage_payload["cache_creation_input_tokens"] = step_cache_creation
                    usage_payload["cache_hit"] = step_cache_read > 0
                await self._write_event(
                    event_type="usage.reported",
                    payload=usage_payload,
                    step_index=step_index,
                )

                # Re-check budget once this step's token usage is counted so a
                # single over-budget response terminates with budget_exceeded
                # instead of falling through as a normal "final" completion.
                if self._budget_exceeded(state):
                    state.budget_exceeded = True
                    state.termination_reason = "budget_exceeded"

                if tool_calls:
                    state.messages.append(assistant_tool_uses(tool_calls, text=response_text))
                    tool_outcome = await self._run_tool_batch(
                        tool_calls,
                        state,
                        step_index,
                        _ensure_step_within_budget,
                    )
                    if tool_outcome == "CANCELLED":
                        step_outcome = "cancelled"
                        break
                    if tool_outcome == "waiting_approval":
                        step_outcome = "waiting_approval"
                        return "waiting_approval"
                    if tool_outcome == "TERMINATE":
                        final_summary = json.loads(
                            state.messages[-1]["content"][0]["content"]
                        ).get("summary", "stub completed")
                        return final_summary
                    if tool_outcome:
                        final_summary = tool_outcome
                    if state.cancelled:
                        step_outcome = "cancelled"
                        break
                    continue

                if response_text:
                    state.messages.append(assistant_text(response_text))
                    final_summary = response_text
                record_step_duration(
                    scenario_id=state.scenario_id,
                    duration_seconds=_step_elapsed(),
                )
                break
            except StepTimeoutError:
                step_outcome = "failed"
                raise
            finally:
                await self._complete_step(step_index, step_started_at, step_outcome)
                if self._on_step_checkpoint is not None:
                    await self._on_step_checkpoint(state, step_index)

        if state.cancelled:
            return final_summary
        if state.budget_exceeded:
            return final_summary or "budget exceeded"
        if state.step_count >= state.max_steps:
            state.termination_reason = "max_steps"
            return final_summary or "max_steps reached"
        return final_summary

    @staticmethod
    def _tool_cache_key(tool_name: str, arguments: dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(arguments, sort_keys=True, default=str)}"

    def _lookup_tool_cache(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        if tool_name not in _CACHEABLE_TOOLS:
            return None
        cache_key = self._tool_cache_key(tool_name, arguments)
        cached = self._tool_result_cache.get(cache_key)
        if cached is None:
            return None
        repeat = self._tool_repeat_counts.get(cache_key, 1) + 1
        self._tool_repeat_counts[cache_key] = repeat
        result = dict(cached)
        result["_cached"] = True
        result["_repeat_count"] = repeat
        if repeat >= 2:
            result["_note"] = (
                "Identical read-only tool call repeated; result unchanged. "
                "Do NOT call this tool again with the same arguments. "
                "Use prior results, try a different path, or produce the deliverable."
            )
            record_tool_misuse(kind="cached_repeat", tool_name=tool_name)
        return result

    def _store_tool_cache(
        self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]
    ) -> None:
        if tool_name not in _CACHEABLE_TOOLS or result.get("error"):
            return
        cache_key = self._tool_cache_key(tool_name, arguments)
        self._tool_result_cache[cache_key] = dict(result)
        self._tool_repeat_counts[cache_key] = 1

    def _budget_exceeded(self, state: TurnState) -> bool:
        limit = settings.turn_token_budget
        if limit <= 0:
            return False
        total = state.usage.input_tokens + state.usage.output_tokens
        return total >= limit

    async def _complete_step(self, step_index: int, started_at: float, outcome: str) -> None:
        await self._write_event(
            event_type="step.completed",
            payload={
                "step_index": step_index,
                "label": f"step-{step_index}",
                "outcome": outcome,
                "duration_ms": max(0, int((time.monotonic() - started_at) * 1000)),
            },
            step_index=step_index,
        )

    async def _run_tool_batch(
        self,
        tool_calls: list[dict[str, Any]],
        state: TurnState,
        step_index: int,
        ensure_step_budget: Callable[[], Awaitable[None]] | None = None,
    ) -> str | None:
        """Run tool_calls: consecutive readonly tools in parallel; mutating serial."""
        index = 0
        last_summary: str | None = None
        while index < len(tool_calls):
            if ensure_step_budget is not None:
                await ensure_step_budget()
            call = tool_calls[index]
            name = str(call.get("name") or "")
            if name in _CACHEABLE_TOOLS:
                batch: list[dict[str, Any]] = []
                while index < len(tool_calls) and str(tool_calls[index].get("name") or "") in _CACHEABLE_TOOLS:
                    batch.append(tool_calls[index])
                    index += 1
                if len(batch) == 1:
                    summaries = [
                        await self._run_tool(batch[0], state, step_index, ensure_step_budget)
                    ]
                else:
                    # Read-only I/O may complete in any order, but tool results must
                    # retain the provider's tool_use order.  Isolate the mutable
                    # per-turn fields while each task runs, then merge them below.
                    # This keeps the executor calls concurrent without racing
                    # state.messages or state.read_registry.
                    initial_read_registry = deepcopy(state.read_registry)
                    counter_seeds: list[dict[str, int]] = []
                    next_read_file_calls = self._read_file_calls
                    next_search_sources_calls = self._search_sources_calls
                    for item in batch:
                        counters = {
                            "read_file": next_read_file_calls,
                            "search_sources": next_search_sources_calls,
                        }
                        if item.get("name") == "read_file":
                            next_read_file_calls += 1
                        elif item.get("name") == "search_sources":
                            next_search_sources_calls += 1
                        counter_seeds.append(counters)

                    async def run_isolated(
                        item: dict[str, Any], counters: dict[str, int]
                    ) -> tuple[str | None, TurnState]:
                        isolated = copy(state)
                        isolated.messages = []
                        isolated.read_registry = deepcopy(initial_read_registry)
                        summary = await self._run_tool(
                            item,
                            isolated,
                            step_index,
                            ensure_step_budget,
                            counters,
                        )
                        return summary, isolated

                    isolated_runs = await asyncio.gather(
                        *(
                            run_isolated(item, counters)
                            for item, counters in zip(batch, counter_seeds)
                        )
                    )
                    summaries = []
                    for item, (summary, isolated) in zip(batch, isolated_runs):
                        # gather preserves its input order, so these mutations are
                        # deterministic even when the underlying I/O finishes out of
                        # order.
                        state.messages.extend(isolated.messages)
                        self._merge_readonly_read_registry(item, isolated, state)
                        if isolated.cancelled:
                            state.cancelled = True
                            state.cancel_force = state.cancel_force or isolated.cancel_force
                        summaries.append(summary)
                    self._read_file_calls = next_read_file_calls
                    self._search_sources_calls = next_search_sources_calls
                for summary in summaries:
                    if summary == "CANCELLED":
                        return "CANCELLED"
                    if summary == "waiting_approval":
                        return "waiting_approval"
                    if summary == "TERMINATE":
                        return "TERMINATE"
                    if summary:
                        last_summary = summary
                if state.cancelled:
                    return "CANCELLED"
                continue

            summary = await self._run_tool(call, state, step_index, ensure_step_budget)
            index += 1
            if summary == "CANCELLED":
                return "CANCELLED"
            if summary == "waiting_approval":
                return "waiting_approval"
            if summary == "TERMINATE":
                return "TERMINATE"
            if summary:
                last_summary = summary
            if state.cancelled:
                return "CANCELLED"
        return last_summary

    @staticmethod
    def _merge_readonly_read_registry(
        call: dict[str, Any], isolated: TurnState, state: TurnState
    ) -> None:
        """Apply a completed parallel read's registry effect in call order."""
        if call.get("name") != "read_file":
            return
        tool_call_id = call.get("id")
        for message in isolated.messages:
            if message.get("role") != "tool":
                continue
            block = next(
                (
                    content
                    for content in message.get("content", [])
                    if content.get("type") == "tool_result"
                    and content.get("tool_use_id") == tool_call_id
                ),
                None,
            )
            if block is None:
                continue
            try:
                result = json.loads(str(block.get("content", "")))
            except json.JSONDecodeError:
                return
            if not isinstance(result, dict) or result.get("error"):
                return
            try:
                offset = int(result.get("offset") or 1)
                end_line = int(result.get("end_line") or 0)
                next_offset = (
                    int(result["next_offset"])
                    if result.get("next_offset") is not None
                    else None
                )
            except (TypeError, ValueError):
                return
            record_successful_read(
                state.read_registry,
                path=str(
                    result.get("path")
                    or path_from_tool_arguments(
                        call.get("input") if isinstance(call.get("input"), dict) else {}
                    )
                ),
                offset=offset,
                end_line=end_line,
                truncated=bool(result.get("truncated")),
                next_offset=next_offset,
                whole_file_complete=bool(result.get("whole_file_complete")),
            )
            return

    async def _run_tool(
        self,
        call: dict[str, Any],
        state: TurnState,
        step_index: int,
        ensure_step_budget: Callable[[], Awaitable[None]] | None = None,
        counters: dict[str, int] | None = None,
    ) -> str | None:
        tool_call_id = call["id"]
        tool_name = call["name"]
        arguments = call.get("input", {})

        await self._write_event(
            event_type="tool.started",
            payload={"tool_call_id": tool_call_id, "tool_name": tool_name, "arguments": arguments},
            step_index=step_index,
        )

        # C2: keep tools schema static; reject late-stage tools at runtime.
        from app.tools.bootstrap import stage_tool_runtime_blocked

        if stage_tool_runtime_blocked(
            tool_name,
            step_count=state.step_count,
            max_steps=state.max_steps,
            delivery=state.delivery,
        ):
            result = {"error": "tool disabled at this stage"}
            state.messages.append(
                tool_result_message(
                    tool_call_id,
                    json.dumps(result, ensure_ascii=False),
                    is_error=True,
                )
            )
            await self._write_event(
                event_type="tool.completed",
                payload=_tool_completed_base(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    status="error",
                    summary="tool disabled at this stage",
                ),
                step_index=step_index,
            )
            record_tool_call(tool_name=tool_name, status="error")
            return "tool disabled at this stage"

        if tool_name == "read_file":
            args = arguments if isinstance(arguments, dict) else {}
            try:
                read_offset = int(args.get("offset") or 1)
            except (TypeError, ValueError):
                read_offset = 1
            if read_offset < 1:
                read_offset = 1
            read_path = path_from_tool_arguments(args)
            deny = deny_redundant_read(
                state.read_registry,
                path=read_path,
                offset=read_offset,
                evicted_paths=state.evicted_paths,
                evicted_reread_used=state.evicted_reread_used,
            )
            if deny:
                kind = (
                    "read_after_complete"
                    if deny.startswith("read_after_complete")
                    else "read_overlap"
                )
                ui_summary = user_facing_policy_summary(kind, path=read_path)
                # Soft tip to the model (not is_error) + skipped event for Web (not red error).
                result = {
                    "status": "skipped",
                    "policy": kind,
                    "path": read_path,
                    "summary": ui_summary,
                    "hint": deny,
                }
                record_tool_misuse(kind=kind, tool_name="read_file")
                state.messages.append(
                    tool_result_message(
                        tool_call_id,
                        json.dumps(result, ensure_ascii=False),
                        is_error=False,
                    )
                )
                await self._write_event(
                    event_type="tool.completed",
                    payload=_tool_completed_base(
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        status="skipped",
                        summary=ui_summary,
                        policy=kind,
                        **({"path": read_path} if read_path else {}),
                    ),
                    step_index=step_index,
                )
                record_tool_call(tool_name=tool_name, status="skipped")
                return ui_summary

            budget = int(getattr(settings, "read_file_max_per_turn", 0) or 0)
            if budget > 0:
                if counters is None:
                    self._read_file_calls += 1
                    read_file_calls = self._read_file_calls
                else:
                    counters["read_file"] += 1
                    read_file_calls = counters["read_file"]
                if read_file_calls > budget:
                    ui_summary = user_facing_policy_summary(
                        "read_budget", path=read_path, budget=budget
                    )
                    result = {
                        "status": "skipped",
                        "policy": "read_budget",
                        "path": read_path,
                        "summary": ui_summary,
                        "hint": (
                            f"read_file limit ({budget}) reached this Turn; "
                            "edit with content already read, or finish the deliverable."
                        ),
                    }
                    record_tool_misuse(kind="read_budget", tool_name="read_file")
                    state.messages.append(
                        tool_result_message(
                            tool_call_id,
                            json.dumps(result, ensure_ascii=False),
                            is_error=False,
                        )
                    )
                    await self._write_event(
                        event_type="tool.completed",
                        payload=_tool_completed_base(
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            status="skipped",
                            summary=ui_summary,
                            policy="read_budget",
                            **({"path": read_path} if read_path else {}),
                        ),
                        step_index=step_index,
                    )
                    record_tool_call(tool_name=tool_name, status="skipped")
                    return ui_summary

        if tool_name == "search_sources":
            budget = settings.search_sources_max_per_turn
            if budget > 0:
                if counters is None:
                    self._search_sources_calls += 1
                    search_sources_calls = self._search_sources_calls
                else:
                    counters["search_sources"] += 1
                    search_sources_calls = counters["search_sources"]
                if search_sources_calls > budget:
                    result = {
                        "error": "search_sources budget exceeded for this turn",
                        "summary": (
                            f"search_sources limit ({budget}) reached; use read_file on a known "
                            "sources/ path or draft with prior hits."
                        ),
                        "hits": [],
                        "retrieval": "none",
                    }
                    record_tool_misuse(kind="search_budget", tool_name="search_sources")
                    state.messages.append(
                        tool_result_message(
                            tool_call_id,
                            json.dumps(result, ensure_ascii=False),
                            is_error=True,
                        )
                    )
                    await self._write_event(
                        event_type="tool.completed",
                        payload=_tool_completed_base(
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            status="error",
                            summary=result["summary"],
                        ),
                        step_index=step_index,
                    )
                    record_tool_call(tool_name=tool_name, status="error")
                    return result["summary"]

        if tool_name == "draft_section":
            content = str(arguments.get("content", ""))
            section_id = str(arguments.get("section_id", "01"))
            # Content is already fully generated; replay slices without paying a
            # cancel SELECT per 16-char slice. Throttle DB checks to ~4/s and
            # honour the in-memory flag on every slice.
            last_cancel_check = time.monotonic()
            for delta in _chunk_text(content, 16):
                if ensure_step_budget is not None:
                    await ensure_step_budget()
                if time.monotonic() - last_cancel_check >= 0.25:
                    last_cancel_check = time.monotonic()
                    cancelled, force = await self._check_cancel()
                    if cancelled:
                        state.cancelled = True
                        state.cancel_force = force
                if state.cancelled:
                    return "CANCELLED"
                await self._write_event(
                    event_type="section.draft.delta",
                    payload={
                        "section_id": section_id,
                        "delta": _clamp_event_str(delta, 8192),
                    },
                    step_index=step_index,
                )

        result = None
        skip_read_cache = False
        if tool_name == "read_file":
            key = path_from_tool_arguments(arguments if isinstance(arguments, dict) else {})
            st = state.read_registry.get(key) if key else None
            # After edit failure we must hit disk, not the pre-edit cached blob.
            skip_read_cache = bool(st and st.allow_reread_once)
        if not skip_read_cache:
            result = self._lookup_tool_cache(tool_name, arguments)
        if result is None:
            result = await self._executor.run(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                arguments=arguments,
                state=state,
            )
            self._store_tool_cache(tool_name, arguments, result)

        if tool_name == "read_file" and isinstance(result, dict) and not result.get("error"):
            try:
                off = int(result.get("offset") or 1)
            except (TypeError, ValueError):
                off = 1
            try:
                end_line = int(result.get("end_line") or 0)
            except (TypeError, ValueError):
                end_line = 0
            next_off = result.get("next_offset")
            try:
                next_off_i = int(next_off) if next_off is not None else None
            except (TypeError, ValueError):
                next_off_i = None
            record_successful_read(
                state.read_registry,
                path=str(result.get("path") or path_from_tool_arguments(arguments)),
                offset=off,
                end_line=end_line,
                truncated=bool(result.get("truncated")),
                next_offset=next_off_i,
                whole_file_complete=bool(result.get("whole_file_complete")),
            )
            consume_evicted_reread(
                path=str(result.get("path") or path_from_tool_arguments(arguments)),
                evicted_paths=state.evicted_paths,
                evicted_reread_used=state.evicted_reread_used,
            )
        elif isinstance(result, dict) and is_mutating_file_tool_failure(tool_name, result):
            note_edit_failure_allows_reread(
                state.read_registry,
                path=path_from_tool_arguments(arguments if isinstance(arguments, dict) else {}),
            )

        self._ingest_evidence(tool_name, result)
        if settings.citation_verify_enabled:
            self._annotate_unverified_citations(tool_name, arguments, result)

        if tool_name == "run_command" and result.get("stdout"):
            stdout = str(result["stdout"])
            for delta in _chunk_text(stdout, 24):
                if ensure_step_budget is not None:
                    await ensure_step_budget()
                await self._write_event(
                    event_type="tool.delta",
                    payload={
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "delta": delta,
                    },
                    step_index=step_index,
                )

        cancelled, force = await self._check_cancel()
        if cancelled or result.get("status") == "cancelled":
            state.cancelled = True
            state.cancel_force = force or state.cancel_force
            return "CANCELLED"

        if result.get("status") == "approval_required":
            approval_payload: dict[str, Any] = {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "arguments": arguments,
            }
            if tool_name == "write_file":
                path = str(arguments.get("path", ""))
                old_text = ""
                if path:
                    try:
                        from app.tools.core.tools import _resolve_path

                        target = _resolve_path(path)
                        if target.is_file():
                            old_text = target.read_text(encoding="utf-8", errors="replace")
                            if len(old_text) > 32_000:
                                old_text = old_text[:32_000] + "\n...[truncated]"
                    except OSError:
                        pass
                approval_payload["path"] = path
                approval_payload["old_text"] = old_text
                approval_payload["new_text"] = str(arguments.get("content", ""))
            elif tool_name == "edit_file":
                # Span replace — surface old/new for UI unified diff (not whole file).
                approval_payload["path"] = str(arguments.get("path", ""))
                approval_payload["old_text"] = str(arguments.get("old_text", ""))
                approval_payload["new_text"] = str(arguments.get("new_text", ""))
            await self._write_event(
                event_type="approval.requested",
                payload=approval_payload,
                step_index=step_index,
            )
            self.pending_approval = {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "step_index": step_index,
            }
            return "waiting_approval"

        if result.get("status") == "timeout":
            summary = str(result.get("summary", "tool timed out"))
            await self._write_event(
                event_type="tool.completed",
                payload=_tool_completed_base(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    status="timeout",
                    summary=summary,
                ),
                step_index=step_index,
            )
            record_tool_call(tool_name=tool_name, status="timeout")
            state.messages.append(tool_result_message(tool_call_id, json.dumps(result), is_error=True))
            return str(summary)

        event_type = _TOOL_EVENTS.get(tool_name)
        # Skip domain events for error payloads (status=error or bare {"error": ...}).
        if (
            event_type
            and result.get("status") != "error"
            and not result.get("error")
        ):
            domain_payload = _domain_event_payload(event_type, result)
            if domain_payload is not None:
                await self._write_event(
                    event_type=event_type,
                    payload=domain_payload,
                    step_index=step_index,
                )

        if tool_name == "search_sources":
            mode = str(result.get("retrieval", "none"))
            # keyword-fallback is an intentional observability mode (docs/15); still emit.
            if mode in {"vector", "keyword", "hybrid", "keyword-fallback"}:
                raw_hits = result.get("hits", [])
                hits_preview: list[dict[str, Any]] = []
                # Keep path+score for up to 100 hits so official L1 / Ops can score
                # nDCG@10 and R@100 without changing the tool_result the model sees.
                ranked_for_score: list[dict[str, Any]] = []
                if isinstance(raw_hits, list):
                    for i, hit in enumerate(raw_hits[:100]):
                        if not isinstance(hit, dict):
                            continue
                        path = str(hit.get("path", ""))
                        # RET-15-2: prefer score_raw for IR ranked; model-facing score may be 0–100.
                        score = hit.get("score_raw")
                        if score is None:
                            score = hit.get("score")
                        ranked_for_score.append(
                            {
                                "path": path,
                                **({"score": score} if score is not None else {}),
                                **(
                                    {"chunk_id": str(hit["chunk_id"])}
                                    if hit.get("chunk_id")
                                    else {}
                                ),
                            }
                        )
                        if i >= 5:
                            continue
                        preview: dict[str, Any] = {
                            "path": path,
                            "excerpt": _clamp_event_str(hit.get("excerpt", ""), 512),
                        }
                        if hit.get("citation_id"):
                            preview["citation_id"] = str(hit["citation_id"])
                        if hit.get("chunk_id"):
                            preview["chunk_id"] = str(hit["chunk_id"])
                        if score is not None:
                            preview["score"] = score
                        hits_preview.append(preview)
                retrieval_payload: dict[str, Any] = {
                    "query": _clamp_event_str(result.get("query", ""), 4096),
                    "mode": mode,
                    "hit_count": len(raw_hits) if isinstance(raw_hits, list) else 0,
                    "summary": _clamp_event_str(result.get("summary", ""), 512),
                    "hits": hits_preview,
                    "ranked": ranked_for_score,
                }
                if result.get("excerpt_promote_reorder"):
                    retrieval_payload["excerpt_promote_reorder"] = True
                index_info = result.get("index")
                if isinstance(index_info, dict):
                    retrieval_payload["index"] = index_info
                filters_info = result.get("filters")
                if isinstance(filters_info, dict):
                    retrieval_payload["filters"] = filters_info
                # HM5: three-stage audit for Ops (never required for UI hits).
                audit_info = result.get("audit")
                if isinstance(audit_info, dict):
                    retrieval_payload["audit"] = audit_info
                await self._write_event(
                    event_type="retrieval.completed",
                    payload=retrieval_payload,
                    step_index=step_index,
                )

        if tool_name == "propose_patch" and "patch_id" in result:
            # Event schema is strict; keep apply_check fields on the tool result
            # (model-visible) but do not put them on patch.proposed.
            proposed_payload = {
                "patch_id": str(result.get("patch_id") or ""),
                "path": str(result.get("path") or ""),
                "status": "pending",
                "old_text": _clamp_event_str(result.get("old_text") or "", _TOOL_COMPLETED_SPAN_MAX),
                "new_text": _clamp_event_str(result.get("new_text") or "", _TOOL_COMPLETED_SPAN_MAX),
                "summary": _clamp_event_str(result.get("summary") or "", _TOOL_COMPLETED_SUMMARY_MAX),
            }
            if proposed_payload["patch_id"] and proposed_payload["path"]:
                await self._write_event(
                    event_type="patch.proposed",
                    payload=proposed_payload,
                    step_index=step_index,
                )
            if (
                settings.writing_patch_auto_apply
                and str(result.get("status") or "") == "pending"
                and not result.get("error")
            ):
                from app.scenarios.registry import ScenarioRegistry

                try:
                    _profile = ScenarioRegistry.get(state.scenario_id)
                except ValueError:
                    _profile = None
                if _profile and _profile.patch_auto_apply:
                    from app.tools.core import tools as core_tools

                    try:
                        applied = await core_tools.apply_patch(
                            path=str(result.get("path", "")),
                            new_text=str(result.get("new_text", "")),
                            old_text=str(result.get("old_text") or ""),
                        )
                        if applied.get("status") == "error":
                            result["status"] = "error"
                            result["auto_applied"] = False
                            err = applied.get("error")
                            result["error"] = err
                            result["auto_apply_error"] = err
                        else:
                            result["status"] = "applied"
                            result["auto_applied"] = True
                            if applied.get("bytes_written") is not None:
                                result["bytes_written"] = applied["bytes_written"]
                            await self._write_event(
                                event_type="patch.applied",
                                payload={
                                    "patch_id": result["patch_id"],
                                    "path": result.get("path"),
                                    "status": "applied",
                                    "auto_applied": True,
                                    "bytes_written": applied.get("bytes_written"),
                                },
                                step_index=step_index,
                            )
                    except Exception as exc:
                        result["status"] = "error"
                        result["error"] = str(exc)
                        result["auto_applied"] = False
                        result["auto_apply_error"] = str(exc)
                        logger.exception(
                            "writing patch auto-apply failed patch_id=%s",
                            result.get("patch_id"),
                        )

        if tool_name == "export_document":
            state.delivery = {
                "delivery_status": str(result.get("delivery_status", "failed")),
                "delivery_issues": list(result.get("delivery_issues") or []),
                "export_path": str(result.get("output_path", "")),
            }

        summary = result.get("summary") or result.get("content", "")[:200] or json.dumps(result)[:200]
        if tool_name == "search_sources" and result.get("hits"):
            hit = result["hits"][0]
            excerpt = str(hit.get("excerpt", ""))[:160]
            if excerpt:
                summary = f"{summary}; {excerpt}"
        # Prefer concrete error text in the timeline (e.g. auto-apply old_text miss).
        if result.get("error"):
            err_text = str(result.get("error"))[:240]
            if err_text and err_text not in summary:
                summary = err_text
        tool_status = "error" if result.get("error") or str(result.get("status") or "") == "error" else "ok"
        # Event contract only allows ok|error|denied|timeout (not edited/written).
        # Clamp bus fields only — model still receives full tool_result JSON below.
        completed_payload: dict[str, Any] = _tool_completed_base(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            status=tool_status,
            summary=summary,
        )
        # CTX-9: light read coverage fields (no full content on the bus).
        if tool_name == "read_file" and isinstance(result, dict) and not result.get("error"):
            content = result.get("content")
            if isinstance(content, str):
                completed_payload["chars_read"] = len(content)
            elif result.get("chars_read") is not None:
                try:
                    completed_payload["chars_read"] = int(result["chars_read"])
                except (TypeError, ValueError):
                    pass
            # Prefer explicit total; else recover from CTX-2a hint「已读 X / 共 Y 字符」.
            file_chars = result.get("file_chars")
            if file_chars is None:
                hint = str(result.get("hint") or "")
                m = re.search(r"已读\s+(\d+)\s*/\s*共\s+(\d+)\s*字符", hint)
                if m:
                    file_chars = int(m.group(2))
                    if "chars_read" not in completed_payload:
                        completed_payload["chars_read"] = int(m.group(1))
            if file_chars is not None:
                try:
                    completed_payload["file_chars"] = int(file_chars)
                except (TypeError, ValueError):
                    pass
            for key in ("offset", "end_line", "total_lines"):
                if result.get(key) is not None:
                    try:
                        completed_payload[key] = int(result[key])
                    except (TypeError, ValueError):
                        pass
            if result.get("next_offset") not in (None, "", 0, "0"):
                try:
                    completed_payload["next_offset"] = int(result["next_offset"])
                except (TypeError, ValueError):
                    pass
            if result.get("truncated") is not None:
                completed_payload["is_truncated"] = bool(result.get("truncated"))
            path_val = str(result.get("path") or "")
            if path_val:
                completed_payload["path"] = path_val
        if tool_name in {"write_file", "edit_file"}:
            args = arguments if isinstance(arguments, dict) else {}
            path_val = str(result.get("path") or args.get("path") or "")
            if path_val:
                completed_payload["path"] = path_val
            if tool_name == "edit_file":
                completed_payload["old_text"] = _clamp_event_str(
                    result.get("old_text") or args.get("old_text") or "",
                    _TOOL_COMPLETED_SPAN_MAX,
                )
                completed_payload["new_text"] = _clamp_event_str(
                    result.get("new_text") or args.get("new_text") or "",
                    _TOOL_COMPLETED_SPAN_MAX,
                )
            else:
                completed_payload["old_text"] = _clamp_event_str(
                    result.get("old_text") or "",
                    _TOOL_COMPLETED_SPAN_MAX,
                )
                completed_payload["new_text"] = _clamp_event_str(
                    result.get("new_text") or args.get("content") or "",
                    _TOOL_COMPLETED_SPAN_MAX,
                )
            if result.get("bytes_written") is not None:
                completed_payload["bytes_written"] = int(result["bytes_written"])
            if tool_name == "edit_file" and isinstance(result, dict):
                completed_payload.update(_compact_edit_file_event_meta(result))
        if tool_name in {"grep", "search_codebase"} and isinstance(result, dict):
            completed_payload.update(_compact_locate_event_meta(result))
        if tool_name == "export_document":
            issues_raw = result.get("delivery_issues") or []
            issues = [
                _clamp_event_str(x, 1024)
                for x in (issues_raw if isinstance(issues_raw, list) else [])
            ]
            completed_payload.update(
                {
                    "delivery_status": str(result.get("delivery_status", "failed")),
                    "delivery_issues": issues,
                    "output_path": _clamp_event_str(result.get("output_path") or "", 4096),
                }
            )
            if result.get("bytes_written") is not None:
                completed_payload["bytes_written"] = int(result["bytes_written"])
        # CSI §11: structural meta for Ops process metrics (lite dual-track).
        if tool_name in {"read_lints", "goto_definition", "find_references"} and isinstance(
            result, dict
        ):
            if result.get("provider") is not None:
                completed_payload["provider"] = str(result.get("provider"))[:64]
            if result.get("cold_start") is not None:
                completed_payload["cold_start"] = bool(result.get("cold_start"))
            if result.get("degraded_reason"):
                completed_payload["degraded_reason"] = str(result.get("degraded_reason"))[:256]
            if result.get("unsupported") is not None:
                completed_payload["unsupported"] = bool(result.get("unsupported"))
            if result.get("truncated") is not None:
                completed_payload["structural_truncated"] = bool(result.get("truncated"))
        await self._write_event(
            event_type="tool.completed",
            payload=completed_payload,
            step_index=step_index,
        )
        record_tool_call(tool_name=tool_name, status=tool_status)
        is_error = bool(result.get("error")) or tool_status == "error"
        # HM5: keep audit on events only — do not inflate model tool_result tokens.
        model_result = result
        if isinstance(result, dict) and "audit" in result:
            model_result = {k: v for k, v in result.items() if k != "audit"}
        state.messages.append(
            tool_result_message(
                tool_call_id,
                json.dumps(model_result, ensure_ascii=False),
                is_error=is_error,
            )
        )
        if tool_name == "stub_echo":
            return "TERMINATE"
        # Planning phase: after a proposed checklist, stop — wait for「按此执行」(docs/25).
        if (
            tool_name == "update_plan"
            and state.plan_phase == "planning"
            and not is_error
            and result.get("awaiting_consent")
        ):
            state.termination_reason = "plan_awaiting_consent"
            return "TERMINATE"
        return _tool_batch_outcome(str(summary))

    def _ingest_evidence(self, tool_name: str, result: dict[str, Any]) -> None:
        if tool_name == "search_sources":
            hits = result.get("hits")
            if isinstance(hits, list):
                for hit in hits:
                    if not isinstance(hit, dict):
                        continue
                    cid = hit.get("citation_id")
                    if cid:
                        self._evidence_citation_ids.add(str(cid))
        if tool_name == "check_citation" and result.get("valid") is True:
            cid = result.get("citation_id")
            if cid:
                self._evidence_citation_ids.add(str(cid))

    def _annotate_unverified_citations(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        if result.get("error") or result.get("status") in {"approval_required", "timeout", "cancelled"}:
            return
        texts: list[str] = []
        if tool_name == "draft_section":
            texts.append(str(arguments.get("content", "")))
        elif tool_name == "propose_patch":
            texts.append(str(arguments.get("new_text", "")))
        elif tool_name == "export_document":
            # Prefer exported content path already written; fall back to args only.
            texts.append(str(result.get("summary", "")))
            # Scan revised section bodies from return payload if present.
            for key in ("preview", "content"):
                if result.get(key):
                    texts.append(str(result[key]))
        elif tool_name == "write_file":
            texts.append(str(arguments.get("content", "")))
        else:
            return

        cited: list[str] = []
        for text in texts:
            for cid in extract_citation_ids(text):
                if cid not in cited:
                    cited.append(cid)
        if not cited:
            return

        unverified = [cid for cid in cited if cid not in self._evidence_citation_ids]
        result["citations_found"] = cited
        result["unverified_citations"] = unverified
        if unverified:
            note = (
                "Unverified citations (not in this Turn's retrieval/check_citation evidence): "
                + ", ".join(unverified)
            )
            prev = str(result.get("summary") or "")
            result["summary"] = f"{prev}; {note}" if prev else note
            result["citation_check"] = "unverified"
            record_tool_misuse(kind="unverified_citation", tool_name=tool_name)
        else:
            result["citation_check"] = "ok"


def _chunk_text(text: str, size: int = 16) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]