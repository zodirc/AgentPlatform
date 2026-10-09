"""Where a command is allowed to run.

An orchestrator with no sandbox plane URL refuses. A saas tier whose isolation
is still the shared host kernel refuses. Dev monolith keeps local bwrap.
"""

from __future__ import annotations

from app.settings import settings

_ISOLATED = frozenset({"gvisor", "kata", "firecracker"})
_LOCAL_ROLES = frozenset({"monolith", "sandbox"})


def execution_refusal() -> str | None:
    """A reason to refuse local exec, or None when local exec is allowed."""
    tier = str(getattr(settings, "deployment_tier", "dev") or "dev").strip().lower()
    role = str(getattr(settings, "service_role", "monolith") or "monolith").strip().lower()
    isolation = str(getattr(settings, "sandbox_isolation", "bwrap") or "bwrap").strip().lower()
    url = str(getattr(settings, "sandbox_plane_url", "") or "").strip()
    if tier == "saas" and isolation not in _ISOLATED:
        return "saas tier requires an isolated kernel sandbox"
    if tier == "saas":
        from pathlib import Path

        if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
            return "saas tier requires a cgroup"
    from app.tools.core.sandbox import escape_probe_report

    probe = escape_probe_report()
    if probe.get("ran") and probe.get("ok") is False:
        return "sandbox escape probe failed"
    if role not in _LOCAL_ROLES and not url:
        return "orchestrator refuses exec without SANDBOX_PLANE_URL"
    return None


def sandbox_is_ready() -> bool:
    """True only for a remote plane or a working bwrap. Break-glass is not ready."""
    if execution_refusal():
        return False
    from app.tools.core.remote_sandbox import should_use_remote_sandbox

    if should_use_remote_sandbox():
        return True
    try:
        from app.tools.core.sandbox import resolve_sandbox_backend

        return resolve_sandbox_backend() == "bwrap"
    except Exception:
        return False
