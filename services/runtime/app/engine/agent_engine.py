from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

from app.context.engine import ContextEngine, ToolExecutor
from app.context.policy import CompactionPolicy
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


_TOOL_EVENTS: dict[str, str] = {
    "update_outline": "outline.updated",
    "update_plan": "turn.plan",
}

_CACHEABLE_TOOLS = frozenset({"list_dir", "glob", "grep", "read_file", "search_sources"})


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
    ) -> None:
        self._gateway = gateway
        self._executor = ToolExecutor(tools)
        self._system_prompt = system_prompt
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
        self._evidence_citation_ids: set[str] = set()
        self._tool_specs = list(tools)
        self._openai_tools = self._tools_payload(tools)

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
                messages = await self._context.assemble_async(
                    system_prompt=self._system_prompt,
                    state=state,
                    gateway=self._gateway,
                    tools=step_tools,
                )

                from app.context.engine import estimate_window_breakdown

                report = self._context.last_budget_report
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
                        "reserve_tokens": int(report.get("reserve_tokens", 0)),
                        "fill_ratio": float(report.get("fill_ratio", 0.0)),
                        "assemble_ms": float(report.get("assemble_ms", self._context.last_assemble_ms)),
                        "breakdown": breakdown,
                        "source": "estimated",
                        "strategies": strategies,
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
                    async for chunk in stream:
                        await _ensure_step_within_budget()
                        cancelled, force = await self._check_cancel()
                        if cancelled:
                            state.cancelled = True
                            state.cancel_force = force
                            step_outcome = "cancelled"
                            abort = getattr(self._gateway, "abort_stream", None)
                            if abort is not None:
                                abort()
                            break

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
                except ModelError:
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
                usage_payload: dict[str, Any] = {
                    "step_index": step_index,
                    "input_tokens": state.usage.input_tokens,
                    "output_tokens": state.usage.output_tokens,
                    "step_input_tokens": step_input_tokens,
                    "step_output_tokens": step_output_tokens,
                    "source": usage_source,
                    "retry_count": retry_count,
                }
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
                    summaries = await asyncio.gather(
                        *[
                            self._run_tool(item, state, step_index, ensure_step_budget)
                            for item in batch
                        ]
                    )
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

    async def _run_tool(
        self,
        call: dict[str, Any],
        state: TurnState,
        step_index: int,
        ensure_step_budget: Callable[[], Awaitable[None]] | None = None,
    ) -> str | None:
        tool_call_id = call["id"]
        tool_name = call["name"]
        arguments = call.get("input", {})

        await self._write_event(
            event_type="tool.started",
            payload={"tool_call_id": tool_call_id, "tool_name": tool_name, "arguments": arguments},
            step_index=step_index,
        )

        if tool_name == "search_sources":
            budget = settings.search_sources_max_per_turn
            if budget > 0:
                self._search_sources_calls += 1
                if self._search_sources_calls > budget:
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
                        payload={
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "status": "error",
                            "summary": result["summary"],
                        },
                        step_index=step_index,
                    )
                    record_tool_call(tool_name=tool_name, status="error")
                    return result["summary"]

        if tool_name == "draft_section":
            content = str(arguments.get("content", ""))
            section_id = str(arguments.get("section_id", "01"))
            for delta in _chunk_text(content, 16):
                if ensure_step_budget is not None:
                    await ensure_step_budget()
                cancelled, force = await self._check_cancel()
                if cancelled:
                    state.cancelled = True
                    state.cancel_force = force
                    return "CANCELLED"
                await self._write_event(
                    event_type="section.draft.delta",
                    payload={"section_id": section_id, "delta": delta},
                    step_index=step_index,
                )

        result = self._lookup_tool_cache(tool_name, arguments)
        if result is None:
            result = await self._executor.run(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                arguments=arguments,
                state=state,
            )
            self._store_tool_cache(tool_name, arguments, result)

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
                payload={
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "status": "timeout",
                    "summary": summary,
                },
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
            await self._write_event(
                event_type=event_type,
                payload=result,
                step_index=step_index,
            )

        if tool_name == "search_sources":
            mode = str(result.get("retrieval", "none"))
            # keyword-fallback is an intentional observability mode (docs/15); still emit.
            if mode in {"vector", "keyword", "hybrid", "keyword-fallback"}:
                raw_hits = result.get("hits", [])
                hits_preview: list[dict[str, Any]] = []
                if isinstance(raw_hits, list):
                    for hit in raw_hits[:5]:
                        if not isinstance(hit, dict):
                            continue
                        preview: dict[str, Any] = {
                            "path": str(hit.get("path", "")),
                            "excerpt": str(hit.get("excerpt", ""))[:200],
                        }
                        if hit.get("citation_id"):
                            preview["citation_id"] = str(hit["citation_id"])
                        if hit.get("chunk_id"):
                            preview["chunk_id"] = str(hit["chunk_id"])
                        if hit.get("score") is not None:
                            preview["score"] = hit["score"]
                        hits_preview.append(preview)
                retrieval_payload: dict[str, Any] = {
                    "query": str(result.get("query", "")),
                    "mode": mode,
                    "hit_count": len(raw_hits) if isinstance(raw_hits, list) else 0,
                    "summary": str(result.get("summary", ""))[:512],
                    "hits": hits_preview,
                }
                index_info = result.get("index")
                if isinstance(index_info, dict):
                    retrieval_payload["index"] = index_info
                filters_info = result.get("filters")
                if isinstance(filters_info, dict):
                    retrieval_payload["filters"] = filters_info
                await self._write_event(
                    event_type="retrieval.completed",
                    payload=retrieval_payload,
                    step_index=step_index,
                )

        if tool_name == "propose_patch" and "patch_id" in result:
            await self._write_event(
                event_type="patch.proposed",
                payload=result,
                step_index=step_index,
            )
            if (
                state.scenario_id == "writing"
                and settings.writing_patch_auto_apply
                and str(result.get("status") or "") == "pending"
                and not result.get("error")
            ):
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
        completed_payload: dict[str, Any] = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "status": tool_status,
            "summary": summary,
        }
        if tool_name == "export_document":
            completed_payload.update(
                {
                    "delivery_status": str(result.get("delivery_status", "failed")),
                    "delivery_issues": list(result.get("delivery_issues") or []),
                    "output_path": str(result.get("output_path", "")),
                }
            )
            if result.get("bytes_written") is not None:
                completed_payload["bytes_written"] = int(result["bytes_written"])
        await self._write_event(
            event_type="tool.completed",
            payload=completed_payload,
            step_index=step_index,
        )
        record_tool_call(tool_name=tool_name, status=tool_status)
        is_error = bool(result.get("error")) or tool_status == "error"
        state.messages.append(
            tool_result_message(tool_call_id, json.dumps(result, ensure_ascii=False), is_error=is_error)
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
        return str(summary)

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