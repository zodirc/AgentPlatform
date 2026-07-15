from __future__ import annotations

import copy
import re
from typing import Any

# Precompiled patterns — keep deterministic and millisecond-scale (docs/17 S2 A15).
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[REDACTED_PHONE]"),
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[REDACTED_ID]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
            r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
)


def redact_text(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def redact_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deep-copy messages and redact text-bearing fields before model egress."""
    cloned = copy.deepcopy(messages)
    for msg in cloned:
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = redact_text(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                block["text"] = redact_text(block["text"])
            elif block.get("type") == "tool_result" and isinstance(block.get("content"), str):
                block["content"] = redact_text(block["content"])
            elif block.get("type") == "tool_use":
                args = block.get("input")
                if isinstance(args, dict):
                    block["input"] = _redact_mapping(args)
    return cloned


def _redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            out[key] = redact_text(value)
        elif isinstance(value, dict):
            out[key] = _redact_mapping(value)
        elif isinstance(value, list):
            out[key] = [
                redact_text(v) if isinstance(v, str) else v
                for v in value
            ]
        else:
            out[key] = value
    return out


_LOG_STRING_KEYS = frozenset(
    {
        "arguments",
        "message",
        "user_input",
        "user_input_preview",
        "content",
        "summary",
        "text",
        "error",
        "stdout",
        "stderr",
        "command",
    }
)


def redact_log_event(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Structlog processor: redact sensitive string fields in log events."""
    for key, value in list(event_dict.items()):
        if key in _LOG_STRING_KEYS and isinstance(value, str):
            event_dict[key] = redact_text(value)
        elif key == "arguments" and isinstance(value, dict):
            event_dict[key] = _redact_mapping(value)
    return event_dict
