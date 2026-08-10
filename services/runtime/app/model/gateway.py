from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol
from uuid import uuid4

from app.settings import settings

logger = logging.getLogger(__name__)


class ModelError(Exception):
    """Base for model harness failures (distinct from tool/step errors)."""


class ModelTransientError(ModelError):
    """Retryable before any stream output (429/5xx/connect/first-byte timeout)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class ModelFatalError(ModelError):
    """Non-retryable model failure, or failure after streaming already started."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ModelProviderTimeout(ModelError):
    """Raised when model streaming exceeds configured timeout."""


@dataclass
class ModelResponse:
    text: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True)
class StreamActivity:
    """Provider liveness / reasoning signal before text / final ModelResponse.

    OpenAI-compatible models (e.g. DeepSeek) may stream ``reasoning_content`` or
    ``tool_calls`` for a long time with ``content: null``. Gateway first-byte
    timeout waits on the first yielded item — without this signal the harness
    falsely times out while SSE bytes are still arriving.

    When ``text`` is non-empty, the engine forwards it as ``turn.thinking.delta``
    for ephemeral UI only (not assistant output / not projected into history).
    """

    kind: str = "sse"
    text: str = ""


class AbortSignal(Protocol):
    def is_set(self) -> bool: ...

    async def wait(self) -> None: ...


class ModelProvider(Protocol):
    def stream(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        abort: AbortSignal | None = None,
    ) -> AsyncIterator[str | ModelResponse | StreamActivity]:
        ...

class _OrAbort:
    """Duck-typed abort: set when either cancel or attempt-abort fires."""

    def __init__(self, *events: asyncio.Event) -> None:
        self._events = events

    def is_set(self) -> bool:
        return any(event.is_set() for event in self._events)

    async def wait(self) -> None:
        if self.is_set():
            return
        tasks = [asyncio.create_task(event.wait()) for event in self._events]
        try:
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise


class StubModelProvider:
    """Deterministic provider for CI and smoke tests without API keys."""

    async def stream(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        abort: asyncio.Event | None = None,
    ) -> AsyncIterator[str | ModelResponse]:
        # Route on intent only — exclude platform banners ([writing|runtime|project]_context)
        # so work_index phrases like `draft_section` / `propose_patch` cannot steal goldens.
        user_text = _intent_user_text(messages) or _user_text(messages)
        tool_names = {t["name"] for t in tools}
        has_tool_result = _has_tool_result(messages)
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

        # AQ2: /test → run_tests before approval (TEST_EXPAND mentions run_command).
        if "run_tests" in tool_names and _wants_run_tests(user_text) and not has_tool_result:
            yield _tool_call("run_tests", {"command": "pytest -q"})
            return

        if has_tool_result and last_tool == "run_tests" and _wants_run_tests(user_text):
            yield ModelResponse(text="agent.11 tests finished", output_tokens=8)
            return

        if "read_lints" in tool_names and _wants_run_lints(user_text) and not has_tool_result:
            yield _tool_call("read_lints", {"path": "."})
            return

        if has_tool_result and last_tool == "read_lints" and _wants_run_lints(user_text):
            yield ModelResponse(text="agent.12 lints checked", output_tokens=8)
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

        # writing.10: draft → export current_draft. Match golden id on intent *or*
        # full user text (compaction may fold the original message into [autocompact]).
        if "export_document" in tool_names and (
            _wants_draft_export(user_text) or _wants_draft_export(_user_text(messages))
        ):
            if not has_tool_result:
                yield _tool_call(
                    "draft_section",
                    {"section_id": "a", "content": "Current turn draft for export."},
                )
                return
            if last_tool == "export_document":
                if _export_delivery_failed(messages):
                    yield ModelResponse(
                        text="writing.10 export delivery failed",
                        output_tokens=8,
                    )
                    return
                yield ModelResponse(text="本轮草稿已导出", output_tokens=7)
                return
            # Any other prior tool (normally draft_section) → export. Do not fall
            # through to generic stub ack or other routers mid writing.10.
            yield _tool_call(
                "export_document",
                {
                    "section_ids": ["a"],
                    "source": "current_draft",
                    "output_path": "exports/document.md",
                },
            )
            return

        if "check_citation" in tool_names and _wants_check_citation(user_text) and not has_tool_result:
            yield _tool_call(
                "check_citation",
                {
                    "citation_id": (
                        "cite:lab-note-scanner"
                        if "intel.02" in user_text.lower()
                        else "cite:ref-a"
                    ),
                    "source_path": (
                        "sources/lab-note-scanner.md"
                        if "intel.02" in user_text.lower()
                        else "sources/ref-a.md"
                    ),
                },
            )
            return

        if has_tool_result and last_tool == "check_citation":
            yield ModelResponse(text="citation valid", output_tokens=6)
            return

        if "export_document" in tool_names and _wants_export(user_text) and not has_tool_result:
            yield _tool_call(
                "export_document",
                {
                    "section_ids": ["a"],
                    "source": "confirmed",
                    "output_path": "exports/document.md",
                },
            )
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

        if "draft_section" in tool_names and _wants_draft(user_text) and not has_tool_result:
            yield _tool_call(
                "draft_section",
                {
                    "section_id": "02",
                    "content": "第一节草稿内容。" * 8,
                },
            )
            return

        if "enrich_ioc" in tool_names and _wants_enrich_ioc(user_text) and not has_tool_result:
            indicator = _enrich_ioc_indicator(user_text)
            yield _tool_call("enrich_ioc", {"indicator": indicator, "type": "auto"})
            return

        if has_tool_result and last_tool == "enrich_ioc" and _wants_enrich_ioc(user_text):
            if "search_sources" in tool_names and not _intel_already_searched(messages):
                yield _tool_call("search_sources", {"query": "203.0.113.10 scanner evil.example.com"})
                return
            if "draft_section" in tool_names:
                yield _tool_call(
                    "draft_section",
                    {
                        "section_id": "assessment",
                        "content": (
                            "研判简报：203.0.113.10 为可疑扫描源，关联 evil.example.com。"
                            "引用 [cite:lab-note-scanner]。建议人工复核，未执行封禁。"
                        ),
                    },
                )
                return
            reply = "enrich_ioc 完成；建议人工复核，未执行封禁。"
            for chunk in _chunk_text(reply):
                yield chunk
            yield ModelResponse(text=reply, output_tokens=12)
            return

        if (
            has_tool_result
            and last_tool == "search_sources"
            and _wants_enrich_ioc(user_text)
            and "draft_section" in tool_names
        ):
            yield _tool_call(
                "draft_section",
                {
                    "section_id": "assessment",
                    "content": (
                        "研判简报：基于 enrich 与资料检索，203.0.113.10 / evil.example.com "
                        "在实验笔记中标记为可疑 [cite:lab-note-scanner]。不要自动封禁。"
                    ),
                },
            )
            return

        if has_tool_result and last_tool == "draft_section" and _wants_enrich_ioc(user_text):
            reply = (
                "研判简报已起草 [cite:lab-note-scanner]。建议人工复核，未执行封禁。"
            )
            for chunk in _chunk_text(reply):
                yield chunk
            yield ModelResponse(text=reply, output_tokens=16)
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

        if "search_sources" in tool_names and _wants_path_prefix_section(user_text) and not has_tool_result:
            yield _tool_call(
                "search_sources",
                {"query": "张白鹿", "path_prefix": "writing"},
            )
            return

        if has_tool_result and last_tool == "search_sources" and _wants_path_prefix_section(user_text):
            reply = "writing.14 在 sources/writing 下命中张白鹿专节 [cite:liangjian]"
            for chunk in _chunk_text(reply):
                yield chunk
            yield ModelResponse(text=reply, output_tokens=14)
            return

        if has_tool_result and last_tool == "search_sources" and "TENANT_OWN_MARKER_WAVE_A" in user_text:
            reply = "bound Work recall TENANT_OWN_MARKER_WAVE_A from sources/tenant-own.md"
            for chunk in _chunk_text(reply):
                yield chunk
            yield ModelResponse(text=reply, output_tokens=12)
            return

        if "search_sources" in tool_names and _wants_hybrid_character_recall(user_text) and not has_tool_result:
            yield _tool_call("search_sources", {"query": "张白鹿"})
            return

        if has_tool_result and last_tool == "search_sources" and _wants_hybrid_character_recall(user_text):
            reply = "writing.11 命中张白鹿专节"
            for chunk in _chunk_text(reply):
                yield chunk
            yield ModelResponse(text=reply, output_tokens=10)
            return

        if "search_sources" in tool_names and _wants_vector_index(user_text) and not has_tool_result:
            yield _tool_call("search_sources", {"query": "phase2-unique-term"})
            return

        if has_tool_result and last_tool == "search_sources" and _wants_vector_index(user_text):
            reply = "writing.07 召回 phase2-unique-term 自 sources/new-chunk.md"
            for chunk in _chunk_text(reply):
                yield chunk
            yield ModelResponse(text=reply, output_tokens=16)
            return

        if "search_sources" in tool_names and _wants_search(user_text, tool_names=tool_names) and not has_tool_result:
            query = _search_sources_query(user_text)
            yield _tool_call("search_sources", {"query": query})
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

        # collab.03 sub-agent fixture: produce artifact_refs for handoff (no peer bus).
        if (
            "collab.03" in user_text.lower()
            and "delegate" not in tool_names
            and not has_tool_result
        ):
            reply = "Wrote explore notes.\nARTIFACT_REFS: artifacts/collab/findings.md"
            for chunk in _chunk_text(reply):
                yield chunk
            yield ModelResponse(text=reply, output_tokens=12)
            return

        if "delegate" in tool_names and _wants_delegate(user_text) and not has_tool_result:
            agent_type = "researcher" if "researcher" in user_text.lower() else "explore"
            yield _tool_call("delegate", {"task": user_text, "agent_type": agent_type})
            return

        if has_tool_result and last_tool == "delegate":
            if _wants_double_delegate(user_text):
                delegate_results = _delegate_tool_result_count(messages)
                if delegate_results < 2 and not _assistant_requested_verify_delegate(messages):
                    verify_args: dict[str, Any] = {
                        "task": "verify explore findings",
                        "agent_type": "verify",
                    }
                    refs = _artifact_refs_from_last_delegate_result(messages)
                    if not refs and "collab.03" in user_text.lower():
                        refs = ["artifacts/collab/findings.md"]
                    if refs:
                        verify_args["context_refs"] = refs
                    yield _tool_call("delegate", verify_args)
                    return
                if "collab.03" in user_text.lower():
                    yield ModelResponse(text="collab.03 explore→verify handoff 完成", output_tokens=14)
                    return
                yield ModelResponse(text="agent.06 explore→verify 串联完成", output_tokens=14)
                return
            yield ModelResponse(text="主 Turn 已整合子 agent 摘要", output_tokens=12)
            return

        if "search_codebase" in tool_names and _wants_codebase_search(user_text) and not has_tool_result:
            yield _tool_call("search_codebase", {"query": "AgentEngine"})
            return

        if has_tool_result and last_tool == "search_codebase":
            yield ModelResponse(text="search_codebase hits recorded", output_tokens=8)
            return

        # CQ3 agent.10: read → surgical edit_file → read_lints (quality loop)
        if _wants_agent_quality_verify(user_text) and "read_file" in tool_names:
            if not has_tool_result:
                yield _tool_call("read_file", {"path": _extract_path(user_text) or "app.py"})
                return
            if last_tool == "read_file" and "edit_file" in tool_names:
                path = _extract_path(user_text) or "app.py"
                yield _tool_call(
                    "edit_file",
                    {
                        "path": path,
                        "old_text": 'return "old"',
                        "new_text": 'return "new"',
                    },
                )
                return
            if last_tool == "edit_file" and "read_lints" in tool_names:
                path = _extract_path(user_text) or "app.py"
                yield _tool_call("read_lints", {"path": path})
                return
            if last_tool == "read_lints":
                yield ModelResponse(
                    text="agent.10 edit applied; lints checked",
                    output_tokens=10,
                )
                return

        if has_tool_result and last_tool == "read_file" and "edit_file" in tool_names and (
            _wants_patch(user_text) or "agent.01" in user_text
        ):
            path = _extract_path(user_text) or "README.md"
            yield _tool_call(
                "edit_file",
                {
                    "path": path,
                    "old_text": "旧正文",
                    "new_text": "简洁的新正文",
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

        if settings.model_mode == "stub" and (
            os.environ.get("CI", "").lower() == "true"
            or settings.stub_fail_on_unrouted
        ):
            raise ModelFatalError(
                "stub provider received an unrouted intent; add an explicit stub route"
            )
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


def _intent_user_text(messages: list[dict]) -> str:
    """User text for stub routing — skip platform-injected context banners.

    Writing work_index / cards live under ``[writing_context]``; runtime banners under
    ``[runtime_context]``; workspace pins under ``[project_context]``. Matching those
    would make every writing turn look like ``draft_section`` / ``propose_patch`` / ``read``.
    """
    parts: list[str] = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        for block in msg.get("content", []):
            if block.get("type") != "text":
                continue
            text = str(block.get("text", ""))
            stripped = text.lstrip()
            if stripped.startswith(("[writing_context]", "[runtime_context]", "[project_context]")):
                continue
            parts.append(text)
    return " ".join(parts)


def _has_tool_result(messages: list[dict]) -> bool:
    """True if transcript already includes a tool result (role=tool or tool_result block)."""
    for msg in messages:
        if msg.get("role") == "tool":
            return True
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    return True
    return False


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


def _export_delivery_failed(messages: list[dict]) -> bool:
    """True when the latest export_document tool result reports delivery_status=failed."""
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        for block in msg.get("content", []) if isinstance(msg.get("content"), list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            raw = block.get("content", "")
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            if "delivery_status" not in data and "output_path" not in data:
                continue
            return str(data.get("delivery_status", "")).lower() == "failed"
    return False


def _is_smoke_message(text: str) -> bool:
    lowered = text.lower()
    return "smoke" in lowered or lowered.startswith("phase 0") or "l0 golden" in lowered


def _wants_patch(text: str) -> bool:
    keywords = ("改", "patch", "简洁", "修订", "修改", "diff", "[polish]", "writing.12")
    return any(k in text.lower() for k in keywords)


def _wants_agent_quality_verify(text: str) -> bool:
    """CQ3: stub path for read → edit_file → read_lints."""
    lowered = text.lower()
    return "agent.10" in lowered or ("quality" in lowered and "read_lints" in lowered)


def _wants_run_tests(text: str) -> bool:
    lowered = text.lower()
    # Prefer slash-expanded marker / golden id — avoid bare "run_tests" substring.
    return "[test]" in lowered or "agent.11" in lowered


def _wants_run_lints(text: str) -> bool:
    lowered = text.lower()
    if _wants_agent_quality_verify(text):
        return False
    return "[lint]" in lowered or "agent.12" in lowered


def _wants_read(text: str) -> bool:
    keywords = ("read", "读取", "查看", "打开", "read_file")
    return any(k in text.lower() for k in keywords)


def _wants_outline(text: str) -> bool:
    keywords = ("大纲", "outline", "writing.01", "[outline]", "writing.13")
    return any(k in text.lower() for k in keywords)


def _wants_plan(text: str) -> bool:
    keywords = ("agent.07", "update_plan", "制定计划")
    return any(k in text.lower() for k in keywords) or "计划" in text


def _wants_draft(text: str) -> bool:
    # Prefer golden id / 流式. Bare "draft_section" is injected by work_index and must
    # not route every writing turn (see _intent_user_text).
    keywords = ("流式", "writing.04")
    return any(k in text.lower() for k in keywords)


def _wants_enrich_ioc(text: str) -> bool:
    lowered = text.lower()
    if "intel.02" in lowered or "intel.03" in lowered:
        return False
    keywords = (
        "intel.01",
        "enrich_ioc",
        "203.0.113.10",
        "研判简报",
        "威胁情报",
    )
    return any(k in lowered for k in keywords)


def _enrich_ioc_indicator(text: str) -> str:
    for token in ("203.0.113.10", "evil.example.com", "aabbccddeeff00112233445566778899"):
        if token in text:
            return token
    return "203.0.113.10"


def _intel_already_searched(messages: list) -> bool:
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "tool":
            continue
        name = str(message.get("name") or "")
        if name == "search_sources":
            return True
    return False


def _wants_check_citation(text: str) -> bool:
    keywords = ("writing.08", "intel.02", "check_citation")
    return any(k in text.lower() for k in keywords)


def _wants_export(text: str) -> bool:
    keywords = ("writing.09", "export_document", "导出文档")
    return any(k in text.lower() for k in keywords)


def _wants_draft_export(text: str) -> bool:
    return "writing.10" in text.lower()


def _wants_glob(text: str) -> bool:
    keywords = ("agent.08", "glob", "*.md")
    return any(k in text.lower() for k in keywords)


def _wants_search(text: str, *, tool_names: set[str] | None = None) -> bool:
    if tool_names and "delegate" in tool_names and _wants_delegate(text):
        return False
    lowered = text.lower()
    # Style / outline passes: never auto-retrieve (docs/14 §4.2 W3/W4).
    if "[polish]" in lowered or "[outline]" in lowered or "writing.12" in lowered or "writing.13" in lowered:
        return False
    # Golden cases and explicit tool requests always exercise retrieval, even
    # when their surrounding wording also happens to describe the library.
    if any(k in lowered for k in ("search_sources", "writing.05", "writing.06")):
        return True
    if _is_sources_meta_question(lowered):
        return False
    return any(k in lowered for k in ("引用", "调研", "资料"))


def _search_sources_query(text: str) -> str:
    """Prefer a compact query for stub search_sources (avoid runtime_context noise)."""
    import re

    marker = re.search(r"(TENANT_OWN_MARKER_WAVE_A|phase2-unique-term|TENANT_DENY_SECRET_OTHER_WORK)", text)
    if marker:
        return marker.group(1)
    # Strip injected runtime banners if present.
    cleaned = re.sub(r"\[runtime_context\][^\n]*", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:200] or text[:200]


def _is_sources_meta_question(lowered: str) -> bool:
    """Return whether the user is asking to browse/describe the source library."""
    if "资料库" in lowered and any(
        marker in lowered
        for marker in ("理解", "有什么", "是什么", "介绍", "看看", "内容", "目录", "列表", "有哪些")
    ):
        return True
    if "对" in lowered and "资料库" in lowered:
        return True
    if "sources" in lowered and any(marker in lowered for marker in ("目录", "列表", "有哪些", "介绍")):
        return True
    return "有哪些资料" in lowered


def _wants_delegate(text: str) -> bool:
    if _wants_double_delegate(text):
        return True
    keywords = (
        "delegate",
        "researcher",
        "子 agent",
        "writing.06",
        "agent.05",
        "collab.01",
    )
    return any(k in text.lower() for k in keywords)


def _wants_double_delegate(text: str) -> bool:
    keywords = ("agent.06", "explore→verify", "explore verify", "collab.03")
    return any(k in text.lower() for k in keywords)


def _artifact_refs_from_last_delegate_result(messages: list[dict]) -> list[str]:
    """Pull artifact_refs from the latest delegate tool result (handoff)."""
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content")
        raw = ""
        if isinstance(content, str):
            raw = content
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    raw = str(block.get("content") or block.get("text") or "")
                    break
                if "text" in block:
                    raw = str(block.get("text") or "")
                    break
        if not raw or "subagent_id" not in raw:
            continue
        try:
            data = json.loads(raw) if raw.lstrip().startswith("{") else {}
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict):
            refs = data.get("artifact_refs")
            if isinstance(refs, list):
                return [str(r).strip() for r in refs if str(r).strip()][:12]
            summary = str(data.get("summary") or "")
            from app.tools.delegate_runner import _extract_artifact_refs

            return _extract_artifact_refs(summary)
    return []


def _wants_vector_index(text: str) -> bool:
    keywords = ("writing.07", "phase2-unique-term")
    return any(k in text.lower() for k in keywords)


def _wants_hybrid_character_recall(text: str) -> bool:
    return "writing.11" in text.lower()


def _wants_path_prefix_section(text: str) -> bool:
    return "writing.14" in text.lower()


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
    # Prefer run_tests when /test or agent.11 (TEST_EXPAND mentions run_command).
    if _wants_run_tests(text):
        return False
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
    """Thin harness around a provider: overall timeout, fast first-byte fail, retry."""

    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider
        self._cancel_event = asyncio.Event()
        self.retry_count = 0

    def abort_stream(self) -> None:
        self._cancel_event.set()

    async def stream(self, *, messages: list[dict], tools: list[dict]) -> AsyncIterator[str | ModelResponse]:
        self._cancel_event.clear()
        self.retry_count = 0
        overall_deadline = time.monotonic() + settings.model_timeout_seconds
        max_attempts = max(1, settings.model_max_retries + 1)
        attempt = 0
        last_error: BaseException | None = None
        outbound = messages
        if settings.pii_redact_enabled:
            from app.privacy.redact import redact_messages

            outbound = redact_messages(messages)

        try:
            while attempt < max_attempts:
                if self._cancel_event.is_set():
                    return
                remaining = overall_deadline - time.monotonic()
                if remaining <= 0:
                    raise ModelProviderTimeout("model stream exceeded timeout")

                attempt += 1
                attempt_abort = asyncio.Event()
                emitted_user_visible = False
                emitted_liveness = False
                try:
                    async for item in self._stream_attempt(
                        messages=outbound,
                        tools=tools,
                        overall_deadline=overall_deadline,
                        attempt_abort=attempt_abort,
                    ):
                        if isinstance(item, StreamActivity):
                            emitted_liveness = True
                        else:
                            # Text deltas and final ModelResponse are committed
                            # to the user-visible turn; retrying them duplicates
                            # output. Liveness/reasoning signals are ephemeral.
                            emitted_user_visible = True
                        yield item
                    return
                except ModelTransientError as exc:
                    # Abort via aclose often surfaces as transport errors; Cancel
                    # must end cleanly, not as "failed after streaming started".
                    if self._cancel_event.is_set():
                        return
                    last_error = exc
                    if emitted_user_visible:
                        raise ModelFatalError(
                            f"model failed after streaming started: {exc}"
                        ) from exc
                    if attempt >= max_attempts:
                        break
                    delay = _backoff_seconds(attempt, exc)
                    logger.info(
                        "model retry attempt=%s/%s delay=%.2fs liveness=%s error=%s",
                        attempt,
                        max_attempts,
                        delay,
                        emitted_liveness,
                        exc,
                    )
                    self.retry_count = attempt
                    attempt_abort.set()
                    if not await self._interruptible_sleep(delay, overall_deadline):
                        if self._cancel_event.is_set():
                            return
                        raise ModelProviderTimeout(
                            "model retry budget exhausted during backoff"
                        ) from exc
                except ModelProviderTimeout:
                    raise
                except ModelFatalError:
                    raise
                except Exception as exc:
                    if self._cancel_event.is_set():
                        return
                    classified = classify_provider_exception(exc)
                    if isinstance(classified, ModelTransientError) and not emitted_user_visible:
                        last_error = classified
                        if attempt >= max_attempts:
                            break
                        if self._cancel_event.is_set():
                            return
                        delay = _backoff_seconds(attempt, classified)
                        logger.info(
                            "model retry attempt=%s/%s delay=%.2fs liveness=%s error=%s",
                            attempt,
                            max_attempts,
                            delay,
                            emitted_liveness,
                            classified,
                        )
                        self.retry_count = attempt
                        attempt_abort.set()
                        if not await self._interruptible_sleep(delay, overall_deadline):
                            if self._cancel_event.is_set():
                                return
                            raise ModelProviderTimeout(
                                "model retry budget exhausted during backoff"
                            ) from classified
                        continue
                    if isinstance(classified, ModelError):
                        raise classified from exc
                    raise

            raise ModelFatalError(
                f"model retries exhausted after {attempt} attempts: {last_error}"
            )
        finally:
            self._cancel_event.clear()

    async def _stream_attempt(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        overall_deadline: float,
        attempt_abort: asyncio.Event,
    ) -> AsyncIterator[str | ModelResponse]:
        abort = _OrAbort(self._cancel_event, attempt_abort)
        agen = self._provider.stream(messages=messages, tools=tools, abort=abort)
        first_byte_budget = min(
            settings.model_first_byte_timeout_seconds,
            max(0.01, overall_deadline - time.monotonic()),
        )
        try:
            try:
                first = await asyncio.wait_for(agen.__anext__(), timeout=first_byte_budget)
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError as exc:
                attempt_abort.set()
                if time.monotonic() >= overall_deadline:
                    raise ModelProviderTimeout("model stream exceeded timeout") from exc
                raise ModelTransientError(
                    f"first byte timeout after {first_byte_budget:.1f}s"
                ) from exc
            except ModelError:
                if self._cancel_event.is_set() or attempt_abort.is_set():
                    return
                raise
            except Exception as exc:
                # Cancel/timeout often surfaces as transport errors after aclose.
                if self._cancel_event.is_set() or attempt_abort.is_set():
                    return
                raise classify_provider_exception(exc) from exc

            if self._cancel_event.is_set():
                return
            if time.monotonic() > overall_deadline:
                raise ModelProviderTimeout("model stream exceeded timeout")
            yield first

            try:
                async for item in agen:
                    if self._cancel_event.is_set() or attempt_abort.is_set():
                        return
                    if time.monotonic() > overall_deadline:
                        raise ModelProviderTimeout("model stream exceeded timeout")
                    yield item
            except ModelError:
                if self._cancel_event.is_set() or attempt_abort.is_set():
                    return
                raise
            except Exception as exc:
                if self._cancel_event.is_set() or attempt_abort.is_set():
                    return
                raise classify_provider_exception(exc) from exc
        finally:
            # Always close the provider async generator so httpx/SSE connections
            # do not linger after first-byte timeout, cancel, or retry.
            aclose = getattr(agen, "aclose", None)
            if callable(aclose):
                try:
                    await aclose()
                except Exception:
                    logger.debug("provider stream aclose failed", exc_info=True)

    async def _interruptible_sleep(self, delay: float, deadline: float) -> bool:
        """Sleep up to delay; return False if cancel or overall deadline wins."""
        end = min(time.monotonic() + max(0.0, delay), deadline)
        while time.monotonic() < end:
            if self._cancel_event.is_set():
                return False
            await asyncio.sleep(min(0.05, end - time.monotonic()))
        return not self._cancel_event.is_set() and time.monotonic() <= deadline


def _backoff_seconds(attempt: int, exc: ModelTransientError) -> float:
    if exc.retry_after is not None and exc.retry_after >= 0:
        return min(float(exc.retry_after), settings.model_retry_max_delay_seconds)
    base = settings.model_retry_base_delay_seconds
    return min(base * (2 ** (attempt - 1)), settings.model_retry_max_delay_seconds)


def classify_provider_exception(exc: BaseException) -> ModelError | BaseException:
    """Map transport/HTTP failures into harness error types."""
    if isinstance(exc, ModelError):
        return exc

    try:
        import httpx
    except ImportError:  # pragma: no cover
        httpx = None  # type: ignore[assignment]

    if httpx is not None:
        if isinstance(exc, httpx.HTTPStatusError):
            return classify_http_status(
                exc.response.status_code,
                body=str(exc),
                headers=exc.response.headers,
            )
        if isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ),
        ):
            return ModelTransientError(f"transport error: {exc}")
        if isinstance(exc, httpx.TimeoutException):
            return ModelTransientError(f"http timeout: {exc}")

    name = type(exc).__name__
    if name in {"ConnectError", "TimeoutException", "ReadTimeout", "RemoteProtocolError"}:
        return ModelTransientError(str(exc))
    return exc


def classify_http_status(
    status_code: int,
    *,
    body: str = "",
    headers: Any | None = None,
) -> ModelError:
    retry_after = _parse_retry_after(headers)
    snippet = (body or "")[:400]
    if status_code == 429 or status_code >= 500:
        return ModelTransientError(
            f"model API {status_code}: {snippet}",
            status_code=status_code,
            retry_after=retry_after,
        )
    return ModelFatalError(f"model API {status_code}: {snippet}", status_code=status_code)


def _parse_retry_after(headers: Any | None) -> float | None:
    if headers is None:
        return None
    raw = None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
