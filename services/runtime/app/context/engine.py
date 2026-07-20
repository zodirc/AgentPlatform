from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.context.policy import CompactionPolicy
from app.context.project import build_runtime_context, load_project_context
from app.context.summary import structured_summary_from_messages
from app.engine.state import TurnState
from app.tools.registry import ToolSpec

logger = logging.getLogger(__name__)

TOOL_RESULT_CHAR_BUDGET = 4_000
SHORT_TOOL_RESULT_MAX_CHARS = 800


class ToolExecutor:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs = {s.name: s for s in specs}

    async def run(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        arguments: dict[str, Any],
        state: TurnState,
        force_approval: bool = False,
    ) -> dict[str, Any]:
        spec = self._specs.get(tool_name)
        if spec is None:
            return {"error": f"Tool not available: {tool_name}"}
        if spec.requires_approval and not force_approval:
            return {
                "status": "approval_required",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
            }

        from app.settings import settings
        from app.tools.validate import validate_tool_arguments

        if settings.tool_schema_validate:
            invalid = validate_tool_arguments(
                tool_name=tool_name,
                arguments=arguments,
                parameters=spec.parameters,
            )
            if invalid is not None:
                from app.observability.metrics import record_tool_misuse

                record_tool_misuse(kind="invalid_arguments", tool_name=tool_name)
                return invalid

        timeout_s = spec.timeout_s
        try:
            result = await asyncio.wait_for(
                spec.handler(
                    **arguments,
                    turn_id=state.turn_id,
                    run_id=state.run_id,
                    session_id=state.session_id,
                ),
                timeout=timeout_s,
            )
            return result
        except asyncio.TimeoutError:
            return {
                "status": "timeout",
                "summary": f"tool {tool_name} timed out after {timeout_s:.0f}s",
            }
        except TypeError as exc:
            # Defensive: unexpected kwargs / missing positional after schema gate.
            return {
                "error": "invalid_arguments",
                "tool_name": tool_name,
                "summary": f"Tool {tool_name} rejected arguments: {exc}",
                "details": [str(exc)],
                "missing": [],
            }
        except Exception as exc:
            return {"error": str(exc)}


@dataclass
class ContextEnvelope:
    messages: list[dict[str, Any]]
    budget_report: dict[str, Any] = field(default_factory=dict)
    compaction_trace: list[dict[str, str]] = field(default_factory=list)
    project_context: str = ""
    runtime_context: str = ""
    included_tools: list[str] = field(default_factory=list)
    assemble_ms: float = 0.0
    system_prompt: str = ""


class ContextEngine:
    def __init__(
        self,
        *,
        policy: CompactionPolicy | None = None,
        token_budget: int | None = None,
    ) -> None:
        if policy is not None:
            self._policy = policy
        elif token_budget is not None:
            self._policy = CompactionPolicy.legacy_messages_budget(token_budget)
        else:
            self._policy = CompactionPolicy.from_settings()
        self.last_compaction_trace: list[dict[str, str]] = []
        self.last_budget_report: dict[str, Any] = {
            "tokens_before": 0,
            "tokens_after": 0,
            "token_budget": self._policy.model_window_tokens,
            "fill_ratio": 0.0,
        }
        self.last_assemble_ms: float = 0.0
        self._reuse_fingerprint: str | None = None
        self._reuse_messages: list[dict[str, Any]] | None = None

    def assemble(
        self,
        *,
        system_prompt: str,
        state: TurnState,
        tools: list[dict[str, Any]] | None = None,
        model_name: str | None = None,
    ) -> list[dict]:
        started = time.monotonic()
        envelope = self._build_envelope(
            state=state,
            system_prompt=system_prompt,
            tools=tools,
            model_name=model_name,
        )
        envelope.assemble_ms = (time.monotonic() - started) * 1000
        self._finalize_envelope(envelope, state.turn_id)
        return self._materialize_messages(envelope)

    async def assemble_async(
        self,
        *,
        system_prompt: str,
        state: TurnState,
        gateway: Any | None = None,
        tools: list[dict[str, Any]] | None = None,
        model_name: str | None = None,
        abort: Any | None = None,
    ) -> list[dict]:
        from app.context.compact_summarizer import summarize_messages_with_gateway

        started = time.monotonic()
        fingerprint = _assemble_fingerprint(system_prompt, state, tools)
        if (
            self._reuse_fingerprint == fingerprint
            and self._reuse_messages is not None
            and not any(
                t.get("detail") == "autocompact_pending"
                for t in (self.last_compaction_trace or [])
            )
        ):
            # Reuse only when fingerprint matches and no pending LLM compact needed.
            self.last_assemble_ms = 0.0
            self.last_budget_report = {
                **self.last_budget_report,
                "assemble_ms": 0.0,
            }
            return [dict(m) for m in self._reuse_messages]

        defer = gateway is not None
        envelope = self._build_envelope(
            state=state,
            system_prompt=system_prompt,
            tools=tools,
            defer_autocompact=defer,
            model_name=model_name,
        )
        trace = list(envelope.compaction_trace)
        messages = list(envelope.messages)

        if abort is not None and getattr(abort, "is_set", lambda: False)():
            envelope.assemble_ms = (time.monotonic() - started) * 1000
            self._finalize_envelope(envelope, state.turn_id)
            return self._materialize_messages(envelope)

        if gateway is not None and any(t.get("detail") == "autocompact_pending" for t in trace):
            compact_gateway = gateway
            if settings.compact_model_name.strip():
                from app.controller.session_context import load_session_owner_user_id
                from app.model.config import resolve_model_config
                from app.model.factory import create_gateway

                owner_user_id = await load_session_owner_user_id(state.session_id)
                cfg = await resolve_model_config(owner_user_id=owner_user_id)
                compact_gateway = create_gateway(
                    cfg,
                    messages=[],
                    scenario_id=state.scenario_id,
                    for_compact=True,
                )
            messages = [await summarize_messages_with_gateway(compact_gateway, state.messages)]
            trace = [t for t in trace if t.get("detail") != "autocompact_pending"]
            trace.append({"strategy": "compact", "detail": "autocompact_llm"})
            fill_ratio, window = _window_fill(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                policy=self._policy,
                project_context=envelope.project_context,
                runtime_context=envelope.runtime_context,
            )
            envelope.budget_report = {
                **envelope.budget_report,
                "tokens_after": window["tokens_after"],
                "messages_tokens": window["messages_tokens"],
                "fill_ratio": round(fill_ratio, 4),
            }
            envelope.messages = messages
            envelope.compaction_trace = trace

        envelope.assemble_ms = (time.monotonic() - started) * 1000
        self._finalize_envelope(envelope, state.turn_id)
        result = self._materialize_messages(envelope)
        self._reuse_fingerprint = fingerprint
        self._reuse_messages = [dict(m) for m in result]
        return result

    def _materialize_messages(self, envelope: ContextEnvelope) -> list[dict[str, Any]]:
        system_text = envelope.system_prompt
        if envelope.project_context:
            system_text = f"{system_text}\n\n[project_context]\n{envelope.project_context}"
        system = {"role": "system", "content": [{"type": "text", "text": system_text}]}
        out: list[dict[str, Any]] = [system]
        if envelope.runtime_context:
            out.append(
                {
                    "role": "user",
                    "content": [{"type": "text", "text": envelope.runtime_context}],
                }
            )
        out.extend(envelope.messages)
        return out

    def _finalize_envelope(self, envelope: ContextEnvelope, turn_id: Any) -> None:
        self.last_compaction_trace = envelope.compaction_trace
        self.last_budget_report = dict(envelope.budget_report)
        self.last_budget_report["assemble_ms"] = envelope.assemble_ms
        self.last_budget_report["project_tokens"] = estimate_payload_tokens(
            envelope.project_context
        )
        self.last_budget_report["runtime_tokens"] = estimate_payload_tokens(
            envelope.runtime_context
        )
        self.last_assemble_ms = envelope.assemble_ms
        if envelope.compaction_trace:
            logger.info(
                "context compaction turn_id=%s strategies=%s before=%s after=%s fill=%s",
                turn_id,
                [t.get("strategy") for t in envelope.compaction_trace],
                envelope.budget_report.get("tokens_before"),
                envelope.budget_report.get("tokens_after"),
                envelope.budget_report.get("fill_ratio"),
            )

    def _build_envelope(
        self,
        *,
        state: TurnState,
        system_prompt: str,
        tools: list[dict[str, Any]] | None,
        defer_autocompact: bool = False,
        model_name: str | None = None,
    ) -> ContextEnvelope:
        policy = self._policy
        messages = [dict(m) for m in state.messages]
        trace: list[dict[str, str]] = []
        project_context = load_project_context(session_id=state.session_id)
        runtime_context = build_runtime_context(
            scenario_id=state.scenario_id,
            step_count=state.step_count,
            max_steps=state.max_steps,
            model_name=model_name,
            plan_hint=state.plan_hint,
        )
        included_tools = [str(t.get("name", "")) for t in (tools or []) if t.get("name")]

        _, window_before = _window_fill(
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
            policy=policy,
            project_context=project_context,
            runtime_context=runtime_context,
        )
        tokens_before = window_before["tokens_after"]

        messages, budgeted = _apply_tool_result_budget(
            messages, TOOL_RESULT_CHAR_BUDGET, preserve_short=True
        )
        if budgeted:
            trace.append({"strategy": "budget", "detail": f"truncated_{budgeted}_tool_results"})

        messages, micro = _microcompact_tool_results(messages)
        if micro:
            trace.append({"strategy": "microcompact", "detail": f"folded_{micro}_tool_results"})

        fill_ratio, _ = _window_fill(
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
            policy=policy,
            project_context=project_context,
            runtime_context=runtime_context,
        )
        if fill_ratio >= policy.fill_collapse and len(messages) > 4:
            messages = _collapse_tool_history(
                messages,
                trace,
                system_prompt=system_prompt,
                tools=tools,
                policy=policy,
            )

        while len(messages) > 1:
            fill_ratio, _ = _window_fill(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                policy=policy,
                project_context=project_context,
                runtime_context=runtime_context,
            )
            if fill_ratio < policy.fill_snip:
                break
            if not _pop_oldest_message_group(messages):
                break
            trace.append({"strategy": "snip", "detail": "dropped_oldest_message"})

        fill_ratio, _ = _window_fill(
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
            policy=policy,
            project_context=project_context,
            runtime_context=runtime_context,
        )
        if fill_ratio >= policy.fill_autocompact and messages:
            if defer_autocompact:
                trace.append({"strategy": "compact", "detail": "autocompact_pending"})
            else:
                messages = [_summarize_messages(messages)]
                trace.append({"strategy": "compact", "detail": "autocompact_summary"})

        fill_ratio, window_after = _window_fill(
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
            policy=policy,
            project_context=project_context,
            runtime_context=runtime_context,
        )
        reserve_tokens = (
            policy.output_reserve_tokens
            + window_after["system_tokens"]
            + window_after["tools_tokens"]
        )
        return ContextEnvelope(
            messages=messages,
            budget_report={
                "tokens_before": tokens_before,
                "tokens_after": window_after["tokens_after"],
                "messages_tokens": window_after["messages_tokens"],
                "system_tokens": window_after["system_tokens"],
                "tools_tokens": window_after["tools_tokens"],
                "project_tokens": window_after.get("project_tokens", 0),
                "runtime_tokens": window_after.get("runtime_tokens", 0),
                "token_budget": policy.model_window_tokens,
                "reserve_tokens": reserve_tokens,
                "fill_ratio": round(fill_ratio, 4),
            },
            compaction_trace=trace,
            project_context=project_context,
            runtime_context=runtime_context,
            included_tools=included_tools,
            system_prompt=system_prompt,
        )




def _system_message(system_prompt: str) -> dict[str, Any]:
    return {"role": "system", "content": [{"type": "text", "text": system_prompt}]}


def _assemble_fingerprint(
    system_prompt: str,
    state: TurnState,
    tools: list[dict[str, Any]] | None,
) -> str:
    tool_names = ",".join(str(t.get("name", "")) for t in (tools or []))
    return (
        f"{hash(system_prompt)}|{state.step_count}|{len(state.messages)}|"
        f"{state.scenario_id}|{tool_names}|{state.max_steps}"
    )


def _window_fill(
    *,
    messages: list[dict[str, Any]],
    system_prompt: str,
    tools: list[dict[str, Any]] | None,
    policy: CompactionPolicy,
    project_context: str = "",
    runtime_context: str = "",
) -> tuple[float, dict[str, int]]:
    system_text = system_prompt
    if project_context:
        system_text = f"{system_text}\n\n[project_context]\n{project_context}"
    assembled = [_system_message(system_text)]
    if runtime_context:
        assembled.append(
            {"role": "user", "content": [{"type": "text", "text": runtime_context}]}
        )
    assembled.extend(messages)
    window = estimate_assembled_window(messages=assembled, tools=tools)
    project_tokens = estimate_payload_tokens(project_context)
    runtime_tokens = estimate_payload_tokens(runtime_context)
    window = {
        **window,
        "project_tokens": project_tokens,
        "runtime_tokens": runtime_tokens,
    }
    usable = max(1, policy.model_window_tokens - policy.output_reserve_tokens)
    fill_ratio = window["tokens_after"] / usable
    return fill_ratio, window


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return max(1, estimate_payload_tokens(messages))


def estimate_payload_tokens(payload: Any) -> int:
    """Cheap token estimate that prefers overestimate (AH4).

    CJK characters ~1 token; ASCII ~1/4. Avoids optimistic chars/4 overflow.
    """
    if payload is None:
        return 0
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False)
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        if ord(ch) > 0x2E80:
            cjk += 1
        else:
            other += 1
    return max(1, cjk + (other + 2) // 3)


def estimate_assembled_window(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Estimate tokens for the actual model request window.

    Includes system/user/assistant/tool messages and tool schemas, which is what
    the provider bills against — not just TurnState.messages.
    """
    system_tokens = 0
    message_tokens = 0
    for msg in messages:
        toks = estimate_payload_tokens(msg)
        if msg.get("role") == "system":
            system_tokens += toks
        else:
            message_tokens += toks
    tools_tokens = estimate_payload_tokens(tools or [])
    return {
        "system_tokens": system_tokens,
        "tools_tokens": tools_tokens,
        "messages_tokens": message_tokens,
        "tokens_after": system_tokens + tools_tokens + message_tokens,
    }


def _message_text(msg: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in msg.get("content", []):
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return " ".join(parts).strip()


def estimate_window_breakdown(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Classify assembled-window tokens into Cursor-like categories."""
    window = estimate_assembled_window(messages=messages, tools=tools)
    breakdown = {
        "system": 0,
        "tools": window["tools_tokens"],
        "session": 0,
        "user": 0,
        "assistant": 0,
        "tool_results": 0,
        "compaction": 0,
        "project": 0,
        "runtime": 0,
    }
    for msg in messages:
        role = msg.get("role")
        toks = estimate_payload_tokens(msg)
        if role == "system":
            text = _message_text(msg)
            if "[project_context]" in text:
                # Approximate split: project section after marker.
                idx = text.find("[project_context]")
                sys_part = text[:idx]
                proj_part = text[idx:]
                breakdown["system"] += estimate_payload_tokens(sys_part)
                breakdown["project"] += estimate_payload_tokens(proj_part)
            else:
                breakdown["system"] += toks
            continue
        text = _message_text(msg)
        lower = text.lower()
        if role == "tool":
            breakdown["tool_results"] += toks
        elif text.startswith("[runtime_context]"):
            breakdown["runtime"] += toks
        elif "session context" in lower:
            breakdown["session"] += toks
        elif text.startswith("[") and any(
            marker in lower
            for marker in ("microcompact", "collapsed", "autocompact", "pinned tool")
        ):
            breakdown["compaction"] += toks
        elif role == "user":
            breakdown["user"] += toks
        elif role == "assistant":
            breakdown["assistant"] += toks
    return breakdown


def _tool_result_text(msg: dict[str, Any]) -> str:
    if msg.get("role") != "tool":
        return ""
    for block in msg.get("content", []):
        if block.get("type") == "tool_result":
            return str(block.get("content", ""))
    return ""


def _is_pinned_short_tool_result(text: str) -> bool:
    """Read-only directory/listing results stay visible through compaction."""
    if not text or len(text) > SHORT_TOOL_RESULT_MAX_CHARS:
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    if "entries" in data and "path" in data:
        return True
    if "files" in data and "pattern" in data:
        return True
    if "matches" in data or "hits" in data:
        return True
    if "error" in data:
        return True
    return False


def _pinned_tool_digest(messages: list[dict[str, Any]]) -> str:
    snippets: list[str] = []
    for msg in messages:
        body = _tool_result_text(msg)
        if _is_pinned_short_tool_result(body):
            snippets.append(body.replace("\n", " ")[:160])
    if not snippets:
        return ""
    joined = " | ".join(snippets[:6])
    return f"[pinned tool results preserved: {joined}]"


def _dropped_tools_summary(messages: list[dict[str, Any]]) -> str:
    """Count tool_use names in collapsed middle (deterministic, no importance ranking)."""
    counts: dict[str, int] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []) or []:
            if block.get("type") != "tool_use":
                continue
            name = str(block.get("name") or "unknown")
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return ""
    parts = [
        f"{name}×{count}"
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return "dropped tools: " + ", ".join(parts)


def _apply_tool_result_budget(
    messages: list[dict[str, Any]],
    char_budget: int,
    *,
    preserve_short: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    out: list[dict[str, Any]] = []
    truncated = 0
    for msg in messages:
        if msg.get("role") != "tool":
            out.append(msg)
            continue
        content = msg.get("content", [])
        new_blocks = []
        for block in content:
            if block.get("type") != "tool_result":
                new_blocks.append(block)
                continue
            text = str(block.get("content", ""))
            if preserve_short and _is_pinned_short_tool_result(text):
                new_blocks.append(block)
                continue
            if len(text) > char_budget:
                text = text[:char_budget] + "\n...[budget_truncated]"
                truncated += 1
            new_blocks.append({**block, "content": text})
        out.append({**msg, "content": new_blocks})
    return out, truncated


def _message_has_tool_use(msg: dict[str, Any]) -> bool:
    return msg.get("role") == "assistant" and any(
        block.get("type") == "tool_use" for block in msg.get("content", [])
    )


def _microcompact_tool_results(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Fold runs of consecutive tool results into a single pointer message.

    Skips runs that immediately follow an assistant tool_use block — OpenAI-compatible
    providers (e.g. DeepSeek) require each tool_call_id to have a matching tool message.
    """
    if len(messages) < 3:
        return messages, 0
    out: list[dict[str, Any]] = []
    folded = 0
    index = 0
    while index < len(messages):
        msg = messages[index]
        prev = out[-1] if out else None
        if msg.get("role") == "tool" and prev is not None and _message_has_tool_use(prev):
            while index < len(messages) and messages[index].get("role") == "tool":
                out.append(messages[index])
                index += 1
            continue
        if msg.get("role") != "tool":
            out.append(msg)
            index += 1
            continue
        run = [msg]
        next_index = index + 1
        while next_index < len(messages) and messages[next_index].get("role") == "tool":
            run.append(messages[next_index])
            next_index += 1
        if len(run) >= 2:
            bodies = [_tool_result_text(m) for m in run]
            if bodies and all(_is_pinned_short_tool_result(b) for b in bodies):
                out.extend(run)
            else:
                folded += len(run) - 1
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"[microcompact: folded {len(run)} tool results; "
                                    "re-read with tools if needed]"
                                ),
                            }
                        ],
                    }
                )
        else:
            out.append(msg)
        index = next_index
    return out, folded


def _pop_oldest_message_group(messages: list[dict[str, Any]]) -> bool:
    """Drop the oldest coherent prefix without leaving orphan tool messages."""
    while messages and messages[0].get("role") == "tool":
        messages.pop(0)
    if len(messages) <= 1:
        return False
    if messages[0].get("role") == "assistant" and _message_has_tool_use(messages[0]):
        end = 1
        while end < len(messages) and messages[end].get("role") == "tool":
            end += 1
        if end >= len(messages):
            return False
        del messages[0:end]
        return True
    if messages[0].get("role") == "user":
        end = 1
        while end < len(messages) and messages[end].get("role") != "user":
            end += 1
        if end >= len(messages):
            return False
        del messages[0:end]
        return True
    messages.pop(0)
    return True


def _align_tail_start(messages: list[dict[str, Any]], tail_start: int) -> int:
    """Walk backward so the tail does not start inside a tool-result run."""
    index = max(0, min(tail_start, len(messages) - 1))
    while index > 0 and messages[index].get("role") == "tool":
        index -= 1
    if index >= 0 and _message_has_tool_use(messages[index]):
        return index
    return max(1, tail_start)


def _tail_start_for_token_budget(messages: list[dict[str, Any]], hot_budget: int) -> int:
    total = 0
    index = len(messages)
    while index > 0 and total < hot_budget:
        index -= 1
        total += _estimate_tokens([messages[index]])
    return _align_tail_start(messages, index)


def _collapse_tool_history(
    messages: list[dict[str, Any]],
    trace: list[dict[str, str]],
    *,
    system_prompt: str,
    tools: list[dict[str, Any]] | None,
    policy: CompactionPolicy,
) -> list[dict[str, Any]]:
    """Fold older messages into a pointer block without breaking assistant/tool pairs."""
    fill_ratio, window = _window_fill(
        messages=messages,
        system_prompt=system_prompt,
        tools=tools,
        policy=policy,
    )
    if fill_ratio < policy.fill_collapse or len(messages) <= 4:
        return messages

    working = max(
        1,
        policy.model_window_tokens
        - policy.output_reserve_tokens
        - window["system_tokens"]
        - window["tools_tokens"],
    )
    hot_budget = max(1, int(working * policy.hot_zone_ratio))
    tail_start = _tail_start_for_token_budget(messages, hot_budget)
    head = messages[:1] if messages and messages[0].get("role") == "user" else []
    middle = messages[len(head) : tail_start]
    tail = messages[tail_start:]
    if len(head) + len(tail) >= len(messages) or not middle:
        return messages
    collapsed = len(messages) - len(head) - len(tail)
    trace.append({"strategy": "collapse", "detail": f"collapsed_{collapsed}_messages"})
    dropped = _dropped_tools_summary(middle)
    pinned = _pinned_tool_digest(middle)
    parts = [f"[collapsed {collapsed} earlier messages"]
    if dropped:
        parts.append(f"; {dropped}")
    parts.append("; recent context preserved]")
    pointer_text = "".join(parts)
    if pinned:
        pointer_text = f"{pointer_text} {pinned}"
    pointer = {
        "role": "user",
        "content": [{"type": "text", "text": pointer_text}],
    }
    return [*head, pointer, *tail]


def _summarize_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic autocompact with structured fields."""
    summary = structured_summary_from_messages(messages)
    if not summary.narrative:
        summary.narrative = f"{len(messages)} earlier messages compacted"
    return {
        "role": "user",
        "content": [{"type": "text", "text": summary.to_autocompact_text()}],
    }
