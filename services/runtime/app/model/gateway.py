from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol
from uuid import uuid4

from app.settings import settings


class ModelProviderTimeout(Exception):
    """Raised when model streaming exceeds configured timeout."""


@dataclass
class ModelResponse:
    text: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class ModelProvider(Protocol):
    async def stream(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        abort: asyncio.Event | None = None,
    ) -> AsyncIterator[str | ModelResponse]:
        ...


class StubModelProvider:
    """Deterministic provider for CI and smoke tests without API keys."""

    async def stream(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        abort: asyncio.Event | None = None,
    ) -> AsyncIterator[str | ModelResponse]:
        user_text = _user_text(messages)
        tool_names = {t["name"] for t in tools}
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        last_tool = _last_tool_name(messages)

        if _wants_stall(user_text) and not has_tool_result:
            while True:
                if abort and abort.is_set():
                    return
                await asyncio.sleep(0.5)
            return

        if _wants_timeout(user_text) and not has_tool_result:
            while True:
                if abort and abort.is_set():
                    return
                await asyncio.sleep(0.4)
                yield "."
            return

        if _wants_slow_stream(user_text) and not has_tool_result:
            for i in range(20):
                if abort and abort.is_set():
                    return
                await asyncio.sleep(0.1)
                yield f"stream-{i} "
            yield ModelResponse(text="stream done", output_tokens=20)
            return

        if "stub_echo" in tool_names and _is_smoke_message(user_text) and not has_tool_result:
            yield _tool_call("stub_echo", {"message": user_text})
            return

        if "slow_tool" in tool_names and _wants_slow_tool(user_text) and not has_tool_result:
            yield _tool_call("slow_tool", {"duration_ms": 8000})
            return

        if "run_command" in tool_names and _wants_approval(user_text) and not has_tool_result:
            yield _tool_call("run_command", {"command": "echo approval-test"})
            return

        if has_tool_result and last_tool == "run_command":
            if _tool_result_denied(messages):
                yield ModelResponse(text="agent.09 命令已拒绝", output_tokens=8)
                return
            yield ModelResponse(text="命令已执行", output_tokens=6)
            return

        if "check_citation" in tool_names and _wants_check_citation(user_text) and not has_tool_result:
            yield _tool_call(
                "check_citation",
                {"citation_id": "cite:ref-a", "source_path": "sources/ref-a.md"},
            )
            return

        if has_tool_result and last_tool == "check_citation":
            yield ModelResponse(text="citation valid", output_tokens=6)
            return

        if "export_document" in tool_names and _wants_export(user_text) and not has_tool_result:
            yield _tool_call("export_document", {"output_path": "exports/document.md"})
            return

        if has_tool_result and last_tool == "export_document":
            yield ModelResponse(text="文档已导出", output_tokens=6)
            return

        if "glob" in tool_names and _wants_glob(user_text) and not has_tool_result:
            yield _tool_call("glob", {"pattern": "*.md", "path": "."})
            return

        if has_tool_result and last_tool == "glob":
            yield ModelResponse(text="agent.08 glob 完成", output_tokens=6)
            return

        if "draft_section" in tool_names and (_wants_draft(user_text) or _wants_interview(user_text)) and not has_tool_result:
            section_id = "notes" if _wants_interview(user_text) else "02"
            yield _tool_call(
                "draft_section",
                {
                    "section_id": section_id,
                    "content": "访谈要点：背景、结论与待办。" if _wants_interview(user_text) else "第一节草稿内容。" * 8,
                },
            )
            return

        if "update_outline" in tool_names and _wants_outline(user_text) and not has_tool_result:
            yield _tool_call(
                "update_outline",
                {
                    "content": "# Doc\n- [ ] Section 1\n- [ ] Section 2\n",
                },
            )
            return

        if "update_plan" in tool_names and _wants_plan(user_text) and not has_tool_result:
            yield _tool_call(
                "update_plan",
                {
                    "items": [
                        {"id": "1", "title": "Read codebase", "status": "pending"},
                        {"id": "2", "title": "Propose patch", "status": "pending"},
                    ],
                    "summary": "agent.07 plan",
                },
            )
            return

        if has_tool_result and last_tool == "update_plan":
            yield ModelResponse(text="计划已更新", output_tokens=8)
            return

        if "search_sources" in tool_names and _wants_vector_index(user_text) and not has_tool_result:
            yield _tool_call("search_sources", {"query": "phase2-unique-term"})
            return

        if has_tool_result and last_tool == "search_sources" and _wants_vector_index(user_text):
            reply = "writing.07 召回 phase2-unique-term 自 sources/new-chunk.md"
            yield ModelResponse(text=reply, output_tokens=16)
            return

        if "search_sources" in tool_names and _wants_search(user_text, tool_names=tool_names) and not has_tool_result:
            yield _tool_call("search_sources", {"query": user_text})
            return

        if has_tool_result and last_tool == "search_sources":
            reply = "成稿引用 [cite:ref-a] 来自 sources/ref-a.md"
            for chunk in _chunk_text(reply):
                yield chunk
            yield ModelResponse(text=reply, output_tokens=20)
            return

        if "delegate" in tool_names and _wants_double_delegate(user_text) and not has_tool_result:
            yield _tool_call("delegate", {"task": user_text, "agent_type": "explore"})
            return

        if "delegate" in tool_names and _wants_delegate(user_text) and not has_tool_result:
            agent_type = "researcher" if "researcher" in user_text.lower() else "explore"
            yield _tool_call("delegate", {"task": user_text, "agent_type": agent_type})
            return

        if has_tool_result and last_tool == "delegate":
            if _wants_double_delegate(user_text):
                delegate_results = _delegate_tool_result_count(messages)
                if delegate_results < 2 and not _assistant_requested_verify_delegate(messages):
                    yield _tool_call("delegate", {"task": "verify explore findings", "agent_type": "verify"})
                    return
                yield ModelResponse(text="agent.06 explore→verify 串联完成", output_tokens=14)
                return
            yield ModelResponse(text="主 Turn 已整合子 agent 摘要", output_tokens=12)
            return

        if "search_codebase" in tool_names and _wants_codebase_search(user_text) and not has_tool_result:
            yield _tool_call("search_codebase", {"query": "AgentEngine"})
            return

        if has_tool_result and last_tool == "search_codebase" and "propose_patch" in tool_names:
            yield _tool_call(
                "propose_patch",
                {
                    "path": "README.md",
                    "old_text": "old",
                    "new_text": "patched via agent",
                    "summary": "agent patch",
                },
            )
            return

        if has_tool_result and last_tool == "read_file" and "propose_patch" in tool_names and (
            _wants_patch(user_text) or "agent.01" in user_text
        ):
            path = _extract_path(user_text) or "README.md"
            yield _tool_call(
                "propose_patch",
                {
                    "path": path,
                    "old_text": "旧正文",
                    "new_text": "简洁的新正文",
                    "summary": "read then patch",
                },
            )
            return

        if has_tool_result and last_tool == "read_file" and (
            "shared.04" in user_text or "compact" in user_text.lower()
        ):
            yield ModelResponse(text="继续处理大文件", output_tokens=8)
            return

        if "read_file" in tool_names and _wants_read(user_text) and not has_tool_result:
            path = _extract_path(user_text) or "README.md"
            if "large_file" in user_text:
                path = "large_file.md"
            yield _tool_call("read_file", {"path": path})
            return

        if "propose_patch" in tool_names and _wants_patch(user_text) and not has_tool_result:
            path = _extract_path(user_text) or "sections/01.md"
            yield _tool_call(
                "propose_patch",
                {
                    "path": path,
                    "old_text": "旧正文",
                    "new_text": "简洁的新正文",
                    "summary": "简化文稿",
                },
            )
            return

        reply = f"[stub] Acknowledged: {user_text[:200]}"
        for chunk in _chunk_text(reply):
            yield chunk
        yield ModelResponse(text=reply, output_tokens=len(reply) // 4)


def _tool_call(name: str, arguments: dict[str, Any]) -> ModelResponse:
    return ModelResponse(
        tool_calls=[{"id": f"{name}-{uuid4().hex[:8]}", "name": name, "input": arguments}],
        output_tokens=15,
    )


def _chunk_text(text: str, size: int = 12) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def _user_text(messages: list[dict]) -> str:
    parts: list[str] = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        for block in msg.get("content", []):
            if block.get("type") == "text":
                parts.append(str(block.get("text", "")))
    return " ".join(parts)


def _last_user_text(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        for block in msg.get("content", []):
            if block.get("type") == "text":
                return str(block.get("text", ""))
    return ""


def _last_tool_name(messages: list[dict]) -> str | None:
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if block.get("type") == "tool_use":
                return str(block.get("name"))
    return None


def _is_smoke_message(text: str) -> bool:
    lowered = text.lower()
    return "smoke" in lowered or lowered.startswith("phase 0") or "l0 golden" in lowered


def _wants_patch(text: str) -> bool:
    keywords = ("改", "patch", "简洁", "修订", "修改", "diff")
    return any(k in text.lower() for k in keywords)


def _wants_read(text: str) -> bool:
    keywords = ("read", "读取", "查看", "打开", "read_file")
    return any(k in text.lower() for k in keywords)


def _wants_outline(text: str) -> bool:
    keywords = ("大纲", "outline", "writing.01")
    return any(k in text.lower() for k in keywords)


def _wants_plan(text: str) -> bool:
    keywords = ("agent.07", "update_plan", "制定计划")
    return any(k in text.lower() for k in keywords) or "计划" in text


def _wants_draft(text: str) -> bool:
    keywords = ("draft_section", "流式", "writing.04")
    return any(k in text.lower() for k in keywords)


def _wants_interview(text: str) -> bool:
    keywords = ("interview.01", "访谈纪要", "访谈要点")
    return any(k in text.lower() for k in keywords)


def _wants_check_citation(text: str) -> bool:
    keywords = ("writing.08", "check_citation")
    return any(k in text.lower() for k in keywords)


def _wants_export(text: str) -> bool:
    keywords = ("writing.09", "export_document", "导出文档")
    return any(k in text.lower() for k in keywords)


def _wants_glob(text: str) -> bool:
    keywords = ("agent.08", "glob", "*.md")
    return any(k in text.lower() for k in keywords)


def _wants_search(text: str, *, tool_names: set[str] | None = None) -> bool:
    if tool_names and "delegate" in tool_names and _wants_delegate(text):
        return False
    keywords = ("引用", "search_sources", "writing.05", "writing.06", "调研")
    return any(k in text.lower() for k in keywords) or "资料" in text


def _wants_delegate(text: str) -> bool:
    if _wants_double_delegate(text):
        return True
    keywords = ("delegate", "researcher", "子 agent", "writing.06", "agent.05")
    return any(k in text.lower() for k in keywords)


def _wants_double_delegate(text: str) -> bool:
    keywords = ("agent.06", "explore→verify", "explore verify")
    return any(k in text.lower() for k in keywords)


def _wants_vector_index(text: str) -> bool:
    keywords = ("writing.07", "phase2-unique-term")
    return any(k in text.lower() for k in keywords)


def _assistant_requested_verify_delegate(messages: list[dict]) -> bool:
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if block.get("type") != "tool_use" or block.get("name") != "delegate":
                continue
            args = block.get("input") or {}
            if str(args.get("agent_type", "")).lower() == "verify":
                return True
    return False


def _delegate_tool_result_count(messages: list[dict]) -> int:
    count = 0
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        for block in msg.get("content", []):
            if not isinstance(block, dict):
                continue
            content = str(block.get("content") or "")
            if "subagent_id" in content:
                count += 1
                break
    return count


def _tool_result_denied(messages: list[dict]) -> bool:
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        for block in msg.get("content", []):
            if isinstance(block, dict):
                text = str(block.get("text") or block.get("content") or "")
            else:
                text = str(block)
            if '"status": "denied"' in text or '"status":"denied"' in text:
                return True
        return False
    return False


def _delegate_count(messages: list[dict]) -> int:
    count = 0
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "delegate":
                count += 1
    return count


def _wants_codebase_search(text: str) -> bool:
    keywords = ("search_codebase", "代码库", "agent.04")
    return any(k in text.lower() for k in keywords)


def _wants_approval(text: str) -> bool:
    keywords = ("approval", "run_command", "agent.03", "批准测试")
    return any(k in text.lower() for k in keywords)


def _wants_slow_tool(text: str) -> bool:
    keywords = ("slow_tool", "agent.02", "慢工具")
    return any(k in text.lower() for k in keywords)


def _wants_slow_stream(text: str) -> bool:
    keywords = ("slow stream", "shared.05", "流式取消")
    return any(k in text.lower() for k in keywords)


def _wants_stall(text: str) -> bool:
    keywords = ("shared.09", "stall_watchdog", "卡住检测")
    return any(k in text.lower() for k in keywords)


def _wants_timeout(text: str) -> bool:
    keywords = ("shared.07", "model_timeout", "超时测试")
    return any(k in text.lower() for k in keywords)


def _extract_path(text: str) -> str | None:
    import re

    m = re.search(r"[@`]?([\w./-]+\.(?:md|txt|py|ts|json|yaml))", text)
    return m.group(1) if m else None


class ModelGateway:
    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider
        self._abort_event = asyncio.Event()

    def abort_stream(self) -> None:
        self._abort_event.set()

    async def stream(self, *, messages: list[dict], tools: list[dict]) -> AsyncIterator[str | ModelResponse]:
        self._abort_event.clear()
        deadline = time.monotonic() + settings.model_timeout_seconds
        try:
            async for item in self._provider.stream(
                messages=messages,
                tools=tools,
                abort=self._abort_event,
            ):
                if self._abort_event.is_set():
                    return
                if time.monotonic() > deadline:
                    raise ModelProviderTimeout("model stream exceeded timeout")
                yield item
        finally:
            self._abort_event.clear()
