"""Baseline decision matrix. Detection may only tighten a result from here.

Taint order is system < user < workspace < external. S5 has no approval path.
An empty sink_class means the caller is a unit-test spec; production registration
fills the class from ``TOOL_CLASS`` and refuses names that are not declared.
"""

from __future__ import annotations

from typing import Any

TAINT_RANK = {"system": 0, "user": 1, "workspace": 2, "external": 3}

# sink, result taint. "child" and "stored" are resolved after the handler runs.
TOOL_CLASS: dict[str, tuple[str, str]] = {
    "read_file": ("S0", "workspace"),
    "list_dir": ("S0", "workspace"),
    "grep": ("S0", "workspace"),
    "glob": ("S0", "workspace"),
    "search_codebase": ("S0", "workspace"),
    "goto_definition": ("S0", "workspace"),
    "find_references": ("S0", "workspace"),
    "read_lints": ("S0", "workspace"),
    "check_citation": ("S0", "workspace"),
    "writing_rubric": ("S0", "workspace"),
    "evaluate_writing_fragment": ("S0", "workspace"),
    "author_state": ("S0", "workspace"),
    "reread_book": ("S0", "workspace"),
    "editor_report": ("S0", "workspace"),
    "propose_book_candidates": ("S0", "workspace"),
    "propose_opening_ponds": ("S0", "workspace"),
    "propose_chapter_openings": ("S0", "workspace"),
    "recall": ("S0", "stored"),
    "search_sources": ("S0", "external"),
    "enrich_ioc": ("S0", "external"),
    "lookup_indicator": ("S0", "external"),
    "search_records": ("S0", "external"),
    "delegate": ("S0", "child"),
    "slow_tool": ("S0", "workspace"),
    "stub_echo": ("S0", "workspace"),
    "write_file": ("S1", "workspace"),
    "edit_file": ("S1", "workspace"),
    "rename_file": ("S1", "workspace"),
    "apply_patch": ("S1", "workspace"),
    "propose_patch": ("S1", "workspace"),
    "draft_section": ("S1", "workspace"),
    "update_outline": ("S1", "workspace"),
    "update_plan": ("S1", "workspace"),
    "propose_retcon": ("S1", "workspace"),
    "export_document": ("S1", "workspace"),
    "run_command": ("S2", "workspace"),
    "run_tests": ("S2", "workspace"),
    "remember": ("S3", "user"),
    "forget": ("S3", "user"),
    "load_skill": ("S3", "system"),
    "http_fetch": ("S4", "external"),
}

# Eval is a policy profile: a pre-approved command set, still inside the sandbox,
# still with no network. It is not an executor bypass.
EVAL_COMMAND_PREFIXES = (
    "pytest",
    "python",
    "python3",
    "git",
    "npm",
    "npx",
    "ls",
    "cat",
    "rg",
)

_EMERGENCY_TOOLS: set[str] = set()
_EMERGENCY_HOSTS: set[str] = set()


def _emergency_path():
    from pathlib import Path

    from app.settings import settings

    return Path(settings.data_dir) / "security" / "emergency.json"


_POLICY_UNREADABLE = False


def policy_unreadable() -> bool:
    """True when the emergency file exists but cannot be parsed. Missing is fine."""
    _load_emergency_file()
    return _POLICY_UNREADABLE


def _load_emergency_file() -> dict:
    import json

    global _POLICY_UNREADABLE
    path = _emergency_path()
    try:
        if not path.is_file():
            _POLICY_UNREADABLE = False
            return {"tools": [], "hosts": [], "commands": []}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _POLICY_UNREADABLE = True
        return {"tools": [], "hosts": [], "commands": []}
    if not isinstance(data, dict):
        _POLICY_UNREADABLE = True
        return {"tools": [], "hosts": [], "commands": []}
    _POLICY_UNREADABLE = False
    return data


def _save_emergency_file(data: dict) -> None:
    import json

    path = _emergency_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        return

# Local rules can only tighten. A miss is not an allow.
_WIPE_MARKERS = ("rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev")
_FETCH_EXEC_MARKERS = ("curl ", "wget ", "ssh ", "scp ", "nc ")


def declared_class(name: str) -> tuple[str, str]:
    """Return (sink, result_taint). Unknown names return empty strings."""
    return TOOL_CLASS.get(name, ("", ""))


def higher(left: str, right: str) -> str:
    """The more severe of two taint labels. Unknown labels count as external."""
    rank_l = TAINT_RANK.get(left, TAINT_RANK["external"])
    rank_r = TAINT_RANK.get(right, TAINT_RANK["external"])
    return left if rank_l >= rank_r else right


def emergency_deny_tool(name: str) -> None:
    """Takes effect on the next tool call. Does not wait for the turn to end."""
    _EMERGENCY_TOOLS.add(name)
    data = _load_emergency_file()
    tools = set(data.get("tools") or [])
    tools.add(name)
    data["tools"] = sorted(tools)
    _save_emergency_file(data)


def emergency_deny_host(host: str) -> None:
    name = host.strip().lower()
    _EMERGENCY_HOSTS.add(name)
    data = _load_emergency_file()
    hosts = {str(item).lower() for item in data.get("hosts") or []}
    hosts.add(name)
    data["hosts"] = sorted(hosts)
    _save_emergency_file(data)


def emergency_deny_command(command: str) -> None:
    """A command prefix that is refused on the next call, ahead of the turn pin."""
    text = (command or "").strip()
    if not text:
        return
    data = _load_emergency_file()
    commands = {str(item) for item in data.get("commands") or []}
    commands.add(text)
    data["commands"] = sorted(commands)
    _save_emergency_file(data)


def command_emergency_denied(command: str) -> bool:
    from app.tools.command_allowlist import command_matches_prefix

    text = (command or "").strip()
    if not text:
        return False
    for prefix in _load_emergency_file().get("commands") or []:
        if command_matches_prefix(text, str(prefix)):
            return True
    return False


def emergency_clear() -> None:
    _EMERGENCY_TOOLS.clear()
    _EMERGENCY_HOSTS.clear()
    _save_emergency_file({"tools": [], "hosts": []})


def tool_emergency_denied(name: str) -> bool:
    if name in _EMERGENCY_TOOLS:
        return True
    return name in _load_emergency_file().get("tools", [])


def host_emergency_denied(host: str) -> bool:
    name = (host or "").strip().lower()
    if name in _EMERGENCY_HOSTS:
        return True
    return name in {str(item).lower() for item in _load_emergency_file().get("hosts", [])}


def eval_command_allowed(command: str) -> bool:
    """True when the eval profile's command set covers this argv."""
    from app.tools.command_allowlist import command_matches_prefix

    text = (command or "").strip()
    if not text:
        return False
    return any(command_matches_prefix(text, prefix) for prefix in EVAL_COMMAND_PREFIXES)


def local_tighten(arguments: dict[str, Any] | None) -> str | None:
    """Cheap in-process rules. Returns deny or require_approval, or None."""
    blob = " ".join(
        str(arguments.get(key) or "")
        for key in ("command", "cmd", "url")
        if isinstance(arguments, dict)
    )
    lowered = blob.lower()
    if any(marker in lowered for marker in _WIPE_MARKERS):
        return "deny"
    if any(marker in lowered for marker in _FETCH_EXEC_MARKERS):
        return "require_approval"
    return None


def decide(
    *,
    tool_name: str,
    sink_class: str,
    window_taint: str,
    sandbox_ready: bool,
    command_allowlisted: bool,
    eval_command: bool,
    snapshot_ok: bool,
    http_decision: str | None = None,
) -> tuple[str, str]:
    """Return (decision, reason) from the baseline matrix.

    decision is allow, require_approval, or deny. Callers apply detector output
    only in the tightening direction after this returns.
    """
    if tool_emergency_denied(tool_name):
        return "deny", "emergency denylist"
    if policy_unreadable() and sink_class in {"S1", "S2", "S3", "S4", "S5"}:
        return "deny", "policy unreadable"
    taint = window_taint if window_taint in TAINT_RANK else "external"
    sink = sink_class or ""
    if sink == "S5":
        return "deny", "out of bounds"
    if sink == "S0":
        return "allow", "read"
    if sink == "S1":
        if snapshot_ok:
            return "allow", "reversible write"
        return "require_approval", "snapshot unavailable"
    if sink == "S2":
        if not sandbox_ready:
            return "deny", "sandbox unavailable"
        if command_allowlisted:
            return "allow", "allowlisted command in a healthy sandbox"
        if eval_command:
            return "allow", "eval command set"
        return "require_approval", "command is not on the allowlist"
    if sink == "S3":
        if tool_name == "remember":
            if taint == "external":
                return "require_approval", "memory write after external content"
            return "allow", "memory write inside user or workspace taint"
        return "require_approval", "durable config or skill change"
    if sink == "S4":
        if http_decision in {"allow", "deny", "require_approval"}:
            return http_decision, "egress policy"
        return "require_approval", "outbound side effect"
    return "deny", "undeclared sink"
