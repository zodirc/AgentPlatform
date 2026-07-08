from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.engine.state import TurnState
from app.tools.registry import ToolSpec

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_BUDGET = 12_000
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
        timeout_s = spec.timeout_s
        try:
            result = await asyncio.wait_for(
                spec.handler(**arguments, turn_id=state.turn_id, run_id=state.run_id),
                timeout=timeout_s,
            )
            return result
        except asyncio.TimeoutError:
            return {
                "status": "timeout",
                "summary": f"tool {tool_name} timed out after {timeout_s:.0f}s",
            }
        except Exception as exc:
            return {"error": str(exc)}


@dataclass
class ContextEnvelope:
    messages: list[dict[str, Any]]
    budget_report: dict[str, Any] = field(default_factory=dict)
    compaction_trace: list[dict[str, str]] = field(default_factory=list)


class ContextEngine:
    def __init__(self, *, token_budget: int = DEFAULT_TOKEN_BUDGET) -> None:
        self._token_budget = token_budget
        self.last_compaction_trace: list[dict[str, str]] = []
        self.last_budget_report: dict[str, Any] = {
            "tokens_before": 0,
            "tokens_after": 0,
            "token_budget": token_budget,
        }

    def assemble(self, *, system_prompt: str, state: TurnState) -> list[dict]:
        envelope = self._build_envelope(state=state)
        self.last_compaction_trace = envelope.compaction_trace
        self.last_budget_report = dict(envelope.budget_report)
        if envelope.compaction_trace:
            logger.info(
                "context compaction turn_id=%s strategies=%s before=%s after=%s",
                state.turn_id,
                [t.get("strategy") for t in envelope.compaction_trace],
                envelope.budget_report.get("tokens_before"),
                envelope.budget_report.get("tokens_after"),
            )
        system = {"role": "system", "content": [{"type": "text", "text": system_prompt}]}
        return [system, *envelope.messages]

    async def assemble_async(
        self,
        *,
        system_prompt: str,
        state: TurnState,
        gateway: Any | None = None,
    ) -> list[dict]:
        from app.context.compact_summarizer import summarize_messages_with_gateway

        defer = gateway is not None
        envelope = self._build_envelope(state=state, defer_autocompact=defer)
        trace = list(envelope.compaction_trace)
        messages = list(envelope.messages)

        if gateway is not None and any(t.get("detail") == "autocompact_pending" for t in trace):
            messages = [await summarize_messages_with_gateway(gateway, state.messages)]
            trace = [t for t in trace if t.get("detail") != "autocompact_pending"]
            trace.append({"strategy": "compact", "detail": "autocompact_llm"})
            tokens_after = _estimate_tokens(messages)
            envelope.budget_report = {
                **envelope.budget_report,
                "tokens_after": tokens_after,
            }

        self.last_compaction_trace = trace
        self.last_budget_report = dict(envelope.budget_report)
        if trace:
            logger.info(
                "context compaction turn_id=%s strategies=%s before=%s after=%s",
                state.turn_id,
                [t.get("strategy") for t in trace],
                envelope.budget_report.get("tokens_before"),
                envelope.budget_report.get("tokens_after"),
            )
        system = {"role": "system", "content": [{"type": "text", "text": system_prompt}]}
        return [system, *messages]

    def _build_envelope(self, *, state: TurnState, defer_autocompact: bool = False) -> ContextEnvelope:
        messages = [dict(m) for m in state.messages]
        trace: list[dict[str, str]] = []
        tokens_before = _estimate_tokens(messages)

        messages, budgeted = _apply_tool_result_budget(
            messages, TOOL_RESULT_CHAR_BUDGET, preserve_short=True
        )
        if budgeted:
            trace.append({"strategy": "budget", "detail": f"truncated_{budgeted}_tool_results"})

        messages, micro = _microcompact_tool_results(messages)
        if micro:
            trace.append({"strategy": "microcompact", "detail": f"folded_{micro}_tool_results"})

        while _estimate_tokens(messages) > self._token_budget and len(messages) > 1:
            if not _pop_oldest_message_group(messages):
                break
            trace.append({"strategy": "snip", "detail": "dropped_oldest_message"})

        if len(messages) > 6:
            messages = _collapse_tool_history(messages, trace)

        tokens_after = _estimate_tokens(messages)
        if tokens_after > self._token_budget and messages:
            if defer_autocompact:
                trace.append({"strategy": "compact", "detail": "autocompact_pending"})
            else:
                messages = [_summarize_messages(messages)]
                trace.append({"strategy": "compact", "detail": "autocompact_summary"})

        tokens_after = _estimate_tokens(messages)
        return ContextEnvelope(
            messages=messages,
            budget_report={
                "tokens_before": tokens_before,
                "tokens_after": tokens_after,
                "token_budget": self._token_budget,
            },
            compaction_trace=trace,
        )


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return max(1, len(json.dumps(messages, ensure_ascii=False)) // 4)


def estimate_payload_tokens(payload: Any) -> int:
    """Rough token estimate for any JSON-serializable payload (chars/4)."""
    if payload is None:
        return 0
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False)
    return max(0, (len(text) + 3) // 4)


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
                                "text": f"[microcompact: folded {len(run)} tool results; re-read with tools if needed]",
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


def _collapse_tool_history(messages: list[dict[str, Any]], trace: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Fold older messages into a pointer block without breaking assistant/tool pairs."""
    if len(messages) <= 10:
        return messages
    keep = 6
    tail_start = _align_tail_start(messages, max(1, len(messages) - keep))
    head = messages[:1] if messages and messages[0].get("role") == "user" else []
    middle = messages[len(head) : tail_start]
    tail = messages[tail_start:]
    if len(head) + len(tail) >= len(messages):
        return messages
    collapsed = len(messages) - len(head) - len(tail)
    trace.append({"strategy": "collapse", "detail": f"collapsed_{collapsed}_messages"})
    pinned = _pinned_tool_digest(middle)
    pointer_text = f"[collapsed {collapsed} earlier messages; recent context preserved]"
    if pinned:
        pointer_text = f"{pointer_text} {pinned}"
    pointer = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": pointer_text,
            }
        ],
    }
    return [*head, pointer, *tail]


def _summarize_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic autocompact: preserve recent user/assistant snippets and tool names."""
    user_bits: list[str] = []
    assistant_bits: list[str] = []
    tool_names: list[str] = []

    for msg in messages:
        role = msg.get("role")
        for block in msg.get("content", []):
            if block.get("type") == "text":
                text = str(block.get("text", "")).strip()
                if not text or text.startswith("["):
                    continue
                if role == "user" and len(user_bits) < 2:
                    user_bits.append(text[:120])
                elif role == "assistant" and len(assistant_bits) < 2:
                    assistant_bits.append(text[:120])
            elif block.get("type") == "tool_use":
                name = str(block.get("name", ""))
                if name:
                    tool_names.append(name)
            elif block.get("type") == "tool_result":
                content = str(block.get("content", ""))[:80]
                if content:
                    tool_names.append(f"result:{content[:40]}")

    parts = [f"{len(messages)} earlier messages compacted"]
    if user_bits:
        parts.append(f"user={user_bits[-1]!r}")
    if assistant_bits:
        parts.append(f"assistant={assistant_bits[-1]!r}")
    if tool_names:
        parts.append(f"tools={','.join(tool_names[-4:])}")

    return {
        "role": "user",
        "content": [{"type": "text", "text": f"[autocompact: {'; '.join(parts)}]"}],
    }
