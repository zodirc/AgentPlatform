from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

_PATH_REF = re.compile(r"@([\w./-]+\.(?:md|txt|py|ts|tsx|json|yaml|yml)|[\w./-]+)")
_FILE_IN_TEXT = re.compile(
    r"(?:^|[\s\"'`])([\w./-]+\.(?:md|txt|py|ts|tsx|json|yaml|yml|rs|go|java))(?:[\s\"'`,.:;]|$)"
)


@dataclass
class StructuredSummary:
    task: str = ""
    files_touched: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)
    narrative: str = ""

    def to_message_text(self) -> str:
        parts = [f"[session context: {self.narrative or self.task or 'prior work'}"]
        if self.task:
            parts.append(f"task={self.task[:200]}")
        if self.files_touched:
            parts.append(f"files={', '.join(self.files_touched[:8])}")
        if self.decisions:
            parts.append(f"decisions={'; '.join(self.decisions[:3])}")
        if self.open_items:
            parts.append(f"open={'; '.join(self.open_items[:3])}")
        return " ".join(parts) + "]"

    def to_autocompact_text(self) -> str:
        payload = {
            "task": self.task[:200],
            "files_touched": self.files_touched[:12],
            "decisions": self.decisions[:6],
            "open_items": self.open_items[:6],
            "narrative": self.narrative[:800],
        }
        return f"[autocompact: {json.dumps(payload, ensure_ascii=False)}]"


def structured_summary_from_messages(messages: list[dict[str, Any]]) -> StructuredSummary:
    user_bits: list[str] = []
    assistant_bits: list[str] = []
    files: list[str] = []
    tools: list[str] = []

    for msg in messages:
        role = msg.get("role")
        for block in msg.get("content", []):
            if block.get("type") == "text":
                text = str(block.get("text", "")).strip()
                if not text or text.startswith("["):
                    continue
                files.extend(_PATH_REF.findall(text))
                files.extend(_FILE_IN_TEXT.findall(text))
                if role == "user" and len(user_bits) < 3:
                    user_bits.append(text[:160])
                elif role == "assistant" and len(assistant_bits) < 3:
                    assistant_bits.append(text[:160])
            elif block.get("type") == "tool_use":
                name = str(block.get("name", ""))
                if name:
                    tools.append(name)
                args = block.get("input") or {}
                path = args.get("path")
                if isinstance(path, str):
                    files.append(path)
            elif block.get("type") == "tool_result":
                content = str(block.get("content", ""))[:300]
                files.extend(_PATH_REF.findall(content))
                files.extend(_FILE_IN_TEXT.findall(content))

    unique_files = _dedupe(files)
    task = user_bits[-1] if user_bits else ""
    narrative_bits: list[str] = []
    if assistant_bits:
        narrative_bits.append(assistant_bits[-1])
    if user_bits:
        narrative_bits.append(user_bits[-1])
    narrative = " | ".join(narrative_bits)
    if tools:
        narrative = f"{narrative} (tools: {', '.join(tools[-4:])})".strip()

    return StructuredSummary(
        task=task,
        files_touched=unique_files,
        decisions=assistant_bits[-2:],
        open_items=[],
        narrative=narrative[:500],
    )


def structured_summary_from_turn_rows(rows: list[dict[str, Any]]) -> StructuredSummary:
    user_bits: list[str] = []
    assistant_bits: list[str] = []
    files: list[str] = []

    for row in rows:
        user_input = str(row.get("user_input") or "").strip()
        latest_output = str(row.get("latest_output") or "").strip()
        if user_input and not user_input.startswith("/"):
            user_bits.append(user_input[:200])
            files.extend(_PATH_REF.findall(user_input))
            files.extend(_FILE_IN_TEXT.findall(user_input))
        if latest_output:
            assistant_bits.append(latest_output[:240])
            files.extend(_PATH_REF.findall(latest_output))
            files.extend(_FILE_IN_TEXT.findall(latest_output))

    unique_files = _dedupe(files)
    return StructuredSummary(
        task=user_bits[-1] if user_bits else "",
        files_touched=unique_files,
        decisions=assistant_bits[-3:],
        open_items=[],
        narrative=(assistant_bits[-1] if assistant_bits else user_bits[-1] if user_bits else "")[:500],
    )


def merge_structured_summary(base: StructuredSummary, overlay: StructuredSummary) -> StructuredSummary:
    return StructuredSummary(
        task=overlay.task or base.task,
        files_touched=_dedupe([*base.files_touched, *overlay.files_touched]),
        decisions=_dedupe([*base.decisions, *overlay.decisions])[:8],
        open_items=_dedupe([*base.open_items, *overlay.open_items])[:8],
        narrative=overlay.narrative or base.narrative,
    )


def parse_structured_summary_text(text: str) -> StructuredSummary | None:
    marker = "[autocompact:"
    if marker not in text:
        return None
    start = text.find("{", text.find(marker))
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return StructuredSummary(
        task=str(data.get("task", "")),
        files_touched=[str(v) for v in data.get("files_touched") or []],
        decisions=[str(v) for v in data.get("decisions") or []],
        open_items=[str(v) for v in data.get("open_items") or []],
        narrative=str(data.get("narrative", "")),
    )


def build_context_summary_record(
    summary: StructuredSummary,
    *,
    last_turn_id: str,
    last_status: str,
    turn_count: int,
    source: str,
) -> dict[str, Any]:
    record = {
        "last_turn_id": last_turn_id,
        "last_status": last_status,
        "last_output_preview": (summary.narrative or summary.task)[:500],
        "turn_count": turn_count,
        "task": summary.task[:300],
        "files_touched": summary.files_touched[:20],
        "decisions": summary.decisions[:10],
        "open_items": summary.open_items[:10],
        "compacted_at": datetime.now(UTC).isoformat(),
        "source": source,
    }
    return record


def structured_summary_to_user_message(summary: StructuredSummary) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [{"type": "text", "text": summary.to_message_text()}],
    }


def structured_summary_dict(summary: StructuredSummary) -> dict[str, Any]:
    return asdict(summary)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out
