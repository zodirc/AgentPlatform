"""Per-scenario policy on top of the baseline matrix.

A scenario may add sandboxed command prefixes, and may only tighten every
other decision. S5 and an existing deny stay deny. Bare exec and hosts outside
the deployment allow list are not opened here.
"""

from __future__ import annotations

from typing import Any

_RANK = {"allow": 0, "require_approval": 1, "deny": 2}


def _security(scenario_id: str) -> dict[str, Any]:
    if not scenario_id:
        return {}
    try:
        from app.scenarios.registry import ScenarioRegistry

        profile = ScenarioRegistry.get(scenario_id)
    except Exception:
        return {}
    raw = getattr(profile, "security", None) or {}
    return raw if isinstance(raw, dict) else {}


def scenario_version(scenario_id: str) -> str:
    return str(_security(scenario_id).get("version") or "")


def scenario_command_allowed(scenario_id: str, command: str) -> bool:
    """Extra argv prefixes for this scenario. Still requires a healthy sandbox."""
    from app.tools.command_allowlist import command_matches_prefix

    prefixes = _security(scenario_id).get("commands") or []
    text = (command or "").strip()
    if not text or not isinstance(prefixes, list):
        return False
    return any(command_matches_prefix(text, str(prefix)) for prefix in prefixes)


def scenario_network_hosts(scenario_id: str) -> list[str] | None:
    """None means the deployment allow list stands. A list can only shrink it."""
    network = _security(scenario_id).get("network") or {}
    if not isinstance(network, dict):
        return None
    hosts = network.get("hosts")
    if not isinstance(hosts, list):
        return None
    return [str(item).strip().lower() for item in hosts if str(item).strip()]


def scenario_detector_mode(scenario_id: str) -> str:
    detectors = _security(scenario_id).get("detectors") or {}
    if not isinstance(detectors, dict):
        return ""
    mode = str(detectors.get("injection") or "").strip().lower()
    return mode if mode in {"observe", "enforce"} else ""


def scenario_mode(scenario_id: str) -> str:
    """observe or enforce. Neither value turns the matrix, sandbox, or taint off."""
    mode = str(_security(scenario_id).get("mode") or "observe").strip().lower()
    return mode if mode in {"observe", "enforce"} else "observe"


def structural_controls_hold(scenario_id: str) -> bool:
    """Read the scenario mode and keep structural controls on.

    A profile cannot set mode to off, allow, or disabled and thereby skip the
    sink matrix. The return value is always True; the read is what records that
    the mode was consulted.
    """
    _ = scenario_mode(scenario_id)
    return True


def scenario_path_allowed(scenario_id: str, arguments: dict[str, Any] | None) -> bool:
    """True when the path is under one of the scenario prefixes inside the Work.

    An empty paths list means the whole Work root, which the jail already bounds.
    A prefix can only shrink that root. It cannot point outside it.
    """
    raw = _security(scenario_id).get("paths")
    if not isinstance(raw, list) or not raw:
        return True
    prefixes = [str(item or "").strip().replace("\\", "/") for item in raw]
    if any(item in {"", ".", "./"} for item in prefixes):
        return True
    args = arguments or {}
    path = str(args.get("path") or args.get("file_path") or "").strip()
    if not path:
        return True
    from pathlib import Path

    from app.tenant_context import current_work_root_path

    try:
        root = current_work_root_path().resolve()
    except Exception:
        return True
    try:
        resolved = Path(path).resolve()
        rel = resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    rel_s = "" if rel.as_posix() == "." else rel.as_posix()
    for item in raw:
        prefix = str(item or "").strip().replace("\\", "/").lstrip("./")
        if prefix in {"", "."}:
            return True
        if rel_s == prefix or rel_s.startswith(prefix + "/"):
            return True
    return False


def apply_overlay(
    decision: str,
    *,
    sink: str,
    scenario_id: str,
    tool_name: str,
    window_taint: str = "",
) -> str:
    structural_controls_hold(scenario_id)
    if sink == "S5" or decision == "deny":
        return decision
    if tool_name in {"remember", "forget"}:
        memory = _security(scenario_id).get("memory") or {}
        if isinstance(memory, dict):
            if window_taint == "external":
                choice = str(memory.get("external") or "approval").strip().lower()
                if choice == "deny":
                    return "deny"
                if decision == "allow":
                    return "require_approval"
            if window_taint == "workspace":
                choice = str(memory.get("workspace") or "work").strip().lower()
                if choice == "deny":
                    return "deny"
                if choice in {"approval", "require_approval"} and decision == "allow":
                    return "require_approval"
    matrix = _security(scenario_id).get("matrix") or {}
    wanted = ""
    if isinstance(matrix, dict):
        row = matrix.get(sink) or matrix.get(tool_name) or {}
        if isinstance(row, dict):
            wanted = str(row.get(window_taint) or row.get("*") or "")
        elif isinstance(row, str):
            wanted = row
    if wanted not in {"require_approval", "deny"}:
        return decision
    if _RANK[wanted] > _RANK.get(decision, 0):
        return wanted
    return decision
