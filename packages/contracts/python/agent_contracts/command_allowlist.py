"""Command-prefix allow list matching (run_command approvals)."""

from __future__ import annotations

PREFIX_MAX_LEN = 200


def normalize_command_prefix(raw: str, *, max_len: int = PREFIX_MAX_LEN) -> str:
    text = " ".join((raw or "").replace("\n", " ").replace("\t", " ").split())
    if max_len > 0:
        return text[:max_len]
    return text


def default_prefix_from_command(command: str) -> str:
    """First token of a shell command (the executable / leading path)."""
    norm = normalize_command_prefix(command)
    if not norm:
        return ""
    return norm.split(" ", 1)[0]


def command_matches_prefix(command: str, prefix: str) -> bool:
    """True when ``command`` equals ``prefix`` or continues after it with a space.

    ``python`` does not match ``python3``; ``npm test`` matches ``npm test -q``.
    """
    cmd = normalize_command_prefix(command)
    pre = normalize_command_prefix(prefix)
    if not pre or not cmd:
        return False
    return cmd == pre or cmd.startswith(pre + " ")
