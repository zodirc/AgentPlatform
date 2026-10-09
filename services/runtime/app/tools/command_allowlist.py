"""按用户前缀白名单判断 ``run_command`` 是否免审批。

从 ``command_allow_prefixes`` 表加载 session 所属用户的允许命令前缀，
与待执行命令做规范化前缀匹配（``agent_contracts.command_matches_prefix``）。
匹配成功时 executor 可跳过 approval 门控。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.controller.session_context import load_session_owner_user_id
from app.db.pool import get_pool

try:
    from agent_contracts.command_allowlist import command_argv, command_matches_prefix
except ImportError:  # pragma: no cover - stale venv/image still on older agent-contracts
    import shlex

    _SHELL_META = frozenset(";|&`$<>(){}!\n\r")

    def command_argv(command: str) -> list[str] | None:
        raw = command or ""
        if not raw.strip() or any(ch in raw for ch in "\n\r"):
            return None
        try:
            argv = shlex.split(raw, posix=True)
        except ValueError:
            return None
        if not argv or any(any(ch in token for ch in _SHELL_META) for token in argv):
            return None
        return argv

    def command_matches_prefix(command: str, prefix: str) -> bool:
        cmd = command_argv(command)
        pre = command_argv(prefix)
        if not cmd or not pre or len(cmd) < len(pre):
            return False
        return cmd[: len(pre)] == pre


async def command_is_allowlisted(state: Any, arguments: dict[str, Any] | None) -> bool:
    """检查本次 ``run_command`` 是否命中用户命令前缀白名单。

    参数:
        state: Turn 状态对象，须含 ``session_id``。
        arguments: tool 参数 dict，读取 ``command`` 字段。

    返回:
        ``True`` 表示命令与某条已存前缀匹配；无 session、空命令、DB 异常或未匹配均为 ``False``。

    说明:
        DB/网络异常时 fail-closed 返回 ``False``，不静默放行未知命令。
    """
    session_id = getattr(state, "session_id", None)
    if session_id is None:
        return False
    command = ""
    if isinstance(arguments, dict):
        command = str(arguments.get("command") or "")
    if not command.strip():
        return False
    try:
        owner = await load_session_owner_user_id(session_id)
        if owner is None:
            return False
        pool = await get_pool()
        from app.tenant_context import current_work_id

        work_id = current_work_id()
        try:
            rows = await pool.fetch(
                """
                SELECT prefix FROM command_allow_prefixes
                WHERE owner_user_id = $1
                  AND (work_id IS NULL OR work_id = $2)
                """,
                UUID(str(owner)),
                work_id,
            )
        except Exception as exc:
            if "work_id" not in str(exc):
                return False
            rows = await pool.fetch(
                """
                SELECT prefix FROM command_allow_prefixes
                WHERE owner_user_id = $1
                """,
                UUID(str(owner)),
            )
    except Exception:
        return False
    for row in rows:
        if command_matches_prefix(command, str(row["prefix"] or "")):
            return True
    return False
