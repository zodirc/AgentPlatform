"""S1 snapshot. A failed snapshot becomes require_approval instead of a write."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


def canonicalize_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve paths and argv before the matrix and the approval hash.

    A path that cannot be resolved is left unchanged so the escape check still
    sees it. A command that is not clean argv is left unchanged so it stays
    off the allow list.
    """
    if not isinstance(arguments, dict):
        return {}
    out = dict(arguments)
    for key in ("path", "file_path"):
        raw = out.get(key)
        if isinstance(raw, str) and raw.strip():
            resolved = _canonical_path(raw)
            if resolved:
                out[key] = resolved
    command = out.get("command")
    if isinstance(command, str) and command.strip():
        from app.tools.command_allowlist import command_argv

        argv = command_argv(command)
        if argv:
            out["command"] = " ".join(argv)
    return out


def _canonical_path(raw: str) -> str | None:
    try:
        from app.tenant_context import current_work_root

        root = Path(current_work_root()).resolve()
    except Exception:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return str(candidate.resolve())
    except OSError:
        return None


def path_escapes(arguments: dict[str, Any] | None) -> bool:
    """True when a path argument resolves outside the current Work root."""
    if not isinstance(arguments, dict):
        return False
    raw = arguments.get("path") or arguments.get("file_path")
    if not isinstance(raw, str) or not raw.strip():
        return False
    try:
        from app.tenant_context import current_work_root

        root = Path(current_work_root()).resolve()
    except Exception:
        return False
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return True
    try:
        resolved.relative_to(root)
    except ValueError:
        return True
    return False


def take_snapshot(state: Any, arguments: dict[str, Any] | None) -> bool:
    """Save the previous bytes of the target file. Missing files snapshot as empty.

    Returns False when the read fails for a reason other than "not there yet",
    or when the Work root cannot be resolved. Callers then ask for approval.
    """
    if not isinstance(arguments, dict):
        return True
    raw = arguments.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return True
    try:
        from app.tenant_context import current_work_root

        root = Path(current_work_root()).resolve()
    except Exception:
        return False
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    try:
        if resolved.is_file():
            old = resolved.read_bytes()
        elif resolved.exists():
            return False
        else:
            old = b""
    except OSError:
        return False
    try:
        text = old.decode("utf-8")
        stored: Any = text
    except UnicodeDecodeError:
        stored = {"b64": base64.b64encode(old).decode("ascii")}
    snaps = getattr(state, "s1_snapshots", None)
    if not isinstance(snaps, dict):
        try:
            state.s1_snapshots = {str(resolved): stored}
        except Exception:
            return True
    else:
        snaps[str(resolved)] = stored
    return True
