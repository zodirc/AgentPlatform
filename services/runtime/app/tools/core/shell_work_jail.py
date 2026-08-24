"""OS 沙箱降级时的软 FS jail（shell/argv 路径扫描）。

意图对齐 ``build_bwrap_argv``：Work Turn 不得触碰其它产品根。典型事故：无沙箱
``cp -a … /workspace/…`` 从 ops-l1 SWE Turn 污染 legacy 默认 Work 挂载。
"""

from __future__ import annotations

import re
from pathlib import Path

# Absolute paths in shell text (unquoted). Do not treat "../x" as "/x".
_ABS_PATH_RE = re.compile(
    r"""(?<![A-Za-z0-9_./])(/(?:[A-Za-z0-9._+@%=\-]+/)*[A-Za-z0-9._+@%=\-]*)"""
)
_QUOTED_ABS_RE = re.compile(r"""['"](/(?:[^'"]*))['"]""")
# Relative escapes that climb out of the work root.
_DOTDOT_RE = re.compile(
    r"""(?<![A-Za-z0-9_])((?:\.\./)+[A-Za-z0-9._+@%=\-/]*|\.\.(?=/|$))"""
)

# Readable system locations (same spirit as bwrap --ro-bind list).
_SYSTEM_PREFIXES: tuple[str, ...] = (
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/lib32",
    "/etc",
    "/opt",
    "/proc",
    "/dev",
    "/sys",
    "/tmp",
    "/var/tmp",
    "/run",
    "/app",  # runtime image
)


def _is_relative_to(path: Path, root: Path) -> bool:
    """``path`` 是否位于 ``root`` 之下（``relative_to`` 不抛即 True）。"""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _lexical_norm(path_str: str) -> str:
    """词法规范化路径（不要求存在；保留绝对路径语义）。"""
    raw = (path_str or "").strip().rstrip(",;:)].")
    if not raw:
        return ""
    # Strip trailing shell redirections glued on (rare): /tmp/out.txt>
    while raw and raw[-1] in "<>|":
        raw = raw[:-1]
    if not raw.startswith("/"):
        return str(Path(raw))
    parts: list[str] = []
    for part in Path(raw).parts:
        if part in ("", "/"):
            continue
        if part == ".":
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/" + "/".join(parts) if parts else "/"


def _under_prefix(norm: str, prefix: str) -> bool:
    """规范化路径 ``norm`` 是否等于或以 ``prefix`` 为前缀。"""
    return norm == prefix or norm.startswith(prefix.rstrip("/") + "/")


def _system_allowed(norm: str) -> bool:
    """是否为允许读取的系统前缀（``/usr``、``/bin`` 等）或 ``/``。"""
    if norm == "/":
        return True
    return any(_under_prefix(norm, p) for p in _SYSTEM_PREFIXES)


def _path_allowed(abs_path: str, cwd: Path) -> bool:
    """绝对路径是否允许访问：系统前缀、当前 work_root 或受限 ``/workspace``/``/data``。"""
    norm = _lexical_norm(abs_path)
    if not norm.startswith("/"):
        return True
    if _system_allowed(norm):
        return True

    try:
        cwd_r = cwd.resolve()
    except OSError:
        cwd_r = cwd.absolute()
    cwd_s = str(cwd_r)

    # Inside the work root (including the root itself).
    if norm == cwd_s or norm.startswith(cwd_s.rstrip("/") + "/"):
        return True

    # Legacy product Work mount: only when this Turn's root lives there.
    if _under_prefix(norm, "/workspace"):
        return _is_relative_to(cwd_r, Path("/workspace"))

    # Shared data volume: only the current work tree (ops-l1 / works / …).
    if _under_prefix(norm, "/data"):
        return norm == cwd_s or norm.startswith(cwd_s.rstrip("/") + "/")

    # Other absolute paths (e.g. /home, /root, /repo) are denied outside cwd.
    return False


def _iter_abs_candidates(text: str) -> list[str]:
    """从 shell 文本提取引号内与裸写的绝对路径候选。"""
    found: list[str] = []
    for m in _QUOTED_ABS_RE.finditer(text):
        found.append(m.group(1))
    for m in _ABS_PATH_RE.finditer(text):
        found.append(m.group(1))
    return found


def shell_command_jail_violation(command: str, cwd: Path) -> str | None:
    """若 ``command`` 逃逸 work root 则返回短原因；否则 ``None``。"""
    text = command or ""
    if not text.strip():
        return None

    try:
        cwd_r = cwd.resolve()
    except OSError:
        cwd_r = cwd.absolute()

    for raw in _iter_abs_candidates(text):
        if not raw.startswith("/"):
            continue
        if not _path_allowed(raw, cwd_r):
            return (
                f"path outside work root blocked (sandbox soft-jail): {raw!r} "
                f"(work_root={cwd_r})"
            )

    for m in _DOTDOT_RE.finditer(text):
        rel = m.group(1)
        try:
            target = (cwd_r / rel).resolve()
        except OSError:
            continue
        if not _is_relative_to(target, cwd_r):
            return (
                f"relative path escape blocked (sandbox soft-jail): {rel!r} "
                f"(work_root={cwd_r})"
            )

    return None


def argv_jail_violation(argv: list[str] | tuple[str, ...], cwd: Path) -> str | None:
    """argv exec 版 jail：拼接扫描并对各绝对参数单独校验。"""
    if not argv:
        return None
    joined = " ".join(str(a) for a in argv)
    hit = shell_command_jail_violation(joined, cwd)
    if hit:
        return hit
    for arg in argv:
        s = str(arg)
        if s.startswith("/") and not _path_allowed(s, cwd):
            return (
                f"argv path outside work root blocked (sandbox soft-jail): {s!r} "
                f"(work_root={cwd})"
            )
    return None
