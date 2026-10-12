"""编辑读写的字节保真：编码、BOM、换行风格。

匹配在 LF 归一化后的文本上进行，写回时恢复原编码与多数派换行。
无法往返的字节拒绝写入，不把非法字节替换成 U+FFFD。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CODING_RE = re.compile(rb"coding[:=]\s*([A-Za-z0-9_.-]+)")


@dataclass(frozen=True)
class LoadedText:
    """一次可往返的文本视图。``text`` 使用 LF。"""

    text: str
    newline: str
    encoding: str
    bom: bool


@dataclass(frozen=True)
class SpanPlan:
    start: int
    end: int
    new_text: str
    mode: str


def load_text_bytes(raw: bytes) -> LoadedText | dict[str, str]:
    """探测编码与换行。失败时返回 ``error=unsupported_encoding``。"""
    bom = raw.startswith(b"\xef\xbb\xbf")
    body = raw[3:] if bom else raw
    newline = _majority_newline(body)
    decoded = _decode_roundtrip(body)
    if isinstance(decoded, dict):
        return decoded
    codec, text = decoded
    text_lf = text.replace("\r\n", "\n").replace("\r", "\n")
    return LoadedText(text=text_lf, newline=newline, encoding=codec, bom=bom)


def dump_text(loaded: LoadedText, text_lf: str) -> bytes:
    """把 LF 文本按原换行与编码写回。"""
    if loaded.newline == "\r\n":
        text = text_lf.replace("\n", "\r\n")
    else:
        text = text_lf
    body = text.encode(loaded.encoding)
    if loaded.bom:
        return b"\xef\xbb\xbf" + body
    return body


def encode_preserving(loaded: LoadedText, content: str) -> bytes:
    """覆盖写入：新内容自带 CRLF 时不改写其换行，否则继承原风格。"""
    if "\r\n" in content:
        text = content.replace("\r\n", "\n").replace("\r", "\n")
        # 调用方要求保留 CRLF：先归一再按 CRLF 写回，编码仍用原文件。
        body = text.replace("\n", "\r\n").encode(loaded.encoding)
    else:
        text = content.replace("\r", "\n")
        body = dump_text(loaded, text)
        return body
    if loaded.bom:
        return b"\xef\xbb\xbf" + body
    return body


def plan_spans(
    text: str,
    spans: list[dict[str, object]],
    *,
    trailing_ws: bool,
    reindent: bool = False,
) -> tuple[list[SpanPlan], dict[str, object] | None]:
    """在原文上定位全部 span。任一失败或重叠则不返回可应用计划。"""
    planned: list[SpanPlan] = []
    failures: list[dict[str, object]] = []
    for index, span in enumerate(spans):
        old = str(span.get("old_text") or "")
        new = span.get("new_text")
        new_text = "" if new is None else str(new)
        replace_all = bool(span.get("replace_all"))
        ranges, count, mode = _locate(
            text, old, trailing_ws=trailing_ws, replace_all=replace_all, reindent=reindent
        )
        if count == 0:
            failures.append({"index": index, "error": "old_text not found", "old_text": old})
            continue
        if not replace_all and count > 1:
            failures.append(
                {
                    "index": index,
                    "error": f"old_text matches {count} times; use a longer unique span",
                    "match_count": count,
                    "old_text": old,
                }
            )
            continue
        for start, end in ranges:
            replacement = new_text
            if mode == "reindent":
                replacement = _reindent_replacement(text[start:end], old, new_text)
            planned.append(SpanPlan(start=start, end=end, new_text=replacement, mode=mode))
    if failures:
        first = failures[0]
        return [], {
            "error": str(first.get("error") or "edit failed"),
            "spans": failures,
            "match_count": first.get("match_count"),
            "old_text": first.get("old_text") or "",
        }
    planned.sort(key=lambda item: item.start)
    for left, right in zip(planned, planned[1:]):
        if right.start < left.end:
            return [], {"error": "overlapping edits", "spans": []}
    return planned, None


def apply_spans(text: str, planned: list[SpanPlan]) -> str:
    """从后往前替换，保持前面的偏移有效。"""
    updated = text
    for span in reversed(planned):
        updated = updated[: span.start] + span.new_text + updated[span.end :]
    return updated


def post_edit_excerpt(text: str, line: int, *, radius: int = 5) -> str:
    """改动行前后各 ``radius`` 行，带 1-based 行号。"""
    lines = text.split("\n")
    if text.endswith("\n") and lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines:
        return ""
    anchor = min(max(line, 1), len(lines))
    lo = max(1, anchor - radius)
    hi = min(len(lines), anchor + radius)
    return "\n".join(f"{number}|{lines[number - 1]}" for number in range(lo, hi + 1))


def line_of_offset(text: str, offset: int) -> int:
    return text[: max(offset, 0)].count("\n") + 1


def _majority_newline(body: bytes) -> str:
    crlf = body.count(b"\r\n")
    lf_only = body.count(b"\n") - crlf
    if crlf > lf_only:
        return "\r\n"
    return "\n"


def _decode_roundtrip(body: bytes) -> tuple[str, str] | dict[str, str]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    else:
        if text.encode("utf-8") == body:
            return "utf-8", text
        return {"error": "unsupported_encoding"}
    codec = _declared_codec(body)
    if not codec:
        return {"error": "unsupported_encoding"}
    try:
        decoded = body.decode(codec)
        if decoded.encode(codec) != body:
            return {"error": "unsupported_encoding"}
    except (LookupError, UnicodeError):
        return {"error": "unsupported_encoding"}
    return codec, decoded


def _declared_codec(body: bytes) -> str | None:
    head = b"\n".join(body.split(b"\n", 2)[:2])
    match = _CODING_RE.search(head)
    if match is None:
        return None
    return match.group(1).decode("ascii", errors="ignore") or None


def _locate(
    text: str,
    old: str,
    *,
    trailing_ws: bool,
    replace_all: bool,
    reindent: bool = False,
) -> tuple[list[tuple[int, int]], int, str]:
    if old == "":
        # 空 span 在原文中不是唯一替换，与 ``str.count("")`` 一样拒绝。
        return [], max(text.count(""), 2), "exact"
    exact = _find_exact(text, old)
    if exact:
        ranges = exact if replace_all else exact[:1]
        # count is the full exact count so a non-unique span still errors
        return (exact if replace_all else exact), len(exact), "exact"
    if not trailing_ws:
        return [], 0, "exact"
    ranged = _find_trailing(text, old, replace_all=replace_all)
    if ranged:
        return ranged, len(ranged), "trailing_ws"
    if reindent:
        ranged = _find_reindent(text, old, replace_all=replace_all)
        if ranged:
            return ranged, len(ranged), "reindent"
    return [], 0, "exact"


def _find_exact(text: str, needle: str) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    start = 0
    step = len(needle)
    while True:
        index = text.find(needle, start)
        if index < 0:
            return found
        found.append((index, index + step))
        start = index + step
    return found


def _find_trailing(text: str, old: str, *, replace_all: bool) -> list[tuple[int, int]]:
    file_lines = text.split("\n")
    if text.endswith("\n"):
        file_lines = file_lines[:-1]
    old_lines = old.split("\n")
    if old.endswith("\n"):
        old_lines = old_lines[:-1]
    if not old_lines:
        return []
    stripped = [line.rstrip() for line in old_lines]
    if not any(stripped):
        return []
    width = len(old_lines)
    starts: list[int] = []
    last = len(file_lines) - width + 1
    index = 0
    while index < last:
        window = file_lines[index : index + width]
        if [line.rstrip() for line in window] == stripped:
            starts.append(index)
            index += width if replace_all else 1
            continue
        index += 1
    if not replace_all and len(starts) != 1:
        return [(0, 0)] * len(starts) if len(starts) > 1 else []
    offsets = _line_offsets(file_lines)
    ranges: list[tuple[int, int]] = []
    for line_index in starts:
        start = offsets[line_index]
        end_line = line_index + width - 1
        end = offsets[end_line] + len(file_lines[end_line])
        if end < len(text) and text[end : end + 1] == "\n":
            end += 1
        ranges.append((start, end))
    return ranges


def _reindent_replacement(file_chunk: str, old: str, new_text: str) -> str:
    """把 new_text 的相对缩进挪到文件里命中块的缩进上。"""

    def indent_of(lines: list[str]) -> str:
        for line in lines:
            if line.strip():
                return line[: len(line) - len(line.lstrip(" \t"))]
        return ""

    file_lines = file_chunk.split("\n")
    old_lines = old.split("\n")
    file_indent = indent_of(file_lines)
    old_indent = indent_of(old_lines)
    rewritten: list[str] = []
    for line in new_text.split("\n"):
        if old_indent and line.startswith(old_indent):
            rewritten.append(file_indent + line[len(old_indent) :])
        elif not line.strip():
            rewritten.append(line)
        else:
            rewritten.append(file_indent + line.lstrip(" \t"))
    return "\n".join(rewritten)


def _line_offsets(lines: list[str]) -> list[int]:
    offsets = [0]
    cursor = 0
    for line in lines[:-1]:
        cursor += len(line) + 1
        offsets.append(cursor)
    if not lines:
        return [0]
    return offsets


def _find_reindent(text: str, old: str, *, replace_all: bool) -> list[tuple[int, int]]:
    """忽略每行行首空白后再比较。默认关闭，只在 structural_match_reindent 打开时调用。"""
    file_lines = text.split("\n")
    if text.endswith("\n"):
        file_lines = file_lines[:-1]
    old_lines = old.split("\n")
    if old.endswith("\n"):
        old_lines = old_lines[:-1]
    if not old_lines:
        return []
    stripped = [line.strip() for line in old_lines]
    if not any(stripped):
        return []
    width = len(old_lines)
    starts: list[int] = []
    index = 0
    last = len(file_lines) - width + 1
    while index < last:
        window = file_lines[index : index + width]
        if [line.strip() for line in window] == stripped:
            starts.append(index)
            index += width if replace_all else 1
            continue
        index += 1
    if not replace_all and len(starts) != 1:
        return []
    offsets = _line_offsets(file_lines)
    ranges: list[tuple[int, int]] = []
    for line_index in starts:
        start = offsets[line_index]
        end_line = line_index + width - 1
        end = offsets[end_line] + len(file_lines[end_line])
        if end < len(text) and text[end : end + 1] == "\n":
            end += 1
        ranges.append((start, end))
    return ranges
