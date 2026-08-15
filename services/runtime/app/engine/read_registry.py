"""Turn-scoped read_file registry (docs/34 RC1/RC3).

Deterministic, in-memory only — no I/O. Hard-gates:
- RC1: read-after-whole-file-complete
- RC3: overlapping line windows already covered this Turn (mode B short deny)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def normalize_read_path(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def _line_covered(ranges: list[tuple[int, int]], line: int) -> bool:
    return any(start <= line <= end for start, end in ranges)


def _format_ranges(ranges: list[tuple[int, int]], *, limit: int = 6) -> str:
    if not ranges:
        return "(none)"
    parts = [f"{a}–{b}" for a, b in ranges[:limit]]
    if len(ranges) > limit:
        parts.append("…")
    return ", ".join(parts)


@dataclass
class PathReadState:
    """Coverage for one workspace path within a single Turn."""

    covered_ranges: list[tuple[int, int]] = field(default_factory=list)
    whole_file_complete: bool = False
    next_offset: int | None = None
    allow_reread_once: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "covered_ranges": [list(r) for r in self.covered_ranges],
            "whole_file_complete": self.whole_file_complete,
            "next_offset": self.next_offset,
            "allow_reread_once": self.allow_reread_once,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PathReadState:
        if not isinstance(data, dict):
            return cls()
        ranges: list[tuple[int, int]] = []
        for item in data.get("covered_ranges") or []:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                ranges.append((int(item[0]), int(item[1])))
        next_off = data.get("next_offset")
        return cls(
            covered_ranges=ranges,
            whole_file_complete=bool(data.get("whole_file_complete")),
            next_offset=int(next_off) if next_off is not None else None,
            allow_reread_once=bool(data.get("allow_reread_once")),
        )


def serialize_read_registry(registry: dict[str, PathReadState]) -> dict[str, Any]:
    return {path: st.to_dict() for path, st in registry.items()}


def deserialize_read_registry(raw: Any) -> dict[str, PathReadState]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, PathReadState] = {}
    for path, data in raw.items():
        key = normalize_read_path(str(path))
        if not key:
            continue
        out[key] = PathReadState.from_dict(data if isinstance(data, dict) else None)
    return out


def deny_redundant_read(
    registry: dict[str, PathReadState],
    *,
    path: str,
    offset: int = 1,
    evicted_paths: set[str] | None = None,
    evicted_reread_used: set[str] | None = None,
) -> str | None:
    """RC1 + RC3: refuse complete re-reads and overlapping offset windows.

    C1: if the path was evicted from the visible window and this Turn has not
    already used the one-shot re-read exemption, allow the call.
    """
    key = normalize_read_path(path)
    if not key:
        return None
    st = registry.get(key)
    if st is None:
        return None
    if st.allow_reread_once:
        return None
    if st.next_offset is not None and offset == st.next_offset:
        return None
    # C1: folded/collapsed content may be re-fetched once per path per Turn.
    if (
        evicted_paths is not None
        and key in evicted_paths
        and (evicted_reread_used is None or key not in evicted_reread_used)
    ):
        return None
    if st.whole_file_complete:
        return (
            f"read_after_complete: `{key}` was already read in full this Turn "
            f"(truncated=false / whole_file_complete). Do not re-call read_file with a "
            f"new offset or limit — use edit_file on the content you already have. "
            f"If an edit failed, the platform will allow one re-read automatically."
        )
    if st.covered_ranges and _line_covered(st.covered_ranges, offset):
        return (
            f"read_overlap: `{key}` line {offset} is already covered this Turn "
            f"[{_format_ranges(st.covered_ranges)}]. Do not re-page overlapping windows — "
            f"edit with edit_file, or continue only with offset=next_offset after a truncated read."
        )
    return None


def deny_read_after_complete(
    registry: dict[str, PathReadState],
    *,
    path: str,
    offset: int = 1,
) -> str | None:
    """Backward-compatible alias used by older tests."""
    return deny_redundant_read(registry, path=path, offset=offset)


def note_edit_failure_allows_reread(
    registry: dict[str, PathReadState],
    *,
    path: str,
) -> None:
    key = normalize_read_path(path)
    if not key:
        return
    st = registry.get(key)
    if st is None:
        st = PathReadState()
        registry[key] = st
    st.allow_reread_once = True


def consume_evicted_reread(
    *,
    path: str,
    evicted_paths: set[str],
    evicted_reread_used: set[str],
) -> None:
    """Mark C1 one-shot exemption as used after a successful re-read."""
    key = normalize_read_path(path)
    if not key:
        return
    if key in evicted_paths:
        evicted_reread_used.add(key)
        evicted_paths.discard(key)


def record_successful_read(
    registry: dict[str, PathReadState],
    *,
    path: str,
    offset: int,
    end_line: int,
    truncated: bool,
    next_offset: int | None,
    whole_file_complete: bool,
) -> None:
    key = normalize_read_path(path)
    if not key:
        return
    st = registry.get(key)
    if st is None:
        st = PathReadState()
        registry[key] = st
    if st.allow_reread_once:
        st.allow_reread_once = False
    if end_line >= offset > 0:
        st.covered_ranges.append((offset, end_line))
    if whole_file_complete:
        st.whole_file_complete = True
        st.next_offset = None
    elif truncated and next_offset is not None:
        st.next_offset = int(next_offset)
    else:
        st.next_offset = None


def path_from_tool_arguments(arguments: dict[str, Any] | None) -> str:
    if not isinstance(arguments, dict):
        return ""
    return normalize_read_path(str(arguments.get("path") or ""))


def is_mutating_file_tool_failure(tool_name: str, result: dict[str, Any]) -> bool:
    if tool_name not in {"edit_file", "propose_patch", "apply_patch", "write_file"}:
        return False
    if result.get("error"):
        return True
    status = str(result.get("status") or "").lower()
    return status in {"error", "failed", "denied"}


def user_facing_policy_summary(policy: str, *, path: str = "", budget: int = 0) -> str:
    """Short Chinese copy for Web timeline (docs/34 — skipped ≠ failure)."""
    key = normalize_read_path(path)
    label = f"`{key}`" if key else "该文件"
    if policy == "read_after_complete":
        return f"已跳过：本回合已完整读过 {label}，请直接 edit_file"
    if policy == "read_overlap":
        return f"已跳过：{label} 的该行区间本回合已读过，请 edit_file 或按 next_offset 续读"
    if policy == "read_budget":
        return f"已跳过：本回合 read_file 次数已达上限（{budget}）"
    return f"已跳过：策略 {policy}"


def omit_read_file_content_payload(data: dict[str, Any]) -> dict[str, Any]:
    """RC4: shrink a prior read_file tool_result for assemble; keep a short evidence stub."""
    content = data.get("content")
    body = content if isinstance(content, str) else ""
    offset = data.get("offset")
    end_line = data.get("end_line")
    try:
        off_i = int(offset) if offset is not None else None
    except (TypeError, ValueError):
        off_i = None
    try:
        end_i = int(end_line) if end_line is not None else None
    except (TypeError, ValueError):
        end_i = None
    span = ""
    if off_i is not None and end_i is not None:
        span = f"lines {off_i}-{end_i} "
    head = body[:300]
    tail = body[-300:] if len(body) > 300 else ""
    if tail and tail != head:
        stub = f"[{span}already read this Turn; head: {head} … tail: {tail}]"
    else:
        stub = f"[{span}already read this Turn; head: {head}]"
    out = {
        "path": data.get("path"),
        "offset": data.get("offset"),
        "end_line": data.get("end_line"),
        "total_lines": data.get("total_lines"),
        "truncated": data.get("truncated"),
        "next_offset": data.get("next_offset"),
        "whole_file_complete": data.get("whole_file_complete"),
        "summary": data.get("summary") or data.get("path"),
        "content": stub,
        "_folded_read": True,
    }
    if data.get("hint"):
        out["hint"] = data.get("hint")
    return out
