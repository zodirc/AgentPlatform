"""Remote sandbox plane client (ADR-020)."""

from __future__ import annotations

from typing import Any, Sequence

import httpx

from app.settings import settings


async def remote_sandbox_exec(
    *,
    command: str,
    cwd: str,
    timeout_seconds: float,
    argv: Sequence[str] | None = None,
) -> dict[str, Any]:
    """POST ``/internal/sandbox/exec`` on the sandbox plane."""
    base = (getattr(settings, "sandbox_plane_url", None) or "").rstrip("/")
    if not base:
        raise RuntimeError("SANDBOX_PLANE_URL is required for remote sandbox exec")
    body: dict[str, Any] = {
        "command": command,
        "cwd": cwd,
        "timeout_seconds": float(timeout_seconds),
    }
    if argv is not None:
        body["argv"] = [str(a) for a in argv]
    async with httpx.AsyncClient(timeout=max(30.0, float(timeout_seconds) + 15.0)) as client:
        resp = await client.post(
            f"{base}/internal/sandbox/exec",
            json=body,
            headers={"X-Internal-Token": settings.internal_service_token},
        )
        resp.raise_for_status()
        data = resp.json()
    if isinstance(data, dict) and data.get("accepted") is False:
        return {
            "status": "failed",
            "command": command,
            "stdout": "",
            "stderr": str(data.get("detail") or "sandbox plane rejected"),
            "exit_code": None,
            "summary": str(data.get("detail") or "sandbox plane rejected"),
            "sandbox": "remote",
        }
    if isinstance(data, dict):
        out = {k: v for k, v in data.items() if k != "accepted"}
        out.setdefault("sandbox", "remote")
        return out
    return {
        "status": "failed",
        "command": command,
        "stdout": "",
        "stderr": "invalid sandbox plane response",
        "exit_code": None,
        "summary": "invalid sandbox plane response",
        "sandbox": "remote",
    }


def should_use_remote_sandbox() -> bool:
    role = (getattr(settings, "service_role", None) or "monolith").strip().lower()
    url = (getattr(settings, "sandbox_plane_url", None) or "").strip()
    return bool(url) and role not in {"sandbox", "monolith"}
