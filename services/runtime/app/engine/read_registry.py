"""Turn 级 read_file 覆盖注册表（docs/34 RC1/RC3）。

English: Per-turn read_file coverage registry (docs/34 RC1/RC3/C1).

确定性、纯内存、无 I/O。在工具层与 assemble 层配合实现硬门：
- RC1：整文件读完后禁止同 Turn 换 offset 重读（read-after-complete）
- RC3：本 Turn 已覆盖行区间上的重叠分页拒绝（mode B 短拒）
- C1：正文被 fold/collapse/snip 移出可见窗口时，每路径允许一次豁免重读
- RC4：旧 read_file tool_result 在 assemble 中折叠为证据 stub

序列化形态供 ``TurnState.read_registry`` checkpoint 持久化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def normalize_read_path(path: str) -> str:
    """将工具传入路径规范化为 Turn 内一致的 registry 键。

    参数:
        path: 原始路径字符串（可含 ``./`` 前缀或反斜杠）。

    返回:
        去首尾空白、统一 ``/``、剥 ``./`` 前缀后的路径；空串原样返回。
    """
    p = str(path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def _line_covered(ranges: list[tuple[int, int]], line: int) -> bool:
    """判断行号是否落在任一已覆盖闭区间内。"""
    return any(start <= line <= end for start, end in ranges)


def _format_ranges(ranges: list[tuple[int, int]], *, limit: int = 6) -> str:
    """将行区间格式化为人类可读摘要（拒信与日志用）。"""
    if not ranges:
        return "(none)"
    parts = [f"{a}–{b}" for a, b in ranges[:limit]]
    if len(ranges) > limit:
        parts.append("…")
    return ", ".join(parts)


@dataclass
class PathReadState:
    """单工作区路径在单个 Turn 内的 read_file 覆盖状态。"""

    covered_ranges: list[tuple[int, int]] = field(default_factory=list)
    whole_file_complete: bool = False
    next_offset: int | None = None
    allow_reread_once: bool = False

    def to_dict(self) -> dict[str, Any]:
        """序列化为 checkpoint 友好的 plain dict。

        返回:
            含 covered_ranges、whole_file_complete 等字段的字典。
        """
        return {
            "covered_ranges": [list(r) for r in self.covered_ranges],
            "whole_file_complete": self.whole_file_complete,
            "next_offset": self.next_offset,
            "allow_reread_once": self.allow_reread_once,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PathReadState:
        """从 checkpoint 或 API 载荷反序列化。

        参数:
            data: 可选 dict；非法或缺失字段时使用默认值。

        返回:
            ``PathReadState`` 实例。
        """
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
    """将整个 registry 转为可 JSON 化的 dict。

    参数:
        registry: 路径 → ``PathReadState`` 映射。

    返回:
        路径 → plain dict 的映射。
    """
    return {path: st.to_dict() for path, st in registry.items()}


def deserialize_read_registry(raw: Any) -> dict[str, PathReadState]:
    """从 checkpoint 载荷恢复 registry。

    参数:
        raw: 任意值；非 dict 时返回空 registry。

    返回:
        规范化路径键的 ``PathReadState`` 字典。
    """
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
    """RC1 + RC3：拒绝整文件重复读与重叠 offset 窗口。

    C1：若路径正文已从 assemble 窗口 evict，且本 Turn 尚未消耗
    一次性重读豁免，则放行（返回 None）。

    参数:
        registry: Turn 级读覆盖表。
        path: 待读路径。
        offset: 本次 read_file 起始行（1-based）。
        evicted_paths: 被 fold/snip 移出可见窗口的路径集合。
        evicted_reread_used: 已消耗 C1 豁免的路径集合。

    返回:
        应拒绝时返回英文策略拒信字符串；允许时返回 None。
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
    # C1：被折叠/截断的内容允许每 Turn 每路径重取一次。
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
    """向后兼容别名：旧测试只关心 RC1 整文件完成门。

    参数:
        registry: Turn 级读覆盖表。
        path: 待读路径。
        offset: 起始行。

    返回:
        同 ``deny_redundant_read``。
    """
    return deny_redundant_read(registry, path=path, offset=offset)


def note_edit_failure_allows_reread(
    registry: dict[str, PathReadState],
    *,
    path: str,
) -> None:
    """编辑失败时授予该路径一次性重读豁免（平台自动放行下一笔 read_file）。

    参数:
        registry: 原地更新的 Turn registry。
        path: 编辑目标路径。
    """
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
    """C1：成功完成 evict 豁免重读后，标记已用并移出 evicted 集合。

    参数:
        path: 刚读完的路径。
        evicted_paths: TurnState.evicted_paths（原地修改）。
        evicted_reread_used: TurnState.evicted_reread_used（原地修改）。
    """
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
    """在 read_file 成功返回后更新覆盖区间与分页指针。

    参数:
        registry: Turn 级读覆盖表。
        path: 所读文件路径。
        offset: 本次起始行。
        end_line: 本次结束行（含）。
        truncated: 是否因 limit 截断。
        next_offset: 截断时建议的下一 offset；整文件读完时为 None。
        whole_file_complete: 是否已读完全文件（truncated=false 且到 EOF）。
    """
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
    """从 read_file 类工具参数字典提取规范化路径。

    参数:
        arguments: 工具 input dict。

    返回:
        规范化路径；无效参数时返回空串。
    """
    if not isinstance(arguments, dict):
        return ""
    return normalize_read_path(str(arguments.get("path") or ""))


def is_mutating_file_tool_failure(tool_name: str, result: dict[str, Any]) -> bool:
    """判断写/改文件类工具是否应视为失败（可触发 allow_reread_once）。

    参数:
        tool_name: 工具名。
        result: 工具返回 dict。

    返回:
        属于 mutating 工具且含 error 或 failed/denied 状态时 True。
    """
    if tool_name not in {"edit_file", "propose_patch", "apply_patch", "write_file"}:
        return False
    if result.get("error"):
        return True
    status = str(result.get("status") or "").lower()
    return status in {"error", "failed", "denied"}


def user_facing_policy_summary(policy: str, *, path: str = "", budget: int = 0) -> str:
    """生成 Web 时间轴用的简短中文跳过说明（docs/34 — skipped ≠ failure）。

    参数:
        policy: 内部策略键（read_after_complete / read_overlap / read_budget 等）。
        path: 相关文件路径（展示用）。
        budget: read_budget 时的上限数字。

    返回:
        面向用户的中文一行说明。
    """
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
    """RC4：将历史 read_file 载荷缩为 assemble 用证据 stub，保留元数据。

    参数:
        data: 完整 read_file JSON 结果 dict。

    返回:
        保留 path/offset/行号等字段、``content`` 替换为 head/tail 摘要、
        并设 ``_folded_read=True`` 的新 dict。
    """
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
