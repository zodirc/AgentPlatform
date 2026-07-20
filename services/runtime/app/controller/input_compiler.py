from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from app.engine.state import user_message
from app.settings import settings

_SLASH_HELP = re.compile(r"^\s*/help\b", re.I)
_SLASH_VERSION = re.compile(r"^\s*/version\b", re.I)
_SLASH_COMPACT = re.compile(r"^\s*/compact\b", re.I)
_SLASH_VERIFY = re.compile(r"^\s*/verify\b", re.I)
_SLASH_POLISH = re.compile(r"^\s*/polish(?:\s+(.*))?$", re.I | re.S)
_SLASH_OUTLINE = re.compile(r"^\s*/outline(?:\s+(.*))?$", re.I | re.S)
_PATH_REF = re.compile(r"@([\w./-]+\.(?:md|txt|py|ts|json|yaml|yml)|[\w./-]+)")
_NUMBERED_GOAL = re.compile(r"(?m)^\s*(?:\d+[\.\)、]|[-*•]\s+\S)")
_GOAL_JOIN = re.compile(
    r"(?:然后|接着|并且|同时|另外|还要|此外|and then|also|finally)\s*",
    re.I,
)
_PLAN_HINT = (
    "Multi-goal request detected; consider calling update_plan once before other tools "
    "(optional — not required)."
)

# Deterministic user-side expansions (docs/14 §6.4). Do NOT mutate system prefix (C3).
POLISH_EXPAND = (
    "[polish] 只改文风与节奏；禁改专名、情节、[cite:*]；"
    "禁止调用 search_sources；逐段 propose_patch。"
)
OUTLINE_EXPAND = (
    "[outline] 只产出或修改 outline.md，不写正文；"
    "禁止调用 search_sources；使用 update_outline。"
)


def expand_writing_slash(message: str) -> tuple[str, str | None]:
    """Expand /polish|/outline into user-message suffixes. Returns (text, slash_name|None)."""
    text = message.strip()
    m = _SLASH_POLISH.match(text)
    if m:
        rest = (m.group(1) or "").strip()
        expanded = f"{POLISH_EXPAND}" + (f"\n{rest}" if rest else "")
        return expanded, "polish"
    m = _SLASH_OUTLINE.match(text)
    if m:
        rest = (m.group(1) or "").strip()
        expanded = f"{OUTLINE_EXPAND}" + (f"\n{rest}" if rest else "")
        return expanded, "outline"
    return message, None


def detect_plan_hint(message: str) -> str | None:
    """Deterministic multi-goal heuristic. Returns a short hint or None (never forces plan)."""
    text = message.strip()
    if len(text) < 24:
        return None
    numbered = len(_NUMBERED_GOAL.findall(text))
    if numbered >= 3:
        return _PLAN_HINT
    joins = len(_GOAL_JOIN.findall(text))
    if joins >= 2 and len(text) >= 40:
        return _PLAN_HINT
    return None


@dataclass
class CompiledInput:
    messages: list[dict]
    metadata: dict


class InputCompiler:
    def compile(self, message: str, *, selection: str | None = None) -> CompiledInput:
        text = message.strip()
        metadata: dict = {}
        text, slash = expand_writing_slash(text)
        if slash:
            metadata["slash_expand"] = slash
            text = text.strip()
        plan_hint = detect_plan_hint(text)
        if plan_hint:
            metadata["plan_hint"] = plan_hint
        if selection:
            text = f"{text}\n\n[selection]\n{selection}"
            metadata["has_selection"] = True
        path_refs = _PATH_REF.findall(text)
        if path_refs:
            metadata["path_refs"] = path_refs
            refs_block = "\n".join(f"- {path}" for path in path_refs)
            text = f"{text}\n\n[file_refs]\n{refs_block}"
        return CompiledInput(messages=[user_message(text)], metadata=metadata)

    async def enrich_with_preread(
        self,
        compiled: CompiledInput,
        *,
        abort: asyncio.Event | None = None,
    ) -> CompiledInput:
        """Budgeted @path prereread into the user message; timeout → keep pointers only."""
        path_refs = list(compiled.metadata.get("path_refs") or [])
        if not path_refs:
            return compiled
        max_files = max(1, settings.path_preread_max_files)
        budget = max(200, settings.path_preread_max_chars)
        timeout_s = max(0.05, settings.path_preread_timeout_seconds)
        try:
            snippets = await asyncio.wait_for(
                asyncio.to_thread(
                    _preread_paths,
                    path_refs[:max_files],
                    budget,
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            compiled.metadata["path_preread"] = "timeout"
            return compiled
        if abort is not None and abort.is_set():
            compiled.metadata["path_preread"] = "cancelled"
            return compiled
        if not snippets:
            compiled.metadata["path_preread"] = "empty"
            return compiled
        block = "\n\n".join(snippets)
        compiled.metadata["path_preread"] = "ok"
        compiled.metadata["hot_files"] = [s.split("\n", 1)[0].replace("## ", "").strip() for s in snippets]
        # Append prereread to the last user message text.
        messages = [dict(m) for m in compiled.messages]
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            content = list(msg.get("content") or [])
            for i, block_item in enumerate(content):
                if block_item.get("type") == "text":
                    content[i] = {
                        **block_item,
                        "text": f"{block_item.get('text', '')}\n\n[preread]\n{block}",
                    }
                    break
            msg["content"] = content
            break
        return CompiledInput(messages=messages, metadata=compiled.metadata)


def _preread_paths(paths: list[str], budget: int) -> list[str]:
    root = Path(settings.workspace_root).resolve()
    snippets: list[str] = []
    used = 0
    for rel in paths:
        remaining = budget - used
        if remaining <= 0:
            break
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        head = "\n".join(lines[:80])
        snippet = head[:remaining]
        snippets.append(f"## {rel}\n{snippet}")
        used += len(snippet)
    return snippets


@dataclass
class ShouldQueryResult:
    should_query: bool
    local_response: str | None = None
    failure_reason: str | None = None
    slash_command: str | None = None


def should_query(message: str, *, has_model_key: bool) -> ShouldQueryResult:
    text = message.strip()
    if not text:
        return ShouldQueryResult(False, failure_reason="empty_message")
    if _SLASH_HELP.match(text):
        return ShouldQueryResult(
            False,
            local_response=(
                "Agent Platform — commands:\n"
                "  /help — this message\n"
                "  /version — platform version\n"
                "  /compact — compact session context into summary\n"
                "  /verify — fact-check drafts/exports (does not mutate drafts)\n"
                "  /polish — style-only polish pass (no search_sources; propose_patch)\n"
                "  /outline — outline-only pass (update_outline; no prose)\n"
                "Send any other message to start a turn."
            ),
        )
    if _SLASH_VERSION.match(text):
        return ShouldQueryResult(False, local_response="Agent Platform v0.1.0 (Phase 1)")
    if _SLASH_COMPACT.match(text):
        return ShouldQueryResult(False, slash_command="compact")
    if _SLASH_VERIFY.match(text):
        return ShouldQueryResult(False, slash_command="verify")
    if not has_model_key:
        # Stub mode still runs engine with deterministic stub provider
        return ShouldQueryResult(True)
    return ShouldQueryResult(True)
