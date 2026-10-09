"""Command allow list matching on argv, not shell text.

A command is on the list only when it parses as a single simple argv vector
and that vector starts with the stored prefix tokens. Shell control syntax
(``&&``, pipes, newlines, redirections, substitutions) is never a match:
those commands stay behind approval and run inside the sandbox via ``sh -c``.
"""

from __future__ import annotations

import shlex

PREFIX_MAX_LEN = 200

# Characters that continue or redirect a shell command. Present in any token
# after ``shlex`` splitting, the command is outside the allow list.
_SHELL_META = frozenset(";|&`$<>(){}!\n\r")


def normalize_command_prefix(raw: str, *, max_len: int = PREFIX_MAX_LEN) -> str:
    text = " ".join((raw or "").replace("\n", " ").replace("\t", " ").split())
    if max_len > 0:
        return text[:max_len]
    return text


def command_argv(command: str) -> list[str] | None:
    """Parse ``command`` into argv, or ``None`` when it is not one simple command.

    Newlines and any token that still contains shell metacharacters (``&&``,
    ``|``, ``$()``, redirections, backticks) are rejected. Quoted arguments
    that merely contain those characters are also rejected: the allow list
    does not try to prove a quoted payload is harmless.
    """
    raw = command or ""
    if not raw.strip():
        return None
    if any(ch in raw for ch in "\n\r"):
        return None
    try:
        argv = shlex.split(raw, posix=True)
    except ValueError:
        return None
    if not argv:
        return None
    for token in argv:
        if any(ch in token for ch in _SHELL_META):
            return None
    return argv


def default_prefix_from_command(command: str) -> str:
    """First argv token, for suggesting a prefix after the user approves a command."""
    argv = command_argv(command)
    if argv:
        return argv[0][:PREFIX_MAX_LEN]
    norm = normalize_command_prefix(command)
    if not norm:
        return ""
    return norm.split(" ", 1)[0]


def command_matches_prefix(command: str, prefix: str) -> bool:
    """True when both sides are simple argv and ``command`` starts with ``prefix`` tokens.

    ``python`` does not match ``python3``. ``npm test`` matches ``npm test -q``.
    ``pytest`` does not match ``pytest && curl``.
    """
    cmd = command_argv(command)
    pre = command_argv(prefix)
    if not cmd or not pre:
        return False
    if len(cmd) < len(pre):
        return False
    return cmd[: len(pre)] == pre
