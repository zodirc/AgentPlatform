from __future__ import annotations

import re
from dataclasses import dataclass

from app.engine.state import user_message

_SLASH_HELP = re.compile(r"^\s*/help\b", re.I)
_SLASH_VERSION = re.compile(r"^\s*/version\b", re.I)
_SLASH_COMPACT = re.compile(r"^\s*/compact\b", re.I)
_PATH_REF = re.compile(r"@([\w./-]+\.(?:md|txt|py|ts|json|yaml|yml)|[\w./-]+)")


@dataclass
class CompiledInput:
    messages: list[dict]
    metadata: dict


class InputCompiler:
    def compile(self, message: str, *, selection: str | None = None) -> CompiledInput:
        text = message.strip()
        metadata: dict = {}
        if selection:
            text = f"{text}\n\n[selection]\n{selection}"
            metadata["has_selection"] = True
        path_refs = _PATH_REF.findall(text)
        if path_refs:
            metadata["path_refs"] = path_refs
            refs_block = "\n".join(f"- {path}" for path in path_refs)
            text = f"{text}\n\n[file_refs]\n{refs_block}"
        return CompiledInput(messages=[user_message(text)], metadata=metadata)


@dataclass
class ShouldQueryResult:
    should_query: bool
    local_response: str | None = None
    failure_reason: str | None = None


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
                "Send any other message to start a turn."
            ),
        )
    if _SLASH_VERSION.match(text):
        return ShouldQueryResult(False, local_response="Agent Platform v0.1.0 (Phase 1)")
    if _SLASH_COMPACT.match(text):
        return ShouldQueryResult(
            False,
            local_response="Context compaction is applied automatically when the turn exceeds budget.",
        )
    if not has_model_key:
        # Stub mode still runs engine with deterministic stub provider
        return ShouldQueryResult(True)
    return ShouldQueryResult(True)
