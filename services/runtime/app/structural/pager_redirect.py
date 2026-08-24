
"""Shell pager 命令 → ``read_file`` 窗口重定向。

在 ``run_command`` 路径拦截纯只读的 ``cat`` / ``head`` / ``tail`` / ``sed -n``
等单文件命令，解析出 path + offset/limit，转交 ``read_file`` 工具以复用
ACL、截断与 read_registry 逻辑。含管道、重定向、子 shell 或 glob 的命令
一律不拦截（返回 ``None``）。
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

# Metacharacters that imply pipes, redirects, subshells, or globs.
_UNSAFE = re.compile(r"[|><;&`$(){}*?\n]|&&|\|\|")
_SED_RANGE = re.compile(r"^(\d+),(\d+)p$")
_SED_LINE = re.compile(r"^(\d+)p$")
_HEAD_N = re.compile(r"^-n(\d+)$")
_TAIL_N = re.compile(r"^-n(\d+)$")
_UNIX_N = re.compile(r"^-(\d+)$")


def try_parse_pager_command(command: str) -> dict[str, Any] | None:
    """解析可重定向的 pager 命令为 read_file 参数字典。

    参数:
        command: 原始 shell 命令行（单段，无管道）。

    返回:
        成功时含 ``path``、``offset``、``limit``、``from_end`` 键；
        不可解析或含不安全元字符时 ``None``。
    """
    raw = (command or "").strip()
    if not raw or _UNSAFE.search(raw):
        return None
    try:
        parts = shlex.split(raw, posix=True)
    except ValueError:
        return None
    if not parts:
        return None
    name = Path(parts[0]).name
    rest = parts[1:]
    if name == "cat":
        return _single_file(rest, offset=1, limit=None, allow_flags=False)
    if name == "nl":
        return _single_file(rest, offset=1, limit=None, allow_flags=True)
    if name == "head":
        return _parse_head_tail(rest, from_start=True)
    if name == "tail":
        return _parse_head_tail(rest, from_start=False)
    if name == "sed":
        return _parse_sed(rest)
    return None


def is_pure_pager_command(command: str) -> bool:
    """命令是否完全由可重定向的 pager 子集构成。

    参数:
        command: 待检测命令行。

    返回:
        ``try_parse_pager_command`` 非 ``None`` 时为 True。
    """
    return try_parse_pager_command(command) is not None


def resolve_pager_window(
    *,
    path: Path,
    offset: int | None,
    limit: int | None,
    from_end: int | None,
) -> tuple[int, int | None]:
    """把 tail 式 ``from_end`` 解析为绝对 ``(offset, limit)``。

    参数:
        path: 目标文件路径（用于读行数）。
        offset: 起始行（1-based）；``from_end`` 非空时可忽略。
        limit: 最大行数；``None`` 表示读到 EOF。
        from_end: 从文件末尾向前取 N 行；非空时按文件行数换算 offset。

    返回:
        ``(start_line, line_count)``；读文件失败时退化为 ``(1, from_end)``。
    """
    if from_end is None:
        return max(1, int(offset or 1)), limit
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 1, from_end
    n = text.count("\n") + (0 if text.endswith("\n") else 1 if text else 0)
    take = max(1, int(from_end))
    start = max(1, n - take + 1) if n else 1
    return start, take


def _single_file(
    rest: list[str],
    *,
    offset: int,
    limit: int | None,
    allow_flags: bool,
) -> dict[str, Any] | None:
    """解析 cat/nl 类单文件命令的参数列表。"""
    files: list[str] = []
    for p in rest:
        if p == "--":
            continue
        if p.startswith("-"):
            if not allow_flags:
                return None
            continue
        files.append(p)
    if len(files) != 1:
        return None
    path = files[0]
    if _looks_glob(path):
        return None
    return {"path": path, "offset": offset, "limit": limit, "from_end": None}


def _parse_head_tail(rest: list[str], *, from_start: bool) -> dict[str, Any] | None:
    """解析 head/tail 的 ``-n`` 与单文件路径。"""
    n = 10
    files: list[str] = []
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--":
            i += 1
            continue
        m_head = _HEAD_N.match(tok) or _UNIX_N.match(tok)
        m_n = re.fullmatch(r"-n", tok)
        if m_n and i + 1 < len(rest) and rest[i + 1].isdigit():
            n = int(rest[i + 1])
            i += 2
            continue
        if m_head:
            n = int(m_head.group(1))
            i += 1
            continue
        if tok.startswith("-"):
            return None
        files.append(tok)
        i += 1
    if len(files) != 1 or _looks_glob(files[0]):
        return None
    if from_start:
        return {"path": files[0], "offset": 1, "limit": n, "from_end": None}
    return {"path": files[0], "offset": None, "limit": n, "from_end": n}


def _parse_sed(rest: list[str]) -> dict[str, Any] | None:
    """解析 ``sed -n 'a,bp' file`` / ``sed -n ap file`` 行范围脚本。"""
    # Only ``sed -n 'a,bp' file`` / ``sed -n a,bp file`` / ``sed -n 'ap' file``.
    if not rest or rest[0] not in {"-n", "-ne", "-en"}:
        return None
    expr_and_file = rest[1:]
    if rest[0] in {"-ne", "-en"}:
        # sed -ne '10,20p' file — first remaining token is the script.
        pass
    if len(expr_and_file) < 2:
        return None
    expr = expr_and_file[0].strip()
    files = [p for p in expr_and_file[1:] if p != "--"]
    if len(files) != 1 or _looks_glob(files[0]):
        return None
    rng = _SED_RANGE.fullmatch(expr)
    if rng:
        start, end = int(rng.group(1)), int(rng.group(2))
        if end < start:
            return None
        return {
            "path": files[0],
            "offset": start,
            "limit": end - start + 1,
            "from_end": None,
        }
    one = _SED_LINE.fullmatch(expr)
    if one:
        line = int(one.group(1))
        return {"path": files[0], "offset": line, "limit": 1, "from_end": None}
    return None


def _looks_glob(path: str) -> bool:
    """路径是否含 shell glob 元字符。"""
    return any(ch in path for ch in "*?[]")
