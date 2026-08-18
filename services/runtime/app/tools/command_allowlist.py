"""Load per-user run_command prefixes and match against a pending command."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_contracts.command_allowlist import command_matches_prefix

from app.controller.session_context import load_session_owner_user_id
from app.db.pool import get_pool


async def command_is_allowlisted(state: Any, arguments: dict[str, Any] | None) -> bool:
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
